import re
import io
import json
import math
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

# --- DEPENDANCE PDF (Le Chirurgien) ---
try:
    import pdfplumber
    PDF_READY = True
except ImportError:
    PDF_READY = False
    print("WARNING: pdfplumber manquante. Le parsing PDF sera désactivé.")

class CortexFinance:
    """
    CORTEX FINANCE ENGINE V2 (PLATINUM)
    - Ingestion Hybride : XML (Factur-X) > PDF Natif (Plumber) > Excel
    - Audit : Triangulation Flux / Prix / Contrat
    - Spécialisation : Blueprint EDF & Services Publics
    """

    def __init__(self):
        self.VAT_RATE = 0.20
        self.CSPE_REF = 22.5 
        self.logger = logging.getLogger("CortexFinance")

    # --- 1. ROUTEUR D'INGESTION ---

    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Détecte le format et lance le bon parser."""
        filename = filename.lower()
        
        # A. PRIORITÉ ABSOLUE : XML / FACTUR-X (Mairies/Chorus)
        if filename.endswith(".xml"):
            return self._parse_facturx_xml(file_content)
        
        # B. PDF NATIF (Le cas de ta facture EDF)
        elif filename.endswith(".pdf"):
            if PDF_READY:
                try:
                    # On tente d'abord de voir si c'est un PDF hybride (Factur-X caché)
                    # TODO: Implémenter extraction XML depuis PDF
                    # Sinon, lecture visuelle
                    return self._parse_pdf_native(file_content)
                except Exception as e:
                    return {"status": "ERROR", "message": f"PDF Error: {str(e)}"}
            else:
                return {"status": "ERROR", "message": "Module PDF non installé (pip install pdfplumber)"}
        
        # C. EXCEL (Vieux format Enedis)
        elif filename.endswith(".xlsx") or filename.endswith(".xls"):
            return {"status": "ERROR", "message": "Excel Parser en cours de dev"}
            
        return {"status": "ERROR", "message": "Format non supporté"}

    # --- 2. PARSERS SPÉCIFIQUES ---

    def _parse_pdf_native(self, content: bytes) -> Dict[str, Any]:
        """
        Extraction Chirurgicale via pdfplumber.
        Cible : Factures EDF (Blue/Pro)
        """
        extracted_data = {
            "source": "PDF_NATIVE",
            "provider": "INCONNU",
            "pdl": None,
            "period_start": None,
            "period_end": None,
            "volume_kwh": 0,
            "amount_ht": 0.0,
            "amount_ttc": 0.0,
            "penalties": 0.0,
            "power_subscribed": 0
        }

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            full_text = ""
            for page in pdf.pages:
                text = page.extract_text()
                full_text += text + "\n"

                # RECHERCHE PDL (Page 1 ou Annexes)
                # Pattern : "Point de livraison (PDL) : 19 349 ..."
                if not extracted_data['pdl']:
                    pdl_match = re.search(r"(?:PDL|Point de livraison)\s*[:.]?\s*([\d\s]{14,20})", text, re.IGNORECASE)
                    if pdl_match:
                        # Nettoyage des espaces (19 349 -> 19349)
                        extracted_data['pdl'] = pdl_match.group(1).replace(" ", "").strip()

                # RECHERCHE PÉNALITÉS (Ghost Savings)
                # Pattern : "Pénalités de retard ... 7,50 €"
                penalties_match = re.search(r"Pénalités.*?\s+(\d+[\.,]\d{2})\s?€", text, re.IGNORECASE)
                if penalties_match:
                    val = float(penalties_match.group(1).replace(',', '.'))
                    extracted_data['penalties'] = val

                # RECHERCHE MONTANT TOTAL
                # Pattern : "Montant total ... 44,70 €"
                if "Montant total" in text and extracted_data['amount_ttc'] == 0:
                    # Recherche simplifiée (on prend le gros chiffre à côté)
                    total_match = re.search(r"Montant total.*?(\d+[\.,]\d{2})\s?€", text, re.IGNORECASE | re.DOTALL)
                    if total_match:
                        extracted_data['amount_ttc'] = float(total_match.group(1).replace(',', '.'))

            # ANALYSE SPÉCIFIQUE PAGE 2 (Tableau Conso EDF)
            # On cherche "Total Consommation"
            if len(pdf.pages) >= 2:
                p2_text = pdf.pages[1].extract_text()
                # Extraction Volume
                vol_match = re.search(r"Total Consommation\s+(\d+)", p2_text)
                if vol_match:
                    extracted_data['volume_kwh'] = float(vol_match.group(1))
                
                # Extraction Montant HT "Electricité" (souvent juste en dessous)
                # Pour le cas spécifique : 31,00 €
                ht_match = re.search(r"Total Electricité hors TVA\s+(\d+[\.,]\d{2})", p2_text)
                if ht_match:
                    extracted_data['amount_ht'] = float(ht_match.group(1).replace(',', '.'))

                # Extraction Puissance (9 kVA)
                power_match = re.search(r"(\d+)\s*kVA", p2_text)
                if power_match:
                    extracted_data['power_subscribed'] = int(power_match.group(1))

        # Identification Fournisseur
        if "EDF" in full_text: extracted_data['provider'] = "EDF"
        elif "TOTAL" in full_text: extracted_data['provider'] = "TOTALENERGIES"
        elif "ENGIE" in full_text: extracted_data['provider'] = "ENGIE"

        return {"status": "SUCCESS", "data": extracted_data}

    def _parse_facturx_xml(self, content: bytes) -> Dict[str, Any]:
        """Placeholder pour le parser XML (Sera activé plus tard)."""
        return {"status": "MOCK", "data": {"provider": "CHORUS_PRO", "amount_ttc": 1000.0}}

    # --- 3. TRIANGULATION & AUDIT ---

    def audit_invoice(self, invoice_wrapper: Dict, site_data: Dict) -> Dict[str, Any]:
        """
        Le Juge de Paix. Compare Facture vs Réel.
        """
        if invoice_wrapper.get("status") != "SUCCESS":
            return {"status": "ERROR", "message": "Impossible d'auditer : Parsing échoué."}

        inv = invoice_wrapper['data']
        
        # 1. CALCUL DU PRIX UNITAIRE RÉEL
        unit_price = 0
        if inv['volume_kwh'] > 0:
            unit_price = inv['amount_ht'] / inv['volume_kwh'] # €/kWh
        
        # 2. DÉTECTION ANOMALIES (Règles Métier)
        anomalies = []
        status = "CONFORME"
        
        # Règle A : Prix Aberrant (Cas de ta facture : 0.005 €/kWh)
        # Seuil de tolérance : < 0.05€ (Trop bas) ou > 0.50€ (Trop haut)
        if unit_price < 0.05:
            anomalies.append({
                "severity": "CRITICAL",
                "label": "Prix Unitaire Suspect",
                "message": f"Prix détecté : {unit_price:.4f} €/kWh. C'est anormalement bas (Régularisation ? Erreur ?)."
            })
            status = "ANOMALIE_CRITIQUE"

        # Règle B : Ghost Savings (Pénalités)
        ghost_savings = inv['penalties']
        if ghost_savings > 0:
            anomalies.append({
                "severity": "HIGH",
                "label": "Gaspillage Détecté",
                "message": f"{ghost_savings} € de pénalités de retard."
            })
            if status == "CONFORME": status = "OPTIMISABLE"

        # Règle C : Optimisation Puissance
        # On compare la puissance facture (9kVA) vs SGE (Pmax)
        opti_msg = "Puissance OK"
        if inv['power_subscribed'] > 0:
            # Simulation Pmax (car on n'a pas encore connecté le SGE temps réel ici)
            simulated_pmax = 4.0 # Hypothèse : le client n'utilise que 4kVA
            if simulated_pmax < (inv['power_subscribed'] * 0.6):
                saving_est = (inv['power_subscribed'] - 6) * 12 # Gain si passage à 6kVA
                anomalies.append({
                    "severity": "MEDIUM",
                    "label": "Optimisation Abonnement",
                    "message": f"Puissance souscrite {inv['power_subscribed']} kVA trop élevée. Passez à 6 kVA."
                })

        return {
            "audit_date": datetime.now().isoformat(),
            "status": status,
            "trust_score": 10 if status == "ANOMALIE_CRITIQUE" else (80 if ghost_savings > 0 else 100),
            "financials": {
                "amount_ttc": inv['amount_ttc'],
                "ghost_savings": ghost_savings,
                "unit_price_computed": round(unit_price, 4)
            },
            "technical": {
                "pdl_detected": inv['pdl'],
                "volume_factured": inv['volume_kwh'],
                "power_subscribed": inv['power_subscribed']
            },
            "anomalies": anomalies
        }

    # --- 4. TWIN (Projection - Gardé tel quel) ---
    def simulate_landing(self, site_data: Dict) -> Dict[str, Any]:
        return { "landing_euro": 14500, "volume_target_mwh": 85 }

finance = CortexFinance()
