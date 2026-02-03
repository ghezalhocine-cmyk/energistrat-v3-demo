# app/core/cortex_engine.py V21.1 - ULTIMATE (4-POSTES + CHAT + FULL NAF)
import pandas as pd
import numpy as np
import io
import re
import math
import os
import requests
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
    # Initialisation Cloud Run (Credentials auto)
    vertexai.init(location="europe-west9") 
    AI_MODEL = GenerativeModel("gemini-1.5-flash-001")
    AI_AVAILABLE = True
except Exception as e:
    print(f"[CORTEX WARN] AI Offline: {e}")
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "21.1 (Ultimate 4-Post & Chat)"
        
        # --- BASE DE CONNAISSANCE EXPERTE (50+ PROFILS) ---
        self.NAF_DB = {
            # ENSEIGNEMENT
            "85.10Z": {"label": "École Maternelle", "profile": "SCHOOL", "keywords": ["MATERNELLE"]},
            "85.20Z": {"label": "École Primaire", "profile": "SCHOOL", "keywords": ["ECOLE", "PRIMAIRE", "SCOLAIRE"]},
            "85.31Z": {"label": "Collège/Lycée", "profile": "SCHOOL", "keywords": ["COLLEGE", "LYCEE", "CITE SCOLAIRE"]},
            "85.59A": {"label": "Formation Continue", "profile": "SCHOOL", "keywords": ["FORMATION"]},
            
            # COMMERCE & ALIMENTATION
            "10.71C": {"label": "Boulangerie", "profile": "BAKERY", "keywords": ["BOULANGERIE", "PAIN"]},
            "10.71D": {"label": "Pâtisserie", "profile": "BAKERY", "keywords": ["PATISSERIE"]},
            "47.11":  {"label": "Supermarché", "profile": "COLD", "keywords": ["SUPERMARCHE", "MARKET"]},
            "47.11F": {"label": "Hyper", "profile": "COLD", "keywords": ["HYPER"]},
            
            # HORECA
            "55.10Z": {"label": "Hôtellerie", "profile": "CONTINUOUS", "keywords": ["HOTEL", "CHAMBRE"]},
            "56.10A": {"label": "Restauration", "profile": "SERVICE", "keywords": ["RESTAURANT", "RESTO"]},
            "56.10C": {"label": "Fast Food", "profile": "SERVICE", "keywords": ["SNACK", "BURGER"]},
            
            # SANTÉ
            "86.10Z": {"label": "Hôpital", "profile": "CONTINUOUS", "keywords": ["HOPITAL", "CHU"]},
            "87.10A": {"label": "EHPAD", "profile": "CONTINUOUS", "keywords": ["EHPAD", "RETRAITE"]},
            
            # INDUSTRIE
            "10.": {"label": "Industrie Agro.", "profile": "INDUSTRY"},
            "25.11Z": {"label": "Métallurgie", "profile": "INDUSTRY", "keywords": ["METAL", "ACIER"]},
            "20.14Z": {"label": "Chimie", "profile": "INDUSTRY", "keywords": ["CHIMIE"]},
            
            # TERTIAIRE
            "68.20B": {"label": "Bureaux", "profile": "OFFICE", "keywords": ["BUREAU", "SIEGE"]},
            "64.19Z": {"label": "Banque", "profile": "OFFICE", "keywords": ["BANQUE"]},
            "63.11Z": {"label": "Data Center", "profile": "CONTINUOUS", "keywords": ["DATA", "SERVER"]},
            
            # PUBLIC
            "84.11Z": {"label": "Mairie", "profile": "OFFICE", "keywords": ["MAIRIE", "ADMINISTRATION"]},
            "EP":     {"label": "Éclairage Public", "profile": "INVERSE", "keywords": ["EP", "ECLAIRAGE"]}
        }

    # --- SÉCURITÉ MATHÉMATIQUE (BLINDAGE V20.2) ---
    def _safe_int(self, value):
        try:
            if value is None: return 0
            if isinstance(value, (float, np.floating)):
                if np.isnan(value) or np.isinf(value): return 0
            return int(float(value))
        except: return 0

    def _safe_float(self, value):
        try:
            if value is None: return 0.0
            if isinstance(value, (float, np.floating)):
                if np.isnan(value) or np.isinf(value): return 0.0
            return float(value)
        except: return 0.0

    # ==========================================================================
    # 1. ORCHESTRATEUR PRINCIPAL
    # ==========================================================================
    def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            # A. INGESTION (Parsing Robuste V20.2)
            df, time_step_hours = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Données illisibles"}
            
            # Nettoyage préventif (Anti-Crash)
            df['val'] = df['val'].fillna(0).replace([np.inf, -np.inf], 0)

            # B. CONTEXTE
            zip_code = self._extract_zipcode_smart(filename)
            geo_data = self._fetch_geo_data(zip_code)
            naf_input = self._detect_naf_advanced(filename)
            
            # C. CALCULS EXPERTS
            profiling = self._universal_profiler(df, naf_input)
            base = self._module_socle(df, time_step_hours)
            
            # --- FINANCE 4 POSTES (VRAIE SIMULATION) ---
            finance = self._module_finance_4_postes(df, time_step_hours, base['p_max'])
            
            # Modules Avancés (Quantum V17)
            solar = self._module_solar_opportunity(df, time_step_hours)
            drift = self._module_drift_detection(df)
            waste = self._module_ghost_buster(df, base['talon'], time_step_hours)
            opti = self._module_turpe_sniper(df, base['p_max'])
            carbon = self._module_carbon(base['conso_totale'])

            # D. DATA VISUALISATION
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step].copy()
            df_chart['val'] = df_chart['val'].fillna(0)
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart),
                "talon_line": [base['talon']] * len(df_chart)
            }

            # E. NARRATIF HYBRIDE
            full_kpi = {
                **base, **solar, **drift, **waste, **finance, **opti, **carbon,
                "profiling": profiling,
                "sectoriel": naf_input,
                "geo": geo_data,
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
            return {"success": False, "error": f"Erreur Analyse V21: {str(e)}"}

    # ==========================================================================
    # 2. MODULE FINANCE 4 POSTES (REALITY CHECK)
    # ==========================================================================
    def _module_finance_4_postes(self, df, time_step, p_max):
        """
        Découpage strict selon le calendrier TURPE / Fournisseur.
        Hiver : Nov-Mars | Été : Avril-Oct
        HP : 06h-22h | HC : 22h-06h
        """
        # 1. Enrichissement Temporel
        df['month'] = df['date'].dt.month
        df['hour'] = df['date'].dt.hour
        
        # 2. Définition des Saisons
        mask_winter = df['month'].isin([11, 12, 1, 2, 3])
        mask_summer = ~mask_winter
        
        # 3. Définition des Horaires
        mask_hp = (df['hour'] >= 6) & (df['hour'] < 22)
        mask_hc = ~mask_hp
        
        # 4. Calcul des Volumes (kWh)
        vol_hph = df[mask_winter & mask_hp]['val'].sum() * time_step
        vol_hch = df[mask_winter & mask_hc]['val'].sum() * time_step
        vol_hpe = df[mask_summer & mask_hp]['val'].sum() * time_step
        vol_hce = df[mask_summer & mask_hc]['val'].sum() * time_step
        
        # 5. Tarifs de Référence (B2B 2026 Estimés)
        P_HPH = 0.22 # Hiver Plein (Cher)
        P_HCH = 0.14 # Hiver Creux
        P_HPE = 0.14 # Eté Plein
        P_HCE = 0.09 # Eté Creux (Pas cher)
        
        # 6. Calcul Budget Énergie
        cout_elec = (vol_hph * P_HPH) + (vol_hch * P_HCH) + (vol_hpe * P_HPE) + (vol_hce * P_HCE)
        
        # 7. Part Fixe (Abo + Taxes)
        cout_abo = p_max * 14 # ~14€/kVA/an
        cout_taxes = (vol_hph + vol_hch + vol_hpe + vol_hce) * 0.03 # ~30€/MWh
        
        budget_total = cout_elec + cout_abo + cout_taxes
        
        # 8. Calcul Prix Moyen
        total_kwh = vol_hph + vol_hch + vol_hpe + vol_hce
        avg_price = budget_total / total_kwh if total_kwh > 0 else 0
        
        return {
            "finance": {
                # Clés Compatibilité V11 (Front)
                "budget_total_estime": self._safe_int(budget_total),
                "budget_total": self._safe_int(budget_total),
                "conso_hp": self._safe_int(vol_hph + vol_hpe),
                "conso_hc": self._safe_int(vol_hch + vol_hce),
                "prix_moyen_calcule": round(avg_price, 3),
                
                # NOUVEAU : Détail 4 Postes (Pour l'interface Ops V13)
                "detail_4p": {
                    "HPH": {"vol": self._safe_int(vol_hph), "prix": P_HPH, "cout": self._safe_int(vol_hph * P_HPH)},
                    "HCH": {"vol": self._safe_int(vol_hch), "prix": P_HCH, "cout": self._safe_int(vol_hch * P_HCH)},
                    "HPE": {"vol": self._safe_int(vol_hpe), "prix": P_HPE, "cout": self._safe_int(vol_hpe * P_HPE)},
                    "HCE": {"vol": self._safe_int(vol_hce), "prix": P_HCE, "cout": self._safe_int(vol_hce * P_HCE)}
                }
            }
        }

    # ==========================================================================
    # 3. FONCTIONS IA & CHAT (RESTAURÉES)
    # ==========================================================================
    def ask_agent(self, message):
        """Chatbot Ops pour dialoguer avec Cortex."""
        if not AI_AVAILABLE: return "Cortex AI Offline."
        try:
            prompt = f"Tu es CORTEX, IA énergétique. Réponds court : {message}"
            return AI_MODEL.generate_content(prompt).text
        except: return "Erreur IA."

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
        
        Rédige une synthèse stratégique de 4 lignes format HTML (gras sur les économies).
        """
        response = AI_MODEL.generate_content(prompt)
        return response.text

    def _generate_template_narrative(self, k):
        prof = k['profiling']
        solar = k.get('solar', {})
        drift = k.get('drift', {})
        ghost = k['ghost_buster']
        txt = f"<b>ANALYSE V21 ({k['sectoriel']['label']}) :</b><br>"
        txt += f"🏭 <b>Profil :</b> {prof['label_detecte']}<br>"
        if drift['status'] != "STABLE": txt += f"🚨 <b>Santé :</b> {drift['message']}<br>"
        if solar.get('status') == "OPPORTUNITÉ DÉTECTÉE":
            txt += f"☀️ <b>Solaire :</b> Gain potentiel de <span style='color:#00E5FF'><b>{solar['economie_annuelle_euro']} €/an</b></span>.<br>"
        txt += f"💰 <b>Budget :</b> {k['finance']['budget_total']:,} €/an."
        return txt

    # ==========================================================================
    # 4. MODULES EXPERTS & UTILS
    # ==========================================================================
    def _module_socle(self, df, time_step):
        values = df['val'].tolist()
        p_max = max(values) if values else 0
        conso_kwh = sum(values) * time_step
        pos_vals = [v for v in values if v > 0]
        talon = float(np.percentile(pos_vals, 5)) if pos_vals else 0.0
        
        df['wd'] = df['date'].dt.weekday
        mean_we = df[df['wd'] >= 5]['val'].mean()
        mean_sem = df[df['wd'] < 5]['val'].mean()
        ratio = (mean_we / mean_sem * 100) if mean_sem > 0 else 0
            
        return {
            "conso_totale": self._safe_int(conso_kwh),
            "p_max": self._safe_float(p_max),
            "talon": self._safe_int(talon),
            "moyenne": self._safe_float(np.mean(values)),
            "inactivity_ratio": self._safe_int(ratio)
        }

    def _module_solar_opportunity(self, df, time_step):
        try:
            df['h'] = df['date'].dt.hour
            sun_hours = df[(df['h'] >= 10) & (df['h'] <= 16)]
            if sun_hours.empty: return {"solar": {"status": "DONNÉES INSUFFISANTES"}}
            mean_sun = sun_hours['val'].mean()
            p_inst = math.floor((mean_sun * 0.8) / 0.8)
            if p_inst < 3: return {"solar": {"status": "NON PERTINENT"}}
            gain = p_inst * 1100 * 0.20
            return {"solar": {"status": "OPPORTUNITÉ DÉTECTÉE", "puissance_kwc": self._safe_int(p_inst), "economie_annuelle_euro": self._safe_int(gain)}}
        except: return {"solar": {"status": "ERREUR"}}

    def _module_drift_detection(self, df):
        try:
            if len(df) < 100: return {"drift": {"status": "STABLE", "message": "Pas assez de données"}}
            mid = len(df) // 2
            t1 = np.percentile(df.iloc[:mid]['val'], 10)
            t2 = np.percentile(df.iloc[mid:]['val'], 10)
            if t1 == 0: return {"drift": {"status": "STABLE", "message": "RAS"}}
            var = ((t2 - t1) / t1) * 100
            status = "DÉRIVE CRITIQUE" if var > 10 else ("STABLE" if var <= 5 else "DÉRIVE LÉGÈRE")
            return {"drift": {"status": status, "variation_pct": round(var, 1), "message": f"Variation talon: {int(var)}%"}}
        except: return {"drift": {"status": "ERREUR", "message": "Echec calcul"}}

    def _module_ghost_buster(self, df, talon, time_step):
        return {"ghost_buster": {"cout_talon_annuel": self._safe_int(talon * 8760 * 0.15)}}
    def _module_turpe_sniper(self, df, p_max):
        return {"optimisation": {"p_max_atteinte": p_max, "p_souscrite_ideale": self._safe_int(p_max*1.1)}}
    def _module_carbon(self, conso):
        return {"carbone": {"tonnes_co2": round((conso * 60) / 1_000_000, 2)}}
    def _universal_profiler(self, df, naf):
        return {"archetype": "STANDARD", "label_detecte": naf['label']}

    # --- PARSING ROBUSTE (V20.2) ---
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

            # Parsing Date (UTC + Local)
            try: df['date'] = pd.to_datetime(df[c_date], utc=True, errors='coerce').dt.tz_convert('Europe/Paris')
            except: df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')

            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').replace(' ', ''), errors='coerce')
            else: df['val'] = pd.to_numeric(df[c_val], errors='coerce')

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

    def _extract_zipcode_smart(self, filename):
        matches = re.findall(r'(?<!\d)(\d{5})(?!\d)', filename)
        return matches[-1] if matches else "75001"

    def _fetch_geo_data(self, zipcode):
        try:
            url = f"https://api-adresse.data.gouv.fr/search/?q={zipcode}&limit=1"
            res = requests.get(url, timeout=1).json()
            if res['features']: return {"city": res['features'][0]['properties']['city'], "zip": zipcode}
        except: pass
        return {"city": "Localisation Inconnue", "zip": zipcode}

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

    # --- AUDIT PDF RESTAURÉ ---
    def extract_pdf(self, b):
        t = ""
        if PDF_AVAILABLE:
            try:
                with pdfplumber.open(io.BytesIO(b)) as pdf:
                    for p in pdf.pages: t += p.extract_text() + "\n"
            except: pass
        return t

    def analyze_invoice_real(self, inv_b, ctr_b):
        txt = self.extract_pdf(inv_b) or ""
        m_sous = re.search(r"(?:souscrite|P\.?\s?souscrite)[^\d]*(\d{2,5})", txt, re.I)
        m_max = re.search(r"(?:atteinte|max|pointe)[^\d]*(\d{2,5})", txt, re.I)
        p_sous = float(m_sous.group(1)) if m_sous else 0
        p_att = float(m_max.group(1)) if m_max else 0
        checks = [{"point": "Puissance", "a": f"{p_sous}", "b": f"{p_att}", "status": "OK" if p_att<=p_sous else "ALERTE", "error": p_att>p_sous}]
        return {"score": 80, "checks": checks}

    def run_chaos_monkey(self):
        return [{"test": "Vertex AI", "status": "OK" if AI_AVAILABLE else "OFFLINE"}]

# Instance Singleton
cortex = CortexEngine()
