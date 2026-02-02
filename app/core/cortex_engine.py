# app/core/cortex_engine.py V18.1 - ULTIMATE (FULL NAF + QUANTUM + IA)
import pandas as pd
import numpy as np
import io
import re
import math
import os
from datetime import datetime

# 1. GESTION DES DÉPENDANCES INTELLIGENTES
# PDF
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# VERTEX AI (Google Cloud)
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    # Initialisation automatique sur Cloud Run
    vertexai.init(location="europe-west9") 
    AI_MODEL = GenerativeModel("gemini-1.5-flash-001")
    AI_AVAILABLE = True
except Exception as e:
    print(f"[CORTEX WARN] Vertex AI non dispo (Mode Maths uniquement): {e}")
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "18.1 (Ultimate Edition)"
        
        # --- BASE DE CONNAISSANCE EXPERTE (50+ PROFILS) ---
        self.NAF_DB = {
            # --- ENSEIGNEMENT & PUBLIC ---
            "85.10Z": {"label": "École Maternelle", "profile": "SCHOOL", "keywords": ["MATERNELLE", "PETITE ENFANCE"]},
            "85.20Z": {"label": "École Primaire", "profile": "SCHOOL", "keywords": ["ECOLE", "PRIMAIRE", "SCOLAIRE", "GROUPE SCOLAIRE"]},
            "85.31Z": {"label": "Collège/Lycée", "profile": "SCHOOL", "keywords": ["COLLEGE", "LYCEE", "CITE SCOLAIRE", "POLYVALENT"]},
            "85.59A": {"label": "Formation Continue", "profile": "SCHOOL", "keywords": ["FORMATION", "ADULTE"]},
            "84.11Z": {"label": "Mairie/Administration", "profile": "OFFICE", "keywords": ["MAIRIE", "HOTEL DE VILLE", "PREFECTURE", "ADMINISTRATION"]},
            "93.11Z": {"label": "Gymnase/Stade", "profile": "SPORT", "keywords": ["GYMNASE", "STADE", "PISCINE", "COMPLEXE SPORTIF"]},
            "EP":     {"label": "Éclairage Public", "profile": "INVERSE", "keywords": ["EP", "ECLAIRAGE", "LUM", "LAMPADAIRE"]},

            # --- ALIMENTATION & COMMERCE ---
            "10.71C": {"label": "Boulangerie", "profile": "BAKERY", "keywords": ["BOULANGERIE", "PAIN", "FOURNIL"]},
            "10.71D": {"label": "Pâtisserie", "profile": "BAKERY", "keywords": ["PATISSERIE"]},
            "10.11Z": {"label": "Transformation Viande", "profile": "COLD", "keywords": ["BOUCHERIE", "ABATTOIR", "VIANDE"]},
            "10.51A": {"label": "Laiterie/Fromagerie", "profile": "COLD", "keywords": ["LAIT", "FROMAGE"]},
            "47.11":  {"label": "Supermarché", "profile": "COLD", "keywords": ["SUPERMARCHE", "MARKET", "SUPER"]},
            "47.11D": {"label": "Supermarché", "profile": "COLD", "keywords": ["SUPER"]},
            "47.11F": {"label": "Hyper", "profile": "COLD", "keywords": ["HYPER", "GRAND SURFACE"]},
            "47.22Z": {"label": "Boucherie Détail", "profile": "COLD", "keywords": ["BOUCHERIE"]},

            # --- HORECA (Hôtels, Restos) ---
            "55.10Z": {"label": "Hôtellerie", "profile": "CONTINUOUS", "keywords": ["HOTEL", "CHAMBRE", "HEBERGEMENT"]},
            "56.10A": {"label": "Restauration Traditionnelle", "profile": "SERVICE", "keywords": ["RESTAURANT", "RESTO", "AUBERGE"]},
            "56.10C": {"label": "Restauration Rapide", "profile": "SERVICE", "keywords": ["SNACK", "BURGER", "FAST FOOD"]},
            "56.21Z": {"label": "Traiteur", "profile": "SERVICE", "keywords": ["TRAITEUR", "CUISINE CENTRALE"]},

            # --- SANTÉ ---
            "86.10Z": {"label": "Hôpital", "profile": "CONTINUOUS", "keywords": ["HOPITAL", "CHU", "CLINIQUE"]},
            "87.10A": {"label": "EHPAD", "profile": "CONTINUOUS", "keywords": ["EHPAD", "MAISON DE RETRAITE", "RESIDENCE SENIOR"]},
            "86.21Z": {"label": "Médecin Généraliste", "profile": "OFFICE", "keywords": ["CABINET", "MEDECIN"]},

            # --- INDUSTRIE ---
            "25.11Z": {"label": "Métallurgie", "profile": "PROCESS", "keywords": ["METAL", "ACIER", "STRUCTURE"]},
            "22.29A": {"label": "Plasturgie", "profile": "PROCESS", "keywords": ["PLASTIQUE", "INJECTION", "MOULAGE"]},
            "20.14Z": {"label": "Chimie", "profile": "PROCESS", "keywords": ["CHIMIE", "PHARMA", "LABO"]},
            "16.10A": {"label": "Scierie", "profile": "PROCESS", "keywords": ["BOIS", "SCIERIE"]},
            "25.62B": {"label": "Mécanique Industrielle", "profile": "PROCESS", "keywords": ["MECANIQUE", "USINAGE", "DECOLLETAGE"]},
            "28.29A": {"label": "Fabrication Machines", "profile": "PROCESS", "keywords": ["MACHINE", "INDUSTRIE"]},
            "33.12Z": {"label": "Réparation Machines", "profile": "PROCESS", "keywords": ["MAINTENANCE", "ATELIER"]},

            # --- TERTIAIRE & TECH ---
            "68.20B": {"label": "Bureaux/Immobilier", "profile": "OFFICE", "keywords": ["BUREAU", "SIEGE", "AGENCE", "SCI"]},
            "64.19Z": {"label": "Banque/Assurance", "profile": "OFFICE", "keywords": ["BANQUE", "ASSURANCE", "MUTUELLE"]},
            "62.01Z": {"label": "Informatique", "profile": "OFFICE", "keywords": ["IT", "DEV", "LOGICIEL"]},
            "63.11Z": {"label": "Data Center", "profile": "FLAT_LINE", "keywords": ["DATA", "SERVER", "CLOUD", "HEBERGEMENT WEB"]},
            "61.10Z": {"label": "Télécoms", "profile": "FLAT_LINE", "keywords": ["TELECOM", "RESEAU", "ANTENNE"]},
            "70.10Z": {"label": "Siège Social", "profile": "OFFICE", "keywords": ["SIEGE", "HOLDING"]}
        }

    def _safe_int(self, value):
        try: return 0 if (pd.isna(value) or np.isinf(value)) else int(value)
        except: return 0

    def _safe_float(self, value):
        try: return 0.0 if (pd.isna(value) or np.isinf(value)) else float(value)
        except: return 0.0

    # ==========================================================================
    # 1. ORCHESTRATEUR HYBRIDE
    # ==========================================================================
    def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            # A. INGESTION (Maths)
            df, time_step_hours = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Données illisibles"}

            # B. PROFILAGE (Maths + Base NAF Complète)
            naf_input = self._detect_naf_advanced(filename)
            profiling = self._universal_profiler(df, naf_input)
            
            # C. CALCULS EXPERTS (Moteur Quantum V17)
            base = self._module_socle(df, time_step_hours)
            solar = self._module_solar_opportunity(df, time_step_hours)
            drift = self._module_drift_detection(df)
            waste = self._module_ghost_buster(df, base['talon'], time_step_hours)
            finance = self._module_finance_pro(df, time_step_hours, base['p_max'])
            opti = self._module_turpe_sniper(df, base['p_max'])
            carbon = self._module_carbon(base['conso_totale'])

            # D. DATA VISUALISATION
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step]
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart),
                "talon_line": [base['talon']] * len(df_chart)
            }

            # E. NARRATIF HYBRIDE (Maths -> JSON -> AI)
            full_kpi = {
                **base, **solar, **drift, **waste, **finance, **opti, **carbon, 
                "profiling": profiling,
                "sectoriel": naf_input, # On passe l'info NAF précise à l'IA
                "meta": {"filename": filename, "profile": target_profile}
            }
            
            # GÉNÉRATION DU TEXTE (Vertex AI ou Template de secours)
            narrative = self._generate_hybrid_insight(full_kpi)

            return {
                "success": True,
                "kpi": full_kpi,
                "chart": chart,
                "ai_insight": narrative
            }
        except Exception as e:
            print(f"[HYBRID ERROR] {str(e)}")
            return {"success": False, "error": f"Erreur Analyse: {str(e)}"}

    # ==========================================================================
    # 2. CERVEAU GENERATIF (VERTEX AI)
    # ==========================================================================
    def _generate_hybrid_insight(self, kpi_data):
        if AI_AVAILABLE:
            try:
                return self._ask_vertex_for_strategy(kpi_data)
            except Exception as e:
                print(f"[VERTEX FAIL] Fallback. Error: {e}")
        return self._generate_template_narrative(kpi_data)

    def _ask_vertex_for_strategy(self, data):
        prompt = f"""
        Tu es un Consultant Expert en Stratégie Énergétique.
        Analyse les données techniques (JSON) ci-dessous pour le site "{data['sectoriel']['label']}" ({data['profiling']['archetype']}).
        
        Données :
        - Budget annuel estimé : {data['finance']['budget_total']} €
        - Gaspillage talon (bâtiment vide) : {data['ghost_buster']['cout_talon_annuel']} €/an
        - Santé (Dérive) : {data['drift']['status']} ({data['drift']['message']})
        - Solaire : {data['solar'].get('status', 'Non')} (Gain: {data['solar'].get('economie_annuelle_euro', 0)} €/an)
        - Contrat : Souscrire {data['optimisation']['p_souscrite_ideale']} kVA au lieu de {data['optimisation']['p_max_atteinte']} kVA.

        Rédige une synthèse courte (5 lignes max) format HTML (pas de markdown), ton direct et business.
        Mets en gras les montants d'économies.
        """
        response = AI_MODEL.generate_content(prompt)
        return response.text

    def _generate_template_narrative(self, k):
        prof = k['profiling']
        solar = k.get('solar', {})
        drift = k.get('drift', {})
        ghost = k['ghost_buster']
        
        txt = f"<b>ANALYSE EXPERTE ({k['sectoriel']['label'].upper()}) :</b><br><br>"
        
        if drift['status'] != "STABLE":
            txt += f"🚨 <b>Alerte Santé :</b> {drift['message']}<br>"
            
        if solar.get('status') == "OPPORTUNITÉ DÉTECTÉE":
            txt += f"☀️ <b>Solaire :</b> Potentiel de gain de <span style='color:#00E5FF'><b>{solar['economie_annuelle_euro']} €/an</b></span>.<br>"
            
        txt += f"👻 <b>Gaspillage :</b> {ghost['cout_talon_annuel']:,} €/an perdus (bâtiment vide).<br>"
        txt += f"💰 <b>Budget :</b> {k['finance']['budget_total']:,} €/an."
        return txt

    # ==========================================================================
    # 3. MODULES CALCULS (V17 QUANTUM)
    # ==========================================================================
    
    def _module_solar_opportunity(self, df, time_step):
        df['h'] = df['date'].dt.hour
        sun_hours = df[(df['h'] >= 10) & (df['h'] <= 16)]
        mean_sun_load_kw = sun_hours['val'].mean()
        puissance_installable_kwc = math.floor((mean_sun_load_kw * 0.8) / 0.8)
        
        if puissance_installable_kwc < 3:
            return {"solar": {"status": "NON PERTINENT"}}
            
        prod_annuelle_kwh = puissance_installable_kwc * 1100
        economie_annuelle = prod_annuelle_kwh * 0.20
        roi_years = round((puissance_installable_kwc * 1000) / economie_annuelle, 1) if economie_annuelle > 0 else 99
        
        return {"solar": {"status": "OPPORTUNITÉ DÉTECTÉE", "puissance_kwc": puissance_installable_kwc, "economie_annuelle_euro": self._safe_int(economie_annuelle), "roi_ans": roi_years}}

    def _module_drift_detection(self, df):
        mid_point = len(df) // 2
        part1 = df.iloc[:mid_point]
        part2 = df.iloc[mid_point:]
        talon1 = np.percentile(part1[part1['val']>0]['val'], 10) if not part1.empty else 0
        talon2 = np.percentile(part2[part2['val']>0]['val'], 10) if not part2.empty else 0
        if talon1 == 0: return {"drift": {"status": "STABLE", "message": "RAS"}}
        variation = ((talon2 - talon1) / talon1) * 100
        status = "STABLE"
        msg = "Consommation stable."
        if variation > 10: status, msg = "DÉRIVE CRITIQUE", f"Explosion du talon (+{int(variation)}%)."
        elif variation > 5: status, msg = "DÉRIVE LÉGÈRE", f"Hausse du talon (+{int(variation)}%)."
        elif variation < -5: status, msg = "AMÉLIORATION", f"Baisse du talon (-{abs(int(variation))}%)"
        return {"drift": {"status": status, "variation_pct": round(variation, 1), "message": msg}}

    def _module_ghost_buster(self, df, talon, time_step):
        cout_talon_annuel = talon * 8760 * 0.16
        return {"ghost_buster": {"cout_talon_annuel": self._safe_int(cout_talon_annuel)}}

    def _universal_profiler(self, df, naf_info):
        df['h'] = df['date'].dt.hour
        mean_nuit = df[(df['h'] >= 1) & (df['h'] <= 4)]['val'].mean()
        mean_jour = df[(df['h'] >= 9) & (df['h'] <= 17)]['val'].mean()
        ratio = (mean_nuit / mean_jour) if mean_jour > 0 else 0
        archetype = "STANDARD"
        if ratio > 0.8: archetype = "CONTINUOUS (Industrie/Santé)"
        elif ratio < 0.2: archetype = "DIURNE (Bureaux/Ecole)"
        return {"archetype": archetype, "label_detecte": naf_info['label']}

    def _module_turpe_sniper(self, df, p_max):
        p_opti = math.ceil(p_max * 1.1)
        return {"optimisation": {"p_max_atteinte": p_max, "p_souscrite_ideale": p_opti}}

    def _module_finance_pro(self, df, time_step, p_max):
        conso = df['val'].sum() * time_step
        budget = (conso * 0.16) + (p_max * 15) + (conso * 0.03)
        return {"finance": {"budget_total": self._safe_int(budget)}}

    def _module_carbon(self, conso_kwh):
        co2 = (conso_kwh * 60) / 1_000_000
        return {"carbone": {"tonnes_co2": round(co2, 2)}}

    def _module_socle(self, df, time_step):
        values = df['val'].tolist()
        p_max = max(values) if values else 0
        conso_kwh = sum(values) * time_step
        pos_vals = [v for v in values if v > 0]
        talon = float(np.percentile(pos_vals, 5)) if pos_vals else 0.0
        return {"conso_totale": self._safe_int(conso_kwh), "p_max": self._safe_float(p_max), "talon": self._safe_int(talon), "moyenne": self._safe_float(np.mean(values))}

    # --- UTILS DE BASE ---
    def _parse_data(self, content, filename):
        try:
            buffer = io.BytesIO(content)
            df = None
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python')
                except: buffer.seek(0); df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else: df = pd.read_excel(buffer)
            df.columns = [str(c).lower().strip() for c in df.columns]
            c_date = next((c for c in df.columns if any(x in c for x in ['date','horo','time'])), df.columns[0])
            c_val = next((c for c in df.columns if any(x in c for x in ['puiss','p10','conso','val','kw'])), df.columns[1])
            df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').replace(' ', ''), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')
            df = df.dropna(subset=['date'])
            df['val'] = df['val'].fillna(0).replace([np.inf, -np.inf], 0)
            df = df.sort_values(by='date')
            if df['val'].median() > 2000: df['val'] = df['val'] / 1000
            time_step = 0.166
            if len(df) > 1:
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: time_step = delta / 3600
            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step
        except: return None, 0.166

    def _detect_naf_advanced(self, filename):
        fn = filename.upper()
        # 1. Priorité Mots-clés
        for code, info in self.NAF_DB.items():
            for kw in info.get("keywords", []):
                if kw in fn: return {"code": code, **info}
        # 2. Regex Code NAF
        naf_regex = re.search(r'\b\d{2}[\.]?\d{2}[A-Z]\b', fn)
        if naf_regex:
            code = naf_regex.group(0).replace('.', '')
            # Recherche exacte ou préfixe
            if code in self.NAF_DB: return {"code": code, **self.NAF_DB[code]}
            prefix = code[:3]
            if prefix in self.NAF_DB: return {"code": code, **self.NAF_DB[prefix]}
        
        return {"code": "NA", "label": "Non Identifié", "profile": "STANDARD"}

# Instance Singleton
cortex = CortexEngine()
