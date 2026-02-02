# app/core/cortex_engine.py V14.0 - MIGRATED TO V3 ARCHITECTURE
import pandas as pd
import numpy as np
import io
import re
import requests
import math
from datetime import datetime

# Gestion optionnelle des dépendances lourdes
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "14.0"
        
        # --- BASE DE DONNÉES SECTORIELLE (NAF) ---
        # C'est ton trésor de guerre. Je l'ai gardé intact.
        self.NAF_DB = {
            "10.71C": {"label": "Boulangerie", "profile": "BAKERY", "keywords": ["BOULANGERIE", "PAIN", "FOURNIL"]},
            "10.71D": {"label": "Pâtisserie", "profile": "BAKERY", "keywords": ["PATISSERIE"]},
            "10.11Z": {"label": "Transformation Viande", "profile": "COLD", "keywords": ["BOUCHERIE", "ABATTOIR"]},
            "47.11":  {"label": "Supermarché", "profile": "COLD", "keywords": ["SUPERMARCHE", "MARKET", "SUPER"]},
            "55.10Z": {"label": "Hôtellerie", "profile": "CONTINUOUS", "keywords": ["HOTEL", "CHAMBRE"]},
            "68.20B": {"label": "Bureaux", "profile": "OFFICE", "keywords": ["BUREAU", "SIEGE", "AGENCE"]},
            "EP":     {"label": "Éclairage Public", "profile": "INVERSE", "keywords": ["EP", "ECLAIRAGE", "LUM"]}
            # ... (J'ai abrégé pour la lisibilité, mais tu peux remettre toute ta liste ici)
        }

    # --- SÉCURITÉ MATHÉMATIQUE ---
    def _safe_int(self, value):
        try: return 0 if (pd.isna(value) or np.isinf(value)) else int(value)
        except: return 0

    def _safe_float(self, value):
        try: return 0.0 if (pd.isna(value) or np.isinf(value)) else float(value)
        except: return 0.0

    # ==========================================================================
    # 1. ORCHESTRATEUR PRINCIPAL (Appelé par main.py)
    # ==========================================================================
    def analyze_file(self, file_content, filename, target_profile="demo"):
        """
        Point d'entrée unique pour l'analyse.
        Transforme un fichier brut en JSON structuré pour le Dashboard.
        """
        try:
            # A. INGESTION
            df, time_step_hours = self._parse_data(file_content, filename)
            if df is None or df.empty: 
                return {"success": False, "error": "Fichier illisible ou vide"}

            # B. CONTEXTE (Météo & NAF)
            zip_code = self._extract_zipcode_smart(filename)
            geo_data = self._fetch_geo_data(zip_code)
            naf_info = self._detect_naf_advanced(filename)
            
            # C. CALCULS EXPERTS
            base = self._module_socle(df, time_step_hours)
            turpe = self._module_turpe(df, base['p_max'])
            season = self._module_saison(df)
            finance = self._module_finance(df, time_step_hours)
            
            # D. DATA VISUALISATION (Downsampling pour le web)
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step]
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart)
            }

            # E. NARRATIVE (Cerveau Texte)
            narrative = self._generate_expert_narrative({**base, **turpe, **finance, "geo": geo_data, "sectoriel": naf_info}, target_profile)

            return {
                "success": True,
                "kpi": {**base, **turpe, **season, **finance, "geo": geo_data, "sectoriel": naf_info},
                "chart": chart,
                "ai_insight": narrative
            }

        except Exception as e:
            print(f"[CORTEX ERROR] {str(e)}")
            return {"success": False, "error": f"Erreur interne Cortex: {str(e)}"}

    # ==========================================================================
    # 2. MODULES DE CALCUL (Tes algos V13)
    # ==========================================================================
    
    def _parse_data(self, content, filename):
        try:
            buffer = io.BytesIO(content)
            df = None
            # Support CSV & Excel
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python')
                except: buffer.seek(0); df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else: 
                df = pd.read_excel(buffer)

            # Normalisation des colonnes
            df.columns = [str(c).lower().strip() for c in df.columns]
            
            # Détection intelligente des colonnes
            c_date = next((c for c in df.columns if any(x in c for x in ['date','horo','time'])), df.columns[0])
            c_val = next((c for c in df.columns if any(x in c for x in ['puiss','p10','conso','val','kw'])), df.columns[1])

            # Conversion
            df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').replace(' ', ''), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')

            df = df.dropna(subset=['date'])
            df['val'] = df['val'].fillna(0).replace([np.inf, -np.inf], 0)
            df = df.sort_values(by='date')
            
            # Correction d'échelle (Watts vs kW)
            if df['val'].median() > 2000: df['val'] = df['val'] / 1000
            
            # Détection du pas de temps
            time_step = 0.166 # Par défaut 10 min
            if len(df) > 1:
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: time_step = delta / 3600

            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step
        except Exception as e:
            print(f"Parse Error: {e}")
            return None, 0.166

    def _module_socle(self, df, time_step):
        values = df['val'].tolist()
        p_max = max(values) if values else 0
        conso_kwh = sum(values) * time_step
        
        # Calcul Talon (Bruit de fond)
        pos_vals = [v for v in values if v > 0]
        talon = float(np.percentile(pos_vals, 10)) if pos_vals else 0.0

        return {
            "points_traites": len(values),
            "conso_totale": self._safe_int(conso_kwh),
            "p_max": self._safe_float(p_max),
            "talon": self._safe_int(talon),
            "moyenne": self._safe_float(np.mean(values)),
            "diagnosis": "Analyse V3 OK",
            "status": "OK"
        }

    def _module_turpe(self, df, pmax):
        opti = pmax * 1.05
        return {"turpe_optimisation": {"p_recommandee": self._safe_int(opti)}}

    def _module_finance(self, df, time_step):
        # Simulation simple HP/HC (22h-06h)
        df['h'] = df['date'].dt.hour
        mask_hc = (df['h'] >= 22) | (df['h'] < 6)
        conso_hc = df[mask_hc]['val'].sum() * time_step
        conso_hp = df[~mask_hc]['val'].sum() * time_step
        budg = (conso_hp * 0.18) + (conso_hc * 0.12)
        return {"finance": {"budget_total_estime": self._safe_int(budg)}}

    def _module_saison(self, df):
        df['m'] = df['date'].dt.month
        hiver = df[df['m'].isin([11,12,1,2,3])]['val'].mean()
        ete = df[~df['m'].isin([11,12,1,2,3])]['val'].mean()
        sens = "Neutre"
        if hiver > ete*1.5: sens = "Chauffage Elec."
        elif ete > hiver*1.2: sens = "Climatisation"
        return {"saisonnalite": {"sensibilite": sens}}

    # --- INTELLIGENCE SECTORIELLE ---
    def _detect_naf_advanced(self, filename):
        fn = filename.upper()
        # Recherche par Code ou Mot-clé
        for code, info in self.NAF_DB.items():
            if code in fn: return {"code": code, **info}
            for kw in info["keywords"]:
                if kw in fn: return {"code": code, **info}
        return {"code": "NA", "label": "Standard", "profile": "STANDARD"}

    def _extract_zipcode_smart(self, filename):
        matches = re.findall(r'(?<!\d)(\d{5})(?!\d)', filename)
        return matches[-1] if matches else "75001"

    def _fetch_geo_data(self, zipcode):
        # Mock pour éviter latence API externe au démarrage, à réactiver si besoin
        return {"city": f"Ville ({zipcode})", "lat": 48.85, "lon": 2.35, "zip": zipcode}

    def _generate_expert_narrative(self, k, p):
        txt = f"<b>ANALYSE V3 ({p.upper()}) :</b><br>"
        txt += f"• Conso Totale : {k['conso_totale']:,} kWh.<br>"
        txt += f"• Puissance Max : {k['p_max']} kW.<br>"
        if 'sectoriel' in k:
            txt += f"• Profil Détecté : <b>{k['sectoriel']['label']}</b>.<br>"
        return txt

# Instance unique
cortex = CortexEngine()
