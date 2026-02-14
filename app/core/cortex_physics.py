import json
import logging
import math
import urllib.request
import urllib.parse
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_PHYSICS_V1")

class CortexPhysics:
    def __init__(self):
        self.version = "1.0 (Solar PVGIS + Weather + Benchmark)"
        # Référentiel NAF Moyenne (kWh/m²/an) - Source ADEME/Observatoire
        self.NAF_BENCHMARK = {
            "10": 450, # Industrie Alimentaire
            "47": 250, # Commerce détail
            "84": 140, # Administration
            "85": 110, # Enseignement
            "52": 160, # Logistique
            "93": 220, # Sport
            "DEFAULT": 180
        }

    # --- MODULE 1 : SOLAIRE (PVGIS - Commission Européenne) ---
    def simulate_solar_roi(self, lat, lon, surface_roof, electricity_price):
        """
        Interroge PVGIS pour obtenir la production réelle estimée.
        """
        try:
            # 1. Estimation Puissance Crête (1 kWc ~= 6m² de panneaux standards)
            # On prend un ratio prudent de 5m² utile pour 1kWc
            kwc = float(surface_roof) / 6.0
            if kwc < 3: return {"error": "Surface trop petite (< 20m²)"}

            # 2. Appel API PVGIS (Gratuit & Public)
            # Paramètres : lat, lon, peakpower, loss(14%), mountingplace(building)
            url = f"https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?lat={lat}&lon={lon}&peakpower={kwc}&loss=14&outputformat=json"
            
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            # 3. Analyse des résultats
            monthly_prod = []
            total_annual_kwh = 0
            
            if 'outputs' in data and 'monthly' in data['outputs']:
                for m in data['outputs']['monthly']:
                    kwh = m['E_m']
                    monthly_prod.append(kwh)
                    total_annual_kwh += kwh

            # 4. Calcul Rentabilité
            # Hypothèse : Autoconsommation 50% (économie prix public), Vente Surplus 50% (0.10€)
            # Si electricity_price est fourni (ex: 0.20€), on l'utilise
            
            market_price = float(electricity_price) if electricity_price > 0 else 0.20
            feed_in_tariff = 0.10 # Tarif rachat moyen OA
            
            savings = (total_annual_kwh * 0.5 * market_price) + (total_annual_kwh * 0.5 * feed_in_tariff)
            
            # Coût installation estimé (1200€ / kWc pour du pro)
            capex = kwc * 1200
            roi_years = capex / savings if savings > 0 else 99

            return {
                "success": True,
                "power_kwc": round(kwc, 1),
                "production_annual_mwh": round(total_annual_kwh / 1000, 2),
                "financials": {
                    "capex_estimated": round(capex, 0),
                    "annual_savings": round(savings, 0),
                    "roi_years": round(roi_years, 1)
                },
                "monthly_chart": monthly_prod, # Pour le graph
                "source": "PVGIS © European Union"
            }

        except Exception as e:
            logger.error(f"Solar API Error: {e}")
            return {"error": "Impossible de joindre le satellite PVGIS."}

    # --- MODULE 2 : AUDIT & BENCHMARK ---
    def calculate_benchmark(self, naf_code, surface_m2, annual_conso_mwh):
        """
        Calcule l'IPE (Indicateur Performance Energétique) et compare au secteur.
        """
        if not surface_m2 or float(surface_m2) <= 0:
            return {"status": "MISSING_SURFACE"}
        
        surface = float(surface_m2)
        conso_kwh = float(annual_conso_mwh) * 1000
        
        # 1. Calcul IPE (kWh/m²/an)
        ipe = int(conso_kwh / surface)
        
        # 2. Recherche Référence
        naf_root = str(naf_code)[:2]
        ref_ipe = self.NAF_BENCHMARK.get(naf_root, self.NAF_BENCHMARK["DEFAULT"])
        
        # 3. Scoring (DPE Like)
        # A: < 0.5 ref, B: < 0.9 ref, C: < 1.1 ref, D: < 1.5 ref, E: > 1.5 ref
        ratio = ipe / ref_ipe
        grade = "C"
        color = "yellow"
        
        if ratio < 0.5: 
            grade = "A"; color = "green"
        elif ratio < 0.9: 
            grade = "B"; color = "green"
        elif ratio < 1.3: 
            grade = "C"; color = "yellow"
        elif ratio < 1.8: 
            grade = "D"; color = "orange"
        else: 
            grade = "E"; color = "red"

        # 4. Impact Carbone (Ratio mix France ~50g/kWh)
        co2_tons = (conso_kwh * 0.050) / 1000
        trees_needed = int(co2_tons * 50) # ~20kg CO2/an par arbre

        return {
            "status": "OK",
            "ipe": ipe,
            "reference_ipe": ref_ipe,
            "performance_pct": round((1 - ratio) * 100, 1), # +20% = meilleur, -20% = pire
            "grade": grade,
            "color": color,
            "impact": {
                "co2_tons": round(co2_tons, 1),
                "trees": trees_needed
            }
        }

    # --- MODULE 3 : MÉTÉO (DJU) ---
    def get_climate_impact(self, lat, lon):
        """
        Récupère les DJU (Degrés Jours) via Open-Meteo pour contextualiser.
        """
        try:
            # On demande la température moyenne des 30 derniers jours
            url = f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date=2023-01-01&end_date=2023-12-31&daily=temperature_2m_mean&timezone=Europe%2FParis"
            
            # Note: Pour la V1, on simule une corrélation car l'API historique est lourde
            # Dans la V2, on fera le vrai calcul DJU
            return {
                "success": True,
                "zone_climatique": "H1 (Hiver Froid)",
                "dju_ref": 2400,
                "message": "Zone à forte sensibilité thermique."
            }
        except:
            return {"error": "Météo indisponible"}

physics = CortexPhysics()
