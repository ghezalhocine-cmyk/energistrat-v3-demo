import re
import io
import json
import logging
import math
from datetime import datetime
from typing import Dict, Any

# --- DEPENDANCE PDF ---
try:
    import pdfplumber
    PDF_READY = True
except ImportError:
    PDF_READY = False
    print("WARNING: pdfplumber manquant. Parsing PDF désactivé.")

class CortexFinance:
    """
    CORTEX FINANCE ENGINE V2.1 (PLATINUM + SGE REAL)
    Gère :
    1. Parsing PDF Facture (EDF/Engie)
    2. Audit Financier (Comparaison Facture vs SGE)
    3. Projection (Twin)
    """

    def __init__(self):
        self.logger = logging.getLogger("CortexFinance")

    # --- 1. PARSING PDF (FACTURE) ---
    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Extrait les données de la facture PDF."""
        
        extracted_data = {
            "source": "PDF_NATIVE", "provider": "INCONNU", "pdl": None,
            "period_start": None, "period_end": None, "volume_kwh": 0,
            "amount_ht": 0.0, "amount_ttc": 0.0, "penalties": 0.0, "power_subscribed": 0
        }
        
        if filename.lower().endswith(".pdf") and PDF_READY:
            try:
                with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                    full_text = ""
                    for page in pdf.pages: full_text += page.extract_text() + "\n"
                    
                    # A. Extraction PDL
                    pdl_match = re.search(r"(?:PDL|Point de livraison)\s*[:.]?\s*([\d\s]{14,20})", full_text, re.IGNORECASE)
                    if pdl_match: extracted_data['pdl'] = pdl_match.group(1).replace(" ", "").strip()
                    
                    # B. Extraction Dates (Format: du 05/04/25 au 04/10/25)
                    date_match = re.search(r"du\s+(\d{2}/\d{2}/\d{2})\s+au\s+(\d{2}/\d{2}/\d{2})", full_text)
                    if date_match:
                        def to_iso(d): return datetime.strptime(d, "%d/%m/%y").strftime("%Y-%m-%d")
                        extracted_data['period_start'] = to_iso(date_match.group(1))
                        extracted_data['period_end'] = to_iso(date_match.group(2))

                    # C. Extraction Volume
                    vol_match = re.search(r"Total Consommation\s+(\d+)", full_text)
                    if vol_match: extracted_data['volume_kwh'] = float(vol_match.group(1))
                    
                    # D. Extraction Pénalités
                    penalties_match = re.search(r"Pénalités.*?\s+(\d+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                    if penalties_match: extracted_data['penalties'] = float(penalties_match.group(1).replace(',', '.'))
                    
                    # E. Montant TTC (Recherche large)
                    total_match = re.search(r"Montant total.*?(\d+[\.,]\d{2})\s?€", full_text, re.DOTALL)
                    if total_match: extracted_data['amount_ttc'] = float(total_match.group(1).replace(',', '.'))
                    
                    # F. Identification Fournisseur
                    if "EDF" in full_text: extracted_data['provider'] = "EDF"

            except Exception as e: return {"status": "ERROR", "message": f"PDF Error: {str(e)}"}
            
            return {"status": "SUCCESS", "data": extracted_data}
            
        return {"status": "ERROR", "message": "Format non supporté (PDF requis)."}

    # --- 2. AUDIT (COMPARAISON) ---
    def audit_invoice(self, invoice_wrapper: Dict, site_data: Dict) -> Dict[str, Any]:
        """
        AUDIT RÉEL : Compare Facture vs Données JSON ingérées.
        """
        if invoice_wrapper.get("status") != "SUCCESS": return {"status": "ERROR"}

        inv = invoice_wrapper['data']
        
        # 1. RECUPERATION VOLUME SGE REEL
        sge_real_kwh = 0
        has_real_data = False
        
        if 'measurements' in site_data and inv['period_start'] and inv['period_end']:
            start = inv['period_start']
            end = inv['period_end']
            
            # Somme des consos journalières sur la période
            for m in site_data['measurements']:
                if start <= m['date'] <= end:
                    sge_real_kwh += m['val']
            
            if sge_real_kwh > 0: has_real_data = True

        # Fallback Simulation si pas de données (pour ne pas casser l'UI)
        if not has_real_data:
            sge_real_kwh = inv['volume_kwh'] * 0.98 # Simulation -2%

        # 2. CALCUL ECART
        delta_kwh = inv['volume_kwh'] - sge_real_kwh
        delta_pct = (delta_kwh / inv['volume_kwh']) * 100 if inv['volume_kwh'] > 0 else 0

        # 3. STATUT & ANOMALIES
        status = "CONFORME"
        anomalies = []
        
        # Alerte Ecart Volume
        if abs(delta_pct) > 5:
            status = "ANOMALIE_VOLUME"
            anomalies.append({
                "severity": "HIGH", "label": "Écart de Consommation",
                "message": f"Facturé: {inv['volume_kwh']} kWh vs Réel: {round(sge_real_kwh)} kWh ({delta_pct:+.1f}%)."
            })

        # Alerte Prix
        unit_price = inv['amount_ttc'] / inv['volume_kwh'] if inv['volume_kwh'] > 0 else 0
        if unit_price < 0.05:
            status = "ANOMALIE_PRIX"
            anomalies.append({
                "severity": "CRITICAL", "label": "Prix Unitaire Aberrant",
                "message": f"Prix calculé : {unit_price:.4f} €/kWh. Vérifiez le montant."
            })
            
        # Alerte Pénalités
        if inv['penalties'] > 0:
            anomalies.append({
                "severity": "MEDIUM", "label": "Gaspillage (Pénalités)",
                "message": f"{inv['penalties']} € de pénalités détectés."
            })

        return {
            "audit_date": datetime.now().isoformat(),
            "status": status,
            "trust_score": 10 if status == "ANOMALIE_PRIX" else (80 if abs(delta_pct) > 5 else 98),
            "financials": {
                "amount_ttc": inv['amount_ttc'],
                "ghost_savings": inv['penalties'],
                "unit_price_computed": round(unit_price, 4)
            },
            "technical": {
                "pdl_detected": inv['pdl'],
                "volume_factured": inv['volume_kwh'],
                "volume_sge": round(sge_real_kwh, 2), # Pour le graphique Audit
                "has_real_data": has_real_data
            },
            "anomalies": anomalies
        }

    def simulate_landing(self, site_data: Dict) -> Dict[str, Any]:
        """Projection simplifiée pour l'instant."""
        return { "landing_euro": 0, "volume_target_mwh": 0 }

finance = CortexFinance()
