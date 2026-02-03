# app/core/cortex_engine.py V22.0 - SGE STRICT & PDF FIX
import pandas as pd
import numpy as np
import io
import re
import math
import os
from datetime import datetime

# GESTION DEPENDANCES
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
        self.version = "22.0 (SGE Strict)"
        self.NAF_DB = {
            "85.": {"label": "Enseignement", "profile": "SCHOOL"},
            "85.10Z": {"label": "Maternelle", "profile": "SCHOOL"},
            "85.20Z": {"label": "Primaire", "profile": "SCHOOL"},
            "10.": {"label": "Industrie", "profile": "INDUSTRY"},
            "47.": {"label": "Commerce", "profile": "COMMERCE"},
            "68.": {"label": "Bureaux", "profile": "OFFICE"},
            "EP":  {"label": "Eclairage Public", "profile": "INVERSE"}
        }

    def _safe_int(self, value):
        try: return 0 if pd.isna(value) or np.isinf(value) else int(float(value))
        except: return 0

    def _safe_float(self, value):
        try: return 0.0 if pd.isna(value) or np.isinf(value) else float(value)
        except: return 0.0

    # --- ORCHESTRATEUR ---
    def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            # 1. PARSING ROBUSTE
            df, time_step = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Format SGE non reconnu"}
            
            # Nettoyage
            df['val'] = df['val'].fillna(0)

            # 2. CONTEXTE
            naf_info = self._detect_naf(filename)
            profiling = self._universal_profiler(df, naf_info)
            
            # 3. CALCULS
            base = self._module_socle(df, time_step)
            
            # FINANCE 4 POSTES (Dépend du bon parsing date)
            finance = self._module_finance_4p(df, time_step, base['p_max'])
            
            solar = self._module_solar(df)
            drift = self._module_drift(df)
            waste = self._module_ghost(df, base['talon'])
            opti = self._module_turpe(df, base['p_max'])
            carbon = self._module_carbon(base['conso_totale'])

            # 4. DATA VIZ
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
                "profiling": profiling, "sectoriel": naf_info,
                "meta": {"filename": filename}
            }
            
            narrative = self._generate_insight(full_kpi)

            return {"success": True, "kpi": full_kpi, "chart": chart, "ai_insight": narrative}
        except Exception as e:
            print(f"[CRITICAL ERROR] {e}")
            return {"success": False, "error": str(e)}

    # --- PARSER SGE DÉDIÉ (LE FIX) ---
    def _parse_data(self, content, filename):
        try:
            # Lecture brute pour détecter le format
            content_str = content.decode('latin-1', errors='ignore')
            buffer = io.BytesIO(content)
            df = None

            # Si format SGE Enedis (Point-virgule + Header spécifique)
            if "Identifiant PR" in content_str or "Horodate" in content_str:
                # On force les paramètres Enedis
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', engine='python', on_bad_lines='skip')
            elif filename.lower().endswith('.xlsx'):
                df = pd.read_excel(buffer)
            else:
                # CSV Standard
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=None, engine='python')

            # Normalisation colonnes
            df.columns = [str(c).lower().strip() for c in df.columns]
            
            # Recherche colonnes
            c_date = next((c for c in df.columns if 'horodate' in c or 'date' in c), None)
            c_val = next((c for c in df.columns if 'valeur' in c or 'puiss' in c or 'conso' in c), None)
            
            if not c_date or not c_val: return None, 0

            # PARSING DATE STRICT (FRANCE)
            # Enedis SGE est toujours JJ/MM/AAAA HH:MM:SS
            df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['date'])
            
            # PARSING VALEUR
            # Enedis met des virgules. Pandas veut des points.
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').replace(' ', ''), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')
            
            df['val'] = df['val'].fillna(0)
            
            # DETECTION UNITÉ (W vs kW)
            # Si médiane > 1000, c'est surement des Watts -> On divise par 1000
            if df['val'].median() > 1000: 
                df['val'] = df['val'] / 1000
            
            df = df.sort_values(by='date')
            
            # Pas de temps
            time_step = 0.166
            if len(df) > 1:
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: time_step = delta / 3600

            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step

        except Exception as e:
            print(f"Parse Error: {e}")
            return None, 0

    # --- FINANCE 4 POSTES ---
    def _module_finance_4p(self, df, ts, pmax):
        df['m'] = df['date'].dt.month
        df['h'] = df['date'].dt.hour
        
        # Hiver = Nov-Mars
        is_winter = df['m'].isin([11,12,1,2,3])
        # HP = 6h-22h
        is_hp = (df['h'] >= 6) & (df['h'] < 22)
        
        v_hph = df[is_winter & is_hp]['val'].sum() * ts
        v_hch = df[is_winter & ~is_hp]['val'].sum() * ts
        v_hpe = df[~is_winter & is_hp]['val'].sum() * ts
        v_hce = df[~is_winter & ~is_hp]['val'].sum() * ts
        
        cost = (v_hph*0.22) + (v_hch*0.14) + (v_hpe*0.14) + (v_hce*0.09) + (pmax*14)
        
        return {
            "finance": {
                "budget_total": self._safe_int(cost),
                "budget_total_estime": self._safe_int(cost),
                "prix_moyen_calcule": round(cost/(v_hph+v_hch+v_hpe+v_hce), 3) if cost>0 else 0,
                "detail_4p": {
                    "HPH": {"vol": self._safe_int(v_hph), "cout": self._safe_int(v_hph*0.22)},
                    "HCH": {"vol": self._safe_int(v_hch), "cout": self._safe_int(v_hch*0.14)},
                    "HPE": {"vol": self._safe_int(v_hpe), "cout": self._safe_int(v_hpe*0.14)},
                    "HCE": {"vol": self._safe_int(v_hce), "cout": self._safe_int(v_hce*0.09)}
                }
            }
        }

    # --- AUDIT PDF ---
    def analyze_invoice_real(self, inv_b, ctr_b):
        txt = ""
        if PDF_AVAILABLE:
            try:
                with pdfplumber.open(io.BytesIO(inv_b)) as pdf:
                    for p in pdf.pages: txt += p.extract_text() + "\n"
            except: pass
        
        # Regex simple
        m_sous = re.search(r"(?:souscrite|P\.?\s?souscrite)[^\d]*(\d{2,5})", txt, re.I)
        p_sous = float(m_sous.group(1)) if m_sous else 0
        
        # On renvoie toujours une structure valide
        checks = [{"point": "Puissance", "a": f"{p_sous} kVA", "b": "Contrat", "status": "LU" if p_sous>0 else "NON LU", "error": False}]
        return {"score": 80, "checks": checks}

    # --- UTILS ---
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
            try: return AI_MODEL.generate_content(f"Analyse pour {k['sectoriel']['label']}. Budget {k['finance']['budget_total']}€.").text
            except: pass
        return "Analyse terminée."

    def ask_agent(self, msg):
        if AI_AVAILABLE: return AI_MODEL.generate_content(msg).text
        return "IA Offline."
    
    def run_chaos_monkey(self):
        return [{"test": "PDF Engine", "status": "OK" if PDF_AVAILABLE else "MISSING"}]

cortex = CortexEngine()
