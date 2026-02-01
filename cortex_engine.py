# cortex_engine.py V11.0 - SECTORIAL INTELLIGENCE (NAF + SOLAR)
import pandas as pd
import numpy as np
import io
import os
import json
import re
import logging
import requests
import math # NOUVEAU POUR CALCUL SOLAIRE
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

            # B. CONTEXTE GÉO
            zip_match = re.search(r'(?<!\d)(0[1-9]|[1-8]\d|9[0-5])\d{3}(?!\d)', filename)
            zip_code = zip_match.group(0) if zip_match else "75001"
            geo_data = self._fetch_geo_data(zip_code)
            
            # Dates
            start_date = df['date'].min()
            end_date = df['date'].max()
            dju_data = self._fetch_dju_data(geo_data, start_date, end_date)

            # C. DÉTECTION SECTORIELLE (NOUVEAU V11)
            naf_detected = self._detect_naf(filename)

            # D. MODULES EXPERTS
            base = self._module_socle(df, time_step_hours)
            turpe = self._module_turpe(df, base['p_max'])
            season = self._module_saison(df)
            finance = self._module_finance(df, time_step_hours)
            climat = self._module_climatique(base['conso_totale'], dju_data)
            
            # Module Sectoriel (Analyse Métier)
            sector = self._module_sectoriel(df, naf_detected, geo_data)
            
            context = {
                "start": start_date.strftime('%d/%m/%Y'),
                "end": end_date.strftime('%d/%m/%Y'),
                "days": (end_date - start_date).days,
                "naf": naf_detected
            }
            
            final_kpis = {**base, **turpe, **season, **finance, **climat, **sector, "geo": geo_data, "context": context}
            
            # E. SAMPLING
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
    # 2. INTELLIGENCE SECTORIELLE (NOUVEAU V11)
    # ==========================================================================
    def _detect_naf(self, filename):
        """Détecte l'activité via le nom de fichier"""
        fn = filename.upper()
        if "EP" in fn or "ECLAIRAGE" in fn or "LUM" in fn: return {"code": "EP", "label": "Éclairage Public"}
        if "ECOLE" in fn or "85.20Z" in fn: return {"code": "85.20Z", "label": "Enseignement"}
        if "GYM" in fn or "STADE" in fn: return {"code": "93.11Z", "label": "Sport"}
        if "MAIRIE" in fn or "BUREAU" in fn: return {"code": "84.11Z", "label": "Bureaux/Admin"}
        return {"code": "NA", "label": "Standard"}

    def _module_sectoriel(self, df, naf, geo):
        """Analyse spécifique selon le secteur"""
        code = naf["code"]
        diag_metier = "Analyse générique."
        status_metier = "OK"
        
        # CAS 1 : ÉCLAIRAGE PUBLIC (EP)
        if code == "EP":
            # Analyse Solaire simplifiée (Jour = 10h-16h toute l'année pour être sûr)
            # On vérifie si ça consomme quand il fait jour
            df['hour'] = df['date'].dt.hour
            conso_jour = df[(df['hour'] >= 10) & (df['hour'] <= 16)]['val'].sum()
            total = df['val'].sum()
            
            part_jour = (conso_jour / total * 100) if total > 0 else 0
            
            if part_jour > 5:
                diag_metier = f"⚠️ ALERTE EP : {int(part_jour)}% de conso en plein jour (Allumage diurne)."
                status_metier = "WARNING"
            else:
                diag_metier = "✅ PERFORMANCE EP : Cycles nocturnes synchronisés."
                status_metier = "OPTIMIZED"

        # CAS 2 : BÂTIMENT (ECOLE / BUREAU)
        elif code in ["85.20Z", "84.11Z"]:
            # Vérification Weekend
            df['wd'] = df['date'].dt.weekday
            conso_we = df[df['wd'] >= 5]['val'].mean()
            conso_semaine = df[df['wd'] < 5]['val'].mean()
            
            ratio = (conso_we / conso_semaine * 100) if conso_semaine > 0 else 0
            
            if ratio > 30:
                diag_metier = f"⚠️ ALERTE OCCUPATION : Le bâtiment consomme trop le weekend ({int(ratio)}% vs semaine)."
                status_metier = "WARNING"
            else:
                diag_metier = "✅ GESTION : Bon abaissement le weekend."

        return {
            "sectoriel": {
                "secteur": naf['label'],
                "diagnostic": diag_metier,
                "status": status_metier
            }
        }

    # ==========================================================================
    # 3. API EXTERNES
    # ==========================================================================
    def _fetch_geo_data(self, zipcode):
        try:
            url = f"https://api-adresse.data.gouv.fr/search/?q={zipcode}&limit=1"
            res = requests.get(url, timeout=2).json()
            if res['features']:
                props = res['features'][0]['properties']
                coords = res['features'][0]['geometry']['coordinates']
                return {"city": props['city'], "lat": coords[1], "lon": coords[0], "zip": zipcode}
        except: pass
        return {"city": "Paris (Défaut)", "lat": 48.8566, "lon": 2.3522, "zip": "75001"}

    def _fetch_dju_data(self, geo, start_date, end_date):
        try:
            s_str = start_date.strftime('%Y-%m-%d')
            e_str = end_date.strftime('%Y-%m-%d')
            url = f"https://archive-api.open-meteo.com/v1/archive?latitude={geo['lat']}&longitude={geo['lon']}&start_date={s_str}&end_date={e_str}&daily=temperature_2m_mean&timezone=Europe%2FParis"
            
            res = requests.get(url, timeout=3).json()
            if 'daily' in res and 'temperature_2m_mean' in res['daily']:
                temps = res['daily']['temperature_2m_mean']
                dju = sum([max(0, 18 - t) for t in temps if t is not None])
                return {"dju_total": self._safe_int(dju), "status": "OK"}
        except: pass
        return {"dju_total": 0, "status": "API_ERROR"}

    def _module_climatique(self, conso_totale, dju_data):
        dju = dju_data['dju_total']
        kwh_par_dju = 0
        if dju > 0:
            kwh_par_dju = round(conso_totale / dju, 2)
        
        return {
            "climat": {
                "dju_periode": self._safe_int(dju),
                "signature_kwh_dju": kwh_par_dju,
                "message": f"{dju} DJU Base 18."
            }
        }

    # ==========================================================================
    # 4. MODULES STANDARDS
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
            
            if df['val'].median() > 2000: df['val'] = df['val'] / 1000
            
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
        
        ratio = 0
        if w_mean > 0: ratio = (we_mean / w_mean) * 100
        
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
        txt = f"<b>ANALYSE V11 ({p.upper()}) :</b><br>"
        if 'geo' in k: txt += f"• Lieu : <b>{k['geo']['city']}</b>.<br>"
        
        # Ajout Narratif Sectoriel
        if 'sectoriel' in k:
            txt += f"• Métier : <b>{k['sectoriel']['secteur']}</b>.<br>"
            if k['sectoriel']['status'] != 'OK':
                txt += f"• 🎯 <b>{k['sectoriel']['diagnostic']}</b><br>"
        
        if 'climat' in k and k['climat']['dju_periode'] > 0: txt += f"• Climat : {k['climat']['dju_periode']} DJU.<br>"
        txt += f"• Finance : Budget est. {k['finance']['budget_total_estime']:,} €.<br>"
        
        # Si pas d'alerte sectorielle, on met le diag technique
        if 'sectoriel' not in k or k['sectoriel']['status'] == 'OK':
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

    def ask_agent(self, q): return "Cortex V11.0 Online."
    def run_chaos_monkey(self): return [{"test": "API Météo", "status": "READY"}]

cortex = CortexEngine()
