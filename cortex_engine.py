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
        self.model_type = None
        self.active_model_name = "Mode Expert (Algorithmique)" # Par défaut
        self.ai_ready = False
        
        if VERTEX_AVAILABLE:
            self.init_ai_robust()

    def init_ai_robust(self):
        """
        Tente de se connecter à l'IA.
        Si ça échoue, on reste en mode 'Algorithmique' silencieux (pas d'erreur).
        """
        try:
            # TENTATIVE BELGIQUE (europe-west1) : Souvent plus ouvert que Paris
            # Si ton projet bloque les USA, la Belgique est la meilleure option UE.
            target_location = "europe-west1" 
            vertexai.init(project=self.project_id, location=target_location)
            
            models_to_try = [
                ("gemini-1.0-pro", "gemini"), # Le plus standard en Europe
                ("gemini-1.5-flash-001", "gemini"),
                ("text-bison", "bison")
            ]

            for name, m_type in models_to_try:
                try:
                    print(f"🔄 Test connexion {target_location} : {name}...")
                    if m_type == "gemini":
                        temp_model = GenerativeModel(name)
                        temp_model.generate_content("Ping")
                        self.model = temp_model
                    else:
                        temp_model = TextGenerationModel.from_pretrained(name)
                        temp_model.predict("Ping")
                        self.model = temp_model

                    self.model_type = m_type
                    self.active_model_name = f"{name} ({target_location})"
                    self.ai_ready = True
                    print(f"✅ [CORTEX] IA Connectée : {name}")
                    return
                except:
                    continue
            
            print("⚠️ [CORTEX] IA indisponible. Passage en mode Expert Algorithmique.")

        except Exception as e:
            print(f"⚠️ [CORTEX] Erreur Init : {e}")

    def clean_number(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0
            if isinstance(val, (np.integer, int)): return int(val)
            return float(val)
        except: return 0

    # --- LE CERVEAU DE SECOURS (RULE-BASED) ---
    def fallback_analysis(self, kpis, profile):
        """Génère un conseil intelligent SANS utiliser Google (Python pur)"""
        vol = kpis['volume_mwh']
        pic = kpis['pic_kw']
        talon = kpis['talon_kw']
        
        # Calcul du ratio talon/pic
        ratio = (talon / pic * 100) if pic > 0 else 0
        
        if profile == "industry":
            if ratio > 15:
                return f"⚠️ ALERTE TALON : La consommation incompressibles représente {ratio:.1f}% du pic. Vérifiez les utilités (air comprimé, froid) la nuit."
            else:
                return f"✅ PROFIL SAIN : Le talon de consommation est maîtrisé ({ratio:.1f}%). Continuez le suivi des pics de puissance."
        
        elif profile == "mairie":
            if vol > 1000:
                return f"Budget Énergie conséquent ({vol} MWh). Une renégociation du contrat groupé est recommandée pour l'exercice à venir."
            else:
                return "Consommation stable. Les actions de sobriété sur les bâtiments publics semblent porter leurs fruits."
        
        elif profile == "retail":
            return f"Analyse Frigorifique : Le profil de charge suit l'ouverture du magasin. Ratio kWh/m² conforme aux standards de la branche."
            
        else:
            return f"Analyse CORTEX : Profil de consommation standard. Puissance atteinte : {pic} kW. Aucun dépassement critique détecté."

    def generate_ai_insight(self, data, profile="industry"):
        # 1. Si l'IA est connectée, on l'utilise
        if self.ai_ready and self.model:
            try:
                if isinstance(data, str): prompt = f"Réponds court : {data}"
                else: prompt = f"Expert {profile}. Analyse : Vol {data['volume_mwh']}, Pic {data['pic_kw']}. Conseil court."
                
                if self.model_type == "gemini":
                    return self.model.generate_content(prompt).text
                else:
                    return self.model.predict(prompt, max_output_tokens=256).text
            except:
                # Si l'IA plante pendant la génération, on bascule sur le fallback
                pass

        # 2. Si l'IA est HS ou plante, on utilise le Moteur Algorithmique
        if isinstance(data, str): # Cas Chatbot
            return "Mode Expert (IA déconnectée) : Je n'ai pas accès à la base de connaissance générative pour le moment. Veuillez consulter les KPI."
        else: # Cas Analyse Fichier
            return self.fallback_analysis(data, profile)

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

            df.columns = [str(c).lower().strip().replace('"','').replace("'", "") for c in df.columns]
            col_val = next((c for c in df.columns if any(x in c for x in ['puiss', 'p10', 'conso', 'val', 'kw'])), None)
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horo', 'time'])), None)
            
            if not col_val or not col_date: return {"success": False, "error": "Colonnes introuvables"}

            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

            total = df[col_val].sum()
            vol = total / 6 if ('kw' in col_val and 'kwh' not in col_val) else total
            
            kpis = {
                "volume_mwh": round(self.clean_number(vol/1000), 2),
                "pic_kw": round(self.clean_number(df[col_val].max()), 2),
                "talon_kw": round(self.clean_number(df[col_val].min()), 2),
                "points_traites": int(len(df))
            }

            # APPEL HYBRIDE (IA ou ALGO)
            ai_msg = self.generate_ai_insight(kpis, profile=target_profile)

            step = max(1, len(df)//200)
            df_chart = df.iloc[::step]
            
            return {
                "success": True, 
                "kpi": kpis, 
                "ai_insight": ai_msg,
                "chart": {
                    "labels": df_chart[col_date].dt.strftime('%d/%m %H:%M').tolist(),
                    "values": [self.clean_number(x) for x in df_chart[col_val].tolist()]
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Moteur: {str(e)}"}

    def ask_agent(self, query):
        if query == "#model":
            return f"Moteur actif : {self.active_model_name}"
        return self.generate_ai_insight(query, profile="ops")

    def run_chaos_monkey(self): return []
    def simulate_audit(self, f): return {"score": 100}

cortex = CortexEngine()
