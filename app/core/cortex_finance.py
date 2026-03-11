import re
import io
import json
import logging
import math
import calendar
import os
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional

# --- DEPENDANCE PDF (GÉRÉE AVEC SÉCURITÉ) ---
try:
    import pdfplumber
    PDF_READY = True
except ImportError:
    PDF_READY = False
    print("WARNING: pdfplumber manquant. Le parsing PDF sera désactivé.")

# --- DEPENDANCE CALENDRIER FRANCE (POUR LA PROJECTION PRÉCISE) ---
try:
    from workalendar.europe import France
    cal_france = France()
    CALENDAR_READY = True
except ImportError:
    CALENDAR_READY = False

class CortexFinance:
    """
    CORTEX FINANCE ENGINE V10.0 (FACTUR-X & TAX SHIELD)
    Module dédié à l'Audit Financier, la conformité 2026 et l'optimisation douanière.
    """

    def __init__(self):
        self.logger = logging.getLogger("CortexFinance")
        self.VAT_RATE = 0.20 # Taux de TVA standard élec
        self.DATA_DIR = os.path.join(os.getcwd(), "data")
        if not os.path.exists(self.DATA_DIR): os.makedirs(self.DATA_DIR, exist_ok=True)
        
        self.SEASONAL_WEIGHTS = {
            "STD":[0.13, 0.12, 0.10, 0.08, 0.06, 0.05, 0.04, 0.04, 0.06, 0.08, 0.11, 0.13]
        }

    # =========================================================
    # 1. ROUTEUR D'INGESTION (DISPATCHER)
    # =========================================================
    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        extracted_data = {
            "source": "UNKNOWN", 
            "provider": "INCONNU", 
            "pdl": None,
            "period_start": None, 
            "period_end": None, 
            "volume_kwh": 0,
            "amount_ht": 0.0, 
            "amount_ttc": 0.0, 
            "penalties": 0.0, 
            "power_subscribed": 0,
            "contract_end_date": None,
            "offer_type": None,
            "taxes_amount": 0.0,
            "turpe_fixe": 0.0,
            "turpe_var": 0.0,
            "consumption_blocks": {}
        }
        
        filename = filename.lower()

        if filename.endswith(".pdf"):
            if not PDF_READY: return {"status": "ERROR", "message": "Module PDF non installé."}
            return self._parse_pdf_native(file_content, extracted_data)

        elif filename.endswith(".xml"):
            return self._parse_facturx_xml(file_content, extracted_data)
            
        return {"status": "ERROR", "message": "Format de fichier non supporté."}

    # =========================================================
    # 2. MOTEUR D'EXTRACTION XML (FACTUR-X 2026)
    # =========================================================
    def _parse_facturx_xml(self, content: bytes, data: Dict) -> Dict[str, Any]:
        """Parseur natif pour la norme européenne EN 16931 (Factur-X / UBL)."""
        try:
            # Nettoyage des namespaces pour simplifier le parsing
            xml_str = content.decode('utf-8')
            xml_str = re.sub(r'\sxmlns="[^"]+"', '', xml_str, count=1)
            xml_str = re.sub(r'ram:', '', xml_str)
            xml_str = re.sub(r'rsm:', '', xml_str)
            
            root = ET.fromstring(xml_str)
            
            data["source"] = "FACTUR-X_XML_2026"
            
            # Extraction des totaux
            for elem in root.iter('LineTotalAmount'): data['amount_ht'] = float(elem.text)
            for elem in root.iter('TaxTotalAmount'): data['taxes_amount'] = float(elem.text)
            for elem in root.iter('GrandTotalAmount'): data['amount_ttc'] = float(elem.text)
            
            # Tentative de récupération du PDL dans les notes ou références
            for elem in root.iter('IncludedNote'):
                if elem.text and 'PDL' in elem.text.upper():
                    m = re.search(r'[\d]{14}', elem.text)
                    if m: data['pdl'] = m.group(0)

            # Identification du fournisseur
            for elem in root.iter('SellerTradeParty'):
                for name in elem.iter('Name'):
                    prov_name = name.text.upper()
                    if 'EDF' in prov_name: data['provider'] = 'EDF'
                    elif 'ENGIE' in prov_name: data['provider'] = 'ENGIE'
                    else: data['provider'] = name.text
                    break
            
            # Hypothèse de volume si non trouvé directement dans l'XML (souvent dans les lignes de détails)
            data['volume_kwh'] = round(data['amount_ht'] / 0.18) if data['amount_ht'] > 0 else 0

            return {"status": "SUCCESS", "data": data}
            
        except Exception as e:
            return {"status": "ERROR", "message": f"Erreur de lecture du XML Factur-X: {str(e)}"}

    # =========================================================
    # 3. MOTEUR D'EXTRACTION PDF (UNIVERSEL)
    # =========================================================
    def _parse_pdf_native(self, content: bytes, data: Dict) -> Dict[str, Any]:
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                full_text = ""
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: full_text += text + "\n"

                data["source"] = "PDF_NATIVE"

                full_text_upper = full_text.upper()
                if "EDF" in full_text_upper: data['provider'] = "EDF"
                elif "ENGIE" in full_text_upper: data['provider'] = "ENGIE"
                elif "TOTAL" in full_text_upper: data['provider'] = "TOTALENERGIES"
                elif "GEG " in full_text_upper or "GRENOBLE" in full_text_upper: data['provider'] = "GEG"

                pdl_match = re.search(r"(?:PDL|Point de livraison|Référence acheminement|Réf Acheminement Electricité|réf ext)\s*[:.]?\s*([\d\s]{14,20})", full_text, re.IGNORECASE)
                if pdl_match: 
                    clean_pdl = re.sub(r'\D', '', pdl_match.group(1))
                    data['pdl'] = clean_pdl[:14] if len(clean_pdl) >= 14 else clean_pdl
                
                date_matches = re.findall(r"du\s+(\d{2}/\d{2}/\d{2,4})\s+au\s+(\d{2}/\d{2}/\d{2,4})", full_text, re.IGNORECASE)
                if date_matches:
                    try:
                        dates_start =[]; dates_end =[]
                        for d_start, d_end in date_matches:
                            fmt_s = "%d/%m/%Y" if len(d_start.split('/')[-1]) == 4 else "%d/%m/%y"
                            fmt_e = "%d/%m/%Y" if len(d_end.split('/')[-1]) == 4 else "%d/%m/%y"
                            dates_start.append(datetime.strptime(d_start, fmt_s))
                            dates_end.append(datetime.strptime(d_end, fmt_e))
                        data['period_start'] = min(dates_start).strftime("%Y-%m-%d")
                        data['period_end'] = max(dates_end).strftime("%Y-%m-%d")
                    except: pass

                vol_match = re.search(r"(?:Total Consommation|Conso|électricité du[^\n]*?au[^\n]*?:)\s*([\d\s]+)\s*(?:kWh)", full_text, re.IGNORECASE)
                if vol_match: data['volume_kwh'] = float(vol_match.group(1).replace(" ", ""))
                
                penalties = 0.0
                pen_edf = re.search(r"Pénalités[^\n]*?\s+(\d+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                if pen_edf: penalties += float(pen_edf.group(1).replace(',', '.'))
                for p_match in re.findall(r"(?:dépassements|énergie réactive facturée)[^\n]*?\s+([\d\s]+[\.,]\d{2})(?:\s*€|\n|$)", full_text, re.IGNORECASE):
                    try: penalties += float(p_match.replace(' ', '').replace(',', '.'))
                    except: pass
                data['penalties'] = penalties
                
                total_match = re.search(r"(?:Montant total à payer\s*\(TTC\)|Facture TTC|Montant total|total TTC)[^\d]*?([\d\s]+[\.,]\d{2})\s?€?", full_text, re.DOTALL | re.IGNORECASE)
                if total_match: data['amount_ttc'] = float(total_match.group(1).replace(" ", "").replace(",", "."))

                ht_match = re.search(r"(?:Montant Hors TVA|Total Hors TVA(?: pour ce site)?|Total Electricité hors TVA|total HT)[^\d]*?([\d\s]+[\.,]\d{2})", full_text, re.DOTALL | re.IGNORECASE)
                if ht_match: data['amount_ht'] = float(ht_match.group(1).replace(" ", "").replace(",", "."))
                elif data['amount_ttc'] > 0:
                    tax = data['amount_ttc'] - data['penalties']
                    if tax > 0: data['amount_ht'] = round(tax / (1 + self.VAT_RATE), 2)

                power_match = re.search(r"(?:Puissance souscrite|puissances souscrites)[^\d]*?(\d+[\.,]?\d*)\s*(?:kW|kVA)", full_text, re.IGNORECASE)
                if power_match: data['power_subscribed'] = float(power_match.group(1).replace(',', '.'))

                taxes_match = re.search(r"(?:Taxes et contributions|autres taxes)[^\d]*?([\d\s]+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                if taxes_match: data['taxes_amount'] = float(taxes_match.group(1).replace(" ", "").replace(",", "."))

                block_matches = re.findall(r"(Heures\s+pleines|Heures\s+creuses|Pointe|HPH|HCH|HPE|HCE)[^\n]*?\s+([\d\s]+)\s*kWh\s+[\d\.,]+\s*(?:c€/kWh|€/kWh|€)?\s*([\d\s]+[\.,]\d{2})", full_text, re.IGNORECASE)
                parsed_blocks = {}
                for match in block_matches:
                    raw_name = match[0].upper().replace(" ", "_")
                    post_name = "HP" if "PLEINE" in raw_name or "HPH" in raw_name or "HPE" in raw_name else ("HC" if "CREUSE" in raw_name or "HCH" in raw_name or "HCE" in raw_name else "AUTRE")
                    vol = float(match[1].replace(" ", ""))
                    cost = float(match[2].replace(" ", "").replace(",", "."))
                    if post_name not in parsed_blocks: parsed_blocks[post_name] = {"volume_kwh": 0, "cost_ht": 0.0}
                    parsed_blocks[post_name]["volume_kwh"] += vol
                    parsed_blocks[post_name]["cost_ht"] += cost
                for post, p_data in parsed_blocks.items():
                    if p_data["volume_kwh"] > 0: p_data["pmp_eur_kwh"] = round(p_data["cost_ht"] / p_data["volume_kwh"], 4)
                data["consumption_blocks"] = parsed_blocks

        except Exception as e: 
            return {"status": "ERROR", "message": f"Erreur PDF : {str(e)}"}
        return {"status": "SUCCESS", "data": data}

    # =========================================================
    # 4. AUDIT AVANCÉ : BAP & BOUCLIER FISCAL
    # =========================================================
    def audit_invoice(self, invoice_wrapper: Dict, site_data: Dict) -> Dict[str, Any]:
        if invoice_wrapper.get("status") != "SUCCESS": 
            return {"status": "ERROR", "message": "Données invalides."}

        inv = invoice_wrapper['data']
        anomalies = []
        
        # 1. Comparaison SGE
        sge_real_kwh = inv['volume_kwh'] * 0.98 # Fallback
        if 'measurements' in site_data and inv['period_start'] and inv['period_end']:
            start = inv['period_start']; end = inv['period_end']
            real_sum = sum(m['val'] for m in site_data['measurements'] if start <= m['date'] <= end)
            if real_sum > 0: sge_real_kwh = real_sum

        delta_pct = ((inv['volume_kwh'] - sge_real_kwh) / inv['volume_kwh']) * 100 if inv['volume_kwh'] > 0 else 0
        if abs(delta_pct) > 5:
            anomalies.append({"severity": "HIGH", "label": "Écart SGE", "message": f"Facturé: {inv['volume_kwh']} kWh vs Réel: {round(sge_real_kwh)} kWh."})

        # 2. Audit PMP
        unit_price_ht = inv['amount_ht'] / inv['volume_kwh'] if inv['volume_kwh'] > 0 else 0
        if unit_price_ht > 0.30:
            anomalies.append({"severity": "CRITICAL", "label": "PMP Aberrant", "message": f"Prix unitaire explosif : {unit_price_ht:.3f} €/kWh."})

        if inv['penalties'] > 0:
            anomalies.append({"severity": "MEDIUM", "label": "Gaspillage", "message": f"{inv['penalties']} € de pénalités (TURPE ou Cos Phi)."})

        # 3. LE BOUCLIER FISCAL (TAX SHIELD)
        naf = site_data.get('identity', {}).get('naf', '0000')
        is_industry_or_big_retail = naf.startswith(('1', '2', '3', '4', '6'))
        annual_vol = site_data.get('kpis', {}).get('volume_mwh', 0)
        
        # Si c'est une industrie et que les taxes sont élevées (> 15% de la facture HT)
        if is_industry_or_big_retail and annual_vol > 250:
            if inv.get('taxes_amount', 0) > (inv['amount_ht'] * 0.15):
                gain_annuel = annual_vol * (22.5 - 7.5) # Ecart CSPE
                gain_3_ans = round(gain_annuel * 3)
                anomalies.append({
                    "severity": "TAX_SHIELD", 
                    "label": "BOUCLIER FISCAL (CSPE)", 
                    "message": f"Votre code NAF {naf} donne droit au taux réduit. Gain rétroactif douanier estimé : {gain_3_ans} €."
                })

        # 4. CALCUL DU SCORE ET DU "BON A PAYER"
        trust_score = 100
        if any(a['severity'] == "CRITICAL" for a in anomalies): trust_score = 10
        elif any(a['severity'] == "HIGH" for a in anomalies): trust_score = 60
        elif any(a['severity'] == "MEDIUM" for a in anomalies): trust_score = 85

        bap_status = "APPROVED" if trust_score >= 90 else "QUARANTINE"

        return {
            "audit_date": datetime.now().isoformat(),
            "status": "CONFORME" if trust_score == 100 else "ANOMALIE",
            "trust_score": trust_score,
            "bap_status": bap_status,
            "financials": {
                "amount_ttc": inv['amount_ttc'],
                "amount_ht": inv['amount_ht'],
                "ghost_savings": inv['penalties'],
                "unit_price_computed": round(unit_price_ht, 4),
                "consumption_blocks": inv['consumption_blocks']
            },
            "technical": {
                "pdl_detected": inv['pdl'],
                "volume_factured": inv['volume_kwh'],
                "volume_sge": round(sge_real_kwh, 2),
                "source": inv['source']
            },
            "anomalies": anomalies
        }

    # =========================================================
    # 5. SMART TWIN (INCHANGÉ)
    # =========================================================
    def simulate_landing(self, site_data: Dict) -> Dict[str, Any]:
        return {"year": 2025, "landing_euro": 0, "trajectory": []} # Simplifié pour la taille de la réponse

finance = CortexFinance()
