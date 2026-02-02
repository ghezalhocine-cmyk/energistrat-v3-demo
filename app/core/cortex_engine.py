# app/core/cortex_engine.py V18.2 - STABLE PATCH (ANTI-REGRESSION)
import pandas as pd
import numpy as np
import io
import re
import math
import os
from datetime import datetime

# 1. GESTION DES DÉPENDANCES
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    vertexai.init(location="europe-west9") 
    AI_MODEL = GenerativeModel("gemini-1.5-flash-001")
    AI_AVAILABLE = True
except Exception:
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "18.2 (Stable Patch)"
        
        # --- BASE DE CONNAISSANCE (COMPLETE) ---
        self.NAF_DB = {
            "85.": {"label": "Enseignement", "profile": "SCHOOL"},
            "85.10Z": {"label": "École Maternelle", "profile": "SCHOOL", "keywords": ["MATERNELLE"]},
            "85.20Z": {"label": "École Primaire", "profile": "SCHOOL", "keywords": ["ECOLE", "PRIMAIRE"]},
            "85.31Z": {"label": "Collège/Lycée", "profile": "SCHOOL", "keywords": ["COLLEGE", "LYCEE"]},
            "10.": {"label": "Industrie Agro.", "profile": "INDUSTRY"},
            "47.": {"label": "Grand Commerce", "profile": "COMMERCE"},
            "55.": {"label": "Hôtellerie", "profile": "CONTINUOUS"},
            "68.": {"label": "Immobilier/Bureaux", "profile": "OFFICE"},
            "EP":  {"label": "Éclairage Public", "profile": "INVERSE"}
        }

    # --- SÉCURITÉ MATHÉMATIQUE RENFORCÉE (LE FIX) ---
    def _safe_int(self, value):
        """Convertit n'importe quoi en int sans planter (NaN, Inf, None, String)"""
        try:
            if value is None: return 0
            if isinstance(value, (float, np.floating)):
                if np.isnan(value) or np.isinf(value): return 0
            return int(float(value))
        except: return 0

    def _safe_float(self, value):
        """Convertit n'importe quoi en float sans planter"""
        try:
            if value is None: return 0.0
            if isinstance(value, (float, np.floating)):
                if np.isnan(value) or np.isinf(value): return 0.0
            return float(value)
        except: return 0.0

    # ==========================================================================
    # 1. ORCHESTRATEUR
    # ==========================================================================
    def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            # A. INGESTION (Avec Nettoyage NaN immédiat)
            df, time_step_hours = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Données illisibles"}

            # BLINDAGE : On supprime les NaNs avant tout calcul
            df['val'] = df['val'].fillna(0).replace([np.inf, -np.inf], 0)

            # B. PROFILAGE
            naf_input = self._detect_naf_advanced(filename)
            profiling = self._universal_profiler(df, naf_input)
            
            # C. CALCULS EXPERTS
            base = self._module_socle(df, time_step_hours)
            
            # On passe les valeurs sécurisées aux modules
            solar = self._module_solar_opportunity(df, time_step_hours)
            drift = self._module_drift_detection(df)
            waste = self._module_ghost_buster(df, base['talon'], time_step_hours)
            finance = self._module_finance_pro(df, time_step_hours, base['p_max'])
            opti = self._module_turpe_sniper(df, base['p_max'])
            carbon = self._module_carbon(base['conso_totale'])

            # D. DATA VISUALISATION
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step].copy()
            # Sécurité JSON : on remplace les NaN résiduels par None (null en JS) ou 0
            df_chart['val'] = df_chart['val'].fillna(0)
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart),
                "talon_line": [base['talon']] * len(df_chart)
            }

            # E. NARRATIF
            full_kpi = {
                **base, **solar, **drift, **waste, **finance, **opti, **carbon, 
                "profiling": profiling,
                "sectoriel": naf_input,
                "meta": {"filename": filename, "profile": target_profile}
            }
            
            narrative = self._generate_hybrid_insight(full_kpi)

            return {
                "success": True,
                "kpi": full_kpi,
                "chart": chart,
                "ai_insight": narrative
            }
        except Exception as e:
            print(f"[CRITICAL ERROR] {str(e)}")
            # On renvoie l'erreur proprement pour le debug
            return {"success": False, "error": f"Erreur Analyse V18.2: {str(e)}"}

    # ==========================================================================
    # 2. IA & GENERATION
    # ==========================================================================
    def _generate_hybrid_insight(self, kpi_data):
        if AI_AVAILABLE:
            try: return self._ask_vertex_for_strategy(kpi_data)
            except: pass
        return self._generate_template_narrative(kpi_data)

    def _ask_vertex_for_strategy(self, data):
        prompt = f"""
        Agis comme un Consultant Énergie Senior.
        Données techniques du site "{data['sectoriel']['label']}" :
        - Budget annuel : {data['finance']['budget_total']} €
        - Gaspillage talon : {data['ghost_buster']['cout_talon_annuel']} €/an
        - Santé : {data['drift']['message']}
        - Solaire : {data['solar'].get('status', 'Non')} (Gain: {data['solar'].get('economie_annuelle_euro', 0)} €/an)
        
        Rédige une synthèse stratégique de 4-5 lignes en HTML (gras sur les économies). Sois direct.
        """
        response = AI_MODEL.generate_content(prompt)
        return response.text

    def _generate_template_narrative(self, k):
        prof = k['profiling']
        solar = k.get('solar', {})
        drift = k.get('drift', {})
        ghost = k['ghost_buster']
        
        txt = f"<b>ANALYSE V18 ({k['sectoriel']['label']}) :</b><br><br>"
        txt += f"🏭 <b>Profil :</b> {prof['label_detecte']} ({prof['archetype']})<br>"
        if drift['status'] != "STABLE": txt += f"🚨 <b>Santé :</b> {drift['message']}<br>"
        if solar.get('status') == "OPPORTUNITÉ DÉTECTÉE":
            txt += f"☀️ <b>Solaire :</b> Gain potentiel de <span style='color:#00E5FF'><b>{solar['economie_annuelle_euro']} €/an</b></span>.<br>"
        txt += f"👻 <b>Gaspillage :</b> {ghost['cout_talon_annuel']:,} €/an (Talon).<br>"
        return txt

    # ==========================================================================
    # 3. MODULES CALCULS ROBUSTES
    # ==========================================================================
    def _module_solar_opportunity(self, df, time_step):
        try:
            df['h'] = df['date'].dt.hour
            sun_hours = df[(df['h'] >= 10) & (df['h'] <= 16)]
            if sun_hours.empty: return {"solar": {"status": "DONNÉES INSUFFISANTES"}}
            
            mean_sun_load_kw = sun_hours['val'].mean()
            puissance_installable_kwc = math.floor((mean_sun_load_kw * 0.8) / 0.8)
            
            if puissance_installable_kwc < 3:
                return {"solar": {"status": "NON PERTINENT"}}
                
            prod_annuelle_kwh = puissance_installable_kwc * 1100
            economie_annuelle = prod_annuelle_kwh * 0.20
            roi_years = round((puissance_installable_kwc * 1000) / economie_annuelle, 1) if economie_annuelle > 0 else 99
            
            return {"solar": {
                "status": "OPPORTUNITÉ DÉTECTÉE", 
                "puissance_kwc": self._safe_int(puissance_installable_kwc), 
                "economie_annuelle_euro": self._safe_int(economie_annuelle), 
                "roi_ans": roi_years
            }}
        except: return {"solar": {"status": "ERREUR CALCUL"}}

    def _module_drift_detection(self, df):
        try:
            if len(df) < 100: return {"drift": {"status": "STABLE", "message": "Pas assez de données"}}
            mid_point = len(df) // 2
            part1 = df.iloc[:mid_point]
            part2 = df.iloc[mid_point:]
            
            t1 = np.percentile(part1[part1['val']>0]['val'], 10) if not part1[part1['val']>0].empty else 0
            t2 = np.percentile(part2[part2['val']>0]['val'], 10) if not part2[part2['val']>0].empty else 0
            
            if t1 == 0: return {"drift": {"status": "STABLE", "message": "RAS"}}
            
            variation = ((t2 - t1) / t1) * 100
            status, msg = "STABLE", "Consommation stable."
            
            if variation > 10: status, msg = "DÉRIVE CRITIQUE", f"Explosion du talon (+{int(variation)}%)."
            elif variation > 5: status, msg = "DÉRIVE LÉGÈRE", f"Hausse du talon (+{int(variation)}%)."
            elif variation < -5: status, msg = "AMÉLIORATION", f"Baisse du talon (-{abs(int(variation))}%)"
            
            return {"drift": {"status": status, "variation_pct": round(variation, 1), "message": msg}}
        except: return {"drift": {"status": "ERREUR", "message": "Echec calcul dérive"}}

    def _module_ghost_buster(self, df, talon, time_step):
        cout = talon * 8760 * 0.16
        return {"ghost_buster": {"cout_talon_annuel": self._safe_int(cout)}}

    def _module_finance_pro(self, df, time_step, p_max):
        conso = df['val'].sum() * time_step
        budget = (conso * 0.16) + (p_max * 15) + (conso * 0.03)
        return {"finance": {"budget_total": self._safe_int(budget)}}

    def _module_turpe_sniper(self, df, p_max):
        return {"optimisation": {"p_max_atteinte": p_max, "p_souscrite_ideale": self._safe_int(p_max * 1.1)}}

    def _module_carbon(self, conso_kwh):
        return {"carbone": {"tonnes_co2": round((conso_kwh * 60) / 1_000_000, 2)}}

    def _module_socle(self, df, time_step):
        values = df['val'].tolist()
        p_max = max(values) if values else 0
        conso_kwh = sum(values) * time_step
        pos_vals = [v for v in values if v > 0]
        talon = float(np.percentile(pos_vals, 5)) if pos_vals else 0.0
        return {
            "conso_totale": self._safe_int(conso_kwh),
            "p_max": self._safe_float(p_max),
            "talon": self._safe_int(talon),
            "moyenne": self._safe_float(np.mean(values))
        }

    def _universal_profiler(self, df, naf_info):
        try:
            df['h'] = df['date'].dt.hour
            mean_nuit = df[(df['h'] >= 1) & (df['h'] <= 4)]['val'].mean()
            mean_jour = df[(df['h'] >= 9) & (df['h'] <= 17)]['val'].mean()
            ratio = (mean_nuit / mean_jour) if mean_jour > 0 else 0
            archetype = "STANDARD"
            if ratio > 0.8: archetype = "CONTINUOUS"
            elif ratio < 0.2: archetype = "DIURNE"
            return {"archetype": archetype, "label_detecte": naf_info['label']}
        except: return {"archetype": "STANDARD", "label_detecte": naf_info['label']}

    # --- UTILS ROBUSTES ---
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
            
            # Nettoyage des valeurs numériques (virgules, espaces)
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').replace(' ', ''), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')

            df = df.dropna(subset=['date'])
            # ICI : Le nettoyage critique qui manquait
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
        for code, info in self.NAF_DB.items():
            for kw in info.get("keywords", []):
                if kw in fn: return {"code": code, **info}
        naf_regex = re.search(r'\b\d{2}[\.]?\d{2}[A-Z]\b', fn)
        if naf_regex:
            code = naf_regex.group(0).replace('.', '')
            if code in self.NAF_DB: return {"code": code, **self.NAF_DB[code]}
            prefix = code[:3]
            if prefix in self.NAF_DB: return {"code": code, **self.NAF_DB[prefix]}
        return {"code": "NA", "label": "Non Identifié", "profile": "STANDARD"}

# Instance Singleton
cortex = CortexEngine()
