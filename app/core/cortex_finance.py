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

class CortexFinance:
    """
    CORTEX FINANCE ENGINE V2.7 (PERSISTENCE & PROJECTION)
    Module dédié à l'Audit Financier et à la Triangulation.
    
    CAPACITÉS :
    1. Parsing PDF Natif (EDF Particulier & Pro) avec extraction HT/TTC précise.
    2. Gestion des Pénalités (Ghost Savings).
    3. Audit Financier (Comparaison Facture vs SGE Réel).
    4. Persistance du Prix Calculé (Mise à jour du profil site).
    5. Projection Financière (Smart Twin) basée sur le prix réel.
    """

    def __init__(self):
        self.logger = logging.getLogger("CortexFinance")
        self.VAT_RATE = 0.20 # Taux de TVA standard élec (20%)
        self.CSPE_REF = 22.5 # CSPE standard pour info
        self.DATA_DIR = os.path.join(os.getcwd(), "data")
        
        # PROFILS DE SAISONNALITÉ (Pondération mensuelle type)
        self.SEASONAL_WEIGHTS = {
            "STD": [0.13, 0.12, 0.10, 0.08, 0.06, 0.05, 0.04, 0.04, 0.06, 0.08, 0.11, 0.13]
        }

    # =========================================================
    # 1. ROUTEUR D'INGESTION (DISPATCHER)
    # =========================================================
    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Point d'entrée unique. Détecte le format et lance le bon parser.
        """
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
            "power_subscribed": 0
        }
        
        filename = filename.lower()

        # CAS A : PDF NATIF (EDF, ENGIE...)
        if filename.endswith(".pdf"):
            if not PDF_READY:
                return {"status": "ERROR", "message": "Module PDF (pdfplumber) non installé sur le serveur."}
            return self._parse_pdf_native(file_content, extracted_data)

        # CAS B : XML (FACTUR-X / CHORUS)
        elif filename.endswith(".xml"):
            return self._parse_facturx_xml(file_content, extracted_data)
            
        # CAS C : NON SUPPORTÉ
        return {"status": "ERROR", "message": "Format de fichier non supporté (PDF ou XML requis)."}

    # =========================================================
    # 2. MOTEUR D'EXTRACTION PDF (CHIRURGICAL)
    # =========================================================
    def _parse_pdf_native(self, content: bytes, data: Dict) -> Dict[str, Any]:
        """
        Extraction spécifique pour les PDF générés par les fournisseurs (Non scannés).
        """
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                full_text = ""
                p2_text = ""
                
                # Lecture optimisée des pages
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
                        # La page 2 contient souvent le détail HT chez EDF
                        if i == 1: p2_text = text 

                data["source"] = "PDF_NATIVE"

                # A. Extraction PDL (Regex robuste)
                pdl_match = re.search(r"(?:PDL|Point de livraison)\s*[:.]?\s*([\d\s]{14,20})", full_text, re.IGNORECASE)
                if pdl_match: 
                    data['pdl'] = pdl_match.group(1).replace(" ", "").strip()
                
                # B. Extraction Dates (Format: du 05/04/25 au 04/10/25)
                date_match = re.search(r"du\s+(\d{2}/\d{2}/\d{2})\s+au\s+(\d{2}/\d{2}/\d{2})", full_text)
                if date_match:
                    try:
                        def to_iso(d): return datetime.strptime(d, "%d/%m/%y").strftime("%Y-%m-%d")
                        data['period_start'] = to_iso(date_match.group(1))
                        data['period_end'] = to_iso(date_match.group(2))
                    except Exception as e:
                        print(f"Erreur date parsing: {e}")

                # C. Extraction Volume (Total Consommation)
                vol_match = re.search(r"Total Consommation\s+(\d+)", full_text)
                if vol_match: 
                    data['volume_kwh'] = float(vol_match.group(1))
                
                # D. Extraction Pénalités (Ghost Savings)
                penalties_match = re.search(r"Pénalités.*?\s+(\d+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                if penalties_match: 
                    data['penalties'] = float(penalties_match.group(1).replace(',', '.'))
                
                # E. Montant TTC (Page 1 - Montant total)
                total_match = re.search(r"Montant total.*?(\d+[\.,]\d{2})\s?€", full_text, re.DOTALL | re.IGNORECASE)
                if total_match: 
                    data['amount_ttc'] = float(total_match.group(1).replace(',', '.'))

                # F. Montant HT (CORRECTION MAJEURE V2.4)
                # Stratégie 1 : Recherche explicite sur la Page 2
                ht_match = re.search(r"Total Electricité hors TVA.*?\s(\d+[\.,]\d{2})", p2_text, re.DOTALL)
                
                if ht_match:
                    data['amount_ht'] = float(ht_match.group(1).replace(',', '.'))
                else:
                    # Stratégie 2 : Fallback Mathématique CORRIGÉ
                    # Formule : (TTC - Pénalités) / (1 + TVA)
                    if data['amount_ttc'] > 0:
                        taxable_amount = data['amount_ttc'] - data['penalties']
                        if taxable_amount > 0:
                            data['amount_ht'] = round(taxable_amount / (1 + self.VAT_RATE), 2)

                # G. Identification Fournisseur
                if "EDF" in full_text: data['provider'] = "EDF"
                elif "ENGIE" in full_text: data['provider'] = "ENGIE"
                elif "TOTAL" in full_text: data['provider'] = "TOTALENERGIES"

        except Exception as e: 
            return {"status": "ERROR", "message": f"Erreur critique lors de l'analyse PDF : {str(e)}"}
        
        return {"status": "SUCCESS", "data": data}

    # =========================================================
    # 3. PARSER XML (FACTUR-X / UBL) - STRUCTURE PRÊTE
    # =========================================================
    def _parse_facturx_xml(self, content: bytes, data: Dict) -> Dict[str, Any]:
        """
        Parser dédié aux fichiers XML structurés (Chorus Pro / Factur-X).
        """
        try:
            data["source"] = "FACTUR-X"
            data["provider"] = "CHORUS_PRO"
            return {"status": "MOCK", "message": "Parser XML prêt à être câblé.", "data": data}
        except Exception as e:
            return {"status": "ERROR", "message": f"Erreur XML: {str(e)}"}

    # =========================================================
    # 4. AUDIT & PERSISTANCE (LE CŒUR DU SYSTÈME)
    # =========================================================
    def _persist_price(self, pdl, price):
        """
        Sauvegarde le prix calculé dans le fichier JSON du site.
        Crucial pour que la projection utilise ce prix.
        """
        try:
            safe_id = str(pdl).strip()
            file_path = os.path.join(self.DATA_DIR, f"{safe_id}.json")
            
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'financials' not in data: data['financials'] = {}
                
                # Mise à jour du prix
                data['financials']['unit_price_computed'] = price
                data['financials']['last_audit_date'] = datetime.now().isoformat()
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                
                return True
        except Exception as e:
            print(f"Erreur Persistance Prix: {e}")
        return False

    def audit_invoice(self, invoice_wrapper: Dict, site_data: Dict) -> Dict[str, Any]:
        """
        AUDIT RÉEL : Compare les données extraites de la facture 
        avec les données JSON ingérées (SGE/Linky).
        """
        if invoice_wrapper.get("status") != "SUCCESS": 
            return {"status": "ERROR", "message": "Impossible d'auditer : Données de facture invalides."}

        inv = invoice_wrapper['data']
        
        # 1. RECUPERATION VOLUME SGE RÉEL
        sge_real_kwh = 0
        has_real_data = False
        
        if 'measurements' in site_data and inv['period_start'] and inv['period_end']:
            start = inv['period_start']
            end = inv['period_end']
            
            for m in site_data['measurements']:
                if start <= m['date'] <= end:
                    sge_real_kwh += m['val']
            
            if sge_real_kwh > 0: has_real_data = True

        # Fallback Simulation
        if not has_real_data:
            sge_real_kwh = inv['volume_kwh'] * 0.98

        # 2. CALCUL ECART
        delta_kwh = inv['volume_kwh'] - sge_real_kwh
        delta_pct = 0
        if inv['volume_kwh'] > 0:
            delta_pct = (delta_kwh / inv['volume_kwh']) * 100

        # 3. CALCUL PRIX UNITAIRE (HT)
        unit_price_ht = 0
        if inv['volume_kwh'] > 0:
            unit_price_ht = inv['amount_ht'] / inv['volume_kwh']

        # 4. PERSISTANCE DU PRIX (NOUVEAU V2.7)
        # On sauvegarde ce prix immédiatement pour que la Projection l'utilise
        if inv['pdl'] and unit_price_ht > 0:
            self._persist_price(inv['pdl'], unit_price_ht)

        # 5. GÉNÉRATION DU RAPPORT
        status = "CONFORME"
        anomalies = []
        
        # Règle A : Écart de Volume
        if abs(delta_pct) > 5:
            status = "ANOMALIE_VOLUME"
            anomalies.append({
                "severity": "HIGH", 
                "label": "Écart de Consommation",
                "message": f"Facturé: {inv['volume_kwh']} kWh vs Réel: {round(sge_real_kwh)} kWh ({delta_pct:+.1f}%)."
            })

        # Règle B : Prix Unitaire Aberrant
        if unit_price_ht < 0.05 or unit_price_ht > 0.50:
            status = "ANOMALIE_PRIX"
            anomalies.append({
                "severity": "CRITICAL", 
                "label": "Prix Unitaire Aberrant",
                "message": f"Prix HT calculé : {unit_price_ht:.4f} €/kWh. Vérifiez s'il s'agit d'une régularisation."
            })
            
        # Règle C : Gaspillage
        if inv['penalties'] > 0:
            anomalies.append({
                "severity": "MEDIUM", 
                "label": "Gaspillage (Pénalités)",
                "message": f"{inv['penalties']} € de pénalités de retard détectés."
            })

        trust_score = 100
        if status == "ANOMALIE_PRIX": trust_score = 10
        elif status == "ANOMALIE_VOLUME": trust_score = 60
        elif inv['penalties'] > 0: trust_score = 85

        return {
            "audit_date": datetime.now().isoformat(),
            "status": status,
            "trust_score": trust_score,
            "financials": {
                "amount_ttc": inv['amount_ttc'],
                "amount_ht": inv['amount_ht'],
                "ghost_savings": inv['penalties'],
                "unit_price_computed": round(unit_price_ht, 4)
            },
            "technical": {
                "pdl_detected": inv['pdl'],
                "volume_factured": inv['volume_kwh'],
                "volume_sge": round(sge_real_kwh, 2),
                "has_real_data": has_real_data
            },
            "anomalies": anomalies
        }

    # =========================================================
    # 5. PROJECTION (SMART TWIN)
    # =========================================================
    def simulate_landing(self, site_data: Dict) -> Dict[str, Any]:
        """
        Calcule la trajectoire annuelle (Réalisé + Projeté).
        Utilise le prix unitaire calculé lors de l'audit pour projeter les coûts.
        """
        measurements = site_data.get('measurements', [])
        
        # 1. Analyse de l'existant (Réalisé)
        current_year = datetime.now().year
        # Si on est début 2026, on regarde 2025 pour avoir une année complète ou partielle
        if datetime.now().month < 3: current_year -= 1
            
        realized_by_month = {m: 0 for m in range(1, 13)}
        total_realized_kwh = 0
        last_real_month = 0
        
        # RÉCUPÉRATION DU PRIX EXACT (C'est ici que la persistance sert)
        avg_price = 0.20 # Fallback
        if 'financials' in site_data and 'unit_price_computed' in site_data['financials']:
            avg_price = float(site_data['financials']['unit_price_computed'])
        
        # Somme des consos réelles par mois
        for m in measurements:
            try:
                d = datetime.strptime(m['date'], "%Y-%m-%d")
                if d.year == current_year:
                    realized_by_month[d.month] += m['val']
                    total_realized_kwh += m['val']
                    if d.month > last_real_month: last_real_month = d.month
            except: continue

        # 2. Projection (Forecast)
        trajectory_euro = []
        cumulative_euro = 0
        
        # Estimation du volume annuel total basé sur ce qu'on a déjà
        weight_realized = sum(self.SEASONAL_WEIGHTS["STD"][:last_real_month])
        if weight_realized > 0:
            estimated_annual_vol = total_realized_kwh / weight_realized
        else:
            estimated_annual_vol = site_data.get('kpis', {}).get('volume_mwh', 0) * 1000

        for month in range(1, 13):
            # Volume mensuel
            if month <= last_real_month:
                vol = realized_by_month[month]
                status = "REAL"
            else:
                # Projection : Vol Annuel * Poids du mois
                weight = self.SEASONAL_WEIGHTS["STD"][month-1]
                vol = estimated_annual_vol * weight
                # Correction jours fériés
                if month in [5, 12]: vol *= 0.9
                status = "FORECAST"

            # Calcul Coût avec le VRAI prix
            cost = vol * avg_price
            cumulative_euro += cost
            
            trajectory_euro.append({
                "month": calendar.month_name[month],
                "cost_monthly": round(cost, 2),
                "cost_cumulative": round(cumulative_euro, 2),
                "status": status
            })

        return {
            "year": current_year,
            "landing_euro": round(cumulative_euro, 2),
            "price_used": avg_price, # Info de debug utile
            "trajectory": trajectory_euro
        }

finance = CortexFinance()
