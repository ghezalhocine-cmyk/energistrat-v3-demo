import math
from datetime import datetime, timedelta

class CortexForecast:
    def __init__(self):
        self.version = "1.0 (Multi-Profile Forecasting)"
        
        # COEFFICIENTS MENSUELS (Poids de 1 à 12, Jan -> Dec)
        # Permet de sculpter la forme de l'année
        self.PROFILES = {
            # INDUSTRIE : Stable, baisse Août & Décembre
            "INDUSTRIE": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0, 1.0, 1.0, 0.8],
            
            # RETAIL : Fort en Décembre (Fêtes) et Juillet (Clim)
            "RETAIL": [1.1, 1.0, 0.9, 0.9, 1.0, 1.1, 1.3, 1.2, 1.0, 1.0, 1.1, 1.4],
            
            # PME/ARTISAN : Standard
            "PME": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.2, 1.0, 1.0, 1.0, 1.0],
            
            # COLLECTIVITE (Mixte Ecole/Bureaux) : Baisse été
            "COLLECTIVITE": [1.3, 1.2, 1.0, 0.8, 0.6, 0.4, 0.2, 0.2, 0.5, 0.9, 1.2, 1.3],
            
            # HABITAT (Syndic/Bailleur) : DJU Pur (Chauffage)
            "HABITAT": [1.8, 1.6, 1.3, 0.8, 0.4, 0.1, 0.0, 0.0, 0.2, 0.8, 1.4, 1.7],
            
            # SDE (Eclairage Public) : Inverse du soleil
            "SDE": [1.5, 1.3, 1.1, 0.9, 0.7, 0.5, 0.5, 0.6, 0.8, 1.1, 1.3, 1.5]
        }

    def generate_3_year_projection(self, annual_volume_mwh, profile_type, energy_type="elec"):
        """
        Génère une projection mensuelle sur 36 mois (3 ans)
        Basée sur le volume actuel et le profil d'activité.
        """
        try:
            vol = float(annual_volume_mwh)
            if vol <= 0: return {"error": "Volume nul"}

            # 1. Détermination du Profil
            profile_key = "PME" # Défaut
            
            # Mapping Intelligent
            pt = str(profile_type).upper()
            if "INDUS" in pt or "ISO" in pt: profile_key = "INDUSTRIE"
            elif "RETAIL" in pt or "COMMERCE" in pt or "SHOP" in pt: profile_key = "RETAIL"
            elif "MAIRIE" in pt or "ECOLE" in pt or "ADMIN" in pt: profile_key = "COLLECTIVITE"
            elif "SYNDIC" in pt or "COPRO" in pt or "BAILLEUR" in pt or "LOGEMENT" in pt: profile_key = "HABITAT"
            elif "ECLAIRAGE" in pt or "EP" in pt or "SDE" in pt: profile_key = "SDE"
            
            # Adaptation Gaz (Toujours typé chauffage)
            if energy_type == "gaz" and profile_key not in ["INDUSTRIE", "RETAIL"]:
                profile_key = "HABITAT" # Le gaz suit le DJU par défaut sauf process indus

            coeffs = self.PROFILES.get(profile_key, self.PROFILES["PME"])
            
            # Normalisation des coefficients pour que la somme fasse 1 (Répartition annuelle)
            total_coeff = sum(coeffs)
            norm_coeffs = [c / total_coeff for c in coeffs]

            # 2. Génération des données (36 mois)
            labels = []
            data_trend = [] # Tendanciel (Si on ne fait rien)
            data_sobriety = [] # Avec plan de sobriété (-10% progressif)

            current_date = datetime.now()
            
            # Facteurs d'inflation énergétique (Prix) ou Dérive Conso (Usure)
            # Ici on projette des VOLUMES (MWh)
            
            for i in range(36):
                # Date future
                future_date = current_date + timedelta(days=i*30)
                month_idx = future_date.month - 1
                year_offset = i // 12
                
                month_label = future_date.strftime("%b %Y")
                labels.append(month_label)
                
                # Volume de base mensuel
                monthly_vol = vol * norm_coeffs[month_idx]
                
                # Scénario 1 : Tendanciel (Légère hausse usure/clim +1%/an)
                trend_factor = 1 + (0.01 * year_offset)
                val_trend = monthly_vol * trend_factor
                data_trend.append(round(val_trend, 2))
                
                # Scénario 2 : Sobriété (Décret Tertiaire -4%, -7%, -10%)
                sobriety_factor = 1 - (0.04 * (year_offset + 1))
                val_sobriety = monthly_vol * sobriety_factor
                data_sobriety.append(round(val_sobriety, 2))

            return {
                "success": True,
                "profile_used": profile_key,
                "labels": labels,
                "dataset_trend": data_trend,
                "dataset_sobriety": data_sobriety,
                "total_trend": round(sum(data_trend), 1),
                "total_sobriety": round(sum(data_sobriety), 1),
                "gain_potential_mwh": round(sum(data_trend) - sum(data_sobriety), 1)
            }

        except Exception as e:
            return {"error": str(e)}

forecast = CortexForecast()
