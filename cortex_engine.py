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
    from vertexai.language_models import TextGenerationModel
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False
    print("⚠️ [CORTEX] Vertex AI SDK non installé.")

class CortexEngine:
    def __init__(self):
        self.project_id = "energistrat-saas"
        self.model = None
        self.model_type = None # 'gemini' ou 'bison'
        self.ai_ready = False
        
        # INITIALISATION IA (STRATÉGIE EN CASCADE)
        if VERTEX_AVAILABLE:
            try:
                # 1. Connexion US-CENTRAL1
                vertexai.init(project=self.project_id, location="us-central1")
                
                # 2. TENTATIVE 1 : GEMINI 1.0 PRO (Le Standard)
                try:
                    print("Testing Gemini 1.0 Pro...")
                    self.model = GenerativeModel("gemini-1.0-pro")
                    # Petit ping pour vérifier
                    self.model.generate_content("Ping")
                    self.model_type = 'gemini'
                    self.ai_ready = True
                    print(f"✅ [CORTEX] Connecté à Gemini 1.0 Pro")
                except:
                    # 3. TENTATIVE 2 : GEMINI 1.5 FLASH (Le Rapide - Nom générique)
                    try:
                        print("Testing Gemini 1.5 Flash...")
                        self.model = GenerativeModel("gemini-1.5-flash")
                        self.model.generate_content("Ping")
                        self.model_type = 'gemini'
                        self.ai_ready = True
                        print(f"✅ [CORTEX] Connecté à Gemini 1.5 Flash")
                    except:
                        # 4. TENTATIVE 3 : TEXT-BISON (L'Ancien, ultra-robuste)
                        try:
                            print("Testing Text-Bison (Legacy)...")
                            self.model = TextGenerationModel.from_pretrained("text-bison")
                            self.model.predict("Ping")
                            self.model_type = 'bison'
                            self.ai_ready = True
                            print(f"✅ [CORTEX] Connecté à Text-Bison (Legacy)")
                        except Exception as e:
                            print(f"❌ [CORTEX] AUCUN MODÈLE DISPO : {e}")
                            self.ai_ready = False

            except Exception as e:
                print(f"⚠️ [CORTEX] Erreur Init Globale : {e}")
                self.ai_ready = False

    def safe_value(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0.0
            return float(val)
        except: return 0.0

    def get_prompt_for_profile(self, profile, kpis):
        if isinstance(kpis, str):
            return f"Tu es l'IA Energistrat. Réponds à : {kpis}"

        base_data = f"Données : Volume {kpis['volume_mwh']} MWh, Pic {kpis['pic_kw']} kW."
        
        if profile == "industry":
            return f"Expert Industrie. Analyse ces données : {base_data}. Donne un conseil technique court."
        elif profile == "mairie":
            return f"Conseiller Mairie. Analyse ces données : {base_data}. Rédige une note politique courte."
        else:
            return f"Expert Energie. Analyse : {base_data}. Conseil court."

    def generate_ai_insight(self, data, profile="industry"):
        """
        Appelle Google (Gemini ou Bison selon ce qui a marché)
        """
        if not self.ai_ready:
            return "ERREUR : Aucun modèle IA n'a pu être chargé."

        prompt = self.get_prompt_for_profile(profile, data)

        try:
            # APPEL DIFFÉRENT SELON LE MODÈLE CHARGÉ
            if self.model_type == 'gemini':
                response = self.model.generate_content(prompt)
                return response.text
            elif self.model_type == 'bison':
                response = self.model.predict(prompt, temperature=0.2, max_output_tokens=256)
                return response.text
            else:
                return "Erreur Interne Modèle."
                
        except Exception as e:
            return f"ERREUR GOOGLE ({self.model_type}) : {str(e)}"

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
