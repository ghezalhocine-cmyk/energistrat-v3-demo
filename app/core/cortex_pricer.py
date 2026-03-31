# --- START OF FILE cortex_pricer.py ---
import logging
import math

logger = logging.getLogger("CORTEX_PRICER_V12_8")

class CortexPricer:
    """
    CORTEX PRICER V12.8 - ERP DE SALLE DE MARCHÉS
    Cost Stack complet : Molécule, Capa, CEE, GO, TURPE, Taxes, Marge.
    """
    def __init__(self):
        self.version = "12.8.0"

    def calculate_shadow_price(self, energy: str, segment: str, market_price: float) -> dict:
        """Calcule le risque réel de profilage et d'équilibrage"""
        if energy == "elec":
            true_profiling = 0.5 if segment in ["C1", "C2"] else (1.5 if segment in ["C3", "C4"] else 2.5)
            true_balancing = 1.0
            true_capa = 2.5 if segment in ["C4", "C5"] else 1.8
        else:
            true_profiling = 0.2 if segment in["T4", "T3"] else 1.0
            true_balancing = 0.8
            true_capa = 0.0 # Pas de marché de capacité en gaz

        return { "profiling": true_profiling, "balancing": true_balancing, "capa": true_capa }

    def generate_margin_oracle(self, base_cost: float, franchise_cee: bool) -> dict:
        """L'IA qui dicte la marge au commercial (Yield Management)"""
        market_tension = "HAUTE" if base_cost > 90.0 else "NORMALE"
        base_margin = 1.5 # Marge vitale
        
        if franchise_cee:
            recommended_margin = base_margin + 3.0 # On capte une partie de l'avantage CEE
            win_prob = 92
            insight = "Franchise CEE active. Avantage déloyal détecté. Vous encaissez 3€ de sur-marge tout en restant moins cher que les concurrents."
        elif market_tension == "HAUTE":
            recommended_margin = base_margin + 1.5
            win_prob = 75
            insight = "Marché volatil. Les concurrents sur-pricent le risque. Marge haute sécurisée."
        else:
            recommended_margin = base_margin
            win_prob = 65
            insight = "Marché stable. Compétition rude. Marge standard recommandée pour remporter l'AO."

        return { "recommended_markup": round(recommended_margin, 2), "win_probability": win_prob, "insight": insight }

    def build_quote(self, payload: dict) -> dict:
        """Génère la cotation complète Deal Desk"""
        base_vol = float(payload.get("volume_mwh", 0))
        energy = payload.get("energy_type", "elec").lower()
        segment = payload.get("segment", "C5").upper()
        duration = int(payload.get("duration_years", 1))
        franchise_cee = bool(payload.get("franchise_cee", False))
        green_option = payload.get("green_option", "none")
        mask = payload.get("mask", {})

        if base_vol <= 0: return {"success": False, "error": "Volume MWh nul."}

        # 1. Volume total sur la période (avec -1% usure/an)
        yearly_volumes =[base_vol * (0.99 ** i) for i in range(duration)]
        total_vol = sum(yearly_volumes)

        # 2. Valeurs de marché (Sourcing)
        market_base = float(mask.get("market_price") or (35.0 if energy == "gaz" else 80.0))
        
        # 3. Shadow Pricing (Contre-évaluation CORTEX)
        shadow = self.calculate_shadow_price(energy, segment, market_base)
        cp_profiling = float(mask.get("cp_profiling") or (shadow["profiling"] + 0.5))
        cp_balancing = float(mask.get("cp_balancing") or (shadow["balancing"] + 0.2))
        cp_capa = float(mask.get("cp_capa") or (shadow["capa"] + 0.3))

        toxic_markup = (cp_profiling - shadow["profiling"]) + (cp_balancing - shadow["balancing"])

        # 4. Certificats & Verdissement
        cee_cost = 0.0 if franchise_cee else (3.0 if energy == "gaz" else 5.5)
        green_cost = 0.0
        if green_option == "standard": green_cost = 1.5 # GO classiques
        elif green_option == "premium": green_cost = 4.5 # PPA local / Biogaz

        # 5. Oracle de Marge
        oracle = self.generate_margin_oracle(market_base + cp_profiling, franchise_cee)
        user_markup = mask.get("markup")
        final_markup = float(user_markup) if user_markup is not None else oracle["recommended_markup"]

        # 6. Cost Stack Global (Ventilation pure)
        cost_molecule = total_vol * (market_base + cp_profiling + cp_balancing)
        cost_capa = total_vol * cp_capa
        cost_cee = total_vol * cee_cost
        cost_go = total_vol * green_cost
        
        # Réseaux & Taxes (Variables réalistes)
        if energy == "elec":
            cost_network = total_vol * (14.5 if segment in ["C4", "C5"] else 9.0)
            cost_taxes = total_vol * 22.5 # TICFE Standard (Hors Bouclier Fiscal)
        else:
            cost_network = total_vol * (8.5 if segment in ["T3", "T4"] else 4.0)
            cost_taxes = total_vol * 16.37 # TICGN

        total_margin = total_vol * final_markup
        budget_ht = cost_molecule + cost_capa + cost_cee + cost_go + cost_network + cost_taxes + total_margin

        return {
            "success": True,
            "energy": energy,
            "total_volume_mwh": round(total_vol, 2),
            "shadow_pricing": {
                "toxic_markup_detected": round(toxic_markup, 2),
                "is_fair": toxic_markup <= 1.0
            },
            "oracle": oracle,
            "stack": {
                "molecule_eur": round(cost_molecule, 2),
                "capacite_eur": round(cost_capa, 2),
                "cee_eur": round(cost_cee, 2),
                "go_eur": round(cost_go, 2),
                "acheminement_eur": round(cost_network, 2),
                "taxes_eur": round(cost_taxes, 2),
                "margin_eur": round(total_margin, 2)
            },
            "kpis": {
                "budget_total_ht": round(budget_ht, 2),
                "prix_moyen_mwh": round(budget_ht / total_vol, 2),
                "marge_appliquee_mwh": round(final_markup, 2)
            }
        }

pricer_engine = CortexPricer()
# --- END OF FILE cortex_pricer.py ---
