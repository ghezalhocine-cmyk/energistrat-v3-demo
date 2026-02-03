# app/core/cortex_engine.py V27.0 - DEBUG EDITION
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
    print("⚠️ PDFPLUMBER MANQUANT")

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    vertexai.init(location="europe-west9") 
    AI_MODEL = GenerativeModel("gemini-1.5-flash-001")
    AI_AVAILABLE = True
except Exception as e:
    print(f"⚠️ VERTEX AI ERROR: {e}")
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "27.0 (Debug)"
        # ... (NAF_DB inchangée) ...
        self.NAF_DB = { "85.": {"label": "Enseignement", "profile": "SCHOOL"}, "85.10Z": {"label": "Maternelle", "profile": "SCHOOL"}, "85.20Z": {"label": "Primaire", "profile": "SCHOOL"}, "10.": {"label": "Industrie", "profile": "INDUSTRY"}, "47.": {"label": "Commerce", "profile": "COMMERCE"}, "68.": {"label": "Bureaux", "profile": "OFFICE"}, "EP":  {"label": "Eclairage Public", "profile": "INVERSE"} }

    def _safe_int(self, value):
        try: return 0 if pd.isna(value) or np.isinf(value) else int(float(value))
        except: return 0

    def _safe_float(self, value):
        try: return 0.0 if pd.isna(value) or np.isinf(value) else float(value)
        except: return 0.0

    # --- ORCHESTRATEUR ---
    def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            df, time_step = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Format non reconnu"}
            
            df['val'] = df['val'].fillna(0)
            naf_info = self._detect_naf(filename)
            profiling = self._universal_profiler(df, naf_info)
            base = self._module_socle(df, time_step)
            finance = self._module_finance_4p(df, time_step, base['p_max'])
            solar = self._module_solar(df)
            drift = self._module_drift(df)
            waste = self._module_ghost(df, base['talon'])
            opti = self._module_turpe(df, base['p_max'])
            carbon = self._module_carbon(base['conso_totale'])

            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step].copy()
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart),
                "talon_line": [base['talon']] * len(df_chart)
            }

            full_kpi = { **base, **solar, **drift, **waste, **finance, **opti, **carbon, "profiling": profiling, "sectoriel": naf_info, "meta": {"filename": filename} }
            narrative = self._generate_insight(full_kpi)

            return {"success": True, "kpi": full_kpi, "chart": chart, "ai_insight": narrative}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- PARSING ---
    def _parse_data(self, content, filename):
        try:
            content_str = content.decode('latin-1', errors='ignore')
            buffer = io.BytesIO(content)
            df = None
            if "Identifiant" in content_str and "Horodate" in content_str:
                try: df = pd.read_csv(buffer, sep=';', encoding='latin-1', on_bad_lines='skip')
                except: pass
            
            if df is None:
                buffer.seek(0)
                if filename.lower().endswith('.xlsx'): df = pd.read_excel(buffer)
                else: df = pd.read_csv(buffer, sep=None, engine='python')

            df.columns = [str(c).lower().strip().replace('é','e').replace('è','e') for c in df.columns]
            c_date = next((c for c in df.columns if 'horodate' in c or 'date' in c), None)
            c_val = next((c for c in df.columns if 'valeur' in c or 'puiss' in c or 'conso' in c), None)
            c_unit = next((c for c in df.columns if 'unit' in c), None)
            
            if not c_date or not c_val: return None, 0

            try: df['date'] = pd.to_datetime(df[c_date], format='%d/%m/%Y %H:%M', errors='coerce')
            except: df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')
            
            if df['date'].isna().sum() > len(df) * 0.5:
                df['date'] = pd.to_datetime(df[c_date], utc=True, errors='coerce').dt.tz_convert('Europe/Paris')

            df = df.dropna(subset=['date'])
            
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').replace(r'\s+', '', regex=True), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')
            
            df['val'] = df['val'].fillna(0)
            
            is_watt = False
            if c_unit:
                u = str(df[c_unit].iloc[0]).upper()
                if 'W' in u and 'KW' not in u: is_watt = True
            
            if is_watt or df['val'].median() > 1000: df['val'] = df['val'] / 1000
            
            df = df.sort_values(by='date')
            time_step = 0.166
            if len(df) > 1:
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: time_step = delta / 3600

            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step
        except: return None, 0

    # --- FINANCE ---
    def _module_finance_4p(self, df, ts, pmax):
        df['m'] = df['date'].dt.month
        df['h'] = df['date'].dt.hour
        is_winter = df['m'].isin([11,12,1,2,3])
        is_hp = (df['h'] >= 6) & (df['h'] < 22)
        
        v_hph = df[is_winter & is_hp]['val'].sum() * ts
        v_hch = df[is_winter & ~is_hp]['val'].sum() * ts
        v_hpe = df[~is_winter & is_hp]['val'].sum() * ts
        v_hce = df[~is_winter & ~is_hp]['val'].sum() * ts
        
        cost = (v_hph*0.22) + (v_hch*0.14) + (v_hpe*0.14) + (v_hce*0.09) + (pmax*14)
        
        return {
            "finance": {
                "budget_total": self._safe_int(cost),
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
            except Exception as e:
                return {"score": 0, "checks": [], "error": f"Erreur Lecture PDF: {e}"}
        else:
            return {"score": 0, "checks": [], "error": "Librairie PDF manquante"}
        
        m_sous = re.search(r"souscrite.*?(\d+[.,]?\d*)", txt, re.I | re.DOTALL)
        m_max = re.search(r"(?:atteinte|max|pointe).*?(\d+[.,]?\d*)", txt, re.I | re.DOTALL)
        
        p_sous = float(m_sous.group(1).replace(',', '.')) if m_sous else 0
        p_att = float(m_max.group(1).replace(',', '.')) if m_max else 0
        
        checks = [{"point": "Puissance", "a": f"{p_sous} kVA", "b": f"{p_att} kVA", "status": "OK" if p_att<=p_sous else "ALERTE", "error": p_att>p_sous}]
        return {"score": 80, "checks": checks}

    # --- IA ---
    def ask_agent(self, msg):
        if AI_AVAILABLE:
            try: return AI_MODEL.generate_content(msg).text
            except Exception as e: return f"Erreur API Vertex: {e}"
        return "IA Offline. Vérifiez API Google Cloud."

    def _generate_insight(self, k):
        if AI_AVAILABLE:
            try: return AI_MODEL.generate_content(f"Analyse {k['sectoriel']['label']}. Budget {k['finance']['budget_total']}€.").text
            except: pass
        return "Analyse terminée."

    # --- UTILS ---
    def run_chaos_monkey(self):
        return [{"test": "PDF Engine", "status": "OK" if PDF_AVAILABLE else "MISSING"}, {"test": "Vertex AI", "status": "OK" if AI_AVAILABLE else "OFFLINE"}]
    
    def _module_socle(self, df, ts):
        v = df['val'].tolist()
        pmax = max(v) if v else 0
        talon = np.percentile([x for x in v if x>0], 5) if any(x>0 for x in v) else 0
        df['wd'] = df['date'].dt.weekday
        we = df[df['wd']>=5]['val'].mean()
        sem = df[df['wd']<5]['val'].mean()
        ratio = (we/sem)*100 if sem>0 else 0
        return {"conso_totale": self._safe_int(sum(v)*ts), "p_max": pmax, "talon": self._safe_int(talon), "moyenne": np.mean(v), "inactivity_ratio": self._safe_int(ratio)}

    def _module_solar(self, df): return {"solar": {"status": "NON PERTINENT"}}
    def _module_drift(self, df): return {"drift": {"status": "STABLE", "message": "RAS"}}
    def _module_ghost(self, df, t): return {"ghost_buster": {"cout_talon_annuel": self._safe_int(t * 8760 * 0.15)}}
    def _module_turpe(self, df, p): return {"optimisation": {"p_souscrite_ideale": self._safe_int(p*1.1)}}
    def _module_carbon(self, c): return {"carbone": {"tonnes_co2": 0}}
    def _detect_naf(self, f): return {"label": "Standard", "profile": "STANDARD"}
    def _universal_profiler(self, df, n): return {"archetype": "STANDARD", "label_detecte": n['label']}

# Instance Singleton
cortex = CortexEngine()
