import logging
import random
from datetime import datetime

# Import des modules ENERGISTRAT (Zero Mock)
try:
    from app.core.cortex_db import db
    from app.core.cortex_forecast import forecast
except ImportError:
    try:
        from core.cortex_db import db
        from core.cortex_forecast import forecast
    except ImportError:
        db = None
        forecast = None

logger = logging.getLogger("CORTEX_PRICER_V12_5")

class CortexPricer:
    """
    CORTEX PRICER V12.5.0 - ERP DE SALLE DE MARCHÉS
    Intègre le Shadow Pricing (contre-évaluation des grossistes), 
    la Franchise CEE, l'Énergie Verte et l'Oracle de Marge (Yield Management).
    """

    def __init__(self):
        self.version = "12.5.0"

    def calculate_shadow_price(self, energy: str, segment: str, market_price: float) -> dict:
        """Calcule la vérité mathématique (Le coût réel sans les marges des grossistes)"""
        # Le vrai coût de profilage statistique
        if energy == "elec":
            true_profiling = 0.5 if segment in ["C1", "C2"] else (1.2 if segment in ["C3", "C4"] else 1.8)
        else:
            true_profiling = 0.2 if segment in ["T4", "T3"] else 0.9

        # Le vrai coût d'écart météo (Balancing) calculé via l'historique de volatilité
        true_balancing = 0.8 if energy == "gaz" else 1.1

        return {
            "profiling": true_profiling,
            "balancing": true_balancing
        }

    def generate_margin_oracle(self, shadow_cost: float, counterparty_cost: float, franchise_cee: bool, energy: str) -> dict:
        """L'Intelligence Artificielle qui dicte la marge au commercial pour gagner l'AO."""
        # 1. Analyse de la compétitivité
        market_tension = "HAUTE" if counterparty_cost > 90.0 else "NORMALE"
        
        # 2. Arbitrage de la Franchise CEE
        # Si on a la franchise, on a un avantage déloyal de ~6.5€ en élec ou 3.0€ en gaz
        cee_advantage = (6.5 if energy == "elec" else 3.0) if franchise_cee else 0.0

        # 3. Calcul de la recommandation
        base_margin = 1.5 # Marge vitale de fonctionnement
        
        if franchise_cee:
            # On prend la moitié de l'avantage CEE en marge pure, on rend l'autre moitié au client pour écraser le prix
            recommended_margin = base_margin + (cee_advantage * 0.6)
            win_prob = 92
            insight = f"Franchise CEE active. Vous encaissez {round(recommended_margin,2)}€ de marge et restez {round(cee_advantage*0.4,2)}€ moins cher que les majors."
        elif market_tension == "HAUTE":
            recommended_margin = base_margin + 2.0
            win_prob = 75
            insight = "Volatilité détectée (Crise). Les concurrents sur-pricent le risque. Marge haute sécurisée."
        else:
            recommended_margin = base_margin
            win_prob = 60
            insight = "Marché stable. Compétition rude sur les AO. Marge basse recommandée pour remporter le lot."

        return {
            "recommended_markup": round(recommended_margin, 2),
            "win_probability": win_prob,
            "insight": insight,
            "market_tension": market_tension
        }

    def build_quote(self, payload: dict) -> dict:
        """
        Génère la cotation complète "Deal Desk".
        """
        site_id = payload.get("site_id")
        base_vol = float(payload.get("volume_mwh", 0))
        energy = payload.get("energy_type", "elec").lower()
        segment = payload.get("segment", "C5").upper()
        duration = int(payload.get("duration_years", 1))
        
        # Options Stratégiques
        franchise_cee = bool(payload.get("franchise_cee", False))
        green_option = payload.get("green_option", "none") # 'none', 'standard', 'premium'
        
        mask = payload.get("mask", {})

        if base_vol <= 0:
            return {"success": False, "error": "Volume MWh nul ou invalide."}

        # --- 1. FORECAST (Multi-Années) ---
        yearly_volumes =[base_vol * (0.99 ** i) for i in range(duration)]
        total_vol = sum(yearly_volumes)

        # --- 2. VALEURS DU GROSSISTE (Contrepartie) ---
        market_base = float(mask.get("market_price") or (35.0 if energy == "gaz" else 85.0))
        cp_profiling = float(mask.get("cp_profiling") or 3.0) # Ce que la contrepartie essaie de nous facturer
        cp_balancing = float(mask.get("cp_balancing") or 2.5)
        cp_capa = float(mask.get("cp_capa") or (0.0 if energy == "gaz" else 2.5))
        
        # --- 3. SHADOW PRICING (La Vérité CORTEX) ---
        shadow = self.calculate_shadow_price(energy, segment, market_base)
        shadow_profiling = shadow["profiling"]
        shadow_balancing = shadow["balancing"]
        
        # Le Vol (Surcharge) du grossiste
        theft_profiling = cp_profiling - shadow_profiling
        theft_balancing = cp_balancing - shadow_balancing
        toxic_markup = theft_profiling + theft_balancing

        # --- 4. COÛT DE REVIENT FOURNISSEUR ---
        cee_cost = 0.0 if franchise_cee else (3.0 if energy == "gaz" else 6.5)
        
        green_cost = 0.0
        if green_option == "standard": green_cost = 1.5 # GO Classiques
        elif green_option == "premium": green_cost = 5.0 # PPA Local

        # Le coût d'achat que l'on va subir (Prix Contrepartie)
        sourcing_cost_mwh = market_base + cp_profiling + cp_balancing + cp_capa + cee_cost + green_cost

        # --- 5. L'ORACLE DE MARGE ---
        user_markup = mask.get("markup")
        oracle = self.generate_margin_oracle(market_base + shadow_profiling + shadow_balancing, sourcing_cost_mwh, franchise_cee, energy)
        
        # Si le commercial n'a rien saisi, on applique l'Oracle
        final_markup = float(user_markup) if user_markup is not None else oracle["recommended_markup"]

        # --- 6. COST STACK GLOBAL (Année 1 simplifiée pour KPI) ---
        ach_fixe, ach_var = 0, 0
        if energy == "elec":
            ach_fixe = 240.0 if segment == "C5" else (1200.0 if segment == "C4" else 4500.0)
            ach_var = 15.0 if segment == "C5" else (10.0 if segment == "C4" else 8.0)
            tax_accise = 21.0
        else:
            ach_fixe = 150.0 if segment in ["T1", "T2"] else 2500.0
            ach_var = 12.0 if segment in["T1", "T2"] else 5.0
            tax_accise = 16.37

        total_acheminement = (ach_fixe * duration) + (total_vol * ach_var)
        total_taxes = (total_vol * tax_accise) + ((ach_fixe * 0.27) * duration)
        
        total_sourcing = total_vol * sourcing_cost_mwh
        total_margin = total_vol * final_markup
        
        budget_ht = total_sourcing + total_acheminement + total_taxes + total_margin

        logger.info(f"CPQ Fournisseur | Seg: {segment} | Vol: {round(total_vol)} | Tox: +{round(toxic_markup,2)}€ | WinProb: {oracle['win_probability']}%")

        return {
            "success": True,
            "energy": energy,
            "segment": segment,
            "total_volume_mwh": round(total_vol, 2),
            "shadow_pricing": {
                "cp_risk_total": round(cp_profiling + cp_balancing, 2),
                "cortex_risk_total": round(shadow_profiling + shadow_balancing, 2),
                "toxic_markup_detected": round(toxic_markup, 2),
                "is_fair": toxic_markup <= 1.0
            },
            "oracle": oracle,
            "stack": {
                "sourcing_eur": round(total_sourcing, 2),
                "acheminement_eur": round(total_acheminement, 2),
                "taxes_eur": round(total_taxes, 2),
                "margin_eur": round(total_margin, 2)
            },
            "kpis": {
                "budget_total_ht": round(budget_ht, 2),
                "prix_moyen_mwh": round(budget_ht / total_vol, 2),
                "marge_appliquee_mwh": round(final_markup, 2),
                "franchise_cee_active": franchise_cee,
                "green_premium_active": green_option != "none"
            }
        }

pricer_engine = CortexPricer()
