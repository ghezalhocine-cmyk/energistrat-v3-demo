import pandas as pd
import numpy as np
import io
import os
import json

# IMPORT GOOGLE VERTEX AI
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    from vertexai.language_models import TextGenerationModel # Pour l'ancienne génération (Bison)
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False
    print("⚠️ [CORTEX] Vertex AI SDK non installé.")

class CortexEngine:
    def __init__(self):
        self.project_id = "energistrat-saas"
        self.model = None
        self.model_type = None # 'gemini' ou 'bison'
        self.active_model_name = "Aucun"
        self.ai_ready = False
        self.last_error_log = []
        
        if VERTEX_AVAILABLE:
            self.init_ai_robust()

    def init_ai_robust(self):
        """Tente de se connecter à plusieurs modèles (Gemini PUIS Bison)"""
        try:
            # 1. Connexion Infrastructure (USA)
            vertexai.init(project=self.project_id, location="us-central1")
            
            # 2. Liste des modèles à tester
            # On mixe les nouveaux (Gemini) et les anciens (Bison/PaLM)
            models_to_try = [
                ("gemini-1.5-flash", "gemini"),
                ("gemini-1.0-pro", "gemini"),
                ("text-bison", "bison"),      # Le sauveur
                ("text-bison@001", "bison")   # La version figée
            ]

            for name, m_type in models_to_try:
                try:
                    print(f"🔄 Test connexion : {name}...")
                    
                    if m_type == "gemini":
                        temp_model = GenerativeModel(name)
                        temp_model.generate_content("Ping") # Test
                        self.model = temp_model
                    else:
                        # Initialisation spécifique pour Bison (Legacy)
                        temp_model = TextGenerationModel.from_pretrained(name)
                        temp_model.predict("Ping") # Test
                        self.model = temp_model

                    # Si on arrive ici, c'est gagné
                    self.model_type = m_type
                    self.active_model_name = name
                    self.ai_ready = True
                    print(f"✅ [CORTEX] SUCCÈS : Connecté sur {name}")
                    return

                except Exception as e:
                    err_msg = str(e)
                    print(f"❌ Echec sur {name} : {err_msg}")
                    self.last_error_log.append(f"{name}: {err_msg[:50]}...")
            
            print("⚠️ [CORTEX] Aucun modèle n'a répondu.")

        except Exception as e:
            print(f"⚠️ [CORTEX] Erreur Init Critique : {e}")

    # --- NETTOYAGE JSON (Gardé car il marche bien) ---
    def clean_number(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0
            if isinstance(val, (np.integer, int)): return int(val)
            return float(val)
        except: return 0

    def generate_ai_insight(self, data, profile="industry"):
        if not self.ai_ready:
            # On affiche les erreurs pour comprendre pourquoi ça bloque
            errors = " | ".join(self.last_error_log)
            return f"ERREUR IA : Impossible de charger un modèle. Détails : {errors}"

        # Construction du Prompt
        if isinstance(data, str):
            prompt = f"Tu es l'IA Energistrat. Réponds à : {data}"
        else:
            prompt = f"Agis en expert énergie ({profile}). Analyse : Vol {data['volume_mwh']} MWh, Pic {data['pic_kw']} kW. Conseil court."

        try:
            # APPEL DIFFÉRENCIÉ SELON LE MODÈLE
            if self.model_type == "gemini":
                response = self.model.generate_content(prompt)
                return response.text
            elif self.model_type == "bison":
                # Bison utilise .predict() et non .generate_content()
                response = self.model.predict(prompt, temperature=0.2, max_output_tokens=256)
                return response.text
            else:
                return "Erreur interne type modèle."

        except Exception as e:
            return f"ERREUR RUNTIME ({self.active_model_name}) : {str(e)}"

    async def analyze_file(self, file_content, filename, target_profile="industry"):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # Lecture
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python')
                except: 
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier vide"}

            # Nettoyage
            df.columns = [str(c).lower().strip().replace('"','').replace("'", "") for c in df.columns]
            col_val = next((c for c in df.columns if any(x in c for x in ['puiss', 'p10', 'conso', 'val', 'kw'])), None)
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horo', 'time'])), None)
            
            if not col_val or not col_date: return {"success": False, "error": "Colonnes introuvables"}

            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

            # KPI
            total = df[col_val].sum()
            vol = total / 6 if ('kw' in col_val and 'kwh' not in col_val) else total
            
            kpis = {
                "volume_mwh": round(self.clean_number(vol/1000), 2),
                "pic_kw": round(self.clean_number(df[col_val].max()), 2),
                "talon_kw": round(self.clean_number(df[col_val].min()), 2),
                "points_traites": int(len(df))
            }

            # APPEL IA
            ai_msg = self.generate_ai_insight(kpis, profile=target_profile)

            # Chart
            step = max(1, len(df)//200)
            df_chart = df.iloc[::step]
            
            chart_values = [self.clean_number(x) for x in df_chart[col_val].tolist()]
            chart_labels = df_chart[col_date].dt.strftime('%d/%m %H:%M').tolist()

            return {
                "success": True, 
                "kpi": kpis, 
                "ai_insight": ai_msg,
                "chart": { "labels": chart_labels, "values": chart_values }
            }
        except Exception as e:
            return {"success": False, "error": f"Moteur: {str(e)}"}

    def ask_agent(self, query):
        if query == "#model":
            return f"Modèle actif : {self.active_model_name} ({self.model_type})"
        return self.generate_ai_insight(query, profile="ops")

    def run_chaos_monkey(self): return []
    def simulate_audit(self, f): return {"score": 100}

cortex = CortexEngine()
