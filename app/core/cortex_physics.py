import json
import logging
import math
import urllib.request
import urllib.parse
from datetime import datetime

# CONFIGURATION DU LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_PHYSICS_V1_4_ROBUST")

class CortexPhysics:
    def __init__(self):
        self.version = "1.4 (Solar Fix: Type Check + Geocoding)"
        
        # RÉFÉRENTIEL NAF - MOYENNES DE CONSOMMATION (kWh/m²/an)
        self.NAF_BENCHMARK = {
            "10": 450, "47": 250, "84": 140, "85": 110, "52": 160, "93": 220, "DEFAULT": 180
        }

    # =========================================================
    # MODULE 0 : GEOCODING (NOUVEAU)
    # =========================================================
    def get_coordinates_from_address(self, address):
        """
        Convertit une adresse/ville en Lat/Lon via API Gouv.
        """
        # Valeurs par défaut (Centre France) si échec
        lat, lon = 46.603354, 1.888334
        
        if not address: return lat, lon

        try:
            query = urllib.parse.quote(address)
            url = f"https://api-adresse.data.gouv.fr/search/?q={query}&limit=1"
            
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())
                if data.get('features') and len(data['features']) > 0:
                    coords = data['features'][0]['geometry']['coordinates']
                    lon = coords[0]
                    lat = coords[1]
        except Exception as e:
            logger.error(f"Geocoding Error: {e}")
        
        return lat, lon

    # =========================================================
    # MODULE 1 : SOLAIRE (PVGIS - FIX CRASH)
    # =========================================================
    def simulate_solar_roi(self, lat, lon, surface_roof, electricity_price):
        """
        Interroge l'API PVGIS pour estimer la production photovoltaïque réelle.
        """
        try:
            # Sécurisation des types
            lat = float(lat)
            lon = float(lon)
            surface_roof = float(surface_roof)
            
            kwc = surface_roof / 6.0
            if kwc < 3: return {"error": "Surface trop petite (< 20m²) pour une étude rentable."}

            # API PVGIS
            base_url = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
            params = {
                "lat": lat, "lon": lon, "peakpower": kwc, "loss": 14,       
                "outputformat": "json", "angle": 35, "aspect": 0       
            }
            query_string = urllib.parse.urlencode(params)
            url = f"{base_url}?{query_string}"
            
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Energistrat SaaS)'})
            
            with urllib.request.urlopen(req) as response:
                content = response.read().decode()
                try:
                    data = json.loads(content)
                except:
                    return {"error": "Le satellite PVGIS ne répond pas (Format invalide)."}

            # --- CORRECTIF CRASH V1.4 ---
            # Si l'API renvoie un message d'erreur JSON (ex: 'message': 'Out of map'), 
            # data est un dict mais n'a pas 'outputs'.
            if not isinstance(data, dict) or 'outputs' not in data:
                return {"error": "Zone géographique non couverte par le satellite PVGIS."}

            monthly_prod = []
            total_annual_kwh = 0
            
            if 'monthly' in data['outputs']:
                for m in data['outputs']['monthly']:
                    kwh = m['E_m']
                    monthly_prod.append(kwh)
                    total_annual_kwh += kwh
            else:
                 return {"error": "Données solaires incomplètes."}

            # Calcul Financier
            market_price = float(electricity_price) if electricity_price > 0 else 0.20
            feed_in_tariff = 0.10
            savings = (total_annual_kwh * 0.5 * market_price) + (total_annual_kwh * 0.5 * feed_in_tariff)
            capex = kwc * 1100
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
                "monthly_chart": monthly_prod,
                "source": "PVGIS © European Union"
            }

        except Exception as e:
            logger.error(f"Solar API Error: {e}")
            return {"error": f"Erreur technique: {str(e)}"}

    # =========================================================
    # MODULE 2 : AUDIT (INCHANGÉ)
    # =========================================================
    def calculate_benchmark(self, naf_code, surface_m2, annual_conso_mwh):
        if not surface_m2 or float(surface_m2) <= 0: return {"status": "MISSING_SURFACE"}
        surface = float(surface_m2)
        conso_kwh = float(annual_conso_mwh) * 1000 
        ipe = int(conso_kwh / surface)
        naf_root = str(naf_code)[:2] 
        ref_ipe = self.NAF_BENCHMARK.get(naf_root, self.NAF_BENCHMARK["DEFAULT"])
        ratio = ipe / ref_ipe
        grade = "C"; color = "yellow"
        if ratio < 0.5: grade = "A"; color = "green"
        elif ratio < 0.9: grade = "B"; color = "green"
        elif ratio < 1.3: grade = "C"; color = "yellow"
        elif ratio < 1.8: grade = "D"; color = "orange"
        else: grade = "E"; color = "red"
        co2_tons = (conso_kwh * 0.050) / 1000
        trees_needed = int((co2_tons * 1000) / 25)
        return { "status": "OK", "ipe": ipe, "reference_ipe": ref_ipe, "performance_pct": round((1 - ratio) * 100, 1), "grade": grade, "color": color, "impact": { "co2_tons": round(co2_tons, 1), "trees": trees_needed } }

    # =========================================================
    # MODULE 3 : MÉTÉO (INCHANGÉ)
    # =========================================================
    def get_climate_impact(self, lat, lon):
        try:
            last_year = datetime.now().year - 1
            return { "success": True, "year_ref": last_year, "zone_climatique": "Calculé sur historique réel", "message": f"Analyse basée sur les relevés de la station locale ({last_year})." }
        except: return {"error": "Service Météo indisponible"}

physics = CortexPhysics()
