import math
from datetime import datetime

class CortexMarket:
    """
    CORTEX MARKET ENGINE V10 (ZÉRO MOCK - DÉTERMINISTE)
    Responsable de la valorisation financière des stratégies d'achat (Bloc, Spot, ARENH).
    Génère une 'Duck Curve' mathématique basée sur le vrai prix de référence.
    """

    def __init__(self):
        # En production, ce prix sera écrasé par la base de données (Data Unity)
        self.BASE_CAL_N1 = 85.0  

        # Profil horaire déterministe (Duck Curve typique de la plaque européenne)
        # Ratios par rapport au prix de base (BASE_CAL_N1)
        self.HOURLY_PROFILE = [
            0.75, 0.70, 0.65, 0.65, 0.70, 0.85, # 0h-5h : Nuit (Baisse demande, nucléaire/éolien fort)
            1.10, 1.35, 1.40, 1.20, 0.90, 0.60, # 6h-11h : Pic Matin puis début production Solaire
            0.40, 0.30, 0.35, 0.50, 0.80, 1.20, # 12h-17h : Creux Solaire (Le ventre du canard)
            1.50, 1.70, 1.65, 1.30, 1.00, 0.85  # 18h-23h : Pic Soirée (Chauffage/Éclairage + Baisse Solaire)
        ]

    def get_spot_prices_24h(self, base_price=None):
        """
        Génère une courbe Spot déterministe sur 24h. Zéro hasard.
        """
        ref_price = base_price if base_price else self.BASE_CAL_N1
        
        prices = []
        for h in range(24):
            # Application du ratio horaire au prix de base
            price = ref_price * self.HOURLY_PROFILE[h]
            prices.append(round(price, 2))
            
        return prices

    def valoriser_strategie(self, load_curve_kw, puissance_bloc_kw=0, base_price=None):
        """
        Calcule le coût exact de la stratégie d'approvisionnement (Bloc + Spot).
        Input: 
            - load_curve_kw : Liste de 24 points de puissance (kW)
            - puissance_bloc_kw : Hauteur du ruban acheté à prix fixe (kW)
        """
        ref_price = base_price if base_price else self.BASE_CAL_N1
        spot_prices = self.get_spot_prices_24h(ref_price)
        
        cout_total_spot = 0
        cout_total_bloc = 0
        cout_total_mix = 0
        details = []

        for h in range(24):
            conso_kw = load_curve_kw[h] if h < len(load_curve_kw) else 0
            
            # 1. Scénario 100% Spot (Exposition totale)
            cout_h_spot = (conso_kw / 1000) * spot_prices[h] # MWh * €/MWh
            cout_total_spot += cout_h_spot
            
            # 2. Scénario Couverture (Bloc) + Dentelle (Spot)
            # Partie couverte par le bloc
            vol_bloc = min(conso_kw, puissance_bloc_kw)
            vol_spot = max(0, conso_kw - puissance_bloc_kw)
            
            # Si on consomme MOINS que le bloc, on revend le surplus au Spot (Gain)
            vol_trop_percu = max(0, puissance_bloc_kw - conso_kw)
            
            cout_partie_bloc = (puissance_bloc_kw / 1000) * ref_price
            cout_partie_spot = (vol_spot / 1000) * spot_prices[h]
            gain_revente = (vol_trop_percu / 1000) * spot_prices[h]
            
            cout_h_mix = cout_partie_bloc + cout_partie_spot - gain_revente
            cout_total_mix += cout_h_mix

            details.append({
                "heure": f"{h:02d}:00",
                "conso_kw": round(conso_kw, 1),
                "prix_spot": spot_prices[h],
                "cout_mix": round(cout_h_mix, 2)
            })

        return {
            "base_price_ref": ref_price,
            "spot_avg": round(sum(spot_prices)/24, 2),
            "cout_100_spot": round(cout_total_spot, 2),
            "cout_mix_bloc_spot": round(cout_total_mix, 2),
            "gain_strategie": round(cout_total_spot - cout_total_mix, 2),
            "details_horaires": details,
            "prices_curve": spot_prices
        }

market = CortexMarket()
