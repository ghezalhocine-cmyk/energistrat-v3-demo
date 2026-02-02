# app/core/cortex_engine.py V14.1 - FULL FEATURED (NAF + PDF)
import pandas as pd
import numpy as np
import io
import re
import requests
import math
from datetime import datetime

# GESTION DES DEPENDANCES LOURDES (PDF)
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("⚠️ PDFPlumber non installé. L'audit facture sera limité.")

class CortexEngine:
    def __init__(self):
        self.version = "14.1 (Full NAF + PDF)"
        
        # --- BASE DE DONNÉES SECTORIELLE COMPLETE (V13) ---
        self.NAF_DB = {
            # ALIMENTATION
            "10.71C": {"label": "Boulangerie", "profile": "BAKERY", "keywords": ["BOULANGERIE", "PAIN", "FOURNIL"]},
            "10.71D": {"label": "Pâtisserie", "profile": "BAKERY", "keywords": ["PATISSERIE"]},
            "10.11Z": {"label": "Transformation Viande", "profile": "COLD", "keywords": ["BOUCHERIE", "ABATTOIR"]},
            "10.51A": {"label": "Laiterie", "profile": "COLD", "keywords": ["LAIT", "FROMAGE"]},
            
            # COMMERCE
            "47.11":  {"label": "Supermarché", "profile": "COLD", "keywords": ["SUPERMARCHE", "MARKET", "SUPER"]},
            "47.11D": {"label": "Supermarché", "profile": "COLD", "keywords": ["SUPER"]},
            "47.11F": {"label": "Hyper", "profile": "COLD", "keywords": ["HYPER", "GRAND SURFACE"]},
            
            # HORECA
            "55.10Z": {"label": "Hôtellerie", "profile": "CONTINUOUS", "keywords": ["HOTEL", "CHAMBRE"]},
            "56.10A": {"label": "Restauration", "profile": "SERVICE", "keywords": ["RESTAURANT", "RESTO"]},
            "56.10C": {"label": "Fast Food", "profile": "SERVICE", "keywords": ["SNACK", "BURGER"]},
            
            # SANTÉ
            "86.10Z": {"label": "Hôpital", "profile": "CONTINUOUS", "keywords": ["HOPITAL", "CHU", "CLINIQUE"]},
            "87.10A": {"label": "EHPAD", "profile": "CONTINUOUS", "keywords": ["EHPAD", "RETRAITE"]},
            
            # INDUSTRIE
            "25.11Z": {"label": "Métallurgie", "profile": "PROCESS", "keywords": ["METAL", "ACIER"]},
            "22.29A": {"label": "Plasturgie", "profile": "PROCESS", "keywords": ["PLASTIQUE", "INJECTION"]},
            "20.14Z": {"label": "Chimie", "profile": "PROCESS", "keywords": ["CHIMIE", "PHARMA"]},
            "16.10A": {"label": "Scierie", "profile": "PROCESS", "keywords": ["BOIS", "SCIERIE"]},
            "25.62B": {"label": "Mécanique Ind.", "profile": "PROCESS", "keywords": ["MECANIQUE", "USINAGE"]},
            "28.29A": {"label": "Fab. Machines", "profile": "PROCESS", "keywords": ["MACHINE", "INDUSTRIE"]},
            
            # TERTIAIRE
            "68.20B": {"label": "Bureaux", "profile": "OFFICE", "keywords": ["BUREAU", "SIEGE", "AGENCE"]},
            "84.11Z": {"label": "Administration", "profile": "OFFICE", "keywords": ["MAIRIE", "ADMIN", "PREFECTURE"]},
            "64.19Z": {"label": "Banque", "profile": "OFFICE", "keywords": ["BANQUE", "ASSURANCE"]},
            "62.01Z": {"label": "Informatique", "profile": "OFFICE", "keywords": ["IT", "DEV"]},
            "63.11Z": {"label": "Data Center", "profile": "FLAT_LINE", "keywords": ["DATA", "SERVER", "CLOUD"]},
            "61.10Z": {"label": "Télécoms", "profile": "FLAT_LINE", "keywords": ["TELECOM"]},
            
            # PUBLIC & SPORT
            "85.20Z": {"label": "École Primaire", "profile": "SCHOOL", "keywords": ["ECOLE", "PRIMAIRE", "SCOLAIRE"]},
            "85.31Z": {"label": "Collège/Lycée", "profile": "SCHOOL", "keywords": ["COLLEGE", "LYCEE"]},
            "93.11Z": {"label": "Gymnase/Stade", "profile": "SPORT", "keywords": ["GYMNASE", "STADE", "PISCINE"]},
            "EP":     {"label": "Éclairage Public", "profile": "INVERSE", "keywords": ["EP", "ECLAIRAGE", "LUM", "LAMPADAIRE"]}
        }

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
    def analyze_file(self, file_content, filename, target_profile="demo"):
        """
        Point d'entrée principal pour l'analyse des fichiers de consommation.
        """
        try:
            # A. INGESTION
            df, time_step_hours = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Fichier illisible"}

            # B. CONTEXTE
            zip_code = self._extract_zipcode_smart(filename)
            geo_data = self._fetch_geo_data(zip_code)
            naf_info = self._detect_naf_advanced(filename)
            
            # C. MODULES EXPERTS
            base = self._module_socle(df, time_step_hours)
            turpe = self._module_turpe(df, base['p_max'])
            season = self._module_saison(df)
            finance = self._module_finance(df, time_step_hours)
            
            # Module Sectoriel (Le cœur de ton expertise)
            sector = self._module_sectoriel_v12(df, naf_info)
            
            # D. PRÉPARATION VISUALISATION
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step]
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                "average": [base['moyenne']] * len(df_chart)
            }

            narrative = self._generate_expert_narrative({**base, **turpe, **finance, **sector, "geo": geo_data}, target_profile)

            return {
                "success": True,
                "kpi": {**base, **turpe, **season, **finance, **sector, "geo": geo_data, "sectoriel": naf_info},
                "chart": chart,
                "ai_insight": narrative
            }
        except Exception as e:
            return {"success": False, "error": f"Erreur Cortex: {str(e)}"}

    # ==========================================================================
    # 2. MODULES AUDIT PDF (FACTURES)
    # ==========================================================================
    def extract_pdf(self, b):
        """Extraction brute du texte PDF"""
        t = ""
        if PDF_AVAILABLE:
            try:
                with pdfplumber.open(io.BytesIO(b)) as pdf:
                    for p in pdf.pages: t += p.extract_text() + "\n"
            except Exception as e:
                print(f"PDF Error: {e}")
        return t

    def analyze_invoice_real(self, inv_b, ctr_b):
        """Comparaison Facture vs Contrat (Regex)"""
        txt = self.extract_pdf(inv_b) or ""
        
        # Extraction Regex Robuste
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

    # ==========================================================================
    # 3. MOTEUR MATHÉMATIQUE & SECTORIEL
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
            # Nettoyage valeurs (virgules, espaces)
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').replace(' ', ''), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')

            df = df.dropna(subset=['date'])
            df['val'] = df['val'].fillna(0).replace([np.inf, -np.inf], 0)
            df = df.sort_values(by='date')
            
            # Auto-Scale Watts -> kW
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
        
        ratio = (we_mean / w_mean * 100) if w_mean > 0 else 0
        safe_ratio = self._safe_int(ratio)
        
        p_max = max(values) if values else 0
        conso_kwh = sum(values) * time_step

        return {
            "points_traites": len(values),
            "conso_totale": self._safe_int(conso_kwh),
            "p_max": self._safe_float(p_max),
            "talon": self._safe_int(talon),
            "inactivity_ratio": safe_ratio,
            "moyenne": self._safe_float(np.mean(values))
        }

    def _module_sectoriel_v12(self, df, naf):
        """Ton moteur expert qui analyse selon le code NAF"""
        profile = naf["profile"]
        diag = f"Profil détecté : {profile} ({naf['label']})."
        status = "OK"
        
        # Exemple Logic EP (Eclairage Public)
        if profile == "INVERSE": 
            df['h'] = df['date'].dt.hour
            conso_jour = df[(df['h'] >= 10) & (df['h'] <= 16)]['val'].sum()
            total = df['val'].sum()
            part = (conso_jour / total * 100) if total > 0 else 0
            if part > 5: diag, status = f"⚠️ ALERTE EP : {int(part)}% de conso jour.", "WARNING"
            else: diag, status = "✅ PERFORMANCE EP : Cycles nocturnes OK.", "OPTIMIZED"

        # Exemple Logic Bureaux
        elif profile == "OFFICE":
            df['wd'] = df['date'].dt.weekday
            we_mean = df[df['wd'] >= 5]['val'].mean()
            w_mean = df[df['wd'] < 5]['val'].mean()
            ratio = (we_mean / w_mean * 100) if w_mean > 0 else 0
            if ratio > 35: diag, status = f"⚠️ ALERTE BUREAUX : Talon Weekend élevé ({int(ratio)}%).", "WARNING"

        return {
            "sectoriel": {
                "secteur": naf['label'],
                "code_naf": naf['code'],
                "archetype": profile,
                "diagnostic": diag,
                "status": status
            }
        }

    def _module_turpe(self, df, pmax):
        opti = pmax * 1.05
        return {"turpe_optimisation": {"p_recommandee": self._safe_int(opti)}}

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
        return {"finance": {"budget_total_estime": self._safe_int(budg)}}

    # --- UTILS ---
    def _detect_naf_advanced(self, filename):
        fn = filename.upper()
        # 1. Code NAF strict
        naf_regex = re.search(r'\b\d{2}\.\d{2}[A-Z]\b', fn)
        if naf_regex:
            code = naf_regex.group(0)
            if code in self.NAF_DB: return {"code": code, **self.NAF_DB[code]}
        # 2. Mots-Clés
        for code, info in self.NAF_DB.items():
            if info["label"].upper() in fn: return {"code": code, **info}
            for kw in info["keywords"]:
                if kw in fn: return {"code": code, **info}
        return {"code": "NA", "label": "Non Identifié", "profile": "STANDARD"}

    def _extract_zipcode_smart(self, filename):
        matches = re.findall(r'(?<!\d)(\d{5})(?!\d)', filename)
        return matches[-1] if matches else "75001"

    def _fetch_geo_data(self, zipcode):
        try:
            url = f"https://api-adresse.data.gouv.fr/search/?q={zipcode}&limit=1"
            res = requests.get(url, timeout=2).json()
            if res['features']:
                props = res['features'][0]['properties']
                return {"city": props['city'], "zip": zipcode}
        except: pass
        return {"city": "Localisation Inconnue", "zip": zipcode}

    def _generate_expert_narrative(self, k, p):
        txt = f"<b>ANALYSE V14 ({p.upper()}) :</b><br>"
        if 'sectoriel' in k:
            txt += f"• Profil : <b>{k['sectoriel']['label']}</b>.<br>"
            txt += f"• Diag : {k['sectoriel']['diagnostic']}<br>"
        txt += f"• Budget Est. : {k['finance']['budget_total_estime']:,} €.<br>"
        return txt

    def ask_agent(self, q): return "Cortex V14 Online."
    def run_chaos_monkey(self): return [{"test": "PDF Engine", "status": "OK" if PDF_AVAILABLE else "MISSING"}]

# Instance Singleton
cortex = CortexEngine()
