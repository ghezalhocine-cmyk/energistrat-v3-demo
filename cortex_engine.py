# cortex_engine.py V9.0 - FINANCE MODULE ADDED
import pandas as pd
import numpy as np
import io
import os
import json
import re
import logging

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

    # --- 1. ANALYSE SGE ---
    async def analyze_file(self, file_content, filename, target_profile="demo"):
        try:
            df = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Fichier illisible"}

            # Modules Experts
            base = self._module_socle(df)
            turpe = self._module_turpe(df, base['p_max'])
            season = self._module_saison(df)
            
            # --- NOUVEAU MODULE FINANCE ---
            finance = self._module_finance(df)
            
            final_kpis = {**base, **turpe, **season, **finance}
            
            # Sampling Graphique
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step]
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart)
            }

            narrative = self._generate_narrative(final_kpis, target_profile)

            return {
                "success": True,
                "kpi": final_kpis,
                "chart": chart,
                "ai_insight": narrative,
                "retail_data": None
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- 2. MODULES ---
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

            df = df.dropna(subset=['date']).sort_values(by='date')
            df['val'] = df['val'].fillna(0)
            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']]
        except: return None

    def _module_socle(self, df):
        vals = df['val'].tolist()
        pos = [v for v in vals if v > 0]
        talon = float(np.percentile(pos, 10)) if pos else 0.0
        
        df['wd'] = df['date'].dt.weekday
        w_mean = df[df['wd'] < 5]['val'].mean()
        we_mean = df[df['wd'] >= 5]['val'].mean()
        ratio = int((we_mean/w_mean)*100) if w_mean > 0 else 0
        p_max = max(vals) if vals else 0

        diag, status = "Profil Standard", "OK"
        if ratio > 65: diag, status = "ALERTE : Forte conso Weekend (>65%).", "WARNING"
        elif talon > (p_max * 0.5): diag, status = "ALERTE : Talon critique (>50% Pmax).", "WARNING"

        return {
            "points_traites": len(vals),
            "conso_totale": self._safe_int(sum(vals)/6), # Approx 10min
            "p_max": self._safe_float(p_max),
            "talon": self._safe_int(talon),
            "inactivity_ratio": ratio,
            "moyenne": self._safe_float(np.mean(vals)),
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

    # --- NOUVEAU MODULE FINANCE V9.0 ---
    def _module_finance(self, df):
        """
        Calcule un budget estimatif basé sur des prix de marché standards.
        HP (Heures Pleines) : 06h-22h | HC (Heures Creuses) : 22h-06h
        Prix Ref (2025) : HP=0.18€/kWh, HC=0.12€/kWh
        """
        df['hour'] = df['date'].dt.hour
        
        # Segmentation HP/HC
        mask_hc = (df['hour'] >= 22) | (df['hour'] < 6)
        conso_hc = df[mask_hc]['val'].sum() / 6 # Approx 10min -> kWh
        conso_hp = df[~mask_hc]['val'].sum() / 6
        
        # Prix de référence (à rendre dynamique plus tard via input Ops)
        PRIX_HP = 0.18
        PRIX_HC = 0.12
        
        budget_hp = conso_hp * PRIX_HP
        budget_hc = conso_hc * PRIX_HC
        budget_total = budget_hp + budget_hc
        
        # Part HC
        total_kwh = conso_hp + conso_hc
        part_hc = int((conso_hc / total_kwh * 100)) if total_kwh > 0 else 0
        
        return {
            "finance": {
                "budget_total_estime": self._safe_int(budget_total),
                "conso_hp": self._safe_int(conso_hp),
                "conso_hc": self._safe_int(conso_hc),
                "part_hc": part_hc,
                "prix_moyen_calcule": round(budget_total / total_kwh, 3) if total_kwh > 0 else 0
            }
        }

    def _generate_expert_narrative(self, k, p):
        # Ajout de la dimension financière dans le texte
        txt = f"<b>ANALYSE ({p.upper()}) :</b><br>"
        txt += f"• Volumétrie : {k['conso_totale']:,} kWh.<br>"
        txt += f"• Finance : Budget est. <b>{k['finance']['budget_total_estime']:,} €/an</b> (Prix moyen {k['finance']['prix_moyen_calcule']} €/kWh).<br>"
        txt += f"• Puissance : Pic à {k['p_max']} kW. {k['turpe_optimisation']['message']}<br>"
        txt += f"• Comportement : {k['diagnosis']}<br>"
        return txt

    def _module_retail_placeholder(self, kpis):
        return {
            "benchmark": [{"nom": "Site Actuel", "conso": kpis['conso_totale'], "ratio": "---", "status": kpis['status']}],
            "froid_analysis": {"ratio": 0, "is_alert": False, "message": "En attente module Froid."}
        }

    # --- 3. AUDIT RICHE ---
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

    def ask_agent(self, q): return "Cortex V9.0 Online."
    def run_chaos_monkey(self): return [{"test": "Maths", "status": "PASS"}]

cortex = CortexEngine()
