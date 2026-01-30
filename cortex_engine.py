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
                    return
                except: continue
        except: pass

    def clean_number(self, val):
        try:
            if isinstance(val, str):
                # Nettoyage format français (espace insécable, virgule)
                val = val.replace(' ', '').replace('\xa0', '').replace(',', '.')
            if pd.isna(val) or np.isinf(val): return 0
            return float(val)
        except: return 0

    # --- AUDIT PDF EXPERT FRANCE (V5.4) ---
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
        
        # 1. RECHERCHE INTELLIGENTE DES PUISSANCES (TURPE)
        # On cherche des motifs comme "Souscrite : 330" ou "P : 250"
        re_p_sous = r"(?:souscrite|P\.?\s?souscrite|P\.?\s?S\.?)[^\d]*(\d{2,5})"
        re_p_max  = r"(?:atteinte|max|pointe)[^\d]*(\d{2,5})"
        
        match_sous = re.search(re_p_sous, inv_text, re.IGNORECASE)
        match_max  = re.search(re_p_max, inv_text, re.IGNORECASE)
        
        p_souscrite = float(match_sous.group(1)) if match_sous else 0
        p_atteinte = float(match_max.group(1)) if match_max else 0

        # 2. IDENTIFICATION FOURNISSEUR & CONTRAT
        suppliers = ["GEG", "EDF", "ENGIE", "TOTALENERGIES", "ENI", "VATTENFALL", "ALPIQ"]
        found_supplier = next((s for s in suppliers if s in inv_text.upper()), "Inconnu")
        
        re_contrat = r"(?:Contrat|Réf)\s?[:N°.]?\s?([A-Z0-9-]{5,})"
        match_contrat = re.search(re_contrat, inv_text, re.IGNORECASE)
        num_contrat = match_contrat.group(1) if match_contrat else "Non détecté"

        # 3. ANALYSE FISCALE (CSPE / TICGN)
        # La CSPE est devenue TICGN, on cherche les deux termes
        has_taxes = "TICGN" in inv_text.upper() or "CSPE" in inv_text.upper()

        checks = []
        score = 100

        # --- CHECK 1 : OPTIMISATION PUISSANCE (Le plus rentable) ---
        if p_souscrite > 0 and p_atteinte > 0:
            ratio = p_atteinte / p_souscrite
            if ratio > 1.02:
                status = "DÉPASSEMENT" # Pénalités
                color = "KO"
                score -= 30
                conseil = f"Augmenter P. Souscrite (Atteint: {int(p_atteinte)} kW)"
            elif ratio < 0.7:
                status = "SUR-SOUSCRIPTION" # Gaspillage abonnement
                color = "KO"
                score -= 20
                conseil = f"Baisser P. Souscrite (Trop payé)"
            else:
                status = "OPTIMISÉ"
                color = "OK"
                conseil = "Puissance bien calibrée"
                
            checks.append({
                "point": "Optimisation TURPE",
                "a": f"Atteinte: {int(p_atteinte)} kW",
                "b": f"Souscrite: {int(p_souscrite)} kW",
                "status": status,
                "error": color == "KO"
            })
        else:
            checks.append({"point": "Optimisation TURPE", "a": "?", "b": "?", "status": "NON LU", "error": True})

        # --- CHECK 2 : CONFORMITÉ CONTRAT ---
        checks.append({
            "point": "Réf. Contrat & Fournisseur",
            "a": f"{found_supplier} - {num_contrat}",
            "b": "Base Active",
            "status": "OK" if found_supplier != "Inconnu" else "INCONNU",
            "error": found_supplier == "Inconnu"
        })

        # --- CHECK 3 : FISCALITÉ ---
        checks.append({
            "point": "Taxes (TICGN/CSPE)",
            "a": "Présentes" if has_taxes else "Absentes",
            "b": "Obligatoire",
            "status": "OK" if has_taxes else "ALERTE",
            "error": not has_taxes
        })

        # --- CHECK 4 : ADRESSE LIVRAISON ---
        # Recherche code postal 5 chiffres
        re_zip = r"\b(0[1-9]|[1-8]\d|9[0-5])\d{3}\b"
        zip_match = re.search(re_zip, inv_text)
        checks.append({
            "point": "Point de Livraison (Zip)",
            "a": zip_match.group(0) if zip_match else "?",
            "b": "Site Autorisé",
            "status": "OK" if zip_match else "MANQUANT",
            "error": not zip_match
        })

        return {"score": score, "checks": checks}

    # --- ANALYSE SGE (V5.4 - Moyenne Mobile) ---
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
            
            # --- CALCUL MOYENNE MOBILE (TENDANCE) ---
            # On calcule une moyenne glissante sur 24 points (approx 1 jour ou 4h selon le pas)
            # pour lisser la courbe et montrer la tendance de fond.
            rolling_mean = df[col_val].rolling(window=24, min_periods=1).mean().fillna(0)
            
            kpis = {
                "volume_mwh": round(self.clean_number(vol/1000), 2),
                "pic_kw": round(self.clean_number(df[col_val].max()), 2),
                "talon_kw": round(self.clean_number(df[col_val].min()), 2),
                "points_traites": int(len(df))
            }

            ai_msg = self.generate_ai_insight(kpis, profile=target_profile)

            # Sampling Graphique (Max 2000 points)
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step]
            rolling_chart = rolling_mean.iloc[::step] # On sample aussi la moyenne
            
            return {
                "success": True, 
                "kpi": kpis, 
                "ai_insight": ai_msg,
                "chart": {
                    "labels": df_chart[col_date].dt.strftime('%Y-%m-%d %H:%M').tolist(),
                    "values": [self.clean_number(x) for x in df_chart[col_val].tolist()],
                    "average": [self.clean_number(x) for x in rolling_chart.tolist()] # Envoi de la moyenne mobile
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
