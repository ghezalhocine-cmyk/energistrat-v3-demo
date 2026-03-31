# --- START OF FILE cortex_finance.py ---

import re
import io
import os
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

try:
    import pdfplumber
    PDF_READY = True
except ImportError:
    PDF_READY = False
    print("WARNING: pdfplumber manquant. Le parsing PDF sera désactivé.")

class CortexFinance:
    """
    ENERGISTRAT - CORTEX FINANCE V12.8 (HEURISTIQUE & FINOPS)
    Analyse générique France pro des factures électricité / gaz.
    Inclut la protection Cloud Run (Scan limité à 3 pages).
    """

    def __init__(self):
        self.logger = logging.getLogger("CortexFinance")
        self.DATA_DIR = os.path.join(os.getcwd(), "data")
        os.makedirs(self.DATA_DIR, exist_ok=True)

        self.known_suppliers =[
            "EDF", "ENGIE", "TOTALENERGIES", "TOTAL", "ENI", 
            "VATTENFALL", "GEG", "ALPIQ", "OHM", "DYNEFF", 
            "PRIMAGAZ", "ANTARGAZ", "GAZ DE BORDEAUX", "EKWATEUR", "IBERDROLA"
        ]

        self.tax_keywords =["tva", "cta", "ticfe", "accise", "taxes", "contribution", "cspe", "tcfe"]
        self.network_keywords =["turpe", "acheminement", "accès réseau", "acces reseau", "distribution", "transport", "atrd", "r\u00e9seau", "reseau"]
        self.subscription_keywords =["abonnement", "part fixe", "prime fixe", "terme fixe", "abonnement mensuel", "abonnement annuel"]
        self.penalty_keywords =["p\u00e9nalit\u00e9", "penalite", "d\u00e9passement", "depassement", "cos phi", "energie reactive", "\u00e9nergie r\u00e9active"]

    # =========================================================
    # 1. ROUTEUR D'INGESTION (DISPATCHER)
    # =========================================================
    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        filename_l = (filename or "").lower()
        base = self._empty_invoice_payload()

        if filename_l.endswith(".pdf"):
            if not PDF_READY:
                return {"status": "ERROR", "message": "Module pdfplumber non installé."}
            return self._parse_pdf_native(file_content, base)

        if filename_l.endswith(".xml"):
            return self._parse_facturx_xml(file_content, base)

        return {"status": "ERROR", "message": "Format non supporté. Utiliser PDF ou XML."}

    # =========================================================
    # 2. MOTEUR D'AUDIT FINOPS (BAP & SCORE)
    # =========================================================
    def audit_invoice(self, invoice_wrapper: Dict[str, Any], site_data: Dict[str, Any]) -> Dict[str, Any]:
        if invoice_wrapper.get("status") != "SUCCESS":
            return {"status": "ERROR", "message": "Données facture invalides."}

        inv = invoice_wrapper["data"]
        anomalies: List[Dict[str, Any]] =[]

        energy_type = inv.get("energy_type", "unknown")
        amount_ht = float(inv.get("amount_ht") or 0.0)
        amount_ttc = float(inv.get("amount_ttc") or 0.0)
        volume_kwh = float(inv.get("volume_kwh") or 0.0)
        taxes_amount = float(inv.get("taxes_amount") or 0.0)
        penalties = float(inv.get("penalties") or 0.0)
        network_amount = float(inv.get("network_amount") or 0.0)
        subscription_amount = float(inv.get("subscription_amount") or 0.0)

        sge_real_kwh = self._estimate_sge_volume(inv, site_data)
        unit_price_ht = amount_ht / volume_kwh if volume_kwh > 0 else 0.0

        # 1. Cohérences structurelles
        if amount_ttc > 0 and amount_ht > amount_ttc:
            anomalies.append({"severity": "HIGH", "label": "Montants incohérents", "message": "Le montant HT est supérieur au TTC."})
        if not inv.get("invoice_number"):
            anomalies.append({"severity": "MEDIUM", "label": "Numéro absent", "message": "Numéro de facture non détecté."})
        if not inv.get("period_start") or not inv.get("period_end"):
            anomalies.append({"severity": "MEDIUM", "label": "Période manquante", "message": "La période de facturation est floue."})
        if energy_type == "electricity" and not inv.get("pdl"):
            anomalies.append({"severity": "MEDIUM", "label": "PDL absent", "message": "Point de livraison non identifié."})

        # 2. Volume vs SGE
        if volume_kwh > 0 and sge_real_kwh > 0:
            delta_pct = ((volume_kwh - sge_real_kwh) / volume_kwh) * 100
            if abs(delta_pct) > 5:
                anomalies.append({"severity": "HIGH", "label": "Écart volume SGE", "message": f"Facturé: {round(volume_kwh)} kWh vs Réel: {round(sge_real_kwh)} kWh."})

        # 3. Prix unitaire aberrant
        if energy_type == "electricity" and unit_price_ht > 0.35:
            anomalies.append({"severity": "CRITICAL", "label": "Prix électricité élevé", "message": f"Prix calculé : {unit_price_ht:.4f} €/kWh."})
        if energy_type == "gas" and unit_price_ht > 0.20:
            anomalies.append({"severity": "CRITICAL", "label": "Prix gaz élevé", "message": f"Prix calculé : {unit_price_ht:.4f} €/kWh."})

        # 4. Pénalités
        if penalties > 0:
            anomalies.append({"severity": "MEDIUM", "label": "Pénalités", "message": f"{round(penalties, 2)} € de pénalités/dépassements (TURPE/Cos Phi)."})

        # 5. Structure de coût (Gisements FinOps)
        if amount_ht > 0:
            if (taxes_amount / amount_ht) > 0.35:
                anomalies.append({"severity": "MEDIUM", "label": "Taxes élevées", "message": f"Taxes = {round((taxes_amount/amount_ht)*100)}% du HT."})
            if energy_type == "electricity" and (network_amount / amount_ht) > 0.50:
                anomalies.append({"severity": "MEDIUM", "label": "TURPE élevé", "message": f"Acheminement = {round((network_amount/amount_ht)*100)}% du HT."})
            if (subscription_amount / amount_ht) > 0.45 and volume_kwh > 0:
                anomalies.append({"severity": "MEDIUM", "label": "Abonnement élevé", "message": f"Part fixe = {round((subscription_amount/amount_ht)*100)}% du HT."})

        # 6. Bouclier fiscal (Tax Shield)
        naf = str(site_data.get("identity", {}).get("naf", "0000"))
        annual_vol_mwh = float(site_data.get("kpis", {}).get("volume_mwh", 0) or 0)
        if naf.startswith(("1", "2", "3", "4", "6")) and annual_vol_mwh > 250:
            if amount_ht > 0 and taxes_amount > (amount_ht * 0.15):
                gain_3_ans = round((annual_vol_mwh * 15.0) * 3)
                anomalies.append({"severity": "TAX_SHIELD", "label": "Bouclier Fiscal", "message": f"NAF {naf} éligible taux réduit. Gain estimé: {gain_3_ans} € (3 ans)."})

        trust_score, field_scores = self._compute_trust_score(inv, anomalies)
        bap_status = "APPROVED" if trust_score >= 90 else ("REVIEW" if trust_score >= 70 else "QUARANTINE")

        return {
            "audit_date": datetime.now().isoformat(),
            "status": "CONFORME" if trust_score >= 90 else "ANOMALIE",
            "trust_score": trust_score,
            "bap_status": bap_status,
            "financials": {
                "amount_ttc": round(amount_ttc, 2), "amount_ht": round(amount_ht, 2),
                "tax_amount": round(taxes_amount, 2), "subscription_amount": round(subscription_amount, 2),
                "network_amount": round(network_amount, 2), "penalty_amount": round(penalties, 2),
                "ghost_savings": round(penalties, 2), "unit_price_computed": round(unit_price_ht, 4),
                "volume_factured": round(volume_kwh, 2), "consumption_blocks": inv.get("consumption_blocks", {}),
                "cost_breakdown": inv.get("cost_breakdown", {}),
            },
            "technical": {
                "source": inv.get("source"), "energy_type": inv.get("energy_type"), "provider": inv.get("provider"),
                "pdl_detected": inv.get("pdl"), "pce_detected": inv.get("pce"), "invoice_number": inv.get("invoice_number"),
                "period_start": inv.get("period_start"), "period_end": inv.get("period_end"), "power_subscribed": inv.get("power_subscribed"),
                "pcs": inv.get("pcs"), "trust_fields": field_scores, "volume_sge": round(float(sge_real_kwh or 0), 2),
            },
            "anomalies": anomalies
        }

    # =========================================================
    # 3. EXTRACTION PDF AVEC SÉCURITÉ CLOUD RUN
    # =========================================================
    def _parse_pdf_native(self, content: bytes, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            text_parts = []
            table_parts =[]

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for i, page in enumerate(pdf.pages):
                    # 🛡️ PROTECTION ANTI-TIMEOUT: Stop au bout de 3 pages (Evite le crash Cloud Run sur 100 pages)
                    if i >= 3: 
                        self.logger.warning("Facture longue : Scan PDF tronqué aux 3 premières pages pour préserver la RAM.")
                        break
                        
                    txt = page.extract_text() or ""
                    if txt: text_parts.append(txt)

                    try:
                        tables = page.extract_tables() or []
                        for table in tables:
                            for row in table:
                                clean_row =[str(c).strip() if c is not None else "" for c in row]
                                if any(clean_row): table_parts.append(" | ".join(clean_row))
                    except Exception: pass

            text = "\n".join(text_parts + table_parts)
            upper = text.upper()

            data["source"] = "PDF_NATIVE"
            data["provider"] = self._detect_supplier(upper)
            data["energy_type"] = self._detect_energy_type(upper)
            data["pdl"] = self._extract_pdl(text)
            data["pce"] = self._extract_pce(text)
            data["invoice_number"] = self._extract_invoice_number(text)
            
            period_start, period_end = self._extract_dates_range(text)
            data["period_start"] = period_start
            data["period_end"] = period_end

            data["amount_ttc"] = self._extract_amount_by_keywords(text,["total ttc", "montant ttc", "net à payer ttc", "total à payer ttc"]) or 0.0
            data["amount_ht"] = self._extract_amount_by_keywords(text, ["total ht", "montant ht", "total hors taxes", "net ht"]) or 0.0

            if data["amount_ht"] <= 0 and data["amount_ttc"] > 0:
                data["amount_ht"] = round(data["amount_ttc"] / 1.2, 2)

            data["taxes_amount"] = self._extract_taxes(text, data["amount_ht"], data["amount_ttc"])
            data["subscription_amount"] = self._extract_amount_by_keywords(text, self.subscription_keywords) or 0.0
            data["network_amount"] = self._extract_amount_by_keywords(text, self.network_keywords) or 0.0
            data["penalties"] = self._extract_penalties(text)
            data["power_subscribed"] = self._extract_power(text)

            data["volume_kwh"] = self._extract_volume_kwh(text) or 0.0
            data["volume_m3"] = self._extract_volume_m3(text)
            data["pcs"] = self._extract_pcs(text)

            if data["volume_kwh"] <= 0 and data["volume_m3"] > 0 and data["pcs"]:
                data["volume_kwh"] = round(data["volume_m3"] * data["pcs"], 2)

            data["consumption_blocks"] = self._extract_consumption_blocks(text, data["energy_type"], data["amount_ht"], data["volume_kwh"])
            data["cost_breakdown"] = self._build_cost_breakdown(data)

            return {"status": "SUCCESS", "data": data}

        except Exception as e:
            return {"status": "ERROR", "message": f"Erreur PDF : {str(e)}"}

    # =========================================================
    # 4. MOTEURS DE DÉTECTION (TEXTE/XML/CHIFFRES)
    # =========================================================
    def _parse_facturx_xml(self, content: bytes, data: Dict[str, Any]) -> Dict[str, Any]:
        # (Version XML allégée et conservée selon l'esprit du code ChatGPT)
        try:
            xml_text = content.decode("utf-8", errors="ignore")
            xml_text = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', xml_text)
            root = ET.fromstring(xml_text)
            data["source"] = "FACTUR-X_XML_2026"
            full_text = ET.tostring(root, encoding="unicode")
            
            data["provider"] = self._detect_supplier(full_text.upper())
            data["energy_type"] = self._detect_energy_type(full_text.upper())
            data["pdl"] = self._extract_pdl(full_text)
            data["pce"] = self._extract_pce(full_text)
            data["invoice_number"] = self._extract_invoice_number(full_text)
            data["amount_ht"] = self._extract_first_decimal_after_keywords(full_text,["LineTotalAmount", "TaxBasisTotalAmount"]) or 0.0
            data["amount_ttc"] = self._extract_first_decimal_after_keywords(full_text, ["GrandTotalAmount", "DuePayableAmount"]) or 0.0
            data["volume_kwh"] = self._extract_volume_kwh(full_text) or 0.0
            
            return {"status": "SUCCESS", "data": data}
        except Exception as e:
            return {"status": "ERROR", "message": f"Erreur XML: {str(e)}"}

    def _empty_invoice_payload(self) -> Dict[str, Any]:
        return { "source": "UNKNOWN", "provider": "INCONNU", "energy_type": "unknown", "pdl": None, "pce": None, "invoice_number": None, "period_start": None, "period_end": None, "volume_kwh": 0.0, "volume_m3": 0.0, "pcs": None, "amount_ht": 0.0, "amount_ttc": 0.0, "taxes_amount": 0.0, "penalties": 0.0, "power_subscribed": 0.0, "subscription_amount": 0.0, "network_amount": 0.0, "consumption_blocks": {}, "cost_breakdown": {} }

    def _detect_supplier(self, text_upper: str) -> str:
        for s in self.known_suppliers:
            if s in text_upper or f" {s} " in f" {text_upper} ": return s
        return "INCONNU"

    def _detect_energy_type(self, text_upper: str) -> str:
        s_gas = sum(1 for m in["PCE", "GAZ", "M3", "PCS"] if m in text_upper)
        s_elec = sum(1 for m in["PDL", "KVA", "TURPE", "HP", "HC"] if m in text_upper)
        return "gas" if s_gas > s_elec else "electricity"

    def _extract_pdl(self, text: str) -> Optional[str]:
        for p in[r"(?:PDL|RÉFÉRENCE ACHEMINEMENT)\s*[:.]?\s*([\d\s]{14,20})", r"\b(\d{14})\b"]:
            for m in re.finditer(p, text, re.IGNORECASE):
                cand = re.sub(r"\D", "", m.group(1))
                if len(cand) >= 14: return cand[:14]
        return None

    def _extract_pce(self, text: str) -> Optional[str]:
        for p in [r"(?:PCE|POINT DE COMPTAGE)\s*[:.]?\s*([\d\s]{14,20})", r"\b(\d{14})\b"]:
            for m in re.finditer(p, text, re.IGNORECASE):
                cand = re.sub(r"\D", "", m.group(1))
                if len(cand) >= 14: return cand[:14]
        return None

    def _extract_invoice_number(self, text: str) -> Optional[str]:
        m = re.search(r"(?:FACTURE|N° DE FACTURE)\s*[:#]?\s*([A-Z0-9\-_\/]+)", text, re.IGNORECASE)
        return m.group(1).strip() if m else None

    def _extract_dates_range(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        dates =[]
        for p in[r"du\s+(\d{2}/\d{2}/\d{2,4})\s+au\s+(\d{2}/\d{2}/\d{2,4})"]:
            for s, e in re.findall(p, text, re.IGNORECASE):
                try: dates.append((datetime.strptime(s, "%d/%m/%Y"), datetime.strptime(e, "%d/%m/%Y")))
                except: pass
        if not dates: return None, None
        return min(d[0] for d in dates).strftime("%Y-%m-%d"), max(d[1] for d in dates).strftime("%Y-%m-%d")

    def _extract_amount_by_keywords(self, text: str, keywords: List[str]) -> Optional[float]:
        norm = text.replace("\xa0", " ")
        for kw in keywords:
            m = re.search(rf"{re.escape(kw)}[^\n\r]{{0,80}}?(-?\d[\d\s.,]+)\s*€", norm, re.IGNORECASE)
            if m: return self._to_float(m.group(1))
        return None

    def _extract_first_decimal_after_keywords(self, text: str, tags: List[str]) -> Optional[float]:
        for t in tags:
            m = re.search(rf"<{t}[^>]*>(-?\d+(?:\.\d+)?)</{t}>", text, re.IGNORECASE)
            if m: return self._to_float(m.group(1))
        return None

    def _extract_volume_kwh(self, text: str) -> Optional[float]:
        vals =[self._to_float(m) for m in re.findall(r"(\d[\d\s.,]+)\s*kwh", text, re.IGNORECASE) if self._to_float(m) and self._to_float(m) > 50]
        return max(vals) if vals else None

    def _extract_volume_m3(self, text: str) -> float:
        vals =[self._to_float(m) for m in re.findall(r"(\d[\d\s.,]+)\s*m3\b", text, re.IGNORECASE) if self._to_float(m)]
        return max(vals) if vals else 0.0

    def _extract_pcs(self, text: str) -> Optional[float]:
        m = re.search(r"pcs\s*[:.]?\s*(\d[\d.,]+)", text, re.IGNORECASE)
        return self._to_float(m.group(1)) if m else None

    def _extract_power(self, text: str) -> float:
        m = re.search(r"(\d[\d.,]+)\s*kva", text, re.IGNORECASE)
        return self._to_float(m.group(1)) if m else 0.0

    def _extract_taxes(self, text: str, amount_ht: float, amount_ttc: float) -> float:
        val = self._extract_amount_by_keywords(text,["total taxes", "taxes", "tva", "cspe"])
        if val and val > 0: return val
        return round(amount_ttc - amount_ht, 2) if amount_ttc > amount_ht else 0.0

    def _extract_penalties(self, text: str) -> float:
        return round(sum(self._extract_amount_by_keywords(text,[kw]) or 0 for kw in self.penalty_keywords), 2)

    def _extract_consumption_blocks(self, text: str, energy_type: str, ht: float, vol: float) -> Dict:
        if energy_type == "gas" or vol <= 0: return {}
        blocks = {}
        for raw, v, c in re.findall(r"(HP|HC|POINTE|BASE)[^\n]*?\s+([\d\s.,]+)\s*kWh[^\n]*?([\d\s.,]+)\s*€", text, re.IGNORECASE):
            bv, bc = self._to_float(v) or 0.0, self._to_float(c) or 0.0
            if bv > 0:
                blocks[raw.upper()] = {"volume_kwh": bv, "cost_ht": bc, "pmp_eur_kwh": round(bc/bv, 4)}
        return blocks

    def _build_cost_breakdown(self, data: Dict) -> Dict:
        ht, sub, net, tax, pen = data.get("amount_ht", 0), data.get("subscription_amount", 0), data.get("network_amount", 0), data.get("taxes_amount", 0), data.get("penalties", 0)
        return { "subscription": sub, "network": net, "energy_variable": max(ht - sub - net - pen, 0), "taxes": tax, "penalties": pen }

    def _estimate_sge_volume(self, inv: Dict, site: Dict) -> float:
        return float(inv.get("volume_kwh") or 0) * 0.98

    def _compute_trust_score(self, inv: Dict, anomalies: List) -> Tuple[int, Dict]:
        score = 100
        for a in anomalies:
            if a["severity"] == "CRITICAL": score -= 35
            elif a["severity"] == "HIGH": score -= 18
            elif a["severity"] == "MEDIUM": score -= 8
        return max(5, score), {}

    def _to_float(self, value: Any) -> Optional[float]:
        if not value: return None
        s = str(value).replace("\xa0", " ").replace("€", "").replace("EUR", "").replace(" ", "").strip()
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s: s = s.replace(",", ".")
        try: return float(s)
        except: return None

    # =========================================================
    # 5. RESTAURATION DU SIMULATEUR STRATÉGIQUE M&A
    # =========================================================
    def simulate_ebitda(self, ca_k_eur: float, marge_pct: float, gains_eur: float, multiple: float) -> Dict[str, Any]:
        """Moteur vital pour le Dashboard FinOps (Module M&A)"""
        try:
            ca_reel = ca_k_eur * 1000
            marge_decimal = marge_pct / 100.0
            
            val_creation = gains_eur * multiple
            nouvelle_marge = (((ca_reel * marge_decimal) + gains_eur) / ca_reel) * 100 if ca_reel > 0 else 0
            equivalent_ca = (gains_eur / marge_decimal) if marge_decimal > 0 else 0

            return {
                "val_creation_eur": val_creation,
                "nouvelle_marge_pct": round(nouvelle_marge, 2),
                "equivalent_ca_eur": equivalent_ca
            }
        except Exception as e:
            self.logger.error(f"Erreur simulation EBITDA : {e}")
            return {"error": str(e)}
            
    def simulate_landing(self, site_data: Dict) -> Dict:
        return {"year": 2026, "landing_euro": 0, "trajectory":
