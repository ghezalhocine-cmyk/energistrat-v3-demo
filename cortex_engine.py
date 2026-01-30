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
    print("⚠️ [CORTEX] Vertex AI SDK non installé.")

class CortexEngine:
    def __init__(self):
        self.project_id = "energistrat-saas"
        self.model = None
        self.active_model_name = "Aucun"
        self.ai_ready = False
        
        if VERTEX_AVAILABLE:
            self.init_ai_robust()

    def init_ai_robust(self):
        """Tente de se connecter à plusieurs modèles jusqu'à ce que ça marche"""
        try:
            # 1. Connexion Infrastructure (USA pour max compatibilité)
            vertexai.init(project=self.project_id, location="us-central1")
            
            # 2. Liste des modèles à tester (Ordre de préférence)
            models_to_try = [
                "gemini-1.5-flash-001", # Le plus rapide/récent
                "gemini-1.5-pro-001",   # Le plus puissant
                "gemini-1.0-pro",       # L'ancien standard
                "gemini-pro"            # L'alias générique
            ]

            for model_name in models_to_try:
                try:
                    print(f"🔄 Test connexion : {model_name}...")
                    temp_model = GenerativeModel(model_name)
                    # Test réel de génération
                    temp_model.generate_content("Ping")
                    
                    self.model = temp_model
                    self.active_model_name = model_name
                    self.ai_ready = True
                    print(f"✅ [CORTEX] SUCCÈS : Connecté sur {model_name}")
                    return
                except:
                    continue # On essaie le suivant
            
            print("⚠️ [CORTEX] Aucun modèle n'a répondu.")

        except Exception as e:
            print(f"⚠️ [CORTEX] Erreur Init Critique : {e}")

    # --- FIX CRITIQUE JSON SERIALIZATION ---
    def clean_number(self, val):
        """Convertit les types NumPy (int64, float64) en types Python natifs (int, float)"""
        try:
            if pd.isna(val) or np.isinf(val): return 0
            # Si c'est un entier NumPy
            if isinstance(val, (np.integer, int)):
                return int(val)
            # Si c'est un flottant NumPy
            if isinstance(val, (np.floating, float)):
                return float(val)
            return float(val)
        except:
            return 0

    def generate_ai_insight(self, data, profile="industry"):
        if not self.ai_ready:
            return f"ERREUR IA : Aucun modèle disponible. (Dernier testé : {self.active_model_name})"

        if isinstance(data, str):
            prompt = f"Tu es l'IA Energistrat. Réponds à : {data}"
        else:
            prompt = f"Agis en expert énergie ({profile}). Analyse : Vol {data['volume_mwh']} MWh, Pic {data['pic_kw']} kW. Conseil court."

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"ERREUR RUNTIME ({self.active_model_name}) : {str(e)}"

    async def analyze_file(self, file_content, filename, target_profile="industry"):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # Lecture Robuste
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
            col_val = next((c for c in df.columns if any(x in c for x in ['puiss', 'p10', 'conso', 'val', 'kw'])), None)
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horo', 'time'])), None)
            
            if not col_val or not col_date: return {"success": False, "error": "Colonnes introuvables"}

            # Traitement
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            
            if df[col_val].dtype == object:
                df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(',', '.'), errors='coerce')
            df[col_val] = df[col_val].fillna(0)

            # KPI
            total = df[col_val].sum()
            vol = total / 6 if ('kw' in col_val and 'kwh' not in col_val) else total
            
            # --- FIX JSON : On utilise clean_number partout ---
            kpis = {
                "volume_mwh": round(self.clean_number(vol/1000), 2),
                "pic_kw": round(self.clean_number(df[col_val].max()), 2),
                "talon_kw": round(self.clean_number(df[col_val].min()), 2),
                "points_traites": int(len(df)) # Force le cast en int Python pur
            }

            # APPEL IA
            ai_msg = self.generate_ai_insight(kpis, profile=target_profile)

            # Chart Sampling
            step = max(1, len(df)//200)
            df_chart = df.iloc[::step]

            # --- FIX JSON CHART : List comprehension avec clean_number ---
            chart_values = [self.clean_number(x) for x in df_chart[col_val].tolist()]
            chart_labels = df_chart[col_date].dt.strftime('%d/%m %H:%M').tolist()

            return {
                "success": True, 
                "kpi": kpis, 
                "ai_insight": ai_msg,
                "chart": {
                    "labels": chart_labels,
                    "values": chart_values
                }
            }
        except Exception as e:
            # On log l'erreur exacte pour le debug
            print(f"❌ ERREUR ANALYSE : {str(e)}")
            return {"success": False, "error": f"Moteur: {str(e)}"}

    def ask_agent(self, query):
        if query == "#model":
            return f"Modèle actif : {self.active_model_name} (Région: us-central1)"
        return self.generate_ai_insight(query, profile="ops")

    def run_chaos_monkey(self): return []
    def simulate_audit(self, f): return {"score": 100}

cortex = CortexEngine()
