import pandas as pd
import json
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# On importe les moteurs physiques pour la "Vérité Terrain"
try:
    from app.core.cortex_physics import physics
except ImportError:
    # Fallback pour dev local
    import cortex_physics as physics

class CortexFinance:
    """
    MOTEUR FINANCE & FACTUR-X
    Gère la Triangulation (Audit Facture vs SGE) et le Jumeau Financier (Projection).
    """

    def __init__(self):
        self.VAT_RATE = 0.20
        self.CSPE_REF = 22.5  # €/MWh (Exemple simpliste, à paramétrer)

    # --- 1. INGESTION (FACTUR-X & EXCEL) ---

    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """Détecte le format et extrait les données clés."""
        if filename.endswith(".xml") or filename.endswith(".pdf"):
            # Pour le PDF, on assume ici que c'est un XML extrait ou un pur XML Factur-X
            # En prod, il faudrait une lib PDF pour extraire le XML attaché
            return self._parse_facturx_xml(file_content)
        elif filename.endswith(".xlsx") or filename.endswith(".xls"):
            return self._parse_excel_public(file_content)
        else:
            return {"status": "ERROR", "message": "Format non supporté"}

    def _parse_facturx_xml(self, content: bytes) -> Dict[str, Any]:
        """Extraction native Factur-X (CrossIndustryInvoice)."""
        try:
            root = ET.fromstring(content)
            # Namespaces souvent pénibles en XML, on fait une recherche locale simplifiée
            # CECI EST UN PARSER SIMPLIFIÉ POUR LA DÉMO
            ns = {'rsm': 'urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100'}
            
            # Extraction Données (Mockée sur la structure standard)
            # Dans la réalité, on traverse l'arbre XML spécifique
            amount_ht = 12500.00 # Placeholder extraction
            volume_kwh = 45000   # Placeholder extraction
            pdl = "00000000000000"
            
            return {
                "source": "FACTUR-X",
                "status": "SUCCESS",
                "data": {
                    "pdl": pdl,
                    "period_start": "2023-01-01",
                    "period_end": "2023-01-31",
                    "amount_ht": amount_ht,
                    "volume_kwh": volume_kwh,
                    "provider": "EDF"
                }
            }
        except Exception as e:
            return {"status": "ERROR", "message": f"XML Error: {str(e)}"}

    def _parse_excel_public(self, content: bytes) -> Dict[str, Any]:
        """Ingestion des fichiers Excel type Chorus/Public."""
        try:
            df = pd.read_excel(content)
            # Logique de détection de colonnes floue (Fuzzy Logic)
            # On cherche une colonne qui ressemble à un PDL et un Montant
            return {
                "source": "EXCEL_PUBLIC",
                "status": "SUCCESS",
                "rows": len(df),
                "preview": df.head(5).to_dict(orient='records')
            }
        except Exception as e:
            return {"status": "ERROR", "message": f"Excel Error: {str(e)}"}

    # --- 2. TRIANGULATION (AUDIT) ---

    def audit_invoice(self, invoice_data: Dict, site_data: Dict) -> Dict[str, Any]:
        """
        Compare la Facture (Fournisseur) vs La Réalité (SGE).
        Retourne un rapport d'audit.
        """
        # 1. Vérité SGE (Physique)
        # On simule ici la récupération des données SGE sur la période
        sge_volume_kwh = invoice_data['data']['volume_kwh'] * 0.98 # On simule un écart de 2%
        
        # 2. Vérité Contrat (Prix)
        contract_price = 0.15 # €/kWh (Récupéré du JSON site)
        if 'pricing' in site_data and 'price_kwh' in site_data['pricing']:
            contract_price = float(site_data['pricing']['price_kwh'])

        # 3. Recalcul Théorique (Shadow Bill)
        theoretical_cost_molecule = sge_volume_kwh * contract_price
        theoretical_tax = sge_volume_kwh * (self.CSPE_REF / 1000)
        theoretical_total = theoretical_cost_molecule + theoretical_tax

        # 4. Calcul des Écarts (Gap Analysis)
        billed_amount = invoice_data['data']['amount_ht']
        gap_euro = billed_amount - theoretical_total
        gap_percent = (gap_euro / billed_amount) * 100 if billed_amount > 0 else 0

        status = "CONFORME"
        if abs(gap_percent) > 5: status = "ANOMALIE_MAJEURE"
        elif abs(gap_percent) > 1: status = "A_VERIFIER"

        return {
            "audit_date": datetime.now().isoformat(),
            "status": status,
            "gap_euro": round(gap_euro, 2),
            "gap_percent": round(gap_percent, 2),
            "details": {
                "volume_billed": invoice_data['data']['volume_kwh'],
                "volume_sge": round(sge_volume_kwh, 2),
                "price_applied": round(billed_amount / invoice_data['data']['volume_kwh'], 4),
                "price_contract": contract_price
            }
        }

    # --- 3. FINANCIAL TWIN (PROJECTION) ---

    def simulate_landing(self, site_data: Dict) -> Dict[str, Any]:
        """
        Projette l'atterrissage budgétaire fin d'année (Year-End Landing).
        Basé sur le consommé à date + profil climatique restant.
        """
        # Récupération données actuelles
        current_vol = 0
        if 'kpis' in site_data and 'volume_mwh' in site_data['kpis']:
            current_vol = float(site_data['kpis']['volume_mwh'])
        
        # Projection simple (Linéaire pondérée par DJU - Simplifié ici)
        # Dans la réalité : on utilise cortex_physics pour les DJU
        projected_vol = current_vol * 1.1 # Marge de sécurité
        
        avg_price = 200.0 # €/MWh
        if 'financials' in site_data and 'avg_price_mwh' in site_data['financials']:
            avg_price = float(site_data['financials']['avg_price_mwh'])
            
        budget_landing = projected_vol * avg_price
        
        # Optimisation TURPE (Simulation)
        pmax = float(site_data.get('kpis', {}).get('pmax_kw', 100))
        psouscrite = float(site_data.get('contract', {}).get('power', 120))
        
        turpe_savings = 0
        recommendation = "Optimisé"
        
        if pmax < (psouscrite * 0.8):
            # Sur-souscription détectée
            new_p = math.ceil(pmax * 1.1)
            diff_kva = psouscrite - new_p
            turpe_savings = diff_kva * 12.0 # ~12€/kVA/an (Fixe TURPE)
            recommendation = f"Baisser PS de {psouscrite} à {new_p} kVA"

        return {
            "landing_euro": round(budget_landing, 2),
            "volume_target_mwh": round(projected_vol, 2),
            "turpe_opti": {
                "potential_savings": round(turpe_savings, 2),
                "recommendation": recommendation
            }
        }

finance = CortexFinance()
