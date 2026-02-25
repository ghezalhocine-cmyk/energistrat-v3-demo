import random
import math
from datetime import datetime

class CortexMarket:
    """
    CORTEX MARKET ENGINE
    Responsable de la valorisation financière et de la simulation EEX.
    Gère les stratégies d'achat (Bloc, Spot, Clicks).
    """

    def __init__(self):
        # Prix de référence (à connecter plus tard à l'API EEX)
        self.BASE_CAL_N1 = 85.0  # Prix du ruban annuel (Calendar)
        self.PEAK_CAL_N1 = 110.0 # Prix des heures de pointe (8h-20h)

    def get_spot_prices_24h(self):
        """
        Génère une courbe de prix Spot réaliste pour 24h (Profil "Duck Curve").
        """
        prices = []
        for h in range(24):
            # Base nocturne (nucléaire/éolien)
            price = 40.0 + random.uniform(-5, 5)
            
            # Pic du matin (7h-10h)
            if 7 <= h <= 10: price += 60.0 + random.uniform(0, 20)
            
            # Creux solaire (11h-15h)
            if 11 <= h <= 15: price -= 10.0 # Impact PV
            
            # Pic du soir (18h-21h)
            if 18 <= h <= 21: price += 80.0 + random.uniform(10, 30)
            
            prices.append(round(price, 2))
        return prices

    def valoriser_strategie(self, load_curve_kw, puissance_bloc_kw=0):
        """
        Calcule le coût selon la stratégie Bloc + Spot.
        Input: 
            - load_curve_kw : Liste de 24 points de puissance moyenne (kW)
            - puissance_bloc_kw : Hauteur du ruban acheté à prix fixe (kW)
        """
        spot_prices = self.get_spot_prices_24h()
        
        cout_total_spot = 0
        cout_total_bloc = 0
        cout_total_mix = 0
        
        details = []

        for h in range(24):
            conso_kw = load_curve_kw[h] if h < len(load_curve_kw) else 0
            
            # 1. Scénario 100% Spot
            cout_h_spot = (conso_kw / 1000) * spot_prices[h] # MWh * €/MWh
            cout_total_spot += cout_h_spot
            
            # 2. Scénario Bloc + Spot (Dentelle)
            # La partie Bloc est payée au prix CAL (Fixe)
            # La partie Dentelle (ce qui dépasse ou manque) est régularisée au Spot
            
            # Partie couverte par le bloc
            vol_bloc = min(conso_kw, puissance_bloc_kw)
            vol_spot = max(0, conso_kw - puissance_bloc_kw)
            
            # Si on consomme MOINS que le bloc, on revend le surplus au Spot (Gain)
            vol_trop_percu = max(0, puissance_bloc_kw - conso_kw)
            
            cout_partie_bloc = (puissance_bloc_kw / 1000) * self.BASE_CAL_N1
            cout_partie_spot = (vol_spot / 1000) * spot_prices[h]
            gain_revente = (vol_trop_percu / 1000) * spot_prices[h]
            
            cout_h_mix = cout_partie_bloc + cout_partie_spot - gain_revente
            cout_total_mix += cout_h_mix

            details.append({
                "heure": h,
                "conso_kw": int(conso_kw),
                "prix_spot": spot_prices[h],
                "cout_mix": round(cout_h_mix, 2)
            })

        return {
            "spot_avg": round(sum(spot_prices)/24, 2),
            "cout_100_spot": round(cout_total_spot, 2),
            "cout_mix_bloc_spot": round(cout_total_mix, 2),
            "gain_strategie": round(cout_total_spot - cout_total_mix, 2),
            "details_horaires": details,
            "prices_curve": spot_prices
        }

market = CortexMarket()
