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
    CORTEX FINANCE ENGINE V3.6 (DIAMOND ROBUST - MULTI-FOURNISSEUR)
    Module dédié à l'Audit Financier et à la Triangulation.
    
    CAPACITÉS :
    1. Parsing PDF Natif Universel (EDF, ENGIE, TOTAL, GEG | PRO & Particulier).
    2. Extraction par Poste (HP/HC) & Calcul PMP.
    3. Historisation des Audits (Ledger de fiabilité).
    4. Projection Financière "Smart Twin" (N-1 Mirroring).
    """

    def __init__(self):
        self.logger = logging.getLogger("CortexFinance")
        self.VAT_RATE = 0.20 # Taux de TVA standard élec (20%)
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
    # 2. MOTEUR D'EXTRACTION PDF (UNIVERSEL)
    # =========================================================
    def _parse_pdf_native(self, content: bytes, data: Dict) -> Dict[str, Any]:
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                full_text = ""
                for page in pdf.pages:
                    text = page.extract_text()
                    if text: full_text += text + "\n"

                data["source"] = "PDF_NATIVE"

                # G. Identification Fournisseur (Intégration GEG)
                full_text_upper = full_text.upper()
                if "EDF" in full_text_upper: data['provider'] = "EDF"
                elif "ENGIE" in full_text_upper: data['provider'] = "ENGIE"
                elif "TOTAL" in full_text_upper: data['provider'] = "TOTALENERGIES"
                elif "GEG " in full_text_upper or "GRENOBLE" in full_text_upper: data['provider'] = "GEG"

                # A. Extraction PDL / PRM (14 chiffres) - Ajout "réf ext" pour GEG
                pdl_match = re.search(r"(?:PDL|Point de livraison|Référence acheminement|Réf Acheminement Electricité|réf ext)\s*[:.]?\s*([\d\s]{14,20})", full_text, re.IGNORECASE)
                if pdl_match: 
                    raw_pdl = pdl_match.group(1)
                    clean_pdl = re.sub(r'\D', '', raw_pdl)
                    data['pdl'] = clean_pdl[:14] if len(clean_pdl) >= 14 else clean_pdl
                
                # B. Extraction Dates Période globale
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
                    except Exception: pass

                # C. Volume total (Ajout de la syntaxe GEG)
                vol_match = re.search(r"(?:Total Consommation|Conso|électricité du[^\n]*?au[^\n]*?:)\s*([\d\s]+)\s*(?:kWh)", full_text, re.IGNORECASE)
                if vol_match: data['volume_kwh'] = float(vol_match.group(1).replace(" ", ""))
                
                # D. Pénalités (EDF + GEG Dépassements)
                penalties = 0.0
                pen_edf = re.search(r"Pénalités[^\n]*?\s+(\d+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                if pen_edf: penalties += float(pen_edf.group(1).replace(',', '.'))
                
                # Catch des pénalités GEG (Dépassement de puissance, Réactif)
                for p_match in re.findall(r"(?:dépassements|énergie réactive facturée)[^\n]*?\s+([\d\s]+[\.,]\d{2})(?:\s*€|\n|$)", full_text, re.IGNORECASE):
                    try: penalties += float(p_match.replace(' ', '').replace(',', '.'))
                    except: pass
                data['penalties'] = penalties
                
                # E. Montant TTC (Ajout "total TTC" pour GEG)
                total_match = re.search(r"(?:Montant total à payer\s*\(TTC\)|Facture TTC|Montant total|total TTC)[^\d]*?([\d\s]+[\.,]\d{2})\s?€?", full_text, re.DOTALL | re.IGNORECASE)
                if total_match: data['amount_ttc'] = float(total_match.group(1).replace(" ", "").replace(",", "."))

                # F. Montant HT (Ajout "total HT" pour GEG)
                ht_match = re.search(r"(?:Montant Hors TVA|Total Hors TVA(?: pour ce site)?|Total Electricité hors TVA|total HT)[^\d]*?([\d\s]+[\.,]\d{2})", full_text, re.DOTALL | re.IGNORECASE)
                if ht_match:
                    data['amount_ht'] = float(ht_match.group(1).replace(" ", "").replace(",", "."))
                elif data['amount_ttc'] > 0:
                    tax = data['amount_ttc'] - data['penalties']
                    if tax > 0: data['amount_ht'] = round(tax / (1 + self.VAT_RATE), 2)

                # H. Puissance Souscrite (Universel : "puissance souscrite : 330 kW" ou "P : 330 kW")
                power_match = re.search(r"(?:Puissance souscrite|puissances souscrites)[^\d]*?(\d+[\.,]?\d*)\s*(?:kW|kVA)", full_text, re.IGNORECASE)
                if power_match: data['power_subscribed'] = float(power_match.group(1).replace(',', '.'))

                # I. Date de fin de contrat
                end_date_match = re.search(r"(?:échéance le|date d'échéance)\s*(\d{2}/\d{2}/\d{4})", full_text, re.IGNORECASE)
                if end_date_match: data['contract_end_date'] = end_date_match.group(1)

                # J. Nom de l'Offre
                offer_match = re.search(r"(?:Offre électricité|offre)\s*:\s*([^\n]+)", full_text, re.IGNORECASE)
                if offer_match: data['offer_type'] = offer_match.group(1).strip()

                # K. Taxes (CSPE / Accise / CTA)
                taxes_match = re.search(r"(?:Taxes et contributions|autres taxes)[^\d]*?([\d\s]+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                if taxes_match: data['taxes_amount'] = float(taxes_match.group(1).replace(" ", "").replace(",", "."))

                # L. TURPE (Acheminement EDF vs GEG)
                turpe_edf = re.search(r"part fixe.*?est de\s*([\d\s]+[\.,]\d{2})\s?€.*?part variable est de\s*([\d\s]+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                turpe_geg = re.search(r"(?:sous-total accès au réseau|accès au réseau)[^\d]*?([\d\s]+[\.,]\d{2})\s?€", full_text, re.IGNORECASE)
                if turpe_edf:
                    data['turpe_fixe'] = float(turpe_edf.group(1).replace(" ", "").replace(",", "."))
                    data['turpe_var'] = float(turpe_edf.group(2).replace(" ", "").replace(",", "."))
                elif turpe_geg:
                    data['turpe_fixe'] = float(turpe_geg.group(1).replace(" ", "").replace(",", "."))

                # --- EXTRACTION PAR POSTE (HP/HC) ET PMP ---
                block_matches = re.findall(r"(Heures\s+pleines|Heures\s+creuses|Pointe|HPH|HCH|HPE|HCE)[^\n]*?\s+([\d\s]+)\s*kWh\s+[\d\.,]+\s*(?:c€/kWh|€/kWh|€)?\s*([\d\s]+[\.,]\d{2})", full_text, re.IGNORECASE)
                
                parsed_blocks = {}
                for match in block_matches:
                    raw_name = match[0].upper().replace(" ", "_")
                    post_name = "AUTRE"
                    if "PLEINE" in raw_name or "HPH" in raw_name or "HPE" in raw_name: post_name = "HP"
                    elif "CREUSE" in raw_name or "HCH" in raw_name or "HCE" in raw_name: post_name = "HC"
                    
                    vol = float(match[1].replace(" ", ""))
                    cost = float(match[2].replace(" ", "").replace(",", "."))
                    
                    if post_name not in parsed_blocks:
                        parsed_blocks[post_name] = {"volume_kwh": 0, "cost_ht": 0.0}
                    
                    parsed_blocks[post_name]["volume_kwh"] += vol
                    parsed_blocks[post_name]["cost_ht"] += cost

                for post, p_data in parsed_blocks.items():
                    if p_data["volume_kwh"] > 0:
                        p_data["pmp_eur_kwh"] = round(p_data["cost_ht"] / p_data["volume_kwh"], 4)
                
                data["consumption_blocks"] = parsed_blocks

        except Exception as e: 
            return {"status": "ERROR", "message": f"Erreur critique lors de l'analyse PDF : {str(e)}"}
        
        return {"status": "SUCCESS", "data": data}

    # =========================================================
    # 3. PARSER XML (FACTUR-X)
    # =========================================================
    def _parse_facturx_xml(self, content: bytes, data: Dict) -> Dict[str, Any]:
        return {"status": "MOCK", "message": "Parser XML prêt.", "data": data}

    # =========================================================
    # 4. AUDIT, PERSISTANCE ET HISTORISATION (LEDGER)
    # =========================================================
    def _persist_data_and_historize(self, pdl, price, volume_facture, trust_score, anomalies_count):
        try:
            safe_id = str(pdl).strip()
            file_path = os.path.join(self.DATA_DIR, f"{safe_id}.json")
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
            else:
                data = { "identity": {"id": safe_id, "site_name": f"Site {safe_id}"}, "contract": {"pdl": safe_id}, "measurements":[], "kpis": {} }
            
            if 'financials' not in data: data['financials'] = {}
            data['financials']['unit_price_computed'] = price
            data['financials']['last_audit_date'] = datetime.now().isoformat()
            
            if 'kpis' not in data: data['kpis'] = {}
            data['kpis']['volume_invoice_ref'] = volume_facture
            if 'volume_mwh' not in data['kpis'] or data['kpis']['volume_mwh'] == 0:
                data['kpis']['volume_mwh'] = (volume_facture * 4) / 1000 

            if 'audit_journal' not in data['financials']:
                data['financials']['audit_journal'] =[]
            
            data['financials']['audit_journal'].append({
                "date": datetime.now().isoformat(),
                "volume_audited_kwh": volume_facture,
                "trust_score": trust_score,
                "anomalies": anomalies_count
            })

            scores = [entry["trust_score"] for entry in data['financials']['audit_journal']]
            historical_score = sum(scores) / len(scores) if len(scores) > 0 else 100
            data['financials']['historical_trust_score'] = round(historical_score)

            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
            return historical_score
        except Exception as e:
            print(f"Erreur Persistance: {e}")
            return 100

    def audit_invoice(self, invoice_wrapper: Dict, site_data: Dict) -> Dict[str, Any]:
        if invoice_wrapper.get("status") != "SUCCESS": 
            return {"status": "ERROR", "message": "Impossible d'auditer : Données de facture invalides."}

        inv = invoice_wrapper['data']
        sge_real_kwh = 0
        has_real_data = False
        
        if 'measurements' in site_data and inv['period_start'] and inv['period_end']:
            start = inv['period_start']
            end = inv['period_end']
            for m in site_data['measurements']:
                if start <= m['date'] <= end: sge_real_kwh += m['val']
            if sge_real_kwh > 0: has_real_data = True

        if not has_real_data: sge_real_kwh = inv['volume_kwh'] * 0.98

        delta_pct = 0
        if inv['volume_kwh'] > 0: delta_pct = ((inv['volume_kwh'] - sge_real_kwh) / inv['volume_kwh']) * 100
        unit_price_ht = inv['amount_ht'] / inv['volume_kwh'] if inv['volume_kwh'] > 0 else 0

        status = "CONFORME"
        anomalies =[]
        
        if abs(delta_pct) > 5:
            status = "ANOMALIE_VOLUME"
            anomalies.append({"severity": "HIGH", "label": "Écart de Consommation", "message": f"Facturé: {inv['volume_kwh']} kWh vs Réel: {round(sge_real_kwh)} kWh ({delta_pct:+.1f}%)."})
        if unit_price_ht < 0.05 or unit_price_ht > 0.50:
            status = "ANOMALIE_PRIX"
            anomalies.append({"severity": "CRITICAL", "label": "Prix Unitaire Aberrant", "message": f"Prix PMP global : {unit_price_ht:.4f} €/kWh."})
        if inv['penalties'] > 0:
            anomalies.append({"severity": "MEDIUM", "label": "Gaspillage (Pénalités)", "message": f"{inv['penalties']} € de pénalités de retard détectés."})

        if inv.get('contract_end_date'):
            anomalies.append({"severity": "INFO", "label": "⏱️ Renouvellement", "message": f"Échéance détectée au {inv['contract_end_date']}."})
        if inv.get('taxes_amount') and inv['amount_ht'] > 0:
            tax_pct = (inv['taxes_amount'] / inv['amount_ht']) * 100
            if tax_pct > 15:
                anomalies.append({"severity": "INFO", "label": "⚖️ Poids Fiscal", "message": f"Les taxes représentent {tax_pct:.1f}% ({inv['taxes_amount']}€). Vérifiez l'abattement CSPE."})
        if inv.get('turpe_fixe') and inv.get('turpe_var'):
            anomalies.append({"severity": "INFO", "label": "🔌 Coût Réseau (TURPE)", "message": f"L'acheminement coûte {(inv['turpe_fixe'] + inv['turpe_var']):.2f} €. À optimiser."})
            
        for poste, p_data in inv.get('consumption_blocks', {}).items():
            if p_data.get('pmp_eur_kwh', 0) > 0:
                anomalies.append({
                    "severity": "INFO", 
                    "label": f"📊 Prix Moyen Pondéré ({poste})", 
                    "message": f"Le prix réel de votre énergie sur le poste {poste} est de {p_data['pmp_eur_kwh']:.4f} €/kWh."
                })

        trust_score = 100
        if status == "ANOMALIE_PRIX": trust_score = 10
        elif status == "ANOMALIE_VOLUME": trust_score = 60
        elif inv['penalties'] > 0: trust_score = 85

        historical_score = 100
        if inv['pdl'] and unit_price_ht > 0: 
            historical_score = self._persist_data_and_historize(inv['pdl'], unit_price_ht, inv['volume_kwh'], trust_score, len(anomalies))

        return {
            "audit_date": datetime.now().isoformat(),
            "status": status,
            "trust_score": trust_score,
            "historical_trust_score": round(historical_score),
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
                "has_real_data": has_real_data
            },
            "anomalies": anomalies
        }

    # =========================================================
    # 5. PROJECTION (SMART TWIN)
    # =========================================================
    def _get_calendar_ratio(self, year, month, is_pro=False):
        _, num_days = calendar.monthrange(year, month)
        if not is_pro: return num_days / 30.4375
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
        measurements = site_data.get('measurements',[])
        current_year = datetime.now().year
        if datetime.now().month < 3: current_year = 2026 
        prev_year = current_year - 1

        is_pro = False
        segment = site_data.get('contract', {}).get('segment', '').upper()
        if "C5" not in segment and "C4" not in segment and segment != "": is_pro = True

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
        if months_with_data_n_1 >= 10 and total_n_1 > 0: weights =[n_1_by_month[m] / total_n_1 for m in range(1, 13)]

        total_realized_n = sum(n_by_month.values())
        weight_realized_n = sum(weights[:last_real_month_n])
        estimated_annual_vol_n = 0
        
        if weight_realized_n > 0.1: estimated_annual_vol_n = total_realized_n / weight_realized_n
        elif total_n_1 > 0: estimated_annual_vol_n = total_n_1
        else:
            ref_inv = site_data.get('kpis', {}).get('volume_invoice_ref', 0)
            if ref_inv > 0: estimated_annual_vol_n = ref_inv * 4 
            else: estimated_annual_vol_n = 6000 

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
                base_vol = estimated_annual_vol_n * weights[month-1]
                vol = base_vol * self._get_calendar_ratio(current_year, month, is_pro)
            
            cost = vol * avg_price
            cumulative_euro += cost
            trajectory_euro.append({"month": calendar.month_name[month], "cost_monthly": round(cost, 2), "cost_cumulative": round(cumulative_euro, 2), "status": status})

        return {
            "year": current_year, "landing_euro": round(cumulative_euro, 2),
            "profile_type": "PRO (Jours Ouvrés FR)" if is_pro else "RESID (Jours Calendaires)",
            "trajectory": trajectory_euro
        }

finance = CortexFinance()
