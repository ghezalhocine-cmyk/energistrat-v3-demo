import json
import logging
import math
import urllib.request
import urllib.parse
from datetime import datetime

# Import des librairies mathématiques (Robustesse industrielle)
try:
    import pandas as pd
    import numpy as np
    MATH_ENGINE_READY = True
except ImportError:
    MATH_ENGINE_READY = False
    logging.warning("!!! CORTEX PHYSICS ALERT : Pandas/Numpy manquant. Mode dégradé activé.")

# CONFIGURATION DU LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_PHYSICS_V56_DIAMOND")

class CortexPhysics:
    def __init__(self):
        self.version = "56.0 (Diamond: Integrated Physics Core)"
        
        # RÉFÉRENTIEL NAF - MOYENNES DE CONSOMMATION (kWh/m²/an)
        self.NAF_BENCHMARK = {
            "10": 450, "47": 250, "84": 140, "85": 110, "52": 160, "93": 220, "DEFAULT": 180
        }

        # CONSTANTES INDUSTRIELLES & CARBONE (Base ADEME / CRE)
        self.IND_FACTORS = {
            "co2_elec_fr": 0.052, # kgCO2/kWh (Mix France)
            "co2_gaz": 0.227,     # kgCO2/kWh
            "turpe_fixe": 15.0,   # €/kVA/an (Ordre de grandeur C4)
            "turpe_var": 0.04,    # €/kWh dépassement
            "penalite_reactive": 0.018 # €/kVarh
        }

    # =========================================================
    # 0. POINT D'ENTRÉE PRINCIPAL (REQUIS PAR ENGINE)
    # =========================================================
    def compute_optimization(self, df, time_step, contract_power):
        """
        Le Chef d'Orchestre Physique.
        Appelé par CortexEngine pour analyser une courbe de charge complète.
        """
        if not MATH_ENGINE_READY or df is None or df.empty:
            return {"error": "Données physiques insuffisantes"}

        try:
            # 1. Analyse Statistique de base
            p_max_reached = float(df['val'].max())
            p_min_talon = float(df['val'].min())
            p_avg = float(df['val'].mean())
            total_energy = float(df['val'].sum() * (time_step / 60)) # kW * h
            
            # 2. Optimisation Puissance Souscrite (TURPE)
            turpe_opt = self.simulate_turpe_optimization(p_max_reached, float(contract_power))
            
            # 3. Analyse Gaspillage (Weekend Watcher)
            # Conversion dataframe en liste dict pour la méthode interne
            raw_records = df.to_dict('records')
            weekend_analysis = self.analyze_weekend_waste(raw_records)
            
            # 4. Empreinte Carbone
            carbon = self.calculate_carbon_footprint(total_energy, 0) # 0 gaz ici car courbe elec

            # 5. Facteur de Charge
            load_factor = (p_avg / p_max_reached) if p_max_reached > 0 else 0

            return {
                "stats": {
                    "p_max_reached": round(p_max_reached, 2),
                    "p_min_talon": round(p_min_talon, 2),
                    "load_factor_pct": round(load_factor * 100, 1),
                    "total_energy_kwh": round(total_energy, 0)
                },
                "optimization": turpe_opt,
                "waste_analysis": weekend_analysis,
                "carbon": carbon,
                "monotone": self.generate_load_duration_curve(df['val'].tolist())
            }

        except Exception as e:
            logger.error(f"CRITICAL PHYSICS FAILURE: {e}")
            return {"error": str(e)}

    # =========================================================
    # MODULE 1 : SOLAIRE (PVGIS + FALLBACK)
    # =========================================================
    def simulate_solar_roi(self, lat, lon, surface_roof, electricity_price):
        try:
            lat, lon, surface_roof = float(lat), float(lon), float(surface_roof)
            kwc = surface_roof / 6.0
            
            if kwc < 3: 
                return {"error": "Surface trop petite (< 20m²)."}

            total_annual_kwh = 0
            monthly_prod = []
            api_success = False

            # TENTATIVE 1 : API PVGIS
            try:
                base_url = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
                params = {
                    "lat": lat, "lon": lon, "peakpower": kwc, "loss": 14,       
                    "outputformat": "json", "angle": 35, "aspect": 0       
                }
                url = f"{base_url}?{urllib.parse.urlencode(params)}"
                req = urllib.request.Request(url, headers={'User-Agent': 'Energistrat/V3'})
                
                with urllib.request.urlopen(req, timeout=3) as response:
                    data = json.loads(response.read().decode())
                    if 'outputs' in data and 'monthly' in data['outputs']:
                        for m in data['outputs']['monthly']:
                            monthly_prod.append(m['E_m'])
                            total_annual_kwh += m['E_m']
                        api_success = True
            except Exception:
                pass # Silent fail -> Fallback

            # TENTATIVE 2 : FALLBACK MATHÉMATIQUE
            if not api_success or total_annual_kwh == 0:
                irradiation = 1100 + ((46 - lat) * 60)
                total_annual_kwh = kwc * irradiation
                ratios = [0.03, 0.05, 0.08, 0.11, 0.13, 0.14, 0.15, 0.13, 0.09, 0.06, 0.02, 0.01]
                monthly_prod = [total_annual_kwh * r for r in ratios]
                source_label = "Modèle Mathématique Interne"
            else:
                source_label = "PVGIS © European Union"

            market_price = float(electricity_price) if electricity_price > 0 else 0.20
            savings = total_annual_kwh * 0.5 * market_price # Autoconsommation 50%
            capex = kwc * 1100
            roi = capex / savings if savings > 0 else 99

            return {
                "success": True,
                "power_kwc": round(kwc, 1),
                "production_annual_mwh": round(total_annual_kwh / 1000, 2),
                "financials": {
                    "capex": round(capex, 0),
                    "savings_year": round(savings, 0),
                    "roi_years": round(roi, 1)
                },
                "monthly_chart": [round(p, 1) for p in monthly_prod],
                "source": source_label
            }
        except Exception as e:
            logger.error(f"Solar Error: {e}")
            return {"error": "Erreur calcul solaire"}

    # =========================================================
    # MODULE 2 : OPTIMISATEUR TURPE
    # =========================================================
    def simulate_turpe_optimization(self, max_power_reached, current_sub_power):
        """ Simule l'optimum technico-économique. """
        results = []
        start_p = int(max_power_reached * 0.8)
        end_p = int(max_power_reached * 1.2)
        if start_p < 36: start_p = 36 # Min C5/C4 standard
        
        for p_test in range(start_p, end_p + 1, 6):
            cost_fix = p_test * self.IND_FACTORS["turpe_fixe"]
            
            # Simulation dépassement (Modèle quadratique simplifié)
            overrun_kwh = 0
            if max_power_reached > p_test:
                diff = max_power_reached - p_test
                overrun_kwh = diff * 10 # Facteur durée estimé
            
            cost_var = overrun_kwh * self.IND_FACTORS["turpe_var"]
            results.append({"p": p_test, "cost": cost_fix + cost_var})
            
        if not results: return {"status": "No optimization possible"}

        best = min(results, key=lambda x: x['cost'])
        
        # Coût actuel estimé
        current_overrun = max(0, max_power_reached - current_sub_power) * 10
        current_cost = (current_sub_power * self.IND_FACTORS["turpe_fixe"]) + (current_overrun * self.IND_FACTORS["turpe_var"])
        
        savings = current_cost - best['cost']
        
        return {
            "current_p": current_sub_power,
            "optimal_p": best['p'],
            "potential_savings": round(savings, 2) if savings > 50 else 0,
            "recommendation": "Ajuster Puissance" if abs(best['p'] - current_sub_power) > 6 else "Puissance Optimale"
        }

    # =========================================================
    # MODULE 3 : ANALYSE WEEK-END (GASPILLAGE)
    # =========================================================
    def analyze_weekend_waste(self, records):
        """ Analyse Samedi/Dimanche vs Semaine """
        if not MATH_ENGINE_READY or not records: return {}
        try:
            df = pd.DataFrame(records)
            if 'date' not in df.columns: return {}
            
            df['date'] = pd.to_datetime(df['date'])
            df['weekday'] = df['date'].dt.weekday
            
            week = df[df['weekday'] < 5]['val'].mean()
            weekend = df[df['weekday'] >= 5]['val'].mean()
            
            if pd.isna(week) or pd.isna(weekend): return {}
            
            ratio = weekend / week if week > 0 else 0
            is_waste = ratio > 0.3 # Seuil d'alerte 30%
            
            return {
                "avg_week_kw": round(week, 1),
                "avg_weekend_kw": round(weekend, 1),
                "ratio_pct": round(ratio * 100, 1),
                "alert": is_waste,
                "message": "Talon week-end élevé détecté" if is_waste else "Régulation week-end correcte"
            }
        except Exception:
            return {}

    # =========================================================
    # MODULE 4 : GEOCODING & CARBONE
    # =========================================================
    def get_coordinates_from_address(self, address):
        lat, lon = 46.603354, 1.888334
        if not address: return lat, lon
        try:
            q = urllib.parse.quote(address)
            url = f"https://api-adresse.data.gouv.fr/search/?q={q}&limit=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'Energistrat/V3'})
            with urllib.request.urlopen(req, timeout=2) as r:
                d = json.loads(r.read().decode())
                if d.get('features'):
                    c = d['features'][0]['geometry']['coordinates']
                    return c[1], c[0] # API Gouv renvoie [lon, lat]
        except: pass
        return lat, lon

    def calculate_carbon_footprint(self, kwh_elec, kwh_gaz):
        co2 = (kwh_elec * self.IND_FACTORS["co2_elec_fr"]) + (kwh_gaz * self.IND_FACTORS["co2_gaz"])
        return {
            "total_tco2": round(co2 / 1000.0, 2),
            "trees_needed": int(co2 / 25)
        }

    def generate_load_duration_curve(self, values):
        """ Génère la monotone pour l'affichage """
        if not values: return []
        try:
            sorted_vals = sorted([float(v) for v in values if v is not None], reverse=True)
            step = max(1, len(sorted_vals) // 50) # Downsampling pour le front
            return sorted_vals[::step]
        except: return []

physics = CortexPhysics()
