# --- START OF FILE cortex_ppa.py ---
import logging

class CortexPPA:
    """
    CORTEX PPA ENGINE V2.0 (Corporate Power Purchase Agreement)
    Moteur de simulation financière avancée : Arbitrage HP, Sleeving, Surplus, GOs.
    """
    def __init__(self):
        self.logger = logging.getLogger("CortexPPA")
        
        # Hypothèses de marché (Paramètres modifiables selon conjoncture)
        self.SLEEVING_FEE = 3.5  # €/MWh (Frais du fournisseur pour l'équilibrage/transport)
        self.GO_VALUE = 2.0      # €/MWh (Valeur de revente des Garanties d'Origine Vertes)
        self.SPOT_DISCOUNT = 45.0 # €/MWh (Prix de revente moyen du surplus le week-end)

    def simulate_ppa(self, site_data: dict, coverage_pct: float, strike_price: float) -> dict:
        try:
            # 1. EXTRACTION ROBUSTE DE LA DATA 3D
            kpis = site_data.get('kpis', {})
            pricing = site_data.get('pricing', {})
            
            vol_mwh = float(kpis.get('volume_mwh') or site_data.get('volume_mwh') or 0)
            if vol_mwh == 0: 
                return {"error": "Le volume du site est nul. Simulation impossible."}

            pmc = float(kpis.get('pmc') or 0)
            if pmc <= 0 or pmc > 1000:
                px = float(pricing.get('price_kwh') or pricing.get('hph') or 0.18)
                pmc = (px / 1000 if px > 2 else px) * 1000
                if pmc <= 0 or pmc > 1000: pmc = 180 # Fallback Sécurité

            # 2. MÉCANIQUE DU PPA (LE "CITRON" FINANCIER)
            ppa_vol = vol_mwh * (coverage_pct / 100.0)
            market_vol = vol_mwh - ppa_vol

            # A. Matching Solaire (L'énergie solaire efface les Heures Pleines, plus chères)
            # On simule que le PMC effacé valait 15% plus cher que la moyenne lissée.
            avoided_cost_mwh = pmc * 1.15 
            
            # B. Surplus (Inadéquation de charge : ex. Dimanche d'Août)
            # On estime que 10% du PPA n'est pas consommé et est revendu sur le marché Spot
            surplus_vol = ppa_vol * 0.10
            surplus_revenue = surplus_vol * self.SPOT_DISCOUNT
            
            # C. Garanties d'Origine (GO)
            # Revente des certificats verts générés par le PPA
            go_revenue = ppa_vol * self.GO_VALUE

            # D. Frais de Sleeving (Structuration du contrat par un tiers)
            sleeving_cost = ppa_vol * self.SLEEVING_FEE

            # 3. CALCULS P&L (PROFIT & LOSS)
            cost_ppa = ppa_vol * strike_price
            cost_market = market_vol * pmc

            # Nouveau Budget = (Achats + Frais) - (Revenus Annexes)
            new_budget = (cost_ppa + cost_market + sleeving_cost) - (surplus_revenue + go_revenue)
            old_budget = vol_mwh * pmc

            annual_savings = old_budget - new_budget
            blended_price = new_budget / vol_mwh if vol_mwh > 0 else pmc

            return {
                "success": True,
                "financials": {
                    "old_budget_eur": round(old_budget),
                    "new_budget_eur": round(new_budget),
                    "annual_savings_eur": round(annual_savings),
                    "ten_year_savings_eur": round(annual_savings * 10),
                    "blended_price_eur_mwh": round(blended_price, 2),
                    "current_pmc": round(pmc, 2)
                },
                "value_creation": {
                    "energy_arbitrage_eur": round((avoided_cost_mwh - strike_price) * (ppa_vol - surplus_vol)),
                    "surplus_resale_eur": round(surplus_revenue),
                    "go_resale_eur": round(go_revenue),
                    "sleeving_cost_eur": -round(sleeving_cost)
                },
                "technical": {
                    "total_vol_mwh": round(vol_mwh),
                    "ppa_vol_mwh": round(ppa_vol),
                    "surplus_vol_mwh": round(surplus_vol)
                }
            }

        except Exception as e:
            self.logger.error(f"Erreur moteur CORTEX PPA: {e}")
            return {"error": str(e)}

ppa_engine = CortexPPA()
# --- END OF FILE cortex_ppa.py ---
