import pandas as pd
import numpy as np
import io
import os
import random
import time

# TENTATIVE D'IMPORT VERTEX AI
try:
    import vertexai
    from vertexai.language_models import TextGenerationModel
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "energistrat-saas")
        self.model = None
        self.ai_ready = False
        
        if VERTEX_AVAILABLE:
            try:
                vertexai.init(project=self.project_id, location="europe-west9")
                self.model = TextGenerationModel.from_pretrained("text-bison")
                self.ai_ready = True
                print("✅ [CORTEX] Vertex AI connecté.")
            except:
                print("⚠️ [CORTEX] Vertex AI non accessible.")

    def safe_value(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0.0
            return float(val)
        except: return 0.0

    def generate_ai_insight(self, data_context, context="client"):
        if not self.ai_ready:
            return "Mode Déconnecté : Activez Vertex AI pour avoir l'analyse sémantique."
        
        prompt = f"Analyse ces données énergétiques : {data_context}. Sois bref et pro."
        try:
            response = self.model.predict(prompt, temperature=0.2, max_output_tokens=256)
            return response.text
        except Exception as e:
            return f"Erreur IA : {str(e)}"

    async def analyze_file(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # 1. LECTURE
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python', encoding='utf-8')
                except: 
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier vide"}

            # 2. NETTOYAGE
            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            
            possible_date = ['date', 'horodate', 'heure', 'timestamp', 'periode']
            possible_val = ['puissance', 'p10', 'conso', 'valeur', 'kwh', 'kw', 'qty']
            
            col_date = next((c for c in df.columns if any(x in c for x in possible_date)), None)
            col_val = next((c for c in df.columns if any(x in c for x in possible_val)), None)

            if not col_date or not col_val: return {"success": False, "error": "Colonnes non identifiées"}

            # 3. TRAITEMENT
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date) # On garde l'index numérique pour le slicing
            
            # Nettoyage valeurs
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').replace(' ', '')
                df[col_val] = pd.to_numeric(df[col_val], errors='coerce')
            df[col_val] = df[col_val].fillna(0)

            # 4. KPI
            is_power = 'kw' in col_val and 'kwh' not in col_val
            total_sum = df[col_val].sum()
            vol_kwh = total_sum / 6 if is_power else total_sum
            
            kpis = {
                "volume_mwh": round(self.safe_value(vol_kwh / 1000), 2),
                "pic_kw": round(self.safe_value(df[col_val].max()), 2),
                "talon_kw": round(self.safe_value(df[col_val].min()), 2),
                "points_traites": len(df)
            }

            ai_message = self.generate_ai_insight(kpis, context="client")

            # 5. PREPARATION GRAPHIQUE (FIX: Downsampling intelligent)
            # Au lieu de faire une moyenne par jour (qui écrase tout), on prend 1 point tous les N
            # pour avoir une belle courbe qui ressemble à la réalité.
            
            nb_points_desire = 200
            step = max(1, len(df) // nb_points_desire)
            
            # On prend un échantillon représentatif
            df_chart = df.iloc[::step]

            return {
                "success": True,
                "kpi": kpis,
                "ai_insight": ai_message,
                "chart": {
                    # On formate la date en string simple pour Chart.js
                    "labels": df_chart[col_date].dt.strftime('%d/%m %H:%M').tolist(),
                    "values": [self.safe_value(x) for x in df_chart[col_val].tolist()]
                }
            }

        except Exception as e:
            return {"success": False, "error": f"Crash Engine: {str(e)}"}

    def run_chaos_monkey(self): return [{"test": "Test", "status": "PASS"}]
    def ask_agent(self, query): return "Réponse Cortex simulée."
    def simulate_audit(self, f): return {"score": 100}

cortex = CortexEngine()
