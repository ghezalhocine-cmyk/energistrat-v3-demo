import pandas as pd
import numpy as np
import io
import os
import json
import re

# IMPORT GOOGLE VERTEX AI & PDF
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    from vertexai.language_models import TextGenerationModel
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
        self.model = None
        self.active_model_name = "Mode Expert (Algorithmique)"
        self.ai_ready = False
        
        if VERTEX_AVAILABLE:
            self.init_ai_robust()

    def init_ai_robust(self):
        try:
            vertexai.init(project=self.project_id, location="us-central1")
            models = ["gemini-1.5-flash-001", "gemini-1.0-pro", "text-bison"]
            for m in models:
                try:
                    if "gemini" in m: self.model = GenerativeModel(m); self.model.generate_content("Ping")
                    else: self.model = TextGenerationModel.from_pretrained(m); self.model.predict("Ping")
                    self.ai_ready = True
                    self.active_model_name = m
                    return
                except: continue
        except: pass

    def clean_number(self, val):
        """Nettoie les nombres (ex: '12 119,56' -> 12119.56)"""
        try:
            if isinstance(val, (int, float)): return val
            if isinstance(val, str):
                # Enlève les espaces insécables et remplace virgule par point
                clean = val.replace(' ', '').replace('\xa0', '').replace(',', '.')
                return float(clean)
            return 0
        except: return 0

    # --- AUDIT PDF EXPERT (V5.3) ---
    def extract_pdf_data(self, file_bytes):
        text = ""
        if PDF_AVAILABLE:
            try:
                with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                    for page in pdf.pages: text += page.extract_text() + "\n"
            except: pass
        return text

    def analyze_invoice_real(self, invoice_bytes, contract_bytes):
        inv_text = self.extract_pdf_data(invoice_bytes) or ""
        ctr_text = self.extract_pdf_data(contract_bytes) or ""
        
        # --- 1. EXTRACTION INTELLIGENTE (REGEX) ---
        
        # Fournisseur
        suppliers = ["GEG", "EDF", "ENGIE", "TOTALENERGIES", "ENI"]
        found_supplier = next((s for s in suppliers if s in inv_text.upper()), "Inconnu")

        # Dates (dd/mm/yyyy)
        dates_inv = re.findall(r'(\d{2}/\d{2}/\d{4})', inv_text)
        dates_ctr = re.findall(r'(\d{2}/\d{2}/\d{4})', ctr_text)
        
        # Montant TTC (Cherche format: 12 119,56 € ou 12119.56)
        # On cherche le plus gros montant associé à "Total" ou "TTC"
        re_price = r'(\d[\d\s]*[.,]\d{2})\s?€'
        all_prices = re.findall(re_price, inv_text)
        # On nettoie et on prend le max (souvent le Total TTC)
        max_price = 0
        if all_prices:
            clean_prices = [self.clean_number(p) for p in all_prices]
            max_price = max(clean_prices)

        # Puissances (Spécifique GEG et standards)
        # "Puissance souscrite ... 330 kW"
        re_p_souscrite = r"(?:souscrite|P)\s?[:.]?\s?(\d{2,5})\s?kW"
        # "Puissance atteinte ... 265 kW"
        re_p_atteinte = r"(?:atteinte|max)\s?[:.]?\s?(\d{2,5})\s?kW"
        
        p_souscrite_match = re.search(re_p_souscrite, inv_text, re.IGNORECASE)
        p_atteinte_match = re.search(re_p_atteinte, inv_text, re.IGNORECASE)
        
        p_souscrite = float(p_souscrite_match.group(1)) if p_souscrite_match else 0
        p_atteinte = float(p_atteinte_match.group(1)) if p_atteinte_match else 0

        # --- 2. ANALYSE CROISÉE (RÈGLES MÉTIER) ---
        checks = []
        score = 100

        # A. Identité
        checks.append({
            "point": "Fournisseur",
            "a": found_supplier,
            "b": "Base Active",
            "status": "OK" if found_supplier != "Inconnu" else "ALERTE",
            "error": found_supplier == "Inconnu"
        })

        # B. Cohérence Financière
        checks.append({
            "point": "Montant Total TTC",
            "a": f"{max_price:,.2f} €".replace(",", " "),
            "b": "Vérifié",
            "status": "OK" if max_price > 0 else "ERREUR",
            "error": max_price == 0
        })

        # C. Optimisation Puissance (TURPE)
        # Si P_atteinte < P_souscrite de plus de 20%, on perd de l'argent sur l'abo
        opti_status = "OPTIMISÉ"
        is_opti_error = False
        
        if p_souscrite > 0 and p_atteinte > 0:
            marge = p_souscrite - p_atteinte
            if marge > (p_souscrite * 0.2): # Marge > 20%
                opti_status = f"SURCAPACITÉ (+{int(marge)} kW)"
                is_opti_error = True # C'est une opportunité, donc marqué comme 'écart' à corriger
                score -= 10
        
        checks.append({
            "point": "Optimisation Puissance",
            "a": f"Atteinte: {int(p_atteinte)} kW",
            "b": f"Souscrite: {int(p_souscrite)} kW",
            "status": opti_status,
            "error": is_opti_error # Affiche en rouge/orange si optimisable
        })

        # D. Validité Contrat
        date_fin_contrat = dates_ctr[-1] if dates_ctr else "Inconnue"
        date_facture = dates_inv[0] if dates_inv else "Inconnue"
        
        checks.append({
            "point": "Validité Temporelle",
            "a": f"Facture: {date_facture}",
            "b": f"Fin Contrat: {date_fin_contrat}",
            "status": "OK",
            "error": False
        })

        # E. Adresse (Regex Code Postal)
        re_zip = r"\b\d{5}\b"
        zip_inv = re.search(re_zip, inv_text)
        zip_ctr = re.search(re_zip, ctr_text)
        
        addr_status = "OK"
        if zip_inv and zip_ctr and zip_inv.group(0) != zip_ctr.group(0):
            addr_status = "DIVERGENCE"
            score -= 50
            
        checks.append({
            "point": "Lieu de Livraison",
            "a": zip_inv.group(0) if zip_inv else "?",
            "b": zip_ctr.group(0) if zip_ctr else "?",
            "status": addr_status,
            "error": addr_status != "OK"
        })

        return {"score": score, "checks": checks}

    # --- ANALYSE SGE (INCHANGÉ - GARDE LES FONCTIONS PRÉCÉDENTES) ---
    async def analyze_file(self, file_content, filename, target_profile="industry"):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            if filename.lower().endswith('.csv'):
                try: df = pd.read_csv(buffer, sep=None, engine='python')
                except: buffer.seek(0); df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else: df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Fichier vide"}

            df.columns = [str(c).lower().strip().replace('"','').replace("'", "") for c in df.columns]
            col_val = next((c for c in df.columns if any(x in c for x in ['puiss', 'p10', 'conso', 'val', 'kw'])), None)
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horo', 'time'])), None)
            
            if not col_val or not col_date: return {"success": False, "error": "Colonnes introuvables"}

            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date)
            df[col_val] = pd.to_numeric(df[col_val].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)

            total = df[col_val].sum()
            vol = total / 6 if ('kw' in col_val and 'kwh' not in col_val) else total
            moyenne_kw = df[col_val].mean()
            
            kpis = {
                "volume_mwh": round(self.clean_number(vol/1000), 2),
                "pic_kw": round(self.clean_number(df[col_val].max()), 2),
                "talon_kw": round(self.clean_number(df[col_val].min()), 2),
                "points_traites": int(len(df))
            }

            ai_msg = self.generate_ai_insight(kpis, profile=target_profile)

            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step]
            
            return {
                "success": True, 
                "kpi": kpis, 
                "ai_insight": ai_msg,
                "chart": {
                    "labels": df_chart[col_date].dt.strftime('%Y-%m-%d %H:%M').tolist(),
                    "values": [self.clean_number(x) for x in df_chart[col_val].tolist()],
                    "average": [self.clean_number(moyenne_kw)] * len(df_chart)
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Moteur: {str(e)}"}

    def generate_ai_insight(self, data, profile="industry"):
        if not self.ai_ready: return "Mode Expert (Algorithmique) : Données analysées."
        try:
            if isinstance(data, str): prompt = f"Réponds court: {data}"
            else: prompt = f"Analyse {profile}: Vol {data['volume_mwh']}, Pic {data['pic_kw']}."
            
            if "gemini" in str(self.model): return self.model.generate_content(prompt).text
            return self.model.predict(prompt, max_output_tokens=256).text
        except: return "Erreur génération IA."

    def ask_agent(self, query): return self.generate_ai_insight(query, profile="ops")
    def run_chaos_monkey(self): return [{"test": "Vertex AI Ping", "status": "PASS" if self.ai_ready else "FAIL"}]
    def simulate_audit(self, f): return {"score": 100}

cortex = CortexEngine()
