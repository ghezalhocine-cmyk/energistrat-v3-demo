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
        self.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "energistrat-saas")
        self.model = None
        self.ai_ready = False
        
        # INITIALISATION IA (GEMINI PRO)
        if VERTEX_AVAILABLE:
            try:
                # --- FIX V4.2 : PASSAGE EN US-CENTRAL1 POUR FIABILITÉ ---
                vertexai.init(project=self.project_id, location="us-central1")
                
                # Chargement du modèle Gemini Pro
                self.model = GenerativeModel("gemini-1.0-pro")
                self.ai_ready = True
                print("✅ [CORTEX] Cerveau connecté à Google Gemini Pro (US-Central1).")
            except Exception as e:
                print(f"⚠️ [CORTEX] Erreur connexion Vertex AI : {e}")
                # Fallback simulation si l'API n'est pas active ou erreur de quota
                self.ai_ready = False

    def safe_value(self, val):
        """Nettoyage des valeurs numériques"""
        try:
            if pd.isna(val) or np.isinf(val): return 0.0
            return float(val)
        except: return 0.0

    # --- PROMPT FACTORY : LA PERSONNALITÉ DE L'IA ---
    def get_prompt_for_profile(self, profile, kpis):
        """Génère un prompt adapté au métier du client"""
        
        # Cas spécial pour le Chatbot Ops (Query libre)
        if isinstance(kpis, str):
            return f"""
            Tu es CORTEX, l'IA centrale du SaaS Energistrat.
            Réponds à l'administrateur Ops de manière technique, brève et précise (Style Cyberpunk).
            Question : "{kpis}"
            """

        base_data = f"Données : Volume {kpis['volume_mwh']} MWh, Pic {kpis['pic_kw']} kW, Talon {kpis['talon_kw']} kW."

        if profile == "industry":
            return f"""
            Tu es un Ingénieur Énergéticien Senior pour une industrie Seveso.
            Analyse ces données : {base_data}
            Ton objectif : Identifier les gisements d'économies techniques (Optimisation process, effacement).
            Rédige un conseil technique, précis et chiffré en 2 phrases maximum.
            Ton : Expert, direct, focalisé sur le ROI.
            """
        elif profile == "mairie":
            return f"""
            Tu es un Conseiller en Transition Écologique pour une Mairie.
            Analyse ces données : {base_data}
            Ton objectif : Rassurer sur le budget et valoriser les économies pour le Conseil Municipal.
            Rédige une note de synthèse politique et pédagogique en 2 phrases.
            Ton : Institutionnel, rassurant, orienté "Service Public".
            """
        elif profile == "retail":
            return f"""
            Tu es un Cost-Killer pour une chaîne de magasins.
            Analyse ces données : {base_data}
            Ton objectif : Comparer la performance par rapport aux autres magasins (Benchmarking).
            Rédige un conseil agressif sur la réduction des charges (Froid/Eclairage) en 2 phrases.
            Ton : Business, rapide, challengeant.
            """
        elif profile == "sde":
            return f"""
            Tu es un Analyste de Données Territoriales.
            Analyse ces données : {base_data}
            Ton objectif : Avoir une vision macroscopique du territoire.
            Rédige une observation sur la charge globale du réseau en 2 phrases.
            Ton : Analytique, macro, visionnaire.
            """
        else:
            # Défaut (PME, Syndic, etc.)
            return f"""
            Tu es un Expert Énergie.
            Analyse ces données : {base_data}
            Donne un conseil simple pour réduire la facture en 2 phrases.
            """

    # --- GÉNÉRATION D'INSIGHTS (MOTEUR LLM) ---
    def generate_ai_insight(self, data, profile="industry"):
        """
        Appelle Google Gemini pour générer le texte
        """
        if not self.ai_ready:
            return "Mode Simulation : Le profil de consommation est stable. Activez l'API Vertex AI (US-Central1) pour une analyse sémantique réelle."

        prompt = self.get_prompt_for_profile(profile, data)

        try:
            # Appel à Gemini
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"❌ Erreur Génération Gemini : {e}")
            return "Erreur IA : Impossible de générer le conseil pour le moment."

    # --- INGESTION SGE (Code V3.14 optimisé) ---
    async def analyze_file(self, file_content, filename, target_profile="industry"):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # Lecture
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python', encoding='utf-8')
                except: 
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier vide"}

            # Nettoyage
            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horodate', 'heure', 'timestamp'])), None)
            col_val = next((c for c in df.columns if any(x in c for x in ['puissance', 'p10', 'conso', 'valeur', 'kwh', 'kw'])), None)

            if not col_date or not col_val: return {"success": False, "error": "Colonnes inconnues"}

            # Traitement
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').replace(' ', '')
                df[col_val] = pd.to_numeric(df[col_val], errors='coerce')
            df[col_val] = df[col_val].fillna(0)

            # KPI
            is_power = 'kw' in col_val and 'kwh' not in col_val
            total_sum = df[col_val].sum()
            vol_kwh = total_sum / 6 if is_power else total_sum
            
            kpis = {
                "volume_mwh": round(self.safe_value(vol_kwh / 1000), 2),
                "pic_kw": round(self.safe_value(df[col_val].max()), 2),
                "talon_kw": round(self.safe_value(df[col_val].min()), 2),
                "points_traites": len(df)
            }

            # --- APPEL INTELLIGENT ---
            # On passe le profil cible pour avoir un conseil adapté
            ai_message = self.generate_ai_insight(kpis, profile=target_profile)

            # Chart Sampling (Pour affichage rapide)
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

    # --- AUTRES FONCTIONS ---
    
    # Chatbot Ops : Appelle l'IA avec le contexte "ops"
    def ask_agent(self, query):
        return self.generate_ai_insight(query, profile="ops")

    # Chaos Monkey : Teste la connexion Vertex AI
    def run_chaos_monkey(self): 
        return [{"test": "Vertex AI Ping", "status": "PASS" if self.ai_ready else "FAIL"}]
    
    # Audit : Placeholder
    def simulate_audit(self, f): 
        return {"score": 100}

# Instantiation unique
cortex = CortexEngine()
