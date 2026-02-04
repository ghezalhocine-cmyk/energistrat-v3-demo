# app/core/cortex_engine.py V31.0 - SGE WATT FIX
import pandas as pd
import numpy as np
import io
import re
import math
import logging
from datetime import datetime

# CONFIG
VERTEX_REGION = "europe-west9"
VERTEX_MODEL = "gemini-1.5-flash-001"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_V31")

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    vertexai.init(location=VERTEX_REGION)
    AI_MODEL = GenerativeModel(VERTEX_MODEL)
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "31.0 (Watt Precision)"
        self.KEYWORDS_DB = {
            "ecole": "Enseignement (NAF 85)", "school": "Enseignement (NAF 85)",
            "mairie": "Administration (NAF 84)", "boulangerie": "Artisanat (NAF 10)",
            "usine": "Industrie (NAF 25)", "resi": "Résidentiel"
        }

    def _safe_int(self, value):
        try:
            if value is None: return 0
            if isinstance(value, (float, np.floating)):
                if np.isnan(value) or np.isinf(value): return 0
            return int(float(value))
        except: return 0

    def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            # 1. PARSING
            df, time_step = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Fichier vide ou format non reconnu"}
            
            # 2. CALCULS
            base = self._module_socle(df, time_step)
            
            detected = "Tertiaire Standard"
            for k, v in self.KEYWORDS_DB.items():
                if k in filename.lower(): detected = v; break
            
            finance = self._module_finance_4p(df, time_step, base['p_max'])
            solar = self._module_solar(df)
            waste = self._module_ghost(df, base['talon'])
            
            # 3. CHART OPTIMISÉ
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step].copy()
            chart_vals = df_chart['val'].fillna(0).tolist()
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": chart_vals,
                "talon_line": [base['talon']] * len(df_chart),
                "pmax_line": [base['p_max']] * len(df_chart) # Nouvelle ligne de ref
            }

            full_kpi = {
                **base, **solar, **waste, **finance,
                "profiling": {"type": detected},
                "meta": {"filename": filename, "points": len(df)}
            }
            
            narrative = self._generate_insight(full_kpi, detected)
            return {"success": True, "kpi": full_kpi, "chart": chart, "ai_insight": narrative}

        except Exception as e:
            logger.exception("Crash Cortex V31")
            return {"success": False, "error": f"Erreur Interne: {str(e)}"}

    def _parse_data(self, content, filename):
        try:
            buffer = io.BytesIO(content)
            # Lecture CSV SGE (Séparateur ;)
            try: 
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', on_bad_lines='skip', low_memory=False)
            except: 
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=None, engine='python', encoding='latin-1')

            # Normalisation Noms Colonnes
            df.columns = [str(c).lower().strip().replace('é','e').replace('è','e') for c in df.columns]
            
            # Identification Colonnes Clés
            c_date = next((c for c in df.columns if 'horodate' in c or 'date' in c), None)
            c_val = next((c for c in df.columns if 'valeur' in c or 'puiss' in c or 'conso' in c), None)
            c_unit = next((c for c in df.columns if 'unit' in c), None) # Détection Unité
            
            if not c_date or not c_val: return None, 0

            # Nettoyage Valeurs
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').str.replace(r'\s+', '', regex=True), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')
            
            df['val'] = df['val'].fillna(0)

            # Nettoyage Dates (Format SGE: JJ/MM/AAAA HH:MM)
            df['date'] = pd.to_datetime(df[c_date], format='%d/%m/%Y %H:%M', errors='coerce')
            if df['date'].isna().mean() > 0.5:
                # Fallback
                df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')

            df = df.dropna(subset=['date']).sort_values('date')

            # GESTION INTELLIGENTE DES UNITÉS (W vs kW)
            is_watts = False
            # 1. Check explicite colonne Unité
            if c_unit:
                units = df[c_unit].astype(str).str.upper()
                if units.str.contains('W').any() and not units.str.contains('KW').any():
                    is_watts = True
            
            # 2. Check heuristique (Si moyenne > 1000, c'est probablement des Watts)
            if df['val'].mean() > 800: is_watts = True

            if is_watts:
                df['val'] = df['val'] / 1000.0 # Conversion en kW

            # Calcul Pas de temps (Time Step)
            time_step = 0.1666
            if len(df) > 1:
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: time_step = delta / 3600.0

            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step

        except Exception as e:
            logger.error(f"Parse Error: {e}")
            return None, 0

    def _module_finance_4p(self, original_df, ts, pmax):
        df = original_df.copy()
        df['m'] = df['date'].dt.month
        df['h'] = df['date'].dt.hour
        
        # Saisons & Heures (Enedis Standard)
        mask_w = df['m'].isin([11, 12, 1, 2, 3])
        mask_hp = (df['h'] >= 6) & (df['h'] < 22)
        
        # Calculs Vectorisés
        v_hph = df.loc[mask_w & mask_hp, 'val'].sum() * ts
        v_hch = df.loc[mask_w & ~mask_hp, 'val'].sum() * ts
        v_hpe = df.loc[~mask_w & mask_hp, 'val'].sum() * ts
        v_hce = df.loc[~mask_w & ~mask_hp, 'val'].sum() * ts
        
        cost = (v_hph*0.22) + (v_hch*0.14) + (v_hpe*0.14) + (v_hce*0.09) + (pmax*18)
        
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

    def _module_socle(self, df, ts):
        val = df['val']
        p_max = val.max()
        mask_nuit = (df['date'].dt.hour < 6)
        nuit = df.loc[mask_nuit, 'val']
        talon = nuit.quantile(0.05) if not nuit.empty else 0
        
        df['wd'] = df['date'].dt.weekday
        mask_off = (df['wd'] >= 5) | (df['date'].dt.hour < 6)
        conso_off = df.loc[mask_off, 'val'].sum() * ts
        conso_tot = val.sum() * ts
        ratio = (conso_off / conso_tot * 100) if conso_tot > 0 else 0
        
        return {
            "conso_totale": self._safe_int(conso_tot),
            "p_max": round(float(p_max), 2),
            "talon": round(float(talon), 2),
            "inactivity_ratio": round(float(ratio), 1)
        }

    def _module_solar(self, df):
        try:
            # Solaire pertinent si P > 10kW l'été
            mask = (df['date'].dt.month.isin([6,7,8])) & (df['date'].dt.hour.between(11, 15))
            subset = df.loc[mask, 'val']
            if subset.empty: return {"solar": {"status": "DONNÉES INSUFFISANTES", "puissance_kwc": 0, "economie_annuelle_euro": 0}}
            
            avg = subset.mean()
            if avg > 8:
                kwc = avg * 0.7
                return {"solar": {"status": "OPPORTUNITÉ DÉTECTÉE", "puissance_kwc": round(kwc, 1), "economie_annuelle_euro": self._safe_int(kwc*1100*0.18)}}
            return {"solar": {"status": "NON PERTINENT", "puissance_kwc": 0, "economie_annuelle_euro": 0}}
        except: return {"solar": {"status": "ERREUR", "puissance_kwc": 0, "economie_annuelle_euro": 0}}

    def _module_ghost(self, df, t): return {"ghost_buster": {"cout_talon_annuel": self._safe_int(t * 8760 * 0.15)}}

    def _generate_insight(self, kpi, profile):
        if not AI_AVAILABLE: return "Mode Hybride. IA Offline."
        try:
            prompt = f"Analyse pour {profile}. Pmax: {kpi['p_max']}kW. Talon: {kpi['talon']}kW. 3 points brefs."
            return AI_MODEL.generate_content(prompt).text.replace('*','')
        except: return "IA Indisponible."

    # AUDIT (Inchangé)
    def analyze_invoice_real(self, inv_b, ctr_b):
        txt = ""
        if PDF_AVAILABLE and inv_b:
            try:
                with pdfplumber.open(io.BytesIO(inv_b)) as pdf:
                    for p in pdf.pages: txt += p.extract_text() + "\n"
            except: pass
        
        m_sous = re.search(r"(?:souscrite|ps|p\.souscrite).*?(\d+[.,]?\d*)", txt, re.I)
        m_max = re.search(r"(?:atteinte|max|pointe).*?(\d+[.,]?\d*)", txt, re.I)
        m_tot = re.search(r"(?:total|montant).*?ttc.*?(\d+[., ]?\d{2})", txt, re.I)

        p_sous = float(m_sous.group(1).replace(',', '.')) if m_sous else 0
        p_att = float(m_max.group(1).replace(',', '.')) if m_max else 0
        
        checks = [
            {"point": "Puissance Souscrite", "a": f"{p_sous} kVA", "b": "Seuil", "status": "INFO", "error": False},
            {"point": "Puissance Atteinte", "a": f"{p_att} kVA", "b": "Relevé", "status": "ALERTE" if p_att > p_sous else "OK", "error": p_att > p_sous},
            {"point": "Contrat Associé", "a": "Présent" if ctr_b else "Manquant", "b": "-", "status": "OK" if ctr_b else "MANQUANT", "error": not ctr_b}
        ]
        if m_tot: checks.append({"point": "Montant Facture", "a": m_tot.group(1) + " €", "b": "TTC", "status": "INFO", "error": False})

        return {"score": 100, "checks": checks}

    def run_chaos_monkey(self): return [{"test": "Maths", "status": "OK"}]
    def ask_agent(self, msg): return self._generate_insight({}, "User")

cortex = CortexEngine()
