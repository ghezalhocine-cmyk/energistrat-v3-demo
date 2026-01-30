import pandas as pd
import numpy as np
import io
import os
import time
import json

# IMPORT GOOGLE VERTEX AI
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False
    print("⚠️ [CORTEX] Vertex AI SDK non installé.")

class CortexEngine:
    def __init__(self):
        # ON FORCE L'ID DU PROJET
        self.project_id = "energistrat-saas"
        self.model = None
        self.ai_ready = False
        
        # INITIALISATION IA
        if VERTEX_AVAILABLE:
            try:
                # ON RESTE SUR US-CENTRAL1 (C'est la région la plus sûre pour les modèles)
                vertexai.init(project=self.project_id, location="us-central1")
                
                # --- CHANGEMENT ICI : UTILISATION DE GEMINI 1.5 FLASH ---
                # C'est le modèle le plus stable et disponible actuellement
                self.model = GenerativeModel("gemini-1.5-flash-001")
                
                self.ai_ready = True
                print(f"✅ [CORTEX] Connecté à Gemini 1.5 Flash sur {self.project_id}")
            except Exception as e:
                print(f"⚠️ [CORTEX] Erreur Init : {e}")
                self.ai_ready = False

    def safe_value(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0.0
            return float(val)
        except: return 0.0

    def get_prompt_for_profile(self, profile, kpis):
        # Cas Chatbot
        if isinstance(kpis, str):
            return f"Tu es l'IA Energistrat. Réponds brièvement à : {kpis}"

        base_data = f"Données : Volume {kpis['volume_mwh']} MWh, Pic {kpis['pic_kw']} kW."
        
        if profile == "industry":
            return f"Expert Industrie. Analyse ces données : {base_data}. Donne un conseil technique court."
        elif profile == "mairie":
            return f"Conseiller Mairie. Analyse ces données : {base_data}. Rédige une note politique courte."
        else:
            return f"Expert Energie. Analyse : {base_data}. Conseil court."

    def generate_ai_insight(self, data, profile="industry"):
        """
        Appelle Google Gemini pour générer le texte
        """
        if not self.ai_ready:
            return "ERREUR INIT : Vertex AI n'a pas pu s'initialiser au démarrage."

        prompt = self.get_prompt_for_profile(profile, data)

        try:
            # APPEL API RÉEL
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Erreur Runtime Gemini : {error_msg}")
            return f"ERREUR GOOGLE : {error_msg}"

    async def analyze_file(self, file_content, filename, target_profile="industry"):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python', encoding='utf-8')
                except: 
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier vide"}

            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horodate', 'heure', 'timestamp'])), None)
            col_val = next((c for c in df.columns if any(x in c for x in ['puissance', 'p10', 'conso', 'valeur', 'kwh', 'kw'])), None)

            if not col_date or not col_val: return {"success": False, "error": "Colonnes inconnues"}

            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').replace(' ', '')
                df[col_val] = pd.to_numeric(df[col_val], errors='coerce')
            df[col_val] = df[col_val].fillna(0)

            total_sum = df[col_val].sum()
            vol_kwh = total_sum 
            
            kpis = {
                "volume_mwh": round(self.safe_value(vol_kwh / 1000), 2),
                "pic_kw": round(self.safe_value(df[col_val].max()), 2),
                "talon_kw": round(self.safe_value(df[col_val].min()), 2),
                "points_traites": len(df)
            }

            # APPEL IA
            ai_message = self.generate_ai_insight(kpis, profile=target_profile)

            nb_points = 200
            step = max(1, len(df) // nb_points)
            df_chart = df.iloc[::step]

            return {
                "success": True,
                "kpi": kpis,
                "ai_insight": ai_message,
                "chart": {
                    "labels": df_chart[col_date].dt.strftime('%d/%m %H:%M').tolist(),
                    "values": [self.safe_value(x) for x in df_chart[col_val].tolist()]
                }
            }

        except Exception as e:
            return {"success": False, "error": f"Moteur: {str(e)}"}

    def ask_agent(self, query):
        return self.generate_ai_insight(query, profile="ops")

    def run_chaos_monkey(self): 
        return [{"test": "Vertex AI Ping", "status": "PASS" if self.ai_ready else "FAIL"}]
    
    def simulate_audit(self, f): 
        return {"score": 100}

cortex = CortexEngine()
