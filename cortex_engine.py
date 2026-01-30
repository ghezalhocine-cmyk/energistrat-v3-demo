import pandas as pd
import numpy as np
import io
import os
import json

# IMPORT GOOGLE VERTEX AI
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    from vertexai.language_models import TextGenerationModel
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        # Récupération automatique de l'ID projet (plus fiable que le hardcode)
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "energistrat-saas")
        self.model = None
        self.ai_ready = False
        self.last_error = "Aucune tentative"
        
        if VERTEX_AVAILABLE:
            self.init_ai()

    def init_ai(self):
        """Tentative de connexion forcée en EUROPE (RGPD)"""
        try:
            # 1. On tente PARIS (europe-west9) car ton Cloud Run y est hébergé
            print(f"📡 Tentative connexion Vertex AI sur EUROPE-WEST9 pour {self.project_id}...")
            vertexai.init(project=self.project_id, location="europe-west9")
            
            # 2. On utilise le modèle le plus standard disponible en France
            self.model = GenerativeModel("gemini-1.0-pro")
            
            # 3. Test immédiat
            self.model.generate_content("Ping")
            self.ai_ready = True
            self.last_error = "Connecté (Europe-West9)"
            print("✅ [CORTEX] Connecté à Gemini (Europe)")
            
        except Exception as e:
            # Si ça échoue, on stocke l'erreur pour l'afficher dans le chat
            self.ai_ready = False
            self.last_error = str(e)
            print(f"❌ [CORTEX] Echec Init : {e}")

    def safe_value(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0.0
            return float(val)
        except: return 0.0

    def generate_ai_insight(self, data, profile="industry"):
        if not self.ai_ready:
            return f"ERREUR SYSTÈME : {self.last_error}"

        # Construction du Prompt
        if isinstance(data, str):
            prompt = f"Tu es l'IA Energistrat. Réponds à : {data}"
        else:
            prompt = f"Analyse ces données pour un profil {profile} : Vol {data['volume_mwh']} MWh, Pic {data['pic_kw']} kW."

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"ERREUR RUNTIME : {str(e)}"

    # --- FONCTIONS UTILES ---
    async def analyze_file(self, file_content, filename, target_profile="industry"):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python')
                except: 
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier vide"}

            # Nettoyage minimaliste pour la démo
            df.columns = [str(c).lower().strip() for c in df.columns]
            col_val = next((c for c in df.columns if any(x in c for x in ['puiss', 'p10', 'conso', 'val', 'kw'])), None)
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horo', 'time'])), None)
            
            if not col_val or not col_date: return {"success": False, "error": "Colonnes introuvables"}

            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(',','.'), errors='coerce').fillna(0)

            kpis = {
                "volume_mwh": round(df[col_val].sum()/1000, 2),
                "pic_kw": round(df[col_val].max(), 2),
                "talon_kw": round(df[col_val].min(), 2),
                "points_traites": len(df)
            }

            # Appel IA
            ai_msg = self.generate_ai_insight(kpis, profile=target_profile)

            # Chart
            step = max(1, len(df)//200)
            df_chart = df.iloc[::step]

            return {
                "success": True, 
                "kpi": kpis, 
                "ai_insight": ai_msg,
                "chart": {
                    "labels": df_chart[col_date].dt.strftime('%d/%m %H:%M').tolist(),
                    "values": df_chart[col_val].tolist()
                }
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def ask_agent(self, query):
        # COMMANDE SECRÈTE DE DEBUG
        if query.strip() == "#debug":
            return f"🔍 DIAGNOSTIC :\n- Projet: {self.project_id}\n- AI Ready: {self.ai_ready}\n- Dernière Erreur: {self.last_error}"
        
        return self.generate_ai_insight(query, profile="ops")

    def run_chaos_monkey(self): return []
    def simulate_audit(self, f): return {"score": 100}

cortex = CortexEngine()
