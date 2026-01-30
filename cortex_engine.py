import pandas as pd
import numpy as np
import io
import os
import json

# IMPORT GOOGLE VERTEX AI
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        # Récupération automatique de l'ID projet
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "energistrat-saas")
        self.model = None
        self.ai_ready = False
        self.last_error = "Initialisation..."
        
        if VERTEX_AVAILABLE:
            self.init_ai()

    def init_ai(self):
        """Connexion à la région Mère (US-CENTRAL1) pour garantir l'accès"""
        try:
            print(f"📡 Tentative connexion Vertex AI sur US-CENTRAL1...")
            
            # --- FIX : ON FORCE LA REGION US ---
            vertexai.init(project=self.project_id, location="us-central1")
            
            # On utilise le modèle standard
            self.model = GenerativeModel("gemini-1.0-pro")
            
            # Test immédiat
            self.model.generate_content("Ping")
            self.ai_ready = True
            self.last_error = "Connecté (US-Central1)"
            print("✅ [CORTEX] Connecté à Gemini (USA)")
            
        except Exception as e:
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
            # Chatbot Ops
            prompt = f"Tu es l'IA Energistrat. Réponds de façon technique et concise à : {data}"
        else:
            # Analyse Fichier
            prompt = f"Agis en expert énergie pour un client type '{profile}'. Analyse ces données : Volume {data['volume_mwh']} MWh, Pic {data['pic_kw']} kW. Donne un conseil court (2 phrases)."

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"ERREUR RUNTIME : {str(e)}"

    async def analyze_file(self, file_content, filename, target_profile="industry"):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            # Lecture robuste
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python')
                except: 
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier vide"}

            # Nettoyage Colonnes
            df.columns = [str(c).lower().strip().replace('"','').replace("'", "") for c in df.columns]
            
            # Détection colonnes
            col_val = next((c for c in df.columns if any(x in c for x in ['puiss', 'p10', 'conso', 'val', 'kw'])), None)
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horo', 'time'])), None)
            
            if not col_val or not col_date: return {"success": False, "error": "Colonnes introuvables"}

            # Traitement Données
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            
            # Nettoyage valeurs (virgules)
            if df[col_val].dtype == object:
                df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(',', '.'), errors='coerce')
            df[col_val] = df[col_val].fillna(0)

            # Calculs KPI
            total = df[col_val].sum()
            # Si c'est des kW (Puissance), on divise par 6 pour avoir des kWh (pas 10min)
            # Si c'est déjà des kWh (Conso), on garde tel quel
            is_power = 'kw' in col_val and 'kwh' not in col_val
            vol = total / 6 if is_power else total

            kpis = {
                "volume_mwh": round(vol/1000, 2),
                "pic_kw": round(df[col_val].max(), 2),
                "talon_kw": round(df[col_val].min(), 2),
                "points_traites": len(df)
            }

            # Appel IA
            ai_msg = self.generate_ai_insight(kpis, profile=target_profile)

            # Sampling Graphique (Max 200 points)
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
            return {"success": False, "error": f"Moteur: {str(e)}"}

    def ask_agent(self, query):
        if query.strip() == "#debug":
            return f"🔍 DIAGNOSTIC :\n- Projet: {self.project_id}\n- AI Ready: {self.ai_ready}\n- Dernière Erreur: {self.last_error}"
        return self.generate_ai_insight(query, profile="ops")

    def run_chaos_monkey(self): return [{"test": "Vertex AI Ping", "status": "PASS" if self.ai_ready else "FAIL"}]
    def simulate_audit(self, f): return {"score": 100}

cortex = CortexEngine()
