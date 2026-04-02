# --- START OF FILE cortex_finance.py ---

import re
import io
import os
import json
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
    """
    ENERGISTRAT - CORTEX FINANCE V12.12 UNICORN

    Moteur premium d'analyse de factures énergie France B2B.
    Objectifs :
    - robustesse Cloud Run / FastAPI
    - parsing PDF et Factur-X défensif
    - restitution normalisée pour front, satellites et APIs
    - audit FinOps plus explicable
    - heuristiques France énergie (électricité / gaz)
    """

    VERSION = "V12.12_UNICORN"

    def __init__(self) -> None:
        self.logger = logging.getLogger("CortexFinance")
        self.DATA_DIR = os.path.join(os.getcwd(), "data")
        os.makedirs(self.DATA_DIR, exist_ok=True)

        self.known_suppliers =[
            "EDF", "ENGIE", "TOTALENERGIES", "TOTAL", "ENI",
            "VATTENFALL", "GEG", "ALPIQ", "OHM", "DYNEFF",
            "PRIMAGAZ", "ANTARGAZ", "GAZ DE BORDEAUX", "EKWATEUR", "IBERDROLA",
            "ELMY", "OCTOPUS", "PLENITUDE", "BP", "SHELL ENERGY"
        ]

        self.tax_keywords =[
            "tva", "cta", "ticfe", "accise", "taxes", "contribution", "cspe",
            "tcfe", "ticgn", "tvafe", "contribution tarifaire"
        ]
        self.network_keywords =[
            "turpe", "acheminement", "accès réseau", "acces reseau", "distribution",
            "transport", "atrd", "réseau", "reseau", "part acheminement"
        ]
        self.subscription_keywords =[
            "abonnement", "part fixe", "prime fixe", "terme fixe", "abonnement mensuel",
            "abonnement annuel", "composante de gestion", "composante de comptage"
        ]
        self.penalty_keywords =[
            "pénalité", "penalite", "dépassement", "depassement", "cos phi",
            "energie reactive", "énergie réactive", "reactive", "depassement puissance"
        ]

        self.invoice_date_keywords =[
            "date de facture", "date facture", "émise le", "emise le", "invoice date"
        ]

        self._quadrant_aliases = {
            "HPH":["HPH", "HEURES PLEINES HIVER"],
            "HCH": ["HCH", "HEURES CREUSES HIVER"],
            "HPE": ["HPE", "HEURES PLEINES ETE", "HEURES PLEINES ÉTÉ"],
            "HCE": ["HCE", "HEURES CREUSES ETE", "HEURES CREUSES ÉTÉ"],
            "HP": ["HP", "HEURES PLEINES"],
            "HC": ["HC", "HEURES CREUSES"],
            "BASE": ["BASE"],
            "POINTE": ["POINTE"],
        }

    # =========================================================
    # 1. PUBLIC API
    # =========================================================
    def parse_invoice(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        filename_l = (filename or "").lower()
        base = self._empty_invoice_payload()
        base["filename"] = filename or ""
        base["document_hash"] = self._hash_bytes(file_content)

        if filename_l.endswith(".pdf"):
            if not PDF_READY:
                return {"status": "ERROR", "message": "Module pdfplumber non installé sur le serveur."}
            result = self._parse_pdf_native(file_content, base)
        elif filename_l.endswith(".xml"):
            result = self._parse_facturx_xml(file_content, base)
        else:
            return {
                "status": "ERROR",
                "message": "Format non supporté. Veuillez utiliser un PDF ou un XML (Factur-X)."
            }

        if result.get("status") == "SUCCESS":
            result["data"]["normalized_output"] = self._build_normalized_output(result["data"])
        return result

    def audit_invoice(self, invoice_wrapper: Dict[str, Any], site_data: Dict[str, Any]) -> Dict[str, Any]:
        if invoice_wrapper.get("status") != "SUCCESS":
            return {
                "status": "ERROR",
                "message": "Les données de la facture n'ont pas pu être extraites proprement."
            }

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
        invoice_date = inv.get("invoice_date")

        sge_real_kwh = self._estimate_sge_volume(inv, site_data)
        unit_price_ht = amount_ht / volume_kwh if volume_kwh > 0 else 0.0

        # 1. Cohérences structurelles
        if amount_ttc > 0 and amount_ht > amount_ttc:
            anomalies.append(self._anomaly("HIGH", "Montants incohérents", "Le montant HT est supérieur au TTC."))
        if not inv.get("invoice_number"):
            anomalies.append(self._anomaly("MEDIUM", "Numéro absent", "Numéro de facture non détecté."))
        if not inv.get("period_start") or not inv.get("period_end"):
            anomalies.append(self._anomaly("MEDIUM", "Période manquante", "La période de facturation est floue ou absente."))
        if not invoice_date:
            anomalies.append(self._anomaly("LOW", "Date de facture absente", "La date d'émission n'a pas été détectée."))

        if energy_type == "electricity" and not inv.get("pdl"):
            anomalies.append(self._anomaly("MEDIUM", "PDL absent", "Point de livraison non identifié."))
        if energy_type == "gas" and not inv.get("pce"):
            anomalies.append(self._anomaly("MEDIUM", "PCE absent", "Point de comptage gaz non identifié."))

        # 2. Volume vs SGE / site
        if volume_kwh > 0 and sge_real_kwh > 0:
            delta_pct = ((volume_kwh - sge_real_kwh) / volume_kwh) * 100
            if abs(delta_pct) > 5:
                anomalies.append(self._anomaly(
                    "HIGH",
                    "Écart volume SGE",
                    f"Facturé: {round(volume_kwh)} kWh vs Référence: {round(sge_real_kwh)} kWh.",
                    {"delta_pct": round(delta_pct, 2)}
                ))

        # 3. Prix unitaires aberrants
        if energy_type == "electricity" and unit_price_ht > 0.35:
            anomalies.append(self._anomaly(
                "CRITICAL", "Prix électricité élevé", f"Prix calculé : {unit_price_ht:.4f} €/kWh."
            ))
        if energy_type == "gas" and unit_price_ht > 0.20:
            anomalies.append(self._anomaly(
                "CRITICAL", "Prix gaz élevé", f"Prix calculé : {unit_price_ht:.4f} €/kWh."
            ))
        if unit_price_ht <= 0 and amount_ht > 0 and volume_kwh > 0:
            anomalies.append(self._anomaly("LOW", "Prix unitaire nul", "Le prix unitaire calculé est nul ou non interprétable."))

        # 4. Pénalités
        if penalties > 0:
            anomalies.append(self._anomaly(
                "MEDIUM",
                "Pénalités",
                f"{round(penalties, 2)} € de pénalités/dépassements détectés.",
            ))

        # 5. Structure de coût
        if amount_ht > 0:
            if (taxes_amount / amount_ht) > 0.35:
                anomalies.append(self._anomaly(
                    "MEDIUM", "Taxes élevées", f"Taxes = {round((taxes_amount / amount_ht) * 100)}% du HT."
                ))
            if energy_type == "electricity" and (network_amount / amount_ht) > 0.50:
                anomalies.append(self._anomaly(
                    "MEDIUM", "TURPE élevé", f"Acheminement = {round((network_amount / amount_ht) * 100)}% du HT."
                ))
            if (subscription_amount / amount_ht) > 0.45 and volume_kwh > 0:
                anomalies.append(self._anomaly(
                    "MEDIUM", "Abonnement élevé", f"Part fixe = {round((subscription_amount / amount_ht) * 100)}% du HT."
                ))

        # 6. Bouclier fiscal / accise réduite
        naf = str(site_data.get("identity", {}).get("naf", "0000"))
        annual_vol_mwh = float(site_data.get("kpis", {}).get("volume_mwh", 0) or 0)
        if naf.startswith(("1", "2", "3", "4", "6")) and annual_vol_mwh > 250:
            if amount_ht > 0 and taxes_amount > (amount_ht * 0.15):
                gain_3_ans = round((annual_vol_mwh * 15.0) * 3)
                anomalies.append(self._anomaly(
                    "TAX_SHIELD",
                    "Bouclier Fiscal",
                    f"NAF {naf} potentiellement éligible taux réduit. Gain estimé: {gain_3_ans} € sur 3 ans.",
                    {"estimated_gain_3y_eur": gain_3_ans}
                ))

        trust_score, field_scores = self._compute_trust_score(inv, anomalies)
        bap_status = "APPROVED" if trust_score >= 90 else ("REVIEW" if trust_score >= 70 else "QUARANTINE")
        recommendations = self._build_recommendations(inv, anomalies, trust_score)

        return {
            "audit_date": datetime.now().isoformat(),
            "status": "CONFORME" if trust_score >= 90 else "ANOMALIE",
            "trust_score": trust_score,
            "bap_status": bap_status,
            "financials": {
                "amount_ttc": round(amount_ttc, 2),
                "amount_ht": round(amount_ht, 2),
                "tax_amount": round(taxes_amount, 2),
                "subscription_amount": round(subscription_amount, 2),
                "network_amount": round(network_amount, 2),
                "penalty_amount": round(penalties, 2),
                "ghost_savings": round(penalties, 2),
                "unit_price_computed": round(unit_price_ht, 6),
                "unit_price_eur_mwh": round(unit_price_ht * 1000, 2) if unit_price_ht > 0 else 0.0,
                "volume_factured": round(volume_kwh, 2),
                "consumption_blocks": inv.get("consumption_blocks", {}),
                "cost_breakdown": inv.get("cost_breakdown", {}),
            },
            "technical": {
                "source": inv.get("source"),
                "filename": inv.get("filename"),
                "document_hash": inv.get("document_hash"),
                "energy_type": inv.get("energy_type"),
                "provider": inv.get("provider"),
                "pdl_detected": inv.get("pdl"),
                "pce_detected": inv.get("pce"),
                "invoice_number": inv.get("invoice_number"),
                "invoice_date": inv.get("invoice_date"),
                "period_start": inv.get("period_start"),
                "period_end": inv.get("period_end"),
                "power_subscribed": inv.get("power_subscribed"),
                "pcs": inv.get("pcs"),
                "trust_fields": field_scores,
                "volume_sge": round(float(sge_real_kwh or 0), 2),
            },
            "anomalies": anomalies,
            "recommendations": recommendations,
            "normalized_output": inv.get("normalized_output", {}),
        }

    def simulate_ebitda(self, ca_k_eur: float, marge_pct: float, gains_eur: float, multiple: float) -> Dict[str, Any]:
        try:
            ca_reel = float(ca_k_eur) * 1000
            marge_decimal = float(marge_pct) / 100.0
            gains_eur = float(gains_eur)
            multiple = float(multiple)

            val_creation = gains_eur * multiple
            nouvelle_marge = (((ca_reel * marge_decimal) + gains_eur) / ca_reel) * 100 if ca_reel > 0 else 0.0
            equivalent_ca = (gains_eur / marge_decimal) if marge_decimal > 0 else 0.0

            return {
                "status": "SUCCESS",
                "val_creation_eur": round(val_creation, 2),
                "nouvelle_marge_pct": round(nouvelle_marge, 2),
                "equivalent_ca_eur": round(equivalent_ca, 2),
            }
        except Exception as exc:
            self.logger.error("Erreur simulation EBITDA : %s", exc)
            return {"status": "ERROR", "message": str(exc)}

    def simulate_landing(self, site_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            year = int(site_data.get("year") or datetime.now().year)
            kpis = site_data.get("kpis", {}) or {}
            contract = site_data.get("contract", {}) or {}
            settings = site_data.get("settings", {}) or {}

            annual_mwh = float(kpis.get("volume_mwh") or 0.0)
            annual_kwh = float(kpis.get("volume_kwh") or 0.0)
            if annual_mwh <= 0 and annual_kwh > 0:
                annual_mwh = annual_kwh / 1000.0

            current_price_eur_mwh = float(
                contract.get("price_eur_mwh")
                or contract.get("px_hedged")
                or contract.get("unit_price_eur_mwh")
                or 0.0
            )
            market_price_eur_mwh = float(
                settings.get("market_price_eur_mwh")
                or kpis.get("market_price_eur_mwh")
                or current_price_eur_mwh
                or 0.0
            )
            subscription_eur = float(contract.get("subscription_eur") or contract.get("fixed_cost_eur") or 0.0)
            network_eur = float(contract.get("network_eur") or 0.0)
            taxes_eur = float(contract.get("taxes_eur") or 0.0)
            savings_target_pct = float(settings.get("savings_target_pct") or 0.0)

            energy_cost_eur = annual_mwh * current_price_eur_mwh
            baseline_total_eur = energy_cost_eur + subscription_eur + network_eur + taxes_eur
            market_reference_eur = (annual_mwh * market_price_eur_mwh) + subscription_eur + network_eur + taxes_eur
            potential_savings_eur = max(baseline_total_eur - market_reference_eur, 0.0)
            optimized_landing_eur = baseline_total_eur * (1 - savings_target_pct / 100.0)

            monthly_run_rate_eur = baseline_total_eur / 12.0 if baseline_total_eur > 0 else 0.0
            optimized_monthly = optimized_landing_eur / 12.0 if optimized_landing_eur > 0 else monthly_run_rate_eur
            
            trajectory = list()
            for month in range(1, 13):
                trajectory.append({
                    "month": month,
                    "baseline_eur": round(monthly_run_rate_eur, 2),
                    "optimized_eur": round(optimized_monthly, 2),
                    "delta_eur": round(monthly_run_rate_eur - optimized_monthly, 2),
                })

            return dict(
                status="SUCCESS",
                year=year,
                landing_euro=round(baseline_total_eur, 2),
                optimized_landing_euro=round(optimized_landing_eur, 2),
                market_reference_euro=round(market_reference_eur, 2),
                potential_savings_euro=round(potential_savings_eur, 2),
                volume_mwh=round(annual_mwh, 3),
                unit_price_eur_mwh=round(current_price_eur_mwh, 2),
                trajectory=trajectory
            )
        except Exception as exc:
            self.logger.error("Erreur simulate_landing : %s", exc)
            return dict(
                status="ERROR",
                message=str(exc),
                year=datetime.now().year,
                landing_euro=0.0,
                trajectory=list()
            )

    def healthcheck(self) -> Dict[str, Any]:
        return {
            "status": "OK",
            "engine": "CortexFinance",
            "pdf_ready": PDF_READY,
            "known_suppliers": len(self.known_suppliers),
            "version": self.VERSION,
        }

    # =========================================================
    # 2. PDF / XML INGESTION
    # =========================================================
    def _parse_pdf_native(self, content: bytes, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            text_parts: List[str] = []
            table_parts: List[str] =[]

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for i, page in enumerate(pdf.pages):
                    if i >= 3:
                        self.logger.warning("Facture longue : scan PDF tronqué aux 3 premières pages.")
                        break

                    txt = page.extract_text() or ""
                    if txt:
                        text_parts.append(txt)

                    try:
                        tables = page.extract_tables() or[]
                        for table in tables:
                            for row in table:
                                clean_row =[str(c).strip() if c is not None else "" for c in row]
                                if any(clean_row):
                                    table_parts.append(" | ".join(clean_row))
                    except Exception:
                        pass

            text = "\n".join(text_parts + table_parts)
            upper = text.upper()

            data["source"] = "PDF_NATIVE"
            data["raw_preview"] = text[:1000] # Limité pour ne pas surcharger Firestore
            data["provider"] = self._detect_supplier(upper)
            data["energy_type"] = self._detect_energy_type(upper)
            data["pdl"] = self._extract_pdl(text)
            data["pce"] = self._extract_pce(text)
            data["invoice_number"] = self._extract_invoice_number(text)
            data["invoice_date"] = self._extract_invoice_date(text)

            period_start, period_end = self._extract_dates_range(text)
            data["period_start"] = period_start
            data["period_end"] = period_end

            data["amount_ttc"] = self._extract_amount_by_keywords(
                text,["total ttc", "montant ttc", "net à payer ttc", "total à payer ttc"]
            ) or 0.0
            data["amount_ht"] = self._extract_amount_by_keywords(
                text,["total ht", "montant ht", "total hors taxes", "net ht"]
            ) or 0.0

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

            data["consumption_blocks"] = self._extract_consumption_blocks(text, data["energy_type"])
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
            upper = full_text.upper()

            data["source"] = "FACTUR-X_XML_2026"
            data["raw_preview"] = full_text[:1000] # Limité pour ne pas surcharger Firestore
            data["provider"] = self._detect_supplier(upper)
            data["energy_type"] = self._detect_energy_type(upper)
            data["pdl"] = self._extract_pdl(full_text)
            data["pce"] = self._extract_pce(full_text)
            data["invoice_number"] = self._extract_invoice_number(full_text)
            data["invoice_date"] = self._extract_invoice_date(full_text)
            data["amount_ht"] = self._extract_first_decimal_after_keywords(
                full_text, ["LineTotalAmount", "TaxBasisTotalAmount"]
            ) or 0.0
            data["amount_ttc"] = self._extract_first_decimal_after_keywords(
                full_text,["GrandTotalAmount", "DuePayableAmount"]
            ) or 0.0
            data["taxes_amount"] = self._extract_first_decimal_after_keywords(
                full_text,["TaxTotalAmount"]
            ) or max((data["amount_ttc"] - data["amount_ht"]), 0.0)
            data["volume_kwh"] = self._extract_volume_kwh(full_text) or 0.0
            data["volume_m3"] = self._extract_volume_m3(full_text)
            data["pcs"] = self._extract_pcs(full_text)

            if data["volume_kwh"] <= 0 and data["volume_m3"] > 0 and data["pcs"]:
                data["volume_kwh"] = round(data["volume_m3"] * data["pcs"], 2)

            period_start, period_end = self._extract_dates_range(full_text)
            data["period_start"] = period_start
            data["period_end"] = period_end
            data["consumption_blocks"] = self._extract_consumption_blocks(full_text, data["energy_type"])
            data["cost_breakdown"] = self._build_cost_breakdown(data)

            return {"status": "SUCCESS", "data": data}
        except Exception as exc:
            return {"status": "ERROR", "message": f"Erreur XML: {str(exc)}"}

    # =========================================================
    # 3. DETECTION / EXTRACTION
    # =========================================================
    def _empty_invoice_payload(self) -> Dict[str, Any]:
        return {
            "source": "UNKNOWN",
            "filename": "",
            "document_hash": "",
            "provider": "INCONNU",
            "energy_type": "unknown",
            "pdl": None,
            "pce": None,
            "invoice_number": None,
            "invoice_date": None,
            "period_start": None,
            "period_end": None,
            "volume_kwh": 0.0,
            "volume_m3": 0.0,
            "pcs": None,
            "amount_ht": 0.0,
            "amount_ttc": 0.0,
            "taxes_amount": 0.0,
            "penalties": 0.0,
            "power_subscribed": 0.0,
            "subscription_amount": 0.0,
            "network_amount": 0.0,
            "consumption_blocks": {},
            "cost_breakdown": {},
            "normalized_output": {},
            "raw_preview": "",
        }

    def _hash_bytes(self, payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def _detect_supplier(self, text_upper: str) -> str:
        for supplier in self.known_suppliers:
            if supplier in text_upper or f" {supplier} " in f" {text_upper} ":
                return supplier
        if "GEG" in text_upper and "GRENOBLE" in text_upper:
            return "GEG"
        return "INCONNU"

    def _detect_energy_type(self, text_upper: str) -> str:
        s_gas = sum(1 for marker in["PCE", "GAZ", "M3", "PCS", "TICGN", "ATRD"] if marker in text_upper)
        s_elec = sum(1 for marker in["PDL", "KVA", "TURPE", "HP", "HC", "TICFE", "CTA"] if marker in text_upper)
        return "gas" if s_gas > s_elec else "electricity"

    def _extract_pdl(self, text: str) -> Optional[str]:
        patterns =[
            r"(?:PDL|POINT DE LIVRAISON|RÉFÉRENCE ACHEMINEMENT|REF ACHEMINEMENT|RÉF EXT|PRM)\s*[:.]?\s*([\d\s]{14,20})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                candidate = re.sub(r"\D", "", match.group(1))
                if len(candidate) >= 14:
                    return candidate[:14]
        return None

    def _extract_pce(self, text: str) -> Optional[str]:
        patterns =[
            r"(?:PCE|POINT DE COMPTAGE)\s*[:.]?\s*([\d\s]{14,20})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                candidate = re.sub(r"\D", "", match.group(1))
                if len(candidate) >= 14:
                    return candidate[:14]
        return None

    def _extract_invoice_number(self, text: str) -> Optional[str]:
        patterns = [
            r"(?:N°\s*DE\s*FACTURE|NUM[ÉE]RO\s*DE\s*FACTURE|FACTURE|INVOICE)\s*[:#]?\s*([A-Z0-9\-_/]{4,})",
            r"(?:RÉFÉRENCE\s*FACTURE|REFERENCE\s*FACTURE)\s*[:#]?\s*([A-Z0-9\-_/]{4,})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _parse_fr_date(self, value: str) -> Optional[datetime]:
        normalized = value.strip().replace(".", "/").replace("-", "/")
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(normalized, fmt)
            except Exception:
                pass
        return None

    def _extract_invoice_date(self, text: str) -> Optional[str]:
        patterns =[]
        for keyword in self.invoice_date_keywords:
            patterns.append(rf"{re.escape(keyword)}\s*[:.]?\s*(\d{{2}}[/.-]\d{{2}}[/.-]\d{{2,4}})")
        patterns.append(r"<IssueDateTime[^>]*>.*?(\d{4}-\d{2}-\d{2}).*?</IssueDateTime>")

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            raw = match.group(1)
            if re.match(r"\d{4}-\d{2}-\d{2}", raw):
                return raw
            parsed = self._parse_fr_date(raw)
            if parsed:
                return parsed.strftime("%Y-%m-%d")
        return None

    def _extract_dates_range(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        dates: List[Tuple[datetime, datetime]] = []
        patterns =[
            r"du\s+(\d{2}[/.-]\d{2}[/.-]\d{2,4})\s+au\s+(\d{2}[/.-]\d{2}[/.-]\d{2,4})",
            r"p[ée]riode\s*[:.]?\s*(\d{2}[/.-]\d{2}[/.-]\d{2,4})\s*(?:au|-|à)\s*(\d{2}[/.-]\d{2}[/.-]\d{2,4})",
            r"consommation\s+du\s+(\d{2}[/.-]\d{2}[/.-]\d{2,4})\s+au\s+(\d{2}[/.-]\d{2}[/.-]\d{2,4})",
        ]

        for pattern in patterns:
            for start_raw, end_raw in re.findall(pattern, text, re.IGNORECASE):
                d_start = self._parse_fr_date(start_raw)
                d_end = self._parse_fr_date(end_raw)
                if d_start and d_end:
                    dates.append((d_start, d_end))

        if not dates:
            return None, None
        return (
            min(pair[0] for pair in dates).strftime("%Y-%m-%d"),
            max(pair[1] for pair in dates).strftime("%Y-%m-%d"),
        )

    def _extract_amount_by_keywords(self, text: str, keywords: List[str]) -> Optional[float]:
        normalized = text.replace("\xa0", " ")
        for keyword in keywords:
            match = re.search(
                rf"{re.escape(keyword)}[^\n\r]{{0,100}}?(-?\d[\d\s.,]+)\s*€",
                normalized,
                re.IGNORECASE,
            )
            if match:
                return self._to_float(match.group(1))
        return None

    def _extract_first_decimal_after_keywords(self, text: str, tags: List[str]) -> Optional[float]:
        for tag in tags:
            match = re.search(rf"<{tag}[^>]*>(-?\d+(?:\.\d+)?)</{tag}>", text, re.IGNORECASE)
            if match:
                return self._to_float(match.group(1))
        return None

    def _extract_volume_kwh(self, text: str) -> Optional[float]:
        values = []
        for raw in re.findall(r"(\d[\d\s.,]+)\s*kwh", text, re.IGNORECASE):
            parsed = self._to_float(raw)
            if parsed and parsed > 50:
                values.append(parsed)
        return max(values) if values else None

    def _extract_volume_m3(self, text: str) -> float:
        values = []
        for raw in re.findall(r"(\d[\d\s.,]+)\s*m3\b", text, re.IGNORECASE):
            parsed = self._to_float(raw)
            if parsed:
                values.append(parsed)
        return max(values) if values else 0.0

    def _extract_pcs(self, text: str) -> Optional[float]:
        match = re.search(r"pcs\s*[:.]?\s*(\d[\d.,]+)", text, re.IGNORECASE)
        return self._to_float(match.group(1)) if match else None

    def _extract_power(self, text: str) -> float:
        patterns = [
            r"(\d[\d.,]+)\s*kva",
            r"puissance\s+souscrite\s*[:.]?\s*(\d[\d.,]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return self._to_float(match.group(1)) or 0.0
        return 0.0

    def _extract_taxes(self, text: str, amount_ht: float, amount_ttc: float) -> float:
        value = self._extract_amount_by_keywords(
            text,["total taxes", "taxes", "tva", "cspe", "ticfe", "ticgn", "cta"]
        )
        if value and value > 0:
            return value
        return round(amount_ttc - amount_ht, 2) if amount_ttc > amount_ht else 0.0

    def _extract_penalties(self, text: str) -> float:
        total = 0.0
        for keyword in self.penalty_keywords:
            total += self._extract_amount_by_keywords(text, [keyword]) or 0.0
        return round(total, 2)

    def _extract_consumption_blocks(self, text: str, energy_type: str) -> Dict[str, Any]:
        if energy_type == "gas":
            return {}

        blocks: Dict[str, Any] = {}
        generic_patterns =[
            r"(HPH|HCH|HPE|HCE|HP|HC|POINTE|BASE)[^\n]*?([\d\s.,]+)\s*kWh[^\n]*?([\d\s.,]+)\s*€",
        ]
        for pattern in generic_patterns:
            for raw_label, raw_volume, raw_cost in re.findall(pattern, text, re.IGNORECASE):
                label = raw_label.upper()
                volume = self._to_float(raw_volume) or 0.0
                cost = self._to_float(raw_cost) or 0.0
                if volume > 0:
                    blocks[label] = {
                        "volume_kwh": round(volume, 2),
                        "cost_ht": round(cost, 2),
                        "pmp_eur_kwh": round(cost / volume, 6) if volume > 0 else 0.0,
                    }

        if blocks:
            return blocks

        for canonical, aliases in self._quadrant_aliases.items():
            for alias in aliases:
                pattern = rf"{re.escape(alias)}[^\n]{{0,80}}?(\d[\d\s.,]+)\s*kWh"
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    volume = self._to_float(match.group(1)) or 0.0
                    if volume > 0:
                        blocks[canonical] = {
                            "volume_kwh": round(volume, 2),
                            "cost_ht": 0.0,
                            "pmp_eur_kwh": 0.0,
                        }
        return blocks

    def _build_cost_breakdown(self, data: Dict[str, Any]) -> Dict[str, Any]:
        ht = float(data.get("amount_ht") or 0.0)
        sub = float(data.get("subscription_amount") or 0.0)
        net = float(data.get("network_amount") or 0.0)
        tax = float(data.get("taxes_amount") or 0.0)
        pen = float(data.get("penalties") or 0.0)
        energy_variable = max(ht - sub - net - pen, 0.0)
        return {
            "subscription": round(sub, 2),
            "network": round(net, 2),
            "energy_variable": round(energy_variable, 2),
            "taxes": round(tax, 2),
            "penalties": round(pen, 2),
        }

    # =========================================================
    # 4. SCORING / RECO / NORMALISATION
    # =========================================================
    def _estimate_sge_volume(self, inv: Dict[str, Any], site: Dict[str, Any]) -> float:
        site_kpis = site.get("kpis", {}) or {}
        site_kwh = float(site_kpis.get("volume_kwh") or 0.0)
        if site_kwh > 0:
            return site_kwh
        return float(inv.get("volume_kwh") or 0.0) * 0.98

    def _compute_trust_score(self, inv: Dict[str, Any], anomalies: List[Dict[str, Any]]) -> Tuple[int, Dict[str, int]]:
        field_scores = {
            "provider": 100 if inv.get("provider") and inv.get("provider") != "INCONNU" else 20,
            "invoice_number": 100 if inv.get("invoice_number") else 15,
            "invoice_date": 100 if inv.get("invoice_date") else 25,
            "period": 100 if inv.get("period_start") and inv.get("period_end") else 20,
            "identifier": 100 if inv.get("pdl") or inv.get("pce") else 20,
            "volume": 100 if float(inv.get("volume_kwh") or 0.0) > 0 else 10,
            "amounts": 100 if float(inv.get("amount_ht") or 0.0) > 0 and float(inv.get("amount_ttc") or 0.0) > 0 else 25,
            "pricing_breakdown": 100 if inv.get("cost_breakdown") else 40,
        }
        
        # 1. Base Score = moyenne des critères de présence
        base_score = int(sum(field_scores.values()) / len(field_scores)) if field_scores else 100
        
        # 2. On soustrait les anomalies
        penalty = 0
        for anomaly in anomalies:
            severity = anomaly.get("severity")
            if severity == "CRITICAL": penalty += 35
            elif severity == "HIGH": penalty += 18
            elif severity == "MEDIUM": penalty += 8
            elif severity == "LOW": penalty += 3

        final_score = max(5, min(100, base_score - penalty))
        return final_score, field_scores

    def _build_recommendations(
        self, inv: Dict[str, Any], anomalies: List[Dict[str, Any]], trust_score: int
    ) -> List[Dict[str, Any]]:
        recommendations: List[Dict[str, Any]] =[]

        if trust_score < 70:
            recommendations.append({
                "priority": "HIGH",
                "type": "DATA_QUALITY",
                "label": "Contrôle manuel recommandé",
                "next_action": "Relire la facture source et compléter les champs manquants.",
            })

        if any(a.get("label") == "Écart volume SGE" for a in anomalies):
            recommendations.append({
                "priority": "HIGH",
                "type": "VOLUME_CHECK",
                "label": "Comparer facture et données distributeur",
                "next_action": "Rapprocher le volume facturé avec le relevé distributeur / télérelève.",
            })

        if any(a.get("label") in {"Prix électricité élevé", "Prix gaz élevé"} for a in anomalies):
            recommendations.append({
                "priority": "HIGH",
                "type": "PRICING_REVIEW",
                "label": "Lancer une revue contractuelle",
                "next_action": "Comparer le prix unitaire à l'offre contractuelle et au benchmark marché.",
            })

        if float(inv.get("penalties") or 0.0) > 0:
            recommendations.append({
                "priority": "MEDIUM",
                "type": "PENALTY_REDUCTION",
                "label": "Réduire les pénalités",
                "next_action": "Analyser dépassements, énergie réactive ou paramètres de puissance.",
            })

        if not recommendations:
            recommendations.append({
                "priority": "LOW",
                "type": "MONITORING",
                "label": "Facture cohérente",
                "next_action": "Archiver et poursuivre le monitoring mensuel.",
            })

        return recommendations

    def _build_normalized_output(self, data: Dict[str, Any]) -> Dict[str, Any]:
        identifier = data.get("pdl") or data.get("pce")
        return {
            "document": {
                "filename": data.get("filename"),
                "hash": data.get("document_hash"),
                "source": data.get("source"),
                "invoice_number": data.get("invoice_number"),
                "invoice_date": data.get("invoice_date"),
            },
            "counterparty": {
                "supplier": data.get("provider"),
                "energy_type": data.get("energy_type"),
            },
            "metering": {
                "identifier": identifier,
                "pdl": data.get("pdl"),
                "pce": data.get("pce"),
                "power_subscribed_kva": data.get("power_subscribed"),
                "pcs": data.get("pcs"),
            },
            "period": {
                "start": data.get("period_start"),
                "end": data.get("period_end"),
            },
            "quantities": {
                "volume_kwh": round(float(data.get("volume_kwh") or 0.0), 2),
                "volume_m3": round(float(data.get("volume_m3") or 0.0), 2),
            },
            "amounts": {
                "amount_ht": round(float(data.get("amount_ht") or 0.0), 2),
                "amount_ttc": round(float(data.get("amount_ttc") or 0.0), 2),
                "taxes_amount": round(float(data.get("taxes_amount") or 0.0), 2),
                "subscription_amount": round(float(data.get("subscription_amount") or 0.0), 2),
                "network_amount": round(float(data.get("network_amount") or 0.0), 2),
                "penalties": round(float(data.get("penalties") or 0.0), 2),
            },
            "pricing": {
                "unit_price_eur_kwh": round(
                    (float(data.get("amount_ht") or 0.0) / float(data.get("volume_kwh") or 1.0)), 6
                ) if float(data.get("volume_kwh") or 0.0) > 0 else 0.0,
                "unit_price_eur_mwh": round(
                    (float(data.get("amount_ht") or 0.0) / float(data.get("volume_kwh") or 1.0)) * 1000, 2
                ) if float(data.get("volume_kwh") or 0.0) > 0 else 0.0,
                "consumption_blocks": data.get("consumption_blocks", {}),
                "cost_breakdown": data.get("cost_breakdown", {}),
            },
        }

    def _anomaly(
        self,
        severity: str,
        label: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {"severity": severity, "label": label, "message": message}
        if metadata:
            payload["metadata"] = metadata
        return payload

    def _to_float(self, value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        normalized = (
            str(value)
            .replace("\xa0", " ")
            .replace("€", "")
            .replace("EUR", "")
            .replace(" ", "")
            .strip()
        )
        if "," in normalized and "." in normalized:
            normalized = (
                normalized.replace(".", "").replace(",", ".")
                if normalized.rfind(",") > normalized.rfind(".")
                else normalized.replace(",", "")
            )
        elif "," in normalized:
            normalized = normalized.replace(",", ".")
        try:
            return float(normalized)
        except Exception:
            return None


finance = CortexFinance()

# --- END OF FILE cortex_finance.py ---
