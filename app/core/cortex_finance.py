# --- START OF FILE cortex_finance.py ---
import re
import io
import os
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

try:
    import pdfplumber
    PDF_READY = True
except ImportError:
    PDF_READY = False

class CortexFinance:
    VERSION = "V13.2_CLEAR_SIGHT_FIXED"

    def __init__(self) -> None:
        self.logger = logging.getLogger("CortexFinance")
        self.DATA_DIR = os.path.join(os.getcwd(), "data")
        os.makedirs(self.DATA_DIR, exist_ok=True)

        self.known_suppliers =[
            "EDF", "ENGIE", "TOTALENERGIES", "ENI", "VATTENFALL", "GEG", "ALPIQ", 
            "OHM", "DYNEFF", "PRIMAGAZ", "ANTARGAZ", "GAZ DE BORDEAUX", "EKWATEUR", 
            "IBERDROLA", "ELMY", "OCTOPUS", "PLENITUDE", "BP", "SHELL ENERGY"
        ]

        self.tax_keywords =["tva", "autres taxes", "cta", "ticfe", "accise", "taxes", "contribution", "cspe", "tcfe", "ticgn"]
        self.network_keywords =["sous-total accès au réseau", "accès au réseau", "acces au reseau", "turpe", "acheminement", "distribution", "transport", "atrd", "part acheminement"]
        self.subscription_keywords =["abonnement", "part fixe", "prime fixe", "terme fixe", "abonnement mensuel"]
        self.penalty_keywords =["pénalité", "penalite", "dépassement", "depassement", "cos phi", "energie reactive", "énergie réactive"]
        self.invoice_date_keywords =["date de facture", "date facture", "émise le", "emise le", "invoice date", "éditée le"]

        self._quadrant_aliases = {
            "HPH":["HPH", "HEURES PLEINES HIVER"], "HCH": ["HCH", "HEURES CREUSES HIVER"],
            "HPE":["HPE", "HEURES PLEINES ETE", "HEURES PLEINES ÉTÉ"], "HCE":["HCE", "HEURES CREUSES ETE", "HEURES CREUSES ÉTÉ"],
            "HP":["HP", "HEURES PLEINES"], "HC":["HC", "HEURES CREUSES"], "BASE": ["BASE"], "POINTE": ["POINTE"]
        }

    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        filename_l = (filename or "").lower()
        base = self._empty_invoice_payload()
        base["filename"] = filename or ""
        base["document_hash"] = self._hash_bytes(file_content)

        if filename_l.endswith(".pdf"):
            if not PDF_READY: return {"status": "ERROR", "message": "Module pdfplumber non installé."}
            result = self._parse_pdf_native(file_content, base)
        elif filename_l.endswith(".xml"):
            result = self._parse_facturx_xml(file_content, base)
        else: return {"status": "ERROR", "message": "Format non supporté."}

        if result.get("status") == "SUCCESS":
            result["data"]["normalized_output"] = self._build_normalized_output(result["data"])
        return result

    def audit_invoice(self, invoice_wrapper: Dict[str, Any], site_data: Dict[str, Any]) -> Dict[str, Any]:
        if invoice_wrapper.get("status") != "SUCCESS": return {"status": "ERROR", "message": "Extraction échouée."}

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

        # Tolérance de 2% pour l'équilibre
        if amount_ttc > 0 and amount_ht > 0:
            calculated_ttc = amount_ht + taxes_amount
            if abs(calculated_ttc - amount_ttc) / amount_ttc > 0.02:
                anomalies.append(self._anomaly("HIGH", "Équilibre TTC/HT suspect", "L'addition HT + Taxes diffère de plus de 2% du TTC global."))

        if not inv.get("invoice_number"): anomalies.append(self._anomaly("MEDIUM", "Numéro absent", "Numéro de facture non détecté."))
        if not inv.get("period_start") or not inv.get("period_end"): anomalies.append(self._anomaly("MEDIUM", "Période manquante", "Période de facturation floue."))
        if energy_type == "electricity" and not inv.get("pdl"): anomalies.append(self._anomaly("MEDIUM", "PDL absent", "Point de livraison non identifié."))
        if energy_type == "gas" and not inv.get("pce"): anomalies.append(self._anomaly("MEDIUM", "PCE absent", "Point de comptage gaz non identifié."))

        if volume_kwh > 0 and sge_real_kwh > 0:
            delta_pct = ((volume_kwh - sge_real_kwh) / volume_kwh) * 100
            if abs(delta_pct) > 5.0: anomalies.append(self._anomaly("HIGH", "Écart volume SGE", f"Facturé: {round(volume_kwh)} kWh vs Référence: {round(sge_real_kwh)} kWh."))

        if energy_type == "electricity" and unit_price_ht > 0.35: anomalies.append(self._anomaly("CRITICAL", "Prix électricité élevé", f"Prix calculé : {unit_price_ht:.4f} €/kWh."))
        if energy_type == "gas" and unit_price_ht > 0.20: anomalies.append(self._anomaly("CRITICAL", "Prix gaz élevé", f"Prix calculé : {unit_price_ht:.4f} €/kWh."))
        if penalties > 0: anomalies.append(self._anomaly("MEDIUM", "Pénalités détectées", f"{round(penalties, 2)} € de dépassements facturés."))

        naf = str(site_data.get("identity", {}).get("naf", "0000"))
        annual_vol_mwh = float(site_data.get("kpis", {}).get("volume_mwh", 0) or 0)
        if naf.startswith(("1", "2", "3", "4", "6")) and annual_vol_mwh > 250:
            if amount_ht > 0 and taxes_amount > (amount_ht * 0.15):
                gain_3_ans = round((annual_vol_mwh * 15.0) * 3)
                anomalies.append(self._anomaly("TAX_SHIELD", "Bouclier Fiscal", f"NAF {naf} éligible taux réduit. Gain estimé: {gain_3_ans} € sur 3 ans."))

        trust_score, field_scores = self._compute_trust_score(inv, anomalies)
        bap_status = "APPROVED" if trust_score >= 90 else ("REVIEW" if trust_score >= 70 else "QUARANTINE")
        recommendations = self._build_recommendations(inv, anomalies, trust_score)

        return {
            "audit_date": datetime.now().isoformat(), "status": "CONFORME" if trust_score >= 90 else "ANOMALIE",
            "trust_score": trust_score, "bap_status": bap_status,
            "financials": {
                "amount_ttc": round(amount_ttc, 2), "amount_ht": round(amount_ht, 2), "tax_amount": round(taxes_amount, 2),
                "subscription_amount": round(subscription_amount, 2), "network_amount": round(network_amount, 2),
                "penalty_amount": round(penalties, 2), "ghost_savings": round(penalties, 2), "unit_price_computed": round(unit_price_ht, 6),
                "volume_factured": round(volume_kwh, 2), "cost_breakdown": inv.get("cost_breakdown", {})
            },
            "technical": {
                "source": inv.get("source"), "filename": inv.get("filename"), "energy_type": inv.get("energy_type"), 
                "provider": inv.get("provider"), "pdl_detected": inv.get("pdl"), "pce_detected": inv.get("pce"),
                "invoice_number": inv.get("invoice_number"), 
                "invoice_date": inv.get("invoice_date"),       # LE FIX EST ICI
                "period_start": inv.get("period_start"),       # LE FIX EST ICI
                "period_end": inv.get("period_end"),           # LE FIX EST ICI
                "power_subscribed": inv.get("power_subscribed"), "volume_sge": round(float(sge_real_kwh or 0), 2),
            },
            "anomalies": anomalies, "recommendations": recommendations
        }
        # =========================================================
    # 3. EXTRACTION PDF & XML
    # =========================================================
    def _parse_pdf_native(self, content: bytes, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            text_parts: List[str] =[]
            table_parts: List[str] =[]
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for i, page in enumerate(pdf.pages):
                    if i >= 3: break
                    txt = page.extract_text() or ""
                    if txt: text_parts.append(txt)
                    try:
                        for table in (page.extract_tables() or[]):
                            for row in table:
                                clean_row =[str(c).strip() if c is not None else "" for c in row]
                                if any(clean_row): table_parts.append(" | ".join(clean_row))
                    except: pass

            text = "\n".join(text_parts + table_parts)
            upper = text.upper()

            data["source"] = "PDF_NATIVE"
            data["provider"] = self._detect_supplier(upper)
            data["energy_type"] = self._detect_energy_type(upper)
            
            # Extraction enrichie GEG et Classiques
            data["invoice_number"] = self._extract_invoice_number(text)
            data["pdl"] = self._extract_pdl(text)
            data["pce"] = self._extract_pce(text)
            data["invoice_date"] = self._extract_invoice_date(text)

            period_start, period_end = self._extract_dates_range(text)
            data["period_start"] = period_start
            data["period_end"] = period_end

            data["amount_ttc"] = self._extract_amount_by_keywords(text, ["total ttc", "montant ttc", "total à payer", "net à payer"]) or 0.0
            data["amount_ht"] = self._extract_amount_by_keywords(text,["total ht", "montant ht", "total hors taxes"]) or 0.0

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

            data["cost_breakdown"] = self._build_cost_breakdown(data)
            return {"status": "SUCCESS", "data": data}
        except Exception as exc:
            return {"status": "ERROR", "message": f"Erreur PDF : {str(exc)}"}

    def _parse_facturx_xml(self, content: bytes, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            xml_text = content.decode("utf-8", errors="ignore")
            xml_text = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', xml_text)
            root = ET.fromstring(xml_text)
            full_text = ET.tostring(root, encoding="unicode")
            
            data["source"] = "FACTUR-X_XML_2026"
            data["provider"] = self._detect_supplier(full_text.upper())
            data["energy_type"] = self._detect_energy_type(full_text.upper())
            data["pdl"] = self._extract_pdl(full_text)
            data["invoice_number"] = self._extract_invoice_number(full_text)
            data["amount_ht"] = self._extract_first_decimal_after_keywords(full_text, ["LineTotalAmount", "TaxBasisTotalAmount"]) or 0.0
            data["amount_ttc"] = self._extract_first_decimal_after_keywords(full_text, ["GrandTotalAmount", "DuePayableAmount"]) or 0.0
            data["taxes_amount"] = self._extract_first_decimal_after_keywords(full_text, ["TaxTotalAmount"]) or max((data["amount_ttc"] - data["amount_ht"]), 0.0)
            data["volume_kwh"] = self._extract_volume_kwh(full_text) or 0.0
            
            period_start, period_end = self._extract_dates_range(full_text)
            data["period_start"] = period_start
            data["period_end"] = period_end
            data["cost_breakdown"] = self._build_cost_breakdown(data)

            return {"status": "SUCCESS", "data": data}
        except Exception as exc: return {"status": "ERROR", "message": f"Erreur XML: {str(exc)}"}
    # =========================================================
    # 4. MOTEURS REGEX & NORMALISATION
    # =========================================================
    def _empty_invoice_payload(self) -> Dict[str, Any]:
        return { "source": "UNKNOWN", "filename": "", "document_hash": "", "provider": "INCONNU", "energy_type": "unknown", "pdl": None, "pce": None, "invoice_number": None, "invoice_date": None, "period_start": None, "period_end": None, "volume_kwh": 0.0, "volume_m3": 0.0, "pcs": None, "amount_ht": 0.0, "amount_ttc": 0.0, "taxes_amount": 0.0, "penalties": 0.0, "power_subscribed": 0.0, "subscription_amount": 0.0, "network_amount": 0.0, "consumption_blocks": {}, "cost_breakdown": {}, "normalized_output": {}, "raw_preview": "" }

    def _hash_bytes(self, payload: bytes) -> str: return hashlib.sha256(payload).hexdigest()

    def _detect_supplier(self, text_upper: str) -> str:
        for supplier in self.known_suppliers:
            if supplier in text_upper or f" {supplier} " in f" {text_upper} ": return supplier
        if "GEG" in text_upper and "GRENOBLE" in text_upper: return "GEG"
        return "INCONNU"

    def _detect_energy_type(self, text_upper: str) -> str:
        s_gas = sum(1 for marker in["PCE", "GAZ", "M3", "PCS", "TICGN"] if marker in text_upper)
        s_elec = sum(1 for marker in["PDL", "KVA", "TURPE", "HP", "HC", "TICFE"] if marker in text_upper)
        return "gas" if s_gas > s_elec else "electricity"

    def _extract_pdl(self, text: str) -> Optional[str]:
        # LE FIX EST ICI : Ajout de RÉF EXT (Typique GEG)
        for pattern in[r"(?:PDL|POINT DE LIVRAISON|RÉFÉRENCE ACHEMINEMENT|REF ACHEMINEMENT|RÉF EXT|REF EXT|PRM)\s*[:.]?\s*([\d\s]{14,20})", r"\b(\d{14})\b"]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                cand = re.sub(r"\D", "", match.group(1))
                if len(cand) >= 14: return cand[:14]
        return None

    def _extract_pce(self, text: str) -> Optional[str]:
        for pattern in[r"(?:PCE|POINT DE COMPTAGE)\s*[:.]?\s*([\d\s]{14,20})", r"\b(\d{14})\b"]:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                cand = re.sub(r"\D", "", match.group(1))
                if len(cand) >= 14: return cand[:14]
        return None

    def _extract_invoice_number(self, text: str) -> Optional[str]:
        # LE FIX EST ICI : Ajout de Facture N°
        patterns =[r"(?:FACTURE\s*N[°º]|N[°º]\s*DE\s*FACTURE|FACTURE|INVOICE|R[ÉE]F[ÉE]RENCE\s*FACTURE)\s*[:#]?\s*([A-Z0-9\-_/]+)"]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match: return match.group(1).strip()
        return None

    def _parse_fr_date(self, value: str) -> Optional[datetime]:
        normalized = value.strip().replace(".", "/").replace("-", "/")
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try: return datetime.strptime(normalized, fmt)
            except Exception: pass
        return None

    def _extract_invoice_date(self, text: str) -> Optional[str]:
        patterns =[]
        for keyword in self.invoice_date_keywords: patterns.append(rf"{re.escape(keyword)}\s*[:.]?\s*(\d{{2}}[/.-]\d{{2}}[/.-]\d{{2,4}})")
        patterns.append(r"<IssueDateTime[^>]*>.*?(\d{4}-\d{2}-\d{2}).*?</IssueDateTime>")
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if not match: continue
            raw = match.group(1)
            if re.match(r"\d{4}-\d{2}-\d{2}", raw): return raw
            parsed = self._parse_fr_date(raw)
            if parsed: return parsed.strftime("%Y-%m-%d")
        return None

    def _extract_dates_range(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        dates: List[Tuple[datetime, datetime]] =[]
        # LE FIX EST ICI : Tolerant aux espaces entre DU et AU
        patterns =[r"du\s*([\d]{2}[/.-][\d]{2}[/.-][\d]{2,4})\s*au\s*([\d]{2}[/.-][\d]{2}[/.-][\d]{2,4})"]
        for pattern in patterns:
            for s_raw, e_raw in re.findall(pattern, text, re.IGNORECASE):
                d_start = self._parse_fr_date(s_raw)
                d_end = self._parse_fr_date(e_raw)
                if d_start and d_end: dates.append((d_start, d_end))
        if not dates: return None, None
        return min(pair[0] for pair in dates).strftime("%Y-%m-%d"), max(pair[1] for pair in dates).strftime("%Y-%m-%d")

    def _extract_amount_by_keywords(self, text: str, keywords: List[str]) -> Optional[float]:
        normalized = text.replace("\xa0", " ")
        for keyword in keywords:
            # LE FIX EST ICI : On passe de 50 à 150 caractères pour absorber les grands espaces de mise en page
            match = re.search(rf"{re.escape(keyword)}[^\n\r\d]{{0,150}}?(-?\d[\d\s.,]+)\s*€", normalized, re.IGNORECASE)
            if match: return self._to_float(match.group(1))
        return None

    def _extract_first_decimal_after_keywords(self, text: str, tags: List[str]) -> Optional[float]:
        for tag in tags:
            match = re.search(rf"<{tag}[^>]*>(-?\d+(?:\.\d+)?)</{tag}>", text, re.IGNORECASE)
            if match: return self._to_float(match.group(1))
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
        for pattern in [r"(\d[\d.,]+)\s*kva", r"puissance\s+souscrite\s*[:.]?\s*(\d[\d.,]+)"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match: return self._to_float(match.group(1)) or 0.0
        return 0.0

    def _extract_taxes(self, text: str, amount_ht: float, amount_ttc: float) -> float:
        tva = self._extract_amount_by_keywords(text, ["tva"]) or 0.0
        autres = self._extract_amount_by_keywords(text,["autres taxes", "cspe", "ticfe", "ticgn"]) or 0.0
        if tva > 0 or autres > 0: return round(tva + autres, 2)
        
        val = self._extract_amount_by_keywords(text, ["total taxes", "taxes"])
        if val and val > 0: return val
        return round(amount_ttc - amount_ht, 2) if amount_ttc > amount_ht else 0.0

    def _extract_penalties(self, text: str) -> float:
        return round(sum(self._extract_amount_by_keywords(text, [kw]) or 0.0 for kw in self.penalty_keywords), 2)

    def _build_cost_breakdown(self, data: Dict[str, Any]) -> Dict[str, Any]:
        ht = float(data.get("amount_ht") or 0.0)
        supply_explicit = self._extract_amount_by_keywords(data.get("raw_preview", ""),["sous-total fourniture", "fourniture"])
        sub = float(data.get("subscription_amount") or 0.0)
        net = float(data.get("network_amount") or 0.0)
        tax = float(data.get("taxes_amount") or 0.0)
        pen = float(data.get("penalties") or 0.0)
        energy_variable = supply_explicit if supply_explicit and supply_explicit > 0 else max(ht - sub - net - pen, 0.0)
        return { "subscription": round(sub, 2), "network": round(net, 2), "energy_variable": round(energy_variable, 2), "taxes": round(tax, 2), "penalties": round(pen, 2) }

    def _estimate_sge_volume(self, inv: Dict[str, Any], site: Dict[str, Any]) -> float:
        site_kwh = float(site.get("kpis", {}).get("volume_kwh") or 0.0)
        if site_kwh > 0: return site_kwh
        return float(inv.get("volume_kwh") or 0.0) * 0.98

    def _compute_trust_score(self, inv: Dict[str, Any], anomalies: List[Dict[str, Any]]) -> Tuple[int, Dict[str, int]]:
        field_scores = {
            "provider": 100 if inv.get("provider") and inv.get("provider") != "INCONNU" else 20,
            "invoice_number": 100 if inv.get("invoice_number") else 15,
            "period": 100 if inv.get("period_start") and inv.get("period_end") else 20,
            "identifier": 100 if inv.get("pdl") or inv.get("pce") else 20,
            "volume": 100 if float(inv.get("volume_kwh") or 0.0) > 0 else 10,
            "amounts": 100 if float(inv.get("amount_ht") or 0.0) > 0 and float(inv.get("amount_ttc") or 0.0) > 0 else 25,
            "pricing_breakdown": 100 if inv.get("cost_breakdown") else 40,
        }
        base_score = int(sum(field_scores.values()) / len(field_scores)) if field_scores else 100
        penalty = sum(35 if a.get("severity") == "CRITICAL" else (18 if a.get("severity") == "HIGH" else (8 if a.get("severity") == "MEDIUM" else (3 if a.get("severity") == "LOW" else 0))) for a in anomalies)
        return max(5, min(100, base_score - penalty)), field_scores

    def _build_recommendations(self, inv: Dict[str, Any], anomalies: List[Dict[str, Any]], trust_score: int) -> List[Dict[str, Any]]:
        recommendations: List[Dict[str, Any]] =[]
        if trust_score < 70: recommendations.append({"priority": "HIGH", "type": "DATA_QUALITY", "label": "Contrôle manuel recommandé", "next_action": "Relire la facture."})
        if any(a.get("label") == "Écart volume SGE" for a in anomalies): recommendations.append({"priority": "HIGH", "type": "VOLUME_CHECK", "label": "Comparer facture et données réseau", "next_action": "Rapprocher le volume."})
        if any(a.get("label") in {"Prix électricité élevé", "Prix gaz élevé"} for a in anomalies): recommendations.append({"priority": "HIGH", "type": "PRICING_REVIEW", "label": "Lancer une revue contractuelle", "next_action": "Comparer le prix unitaire."})
        if not recommendations: recommendations.append({"priority": "LOW", "type": "MONITORING", "label": "Facture cohérente", "next_action": "Archiver."})
        return recommendations

    def _build_normalized_output(self, data: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def _to_float(self, value: Any) -> Optional[float]:
        if not value: return None
        s = str(value).replace("\xa0", " ").replace("€", "").replace("EUR", "").replace(" ", "").strip()
        if "," in s and "." in s: s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s: s = s.replace(",", ".")
        try: return float(s)
        except: return None

    def _anomaly(self, severity: str, label: str, message: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"severity": severity, "label": label, "message": message}
        if metadata: payload["metadata"] = metadata
        return payload

    def simulate_ebitda(self, ca_k_eur: float, marge_pct: float, gains_eur: float, multiple: float) -> Dict[str, Any]:
        return {}

    def simulate_landing(self, site_data: dict) -> dict:
        return {}

finance = CortexFinance()        
