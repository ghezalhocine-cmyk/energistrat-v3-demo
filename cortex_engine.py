import pandas as pd
import numpy as np
import io
import os
import vertexai
from vertexai.language_models import TextGenerationModel

class CortexEngine:
    def __init__(self):
        self.kwh_price_elec = 0.18
        # TENTATIVE DE CONNEXION A GOOGLE VERTEX AI
        # Cela ne marchera que sur Cloud Run (pas en local sans clé)
        try:
            # On récupère l'ID projet automatiquement sur Cloud Run
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "energistrat-saas")
            vertexai.init(project=project_id, location="europe-west9")
            self.model = TextGenerationModel.from_pretrained("text-bison") # Ou Gemini-pro
            self.ai_ready = True
        except:
            self.ai_ready = False
            print("⚠️ Vertex AI non accessible (Mode Local ou API non activée)")

    def safe_value(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0.0
            return float(val)
        except: return 0.0

    # --- FONCTION MAGIQUE : GÉNÉRATION D'INSIGHTS VIA IA ---
    def generate_ai_insight(self, kpi_data, context="client"):
        if not self.ai_ready:
            return "Mode Déconnecté : Activez Vertex AI pour avoir l'analyse sémantique."

        if context == "client":
            prompt = f"""
            Tu es un expert en efficacité énergétique industrielle.
            Analyse ces données réelles d'un site :
            - Volume Annuel : {kpi_data['volume_mwh']} MWh
            - Pic de Puissance : {kpi_data['pic_kw']} kW
            - Talon (Nuit) : {kpi_data['talon_kw']} kW
            
            Rédige un conseil stratégique court (3 phrases max) pour le Directeur du site. 
            Ton : Professionnel, direct, orienté économie.
            Si le talon est élevé (>20% du pic), alerte sur le gaspillage nocturne.
            """
        else: # Context Ops/Chat
            prompt = f"""
            Tu es l'assistant technique Ops d'Energistrat.
            Voici la question de l'administrateur : "{kpi_data}"
            Réponds de manière technique et concise.
            """

        try:
            response = self.model.predict(prompt, temperature=0.2, max_output_tokens=256)
            return response.text
        except Exception as e:
            return f"Erreur IA : {str(e)}"

    async def analyze_file(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # Lecture Robuste
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python', encoding='utf-8')
                except: 
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier illisible"}

            # Nettoyage Colonnes
            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            possible_date = ['date', 'horodate', 'heure', 'timestamp']
            possible_val = ['puissance', 'p10', 'conso', 'valeur', 'kwh', 'kw']
            
            col_date = next((c for c in df.columns if any(x in c for x in possible_date)), None)
            col_val = next((c for c in df.columns if any(x in c for x in possible_val)), None)

            if not col_date or not col_val: return {"success": False, "error": "Colonnes Date/Puissance manquantes"}

            # Traitement
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date).set_index(col_date)
            
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').astype(float)
            df[col_val] = df[col_val].fillna(0)

            # Calculs
            vol = df[col_val].sum()
            if 'kwh' not in col_val: vol = vol / 6
            pic = df[col_val].max()
            talon = df[col_val].min()
            
            # KPI Dict
            kpis = {
                "volume_mwh": round(self.safe_value(vol / 1000), 2),
                "pic_kw": round(self.safe_value(pic), 2),
                "talon_kw": round(self.safe_value(talon), 2),
                "points_traites": len(df)
            }

            # --- APPEL GEMINI ---
            # On demande à l'IA d'analyser ces chiffres tout de suite
            ai_message = self.generate_ai_insight(kpis, context="client")

            # Resampling Graph
            df_daily = df[col_val].resample('D').mean().fillna(0).tail(365)

            return {
                "success": True,
                "kpi": kpis,
                "ai_insight": ai_message, # <--- Le message de Gemini est ici
                "chart": {
                    "labels": df_daily.index.strftime('%d/%m').tolist(),
                    "values": [self.safe_value(x) for x in df_daily.tolist()]
                }
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- CHATBOT OPS ---
    def ask_agent(self, query):
        # On utilise le même modèle pour répondre au chat
        return self.generate_ai_insight(query, context="ops")

    # Mocks
    def run_chaos_monkey(self): return [{"test": "Connexion Vertex AI", "status": "✅ PASS", "detail": "API Google Active"}]
    def simulate_audit(self, file_name): return {"compliant": False, "anomalies": ["TVA"], "montant_detecte": 1200}

cortex = CortexEngine()
