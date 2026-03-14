import logging

logger = logging.getLogger("CORTEX_PRICER_V12")

class CortexPricer:
    """
    CORTEX PRICER V12.4 - MOTEUR CPQ (Cost Stack)
    Architecture Isolée et Résiliente. Calcule le prix final (C1 à C5)
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
        # 1. LE MASQUE DE RÉSILIENCE (Variables)
        # ==========================================
        # Si l'utilisateur a rempli le masque, on prend sa valeur. Sinon on met une valeur par défaut du marché.
        market_price = float(mask.get("market_price") or 85.0)
        cee_price = float(mask.get("cee_price") or (6.5 if energy == "elec" else 3.0))
        capa_price = float(mask.get("capa_price") or (2.5 if energy == "elec" else 0.0))
        balancing = float(mask.get("balancing") or 1.5)
        profiling = float(mask.get("profiling") or 2.0)
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
        # En C1-C4, l'abonnement est lourd. En C5, c'est le KWh acheminé qui pèse.
        turpe_fixe = 240.0 if segment == "C5" else 1200.0
        turpe_var = vol * (15.0 if segment == "C5" else 10.0)
        acheminement_total = turpe_fixe + turpe_var

        # D. Les Taxes (CSPE/TICFE et CTA)
        tax_cspe = vol * 21.0 if energy == "elec" else vol * 16.37
        tax_cta = turpe_fixe * 0.27
        taxes_totales = tax_cspe + tax_cta

        # ==========================================
        # 3. RÉSULTAT FINAL
        # ==========================================
        budget_ht = fourniture_totale + margin_totale + acheminement_total + taxes_totales
        
        logger.info(f"Cotation générée : Segment {segment} | Vol: {vol} | Prix: {round(budget_ht/vol, 2)} €/MWh")

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
