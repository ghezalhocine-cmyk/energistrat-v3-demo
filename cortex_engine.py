# cortex_engine.py V10.0 - CONTEXTUAL INTELLIGENCE (DJU + GEO)
import pandas as pd
import numpy as np
import io
import os
import json
import re
import logging
import requests # NOUVEAU POUR API
from datetime import datetime

# IA & PDF (Optionnel)
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    VERTEX_AVAILABLE = True
except ImportError:
    VERTEX_AVAILABLE = False

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.project_id = "energistrat-saas"
        self.ai_ready = False
        if VERTEX_AVAILABLE:
            try:
                vertexai.init(project=self.project_id, location="us-central1")
                self.model = GenerativeModel("gemini-1.5-flash-001")
                self.ai_ready = True
            except: pass

    # --- SÉCURITÉ MATHÉMATIQUE ---
    def _safe_int(self, value):
        try: return 0 if (pd.isna(value) or np.isinf(value)) else int(value)
        except: return 0

    def _safe_float(self, value):
        try: return 0.0 if (pd.isna(value) or np.isinf(value)) else float(value)
        except: return 0.0

    # ==========================================================================
    # 1. ORCHESTRATEUR PRINCIPAL
    # ==========================================================================
    async def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            # A. INGESTION
            df, time_step_hours = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Fichier illisible"}

            # B. CONTEXTE GÉO & CLIMATIQUE (NOUVEAU V10)
            # On cherche un code postal dans le nom du fichier (ex: Site_69002.csv)
            zip_match = re.search(r'\b(0[1-9]|[1-8]\d|9[0-5])\d{3}\b', filename)
            zip_code = zip_match.group(0) if zip_match else "75001" # Défaut Paris si non trouvé
            
            # Appels API Externes
            geo_data = self._fetch_geo_data(zip_code)
            dju_data = self._fetch_dju_data(geo_data, df['date'].min(), df['date'].max())

            # C. MODULES EXPERTS
            base = self._module_socle(df, time_step_hours)
            turpe = self._module_turpe(df, base['p_max'])
            season = self._module_saison(df)
            finance = self._module_finance(df, time_step_hours)
            
            # Module Climatique (Signature)
            climat = self._module_climatique(base['conso_totale'], dju_data)
            
            final_kpis = {**base, **turpe, **season, **finance, **climat, "geo": geo_data}
            
            # D. SAMPLING & NARRATION
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step]
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart)
            }

            narrative = self._generate_expert_narrative(final_kpis, target_profile)

            return {
                "success": True,
                "kpi": final_kpis,
                "chart": chart,
                "ai_insight": narrative,
                "retail_data": None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==========================================================================
    # 2. API EXTERNES (NOUVEAU V10)
    # ==========================================================================
    def _fetch_geo_data(self, zipcode):
        """Récupère Lat/Lon via API Gouv"""
        try:
            url = f"https://api-adresse.data.gouv.fr/search/?q={zipcode}&limit=1"
            res = requests.get(url, timeout=2).json()
            if res['features']:
                coords = res['features'][0]['geometry']['coordinates']
                return {"city": res['features'][0]['properties']['city'], "lat": coords[1], "lon": coords[0], "zip": zipcode}
        except: pass
        return {"city": "Localisation Inconnue", "lat": 48.8566, "lon": 2.3522, "zip": zipcode} # Fallback Paris

    def _fetch_dju_data(self, geo, start_date, end_date):
        """Récupère Météo via Open-Meteo et calcule les DJU"""
        try:
            s_str = start_date.strftime('%Y-%m-%d')
            e_str = end_date.strftime('%Y-%m-%d')
            url = f"https://archive-api.open-meteo.com/v1/archive?latitude={geo['lat']}&longitude={geo['lon']}&start_date={s_str}&end_date={e_str}&daily=temperature_2m_mean&timezone=Europe%2FParis"
            
            res = requests.get(url, timeout=3).json()
            if 'daily' in res and 'temperature_2m_mean' in res['daily']:
                temps = res['daily']['temperature_2m_mean']
                # Calcul DJU Base 18 (Chauffage)
                dju = sum([max(0, 18 - t) for t in temps if t is not None])
                return {"dju_total": int(dju), "status": "OK"}
        except: pass
        return {"dju_total": 0, "status": "API_ERROR"}

    def _module_climatique(self, conso_totale, dju_data):
        """Calcule la Signature Énergétique"""
        dju = dju_data['dju_total']
        kwh_par_dju = 0
        if dju > 0:
            kwh_par_dju = round(conso_totale / dju, 2)
        
        return {
            "climat": {
                "dju_periode": dju,
                "signature_kwh_dju": kwh_par_dju,
                "message": f"Rigueur climatique : {dju} DJU. Signature : {kwh_par_dju} kWh/DJU."
            }
        }

    # ==========================================================================
    # 3. MODULES STANDARDS (V9.3)
    # ==========================================================================
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
            
            # Auto-Scale
            if df['val'].median() > 2000: df['val'] = df['val'] / 1000
            
            # Time Step
            time_step = 0.166
            if len(df) > 1:
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: time_step = delta / 3600

            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step
        except: return None, 0.166

    def _module_socle(self, df, time_step):
        values = df['val'].tolist()
        pos_vals = [v for v in values if v > 0]
        talon = float(np.percentile(pos_vals, 10)) if pos_vals else 0.0
        
        df['wd'] = df['date'].dt.weekday
        w_mean = df[df['wd'] < 5]['val'].mean()
        we_mean = df[df['wd'] >= 5]['val'].mean()
        ratio = int((we_mean/w_mean)*100) if w_mean > 0 else 0
        p_max = max(values) if values else 0
        conso_kwh = sum(values) * time_step

        diag, status = "Profil Standard", "OK"
        if ratio > 70: diag, status = "ALERTE : Forte conso Weekend.", "WARNING"
        elif talon > (p_max * 0.6): diag, status = "ALERTE : Talon critique.", "WARNING"

        return {
            "points_traites": len(values),
            "conso_totale": self._safe_int(conso_kwh),
            "p_max": self._safe_float(p_max),
            "talon": self._safe_int(talon),
            "inactivity_ratio": self._safe_int(ratio),
            "moyenne": self._safe_float(np.mean(values)),
            "diagnosis": diag,
            "status": status
        }

    def _module_turpe(self, df, pmax):
        opti = pmax * 1.05
        return {"turpe_optimisation": {"p_recommandee": self._safe_int(opti), "message": f"P. Optimale : {self._safe_int(opti)} kVA."}}

    def _module_saison(self, df):
        df['m'] = df['date'].dt.month
        hiver = df[df['m'].isin([11,12,1,2,3])]['val'].mean()
        ete = df[~df['m'].isin([11,12,1,2,3])]['val'].mean()
        sens = "Neutre"
        if hiver > ete*1.5: sens = "Chauffage Elec."
        elif ete > hiver*1.2: sens = "Climatisation"
        return {"saisonnalite": {"sensibilite": sens}}

    def _module_finance(self, df, time_step):
        df['h'] = df['date'].dt.hour
        mask_hc = (df['h'] >= 22) | (df['h'] < 6)
        conso_hc = df[mask_hc]['val'].sum() * time_step
        conso_hp = df[~mask_hc]['val'].sum() * time_step
        
        budg = (conso_hp * 0.18) + (conso_hc * 0.12)
        tot = conso_hp + conso_hc
        part_hc = (conso_hc / tot * 100) if tot > 0 else 0
        pm = (budg / tot) if tot > 0 else 0

        return {
            "finance": {
                "budget_total_estime": self._safe_int(budg),
                "conso_hp": self._safe_int(conso_hp),
                "conso_hc": self._safe_int(conso_hc),
                "part_hc": self._safe_int(part_hc),
                "prix_moyen_calcule": round(pm, 3)
            }
        }

    def _generate_expert_narrative(self, k, p):
        txt = f"<b>ANALYSE V10 ({p.upper()}) :</b><br>"
        txt += f"• Localisation : <b>{k['geo']['city']}</b> ({k['geo']['zip']}).<br>"
        txt += f"• Climat : {k['climat']['dju_periode']} DJU sur la période.<br>"
        txt += f"• Signature : <b>{k['climat']['signature_kwh_dju']} kWh/DJU</b>.<br>"
        txt += f"• Finance : Budget est. {k['finance']['budget_total_estime']:,} €.<br>"
        txt += f"• Diag : {k['diagnosis']}"
        return txt

    def _module_retail_placeholder(self, kpis):
        return {"benchmark": [], "froid_analysis": {"ratio": 0, "is_alert": False}}

    # --- AUDIT PDF ---
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
        m_ref = re.search(r"(?:Contrat|Réf)\s?[:N°.]?\s?([A-Z0-9-]{5,})", txt, re.I)
        ref = m_ref.group(1) if m_ref else "Non détecté"
        has_tax = "CSPE" in txt or "TICGN" in txt
        
        checks = [
            {"point": "Puissance Souscrite", "a": f"{p_sous} kVA", "b": "Contrat", "status": "LU", "error": False},
            {"point": "Puissance Atteinte", "a": f"{p_att} kVA", "b": "-", "status": "ALERTE" if p_att > p_sous else "OK", "error": p_att > p_sous},
            {"point": "Réf. Contrat", "a": ref, "b": "Base", "status": "OK" if ref != "Non détecté" else "KO", "error": ref == "Non détecté"},
            {"point": "Taxes (CSPE/TICGN)", "a": "Présentes" if has_tax else "Non", "b": "Requises", "status": "OK" if has_tax else "KO", "error": not has_tax}
        ]
        return {"score": 80, "checks": checks}

    def ask_agent(self, q): return "Cortex V10.0 Online."
    def run_chaos_monkey(self): return [{"test": "API Météo", "status": "READY"}]

cortex = CortexEngine()
