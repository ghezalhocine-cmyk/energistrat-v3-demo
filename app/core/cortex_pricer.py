import logging

logger = logging.getLogger("CORTEX_PRICER_V12")

class CortexPricer:
    """
    CORTEX PRICER V12.4 - MOTEUR CPQ (Cost Stack)
    Architecture Isolée. Calcule le prix final (C1 à C5)
    en priorisant le "Masque Manuel" (Override) du commercial.
    """

    def __init__(self):
        self.version = "12.4.0"

    def build_quote(self, payload: dict) -> dict:
        """
        Génère la cotation (Cost Stack) complète.
        payload = { "volume_mwh": 150, "energy_type": "elec", "segment": "C5", "mask": {...} }
        """
        vol = float(payload.get("volume_mwh", 0))
        if vol <= 0:
            return {"success": False, "error": "Le volume doit être supérieur à 0."}

        mask = payload.get("mask", {})
        energy = payload.get("energy_type", "elec").lower()
        segment = payload.get("segment", "C5").upper()

        # ==========================================
        # 1. LE MASQUE DE RÉSILIENCE (Variables Override)
        # ==========================================
        # On lit le masque. Si vide, valeurs par défaut du marché du jour.
        market_price = float(mask.get("market_price") or (35.0 if energy == "gaz" else 85.0))
        cee_price = float(mask.get("cee_price") or (3.0 if energy == "gaz" else 6.5))
        capa_price = float(mask.get("capa_price") or (0.0 if energy == "gaz" else 2.5))
        profiling = float(mask.get("profiling") or (1.0 if energy == "gaz" else 2.0))
        balancing = float(mask.get("balancing") or 1.5)
        markup = float(mask.get("markup") or 2.0) # Marge ENERGISTRAT

        # ==========================================
        # 2. L'EMPILEMENT TARIFAIRE (Cost Stack)
        # ==========================================
        
        # A. La Fourniture (Marché de Gros)
        cost_molecule = vol * market_price
        cost_cee = vol * cee_price
        cost_capa = vol * capa_price
        cost_risk = vol * (balancing + profiling)
        
        fourniture_totale = cost_molecule + cost_cee + cost_capa + cost_risk
        
        # B. La Marge (Mark-up ENERGISTRAT)
        margin_totale = vol * markup
        
        # C. L'Acheminement (Estimation TURPE / ATRD)
        # Différenciation massive entre Profilé (C5) et Courbe de charge (C4-C1)
        if segment == "C5":
            acheminement_fixe = 240.0
            acheminement_var = vol * (15.0 if energy == "elec" else 12.0)
        else:
            acheminement_fixe = 1200.0 if segment == "C4" else 4500.0
            acheminement_var = vol * (10.0 if energy == "elec" else 8.0)
            
        acheminement_total = acheminement_fixe + acheminement_var

        # D. Les Taxes (CSPE/TICFE, TICGN et CTA)
        tax_accise = vol * (21.0 if energy == "elec" else 16.37) # CSPE ou TICGN
        tax_cta = acheminement_fixe * 0.27
        taxes_totales = tax_accise + tax_cta

        # ==========================================
        # 3. RÉSULTAT FINAL
        # ==========================================
        budget_ht = fourniture_totale + margin_totale + acheminement_total + taxes_totales
        
        logger.info(f"Cotation CPQ : Segment {segment} | Énergie: {energy} | Vol: {vol} | Prix: {round(budget_ht/vol, 2)} €/MWh")

        return {
            "success": True,
            "volume_mwh": vol,
            "segment": segment,
            "energy": energy,
            "stack": {
                "molecule_eur": round(cost_molecule, 2),
                "cee_eur": round(cost_cee, 2),
                "capa_eur": round(cost_capa, 2),
                "risks_eur": round(cost_risk, 2),
                "acheminement_eur": round(acheminement_total, 2),
                "taxes_eur": round(taxes_totales, 2),
                "margin_eur": round(margin_totale, 2)
            },
            "kpis": {
                "budget_annuel_ht": round(budget_ht, 2),
                "prix_moyen_mwh": round(budget_ht / vol, 2),
                "marge_commerciale": round(margin_totale, 2)
            }
        }

pricer_engine = CortexPricer()
