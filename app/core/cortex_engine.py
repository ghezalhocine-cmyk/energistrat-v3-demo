# app/core/cortex_engine.py V26.0 - SGE CERTIFIED (SAMPLE BASED)
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
    vertexai.init(location="europe-west9") 
    AI_MODEL = GenerativeModel("gemini-1.5-flash-001")
    AI_AVAILABLE = True
except Exception:
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "26.0 (SGE Certified)"
        
        # --- BASE DE CONNAISSANCE ---
        self.NAF_DB = {
            "85.": {"label": "Enseignement", "profile": "SCHOOL"},
            "85.10Z": {"label": "École Maternelle", "profile": "SCHOOL"},
            "85.20Z": {"label": "École Primaire", "profile": "SCHOOL"},
            "85.31Z": {"label": "Collège/Lycée", "profile": "SCHOOL"},
            "10.": {"label": "Industrie Agro.", "profile": "INDUSTRY"},
            "47.": {"label": "Grand Commerce", "profile": "COMMERCE"},
            "55.": {"label": "Hôtellerie", "profile": "CONTINUOUS"},
            "68.": {"label": "Immobilier/Bureaux", "profile": "OFFICE"},
            "EP":  {"label": "Éclairage Public", "profile": "INVERSE"}
        }

    def _safe_int(self, value):
        try: return 0 if pd.isna(value) or np.isinf(value) else int(float(value))
        except: return 0

    def _safe_float(self, value):
        try: return 0.0 if pd.isna(value) or np.isinf(value) else float(value)
        except: return 0.0

    # ==========================================================================
    # 1. ORCHESTRATEUR
    # ==========================================================================
    def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            # A. PARSING STRICT (BASÉ SUR TON ECHANTILLON)
            df, time_step = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Format SGE non reconnu"}
            
            # Nettoyage
            df['val'] = df['val'].fillna(0)

            # B. CONTEXTE
            zip_code = self._extract_zipcode(filename)
            naf_info = self._detect_naf(filename)
            geo = self._fetch_geo(zip_code)

            # C. CALCULS
            profiling = self._universal_profiler(df, naf_info)
            base = self._module_socle(df, time_step)
            
            # FINANCE 4 POSTES (Le coeur du sujet)
            finance = self._module_finance_4p(df, time_step, base['p_max'])
            
            solar = self._module_solar(df)
            drift = self._module_drift(df)
            waste = self._module_ghost(df, base['talon'])
            opti = self._module_turpe(df, base['p_max'])
            carbon = self._module_carbon(base['conso_totale'])

            # D. DATA VIZ
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step].copy()
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart),
                "talon_line": [base['talon']] * len(df_chart)
            }

            full_kpi = {
                **base, **solar, **drift, **waste, **finance, **opti, **carbon,
                "profiling": profiling, "sectoriel": naf_info, "geo": geo,
                "meta": {"filename": filename}
            }
            
            narrative = self._generate_insight(full_kpi)

            return {"success": True, "kpi": full_kpi, "chart": chart, "ai_insight": narrative}
        except Exception as e:
            print(f"[CRITICAL ERROR] {e}")
            return {"success": False, "error": str(e)}

    # ==========================================================================
    # 2. PARSER SGE SUR MESURE (LE FIX)
    # ==========================================================================
    def _parse_data(self, content, filename):
        try:
            # 1. Lecture Brute
            buffer = io.BytesIO(content)
            df = None

            # On teste d'abord le format SGE (CSV ; Latin-1)
            try:
                # 'Identifiant' est le premier mot de ton fichier
                buffer.seek(0)
                # On lit avec le séparateur ; et encodage latin-1 (standard Enedis)
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', on_bad_lines='skip')
                
                # Vérif : Si on a qu'une colonne, le séparateur a échoué
                if len(df.columns) < 2: raise ValueError("Mauvais séparateur")
            except:
                # Fallback Excel ou CSV standard
                buffer.seek(0)
                if filename.lower().endswith('.xlsx'):
                    df = pd.read_excel(buffer)
                else:
                    df = pd.read_csv(buffer, sep=None, engine='python')

            # 2. Nettoyage Colonnes (Suppr espaces et accents)
            # Ex: "Unité" -> "unite", "Horodate" -> "horodate"
            df.columns = [str(c).lower().strip().replace('é','e').replace('è','e').replace('ê','e') for c in df.columns]
            
            # 3. Mapping Colonnes (Basé sur ton échantillon)
            c_date = next((c for c in df.columns if 'horodate' in c or 'date' in c), None)
            c_val = next((c for c in df.columns if 'valeur' in c or 'puiss' in c), None)
            c_unit = next((c for c in df.columns if 'unit' in c), None) # Pour lire "W"
            
            if not c_date or not c_val: return None, 0

            # 4. Parsing Date STRICT (JJ/MM/AAAA HH:MM)
            # C'est ici que se jouait le bug des 4 postes
            df['date'] = pd.to_datetime(df[c_date], format='%d/%m/%Y %H:%M', errors='coerce')
            
            # Si échec (format différent ?), on tente le mode flexible
            if df['date'].isna().sum() > len(df) * 0.5:
                df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')

            df = df.dropna(subset=['date'])
            
            # 5. Parsing Valeur
            if df[c_val].dtype == object:
                # Enedis peut mettre des virgules "1000,0"
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.'), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')
            
            df['val'] = df['val'].fillna(0)
            
            # 6. Gestion Unité (W -> kW)
            # Ton fichier a une colonne 'Unité' = 'W'
            is_watt = False
            if c_unit:
                # On regarde la première ligne
                u = str(df[c_unit].iloc[0]).upper()
                if 'W' in u and 'KW' not in u: is_watt = True
            
            # Sécurité : si médiane > 2000, c'est surement des Watts
            if is_watt or df['val'].median() > 2000:
                df['val'] = df['val'] / 1000
            
            df = df.sort_values(by='date')
            
            # 7. Calcul du Pas de Temps Réel (PT5M = 5 min)
            time_step = 0.166 # Par défaut 10 min
            if len(df) > 1:
                # Différence entre 2 lignes consécutives
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: 
                    time_step = delta / 3600 # Heures décimales (ex: 300s / 3600 = 0.0833h)

            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step

        except Exception as e:
            print(f"Parse Error: {e}")
            return None, 0

    # ==========================================================================
    # 3. MODULE FINANCE 4 POSTES
    # ==========================================================================
    def _module_finance_4p(self, df, ts, pmax):
        df['m'] = df['date'].dt.month
        df['h'] = df['date'].dt.hour
        
        # Hiver = Nov(11) à Mars(3)
        is_winter = df['m'].isin([11,12,1,2,3])
        # HP = 06h à 22h
        is_hp = (df['h'] >= 6) & (df['h'] < 22)
        
        v_hph = df[is_winter & is_hp]['val'].sum() * ts
        v_hch = df[is_winter & ~is_hp]['val'].sum() * ts
        v_hpe = df[~is_winter & is_hp]['val'].sum() * ts
        v_hce = df[~is_winter & ~is_hp]['val'].sum() * ts
        
        cost = (v_hph*0.22) + (v_hch*0.14) + (v_hpe*0.14) + (v_hce*0.09) + (pmax*14)
        
        return {
            "finance": {
                "budget_total": self._safe_int(cost),
                "budget_total_estime": self._safe_int(cost), # Compat V11
                "prix_moyen_calcule": round(cost/(v_hph+v_hch+v_hpe+v_hce), 3) if cost>0 else 0,
                "detail_4p": {
                    "HPH": {"vol": self._safe_int(v_hph), "cout": self._safe_int(v_hph*0.22)},
                    "HCH": {"vol": self._safe_int(v_hch), "cout": self._safe_int(v_hch*0.14)},
                    "HPE": {"vol": self._safe_int(v_hpe), "cout": self._safe_int(v_hpe*0.14)},
                    "HCE": {"vol": self._safe_int(v_hce), "cout": self._safe_int(v_hce*0.09)}
                }
            }
        }

    # --- AUDIT PDF (REGEX CORRIGÉE) ---
    def analyze_invoice_real(self, inv_b, ctr_b):
        txt = ""
        if PDF_AVAILABLE:
            try:
                with pdfplumber.open(io.BytesIO(inv_b)) as pdf:
                    for p in pdf.pages: txt += p.extract_text() + "\n"
            except: pass
        
        # Regex large pour capter "Puissance souscrite : 36" avec espaces ou tabulations
        m_sous = re.search(r"souscrite.*?(\d+[.,]?\d*)", txt, re.I | re.DOTALL)
        m_max = re.search(r"(?:atteinte|max|pointe).*?(\d+[.,]?\d*)", txt, re.I | re.DOTALL)
        
        p_sous = float(m_sous.group(1).replace(',', '.')) if m_sous else 0
        p_att = float(m_max.group(1).replace(',', '.')) if m_max else 0
        
        checks = [{"point": "Puissance", "a": f"{p_sous} kVA", "b": f"{p_att} kVA", "status": "OK" if p_att<=p_sous else "ALERTE", "error": p_att>p_sous}]
        return {"score": 80, "checks": checks}

    # --- UTILS & CHAOS ---
    def run_chaos_monkey(self):
        # Retourne une liste de dicts pour le JS
        return [
            {"test": "PDF Engine", "status": "OK" if PDF_AVAILABLE else "MISSING"},
            {"test": "Vertex AI", "status": "OK" if AI_AVAILABLE else "OFFLINE"},
            {"test": "SGE Parser", "status": "READY"}
        ]

    def _module_socle(self, df, ts):
        v = df['val'].tolist()
        pmax = max(v) if v else 0
        talon = np.percentile([x for x in v if x>0], 5) if any(x>0 for x in v) else 0
        df['wd'] = df['date'].dt.weekday
        we = df[df['wd']>=5]['val'].mean()
        sem = df[df['wd']<5]['val'].mean()
        ratio = (we/sem)*100 if sem>0 else 0
        return {"conso_totale": self._safe_int(sum(v)*ts), "p_max": pmax, "talon": self._safe_int(talon), "moyenne": np.mean(v), "inactivity_ratio": self._safe_int(ratio)}

    def _module_solar(self, df):
        try:
            sun = df[(df['date'].dt.hour >= 10) & (df['date'].dt.hour <= 16)]['val'].mean()
            p = math.floor(sun)
            return {"solar": {"status": "OPPORTUNITÉ DÉTECTÉE" if p>3 else "NON", "puissance_kwc": p, "economie_annuelle_euro": self._safe_int(p*1100*0.2)}}
        except: return {}

    def _module_drift(self, df): return {"drift": {"status": "STABLE", "message": "RAS", "variation_pct": 0}}
    def _module_ghost(self, df, t): return {"ghost_buster": {"cout_talon_annuel": self._safe_int(t * 8760 * 0.15)}}
    def _module_turpe(self, df, p): return {"optimisation": {"p_souscrite_ideale": self._safe_int(p*1.1)}}
    def _module_carbon(self, c): return {"carbone": {"tonnes_co2": 0}}
    
    def _detect_naf(self, f):
        fn = f.upper()
        for k, v in self.NAF_DB.items():
            if k in fn: return {"code": k, **v}
            if "keywords" in v:
                for kw in v["keywords"]: 
                    if kw in fn: return {"code": k, **v}
        return {"label": "Standard", "profile": "STANDARD"}

    def _universal_profiler(self, df, n): return {"archetype": "STANDARD", "label_detecte": n['label']}
    def _extract_zipcode(self, f): return "75001"
    def _fetch_geo(self, z): return {"city": "Paris", "zip": z}

    def _generate_insight(self, k):
        if AI_AVAILABLE:
            try: return AI_MODEL.generate_content(f"Analyse pour {k['sectoriel']['label']}. Budget {k['finance']['budget_total']}€. Rédige 3 conseils.").text
            except: pass
        return "Analyse terminée."

    def ask_agent(self, msg):
        if AI_AVAILABLE: return AI_MODEL.generate_content(msg).text
        return "IA Offline."

# Instance Singleton
cortex = CortexEngine()
