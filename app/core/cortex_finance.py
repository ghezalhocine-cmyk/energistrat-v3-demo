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
    # On ne bloque pas le système, on passera en mode dégradé (jours simples)

class CortexFinance:
    """
    CORTEX FINANCE ENGINE V3.3 (DIAMOND ROBUST - FIX PDL)
    Module dédié à l'Audit Financier et à la Triangulation.
    
    CAPACITÉS :
    1. Parsing PDF Natif Avancé (EDF Particulier & PRO C5).
    2. Audit Financier (Facture vs SGE Réel).
    3. Persistance du Prix ET du Volume (pour pallier l'absence de SGE).
    4. Projection Financière "Smart Twin" (N-1 Mirroring + Effet Calendrier France + Fallback).
    """

    def __init__(self):
        self.logger = logging.getLogger("CortexFinance")
        self.VAT_RATE = 0.20 # Taux de TVA standard élec (20%)
        self.CSPE_REF = 22.5 # CSPE standard pour info
        self.DATA_DIR = os.path.join(os.getcwd(), "data")
        if not os.path.exists(self.DATA_DIR): os.makedirs(self.DATA_DIR, exist_ok=True)
        
        # PROFILS DE SAISONNALITÉ (Pondération mensuelle type - Hiver fort)
        self.SEASONAL_WEIGHTS = {
            "STD":[0.13, 0.12, 0.10, 0.08, 0.06, 0.05, 0.04, 0.04, 0.06, 0.08, 0.11, 0.13]
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
            
        return {"status": "ERROR", "message": "Format de fichier non supporté (PDF ou XML requis)."}

    # =========================================================
    # 2. MOTEUR D'EXTRACTION PDF (CHIRURGICAL B2B & B2C)
    # =========================================================
    def _parse_pdf_native(self, content: bytes, data: Dict) -> Dict[str, Any]:
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                full_text = ""
                
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: full_text += text + "\n"

                data["source"] = "PDF_NATIVE"

                # G. Identification Fournisseur
                full_text_upper = full_text.upper()
                if "EDF" in full_text_upper: data['provider'] = "EDF"
                elif "ENGIE" in full_text_upper: data['provider'] = "ENGIE"
                elif "TOTAL" in full_text_upper: data['provider'] = "TOTALENERGIES"

                # A. Extraction PDL / PRM (FIX: Nettoyage strict 14 chiffres)
                pdl_match = re.search(r"(?:PDL|Point de livraison|Référence acheminement|Réf Acheminement Electricité)\s*[:.]?\s*([\d\s]{14,20})", full_text, re.IGNORECASE)
                if pdl_match: 
                    raw_pdl = pdl_match.group(1)
                    # On supprime absolument tout ce qui n'est pas un chiffre (espaces, sauts de ligne, lettres)
                    clean_pdl = re.sub(r'\D', '', raw_pdl)
                    if len(clean_pdl) >= 14:
                        data['pdl'] = clean_pdl[:14] # Force 14 caractères (Norme ENEDIS)
                    else:
                        data['pdl'] = clean_pdl
                
                # B. Extraction Dates
                date_matches = re.findall(r"du\s+(\d{2}/\d{2}/\d{2,4})\s+au\s+(\d{2}/\d{2}/\d{2,4})", full_text, re.IGNORECASE)
                if date_matches:
                    try:
                        dates_start =[]
                        dates_end =[]
                        for d_start, d_end in date_matches:
                            fmt_start = "%d/%m/%Y" if len(d_start.split('/')[-1]) == 4 else "%d/%m/%y"
                            fmt_end = "%d/%m/%Y" if len(d_end.split('/')[-1]) == 4 else "%d/%m/%y"
                            dates_start.append(datetime.strptime(d_start, fmt_start))
                            dates_end.append(datetime.strptime(d_end, fmt_end))
                        
                        data['period_start'] = min(dates_start).strftime("%Y-%m-%d")
                        data['period_end'] = max(dates_end).strftime("%Y-%m-%d")
                    except Exception as e:
                        print(f"Erreur date parsing: {e}")

                # C. Extraction Volume
                vol_match = re.search(r"(?:Total Consommation|Conso)\s+([\d\s]+)\s*(?:kWh)", full_text, re.IGNORECASE)
                if vol_match: 
                    clean_vol = vol_match.group(1).replace(" ", "")
                    data['volume_kwh'] = float(clean_vol)
                
                # D. Extraction Pénalités
                penalties_match = re.search(r"Pénalités[^\n]*?\s+(\d+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                if penalties_match: 
                    data['penalties'] = float(penalties_match.group(1).replace(',', '.'))
                
                # E. Montant TTC
                total_match = re.search(r"(?:Montant total à payer\s*\(TTC\)|Facture TTC|Montant total)[^\d]*?([\d\s]+[\.,]\d{2})\s?€", full_text, re.DOTALL | re.IGNORECASE)
                if total_match: 
                    clean_ttc = total_match.group(1).replace(" ", "").replace(",", ".")
                    data['amount_ttc'] = float(clean_ttc)

                # F. Montant HT
                ht_match = re.search(r"(?:Montant Hors TVA|Total Hors TVA(?: pour ce site)?|Total Electricité hors TVA)[^\d]*?([\d\s]+[\.,]\d{2})", full_text, re.DOTALL | re.IGNORECASE)
                if ht_match:
                    clean_ht = ht_match.group(1).replace(" ", "").replace(",", ".")
                    data['amount_ht'] = float(clean_ht)
                else:
                    # Fallback mathématique (TTC - Pénalités) / (1 + TVA)
                    if data['amount_ttc'] > 0:
                        taxable_amount = data['amount_ttc'] - data['penalties']
                        if taxable_amount > 0:
                            data['amount_ht'] = round(taxable_amount / (1 + self.VAT_RATE), 2)

                # H. Puissance Souscrite (Pour Profils PRO)
                power_match = re.search(r"Puissance souscrite.*?(?:kW|kVA).*?:\s*(\d+[\.,]?\d*)", full_text, re.IGNORECASE)
                if power_match:
                    data['power_subscribed'] = float(power_match.group(1).replace(',', '.'))

        except Exception as e: 
            return {"status": "ERROR", "message": f"Erreur critique lors de l'analyse PDF : {str(e)}"}
        
        return {"status": "SUCCESS", "data": data}

    # =========================================================
    # 3. PARSER XML (FACTUR-X)
    # =========================================================
    def _parse_facturx_xml(self, content: bytes, data: Dict) -> Dict[str, Any]:
        try:
            data["source"] = "FACTUR-X"
            data["provider"] = "CHORUS_PRO"
            return {"status": "MOCK", "message": "Parser XML prêt à être câblé.", "data": data}
        except Exception as e:
            return {"status": "ERROR", "message": f"Erreur XML: {str(e)}"}

    # =========================================================
    # 4. AUDIT & PERSISTANCE
    # =========================================================
    def _persist_data(self, pdl, price, volume_facture):
        """
        Sauvegarde le prix ET le volume de référence.
        C'est CRITIQUE pour la projection si l'historique SGE est manquant.
        """
        try:
            safe_id = str(pdl).strip()
            file_path = os.path.join(self.DATA_DIR, f"{safe_id}.json")
            
            # Chargement ou Création structure de base
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {
                    "identity": {"id": safe_id, "site_name": f"Site {safe_id}"},
                    "contract": {"pdl": safe_id},
                    "measurements":[],
                    "kpis": {}
                }
            
            # Mise à jour Financière
            if 'financials' not in data: data['financials'] = {}
            data['financials']['unit_price_computed'] = price
            data['financials']['last_audit_date'] = datetime.now().isoformat()
            
            # Mise à jour KPI Volume (Fallback Projection)
            if 'kpis' not in data: data['kpis'] = {}
            data['kpis']['volume_invoice_ref'] = volume_facture
            
            if 'volume_mwh' not in data['kpis'] or data['kpis']['volume_mwh'] == 0:
                data['kpis']['volume_mwh'] = (volume_facture * 4) / 1000 

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Erreur Persistance: {e}")
        return False

    def audit_invoice(self, invoice_wrapper: Dict, site_data: Dict) -> Dict[str, Any]:
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

        # 4. PERSISTANCE
        if inv['pdl'] and unit_price_ht > 0:
            self._persist_data(inv['pdl'], unit_price_ht, inv['volume_kwh'])

        # 5. RAPPORT
        status = "CONFORME"
        anomalies =[]
        
        if abs(delta_pct) > 5:
            status = "ANOMALIE_VOLUME"
            anomalies.append({
                "severity": "HIGH", 
                "label": "Écart de Consommation",
                "message": f"Facturé: {inv['volume_kwh']} kWh vs Réel: {round(sge_real_kwh)} kWh ({delta_pct:+.1f}%)."
            })

        if unit_price_ht < 0.05 or unit_price_ht > 0.50:
            status = "ANOMALIE_PRIX"
            anomalies.append({
                "severity": "CRITICAL", 
                "label": "Prix Unitaire Aberrant",
                "message": f"Prix HT calculé : {unit_price_ht:.4f} €/kWh. Vérifiez s'il s'agit d'une régularisation."
            })
            
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
    # 5. PROJECTION (SMART TWIN + CALENDAR)
    # =========================================================
    
    def _get_calendar_ratio(self, year, month, is_pro=False):
        """
        Calcule l'intensité calendaire du mois.
        Utilise Workalendar France si disponible.
        """
        _, num_days = calendar.monthrange(year, month)
        
        if not is_pro:
            return num_days / 30.4375
        else:
            if CALENDAR_READY:
                start_dt = date(year, month, 1)
                end_dt = date(year, month, num_days)
                working_days = cal_france.get_working_days_delta(start_dt, end_dt)
                if cal_france.is_working_day(end_dt): working_days += 1
            else:
                working_days = 0
                for day in range(1, num_days + 1):
                    if date(year, month, day).weekday() < 5: working_days += 1
            
            return working_days / 21.0

    def simulate_landing(self, site_data: Dict) -> Dict[str, Any]:
        """
        Génère une trajectoire annuelle.
        Stratégie : Mirror N-1 + Correction Calendaire + Fallback Volume Facture.
        """
        measurements = site_data.get('measurements',[])
        current_year = datetime.now().year
        if datetime.now().month < 3: current_year = 2026 
        prev_year = current_year - 1

        is_pro = False
        segment = site_data.get('contract', {}).get('segment', '').upper()
        if "C5" not in segment and "C4" not in segment and segment != "": 
            is_pro = True

        n_1_by_month = {m: 0 for m in range(1, 13)}
        total_n_1 = 0
        months_with_data_n_1 = 0
        
        n_by_month = {m: 0 for m in range(1, 13)}
        last_real_month_n = 0

        for m in measurements:
            try:
                d = datetime.strptime(m['date'], "%Y-%m-%d")
                val = m['val']
                if d.year == prev_year:
                    if n_1_by_month[d.month] == 0: months_with_data_n_1 += 1
                    n_1_by_month[d.month] += val
                    total_n_1 += val
                elif d.year == current_year:
                    n_by_month[d.month] += val
                    if d.month > last_real_month_n: last_real_month_n = d.month
            except: continue

        weights = self.SEASONAL_WEIGHTS["STD"]
        if months_with_data_n_1 >= 10 and total_n_1 > 0:
            weights = [n_1_by_month[m] / total_n_1 for m in range(1, 13)]

        total_realized_n = sum(n_by_month.values())
        weight_realized_n = sum(weights[:last_real_month_n])
        
        estimated_annual_vol_n = 0
        
        if weight_realized_n > 0.1:
            estimated_annual_vol_n = total_realized_n / weight_realized_n
        elif total_n_1 > 0:
            estimated_annual_vol_n = total_n_1
        else:
            ref_inv = site_data.get('kpis', {}).get('volume_invoice_ref', 0)
            if ref_inv > 0:
                estimated_annual_vol_n = ref_inv * 4 
            else:
                estimated_annual_vol_n = 6000 

        avg_price = 0.20
        if 'financials' in site_data and 'unit_price_computed' in site_data['financials']:
            avg_price = float(site_data['financials']['unit_price_computed'])

        trajectory_euro =[]
        cumulative_euro = 0
        
        for month in range(1, 13):
            status = "FORECAST"
            
            if month <= last_real_month_n and n_by_month[month] > 0:
                vol = n_by_month[month]
                status = "REAL"
            else:
                weight = weights[month-1]
                base_vol = estimated_annual_vol_n * weight
                calendar_ratio = self._get_calendar_ratio(current_year, month, is_pro)
                vol = base_vol * calendar_ratio
                status = "FORECAST"

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
            "profile_type": "PRO (Jours Ouvrés FR)" if is_pro else "RESID (Jours Calendaires)",
            "trajectory": trajectory_euro
        }

finance = CortexFinance()
