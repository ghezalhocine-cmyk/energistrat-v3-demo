import pandas as pd
import numpy as np
import logging
from datetime import datetime

# Import sécurisé pour éviter les crashs circulaires
try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_physics import physics
except ImportError:
    ingest = None
    physics = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_ENGINE_V70_FULL")

class CortexEngine:
    def __init__(self):
        self.version = "70.0 (Titanium: Price Norm + Smart Naming + Physics Link)"
        self.MARKET_DEFAULTS = {
            "elec": {"price": 0.18, "tax": 0.05}, # €/kWh
            "gas": {"price": 0.08, "tax": 0.02}   # €/kWh
        }

    # =========================================================
    # 1. OUTILS MATHÉMATIQUES (ANTI-NAN)
    # =========================================================
    def _safe_float(self, value, default=0.0):
        try:
            if value is None or pd.isna(value) or str(value).strip() == "": return default
            return float(value)
        except: return default

    def _safe_div(self, num, den):
        n = self._safe_float(num)
        d = self._safe_float(den)
        if d == 0: return 0.0
        return n / d

    # =========================================================
    # 2. ENRICHISSEMENT FINANCIER (BUDGETS & KPIS)
    # =========================================================
    def enrich_site_financials(self, site_data):
        """
        Le cœur du calcul. Transforme Ingest -> Dashboard.
        """
        ident = site_data.get('identity', {})
        contract = site_data.get('contract', {})
        pricing = site_data.get('pricing', {})
        loc = site_data.get('location', {})
        
        # A. RÉPARATION DU NOM (Fix "Site Inconnu")
        site_label = ident.get('site_name', 'Site Inconnu')
        if not site_label or site_label in ["Site Inconnu", "nan", "None"]:
            city = loc.get('city', 'Site')
            pdl = str(contract.get('pdl', ''))
            site_label = f"{city} ({pdl[-4:]})" if len(pdl) > 4 else f"{city} - {pdl}"
        
        # B. DÉTECTION ÉNERGIE
        energy_type = contract.get('energy_type', 'elec').lower()
        is_gas = 'gaz' in energy_type or 'gas' in energy_type
        
        # C. VOLUMES (Normalisés en kWh par Ingest V70)
        vol_kwh = self._safe_float(contract.get('annual_volume_estimated'))
        
        # D. PRIX (Normalisation €/MWh -> €/kWh)
        raw_price = self._safe_float(pricing.get('hph'))
        unit_price = raw_price
        
        # SI PRIX > 2.0 (ex: 45.50), C'EST DU MWh -> /1000
        if raw_price > 2.0:
            unit_price = raw_price / 1000.0
            
        # Fallback si prix absent
        is_estimated_price = False
        if unit_price <= 0.001:
            unit_price = self.MARKET_DEFAULTS['gas']['price'] if is_gas else self.MARKET_DEFAULTS['elec']['price']
            is_estimated_price = True

        # E. CALCUL DU BUDGET
        fixe = self._safe_float(pricing.get('fix'))
        
        # Commodity = Conso (kWh) * Prix (€/kWh)
        commodity = vol_kwh * unit_price
        
        # Taxes
        tax_rate = self.MARKET_DEFAULTS['gas']['tax'] if is_gas else self.MARKET_DEFAULTS['elec']['tax']
        taxes = vol_kwh * tax_rate
        
        budget_ttc = commodity + fixe + taxes

        # F. ATTERRISSAGE (Landing)
        landing = budget_ttc * 1.02 # Simule +2%

        # G. RATIOS
        pmc_mwh = self._safe_div(budget_ttc, (vol_kwh / 1000)) # €/MWh
        
        return {
            "meta": {
                "site_label": str(site_label).upper(),
                "city": loc.get('city', ''),
                "energy_type": "Gaz" if is_gas else "Électricité"
            },
            "volume_kwh": round(vol_kwh, 0),
            "volume_mwh": round(vol_kwh / 1000, 2),
            "budget_annual": round(budget_ttc, 2),
            "landing_forecast": round(landing, 2),
            "details": {
                "commodity": round(commodity, 2),
                "fix": round(fixe, 2),
                "taxes": round(taxes, 2)
            },
            "kpis": {
                "pmc_eur_mwh": round(pmc_mwh, 2),
                "is_estimated_price": is_estimated_price
            }
        }

    # =========================================================
    # 3. ANALYSE PORTEFEUILLE (GREEN LEAGUE)
    # =========================================================
    def analyze_portfolio(self, raw_sites_data):
        if not raw_sites_data:
            return {"global": {"budget_total": 0}, "green_league": []}

        processed_sites = []
        global_stats = {
            "total_elec_kwh": 0, "total_gas_kwh": 0,
            "total_budget": 0, "nb_sites": 0
        }

        for site in raw_sites_data:
            try:
                fin = self.enrich_site_financials(site)
                
                global_stats['nb_sites'] += 1
                global_stats['total_budget'] += fin['budget_annual']
                
                if "Gaz" in fin['meta']['energy_type']:
                    global_stats['total_gas_kwh'] += fin['volume_kwh']
                else:
                    global_stats['total_elec_kwh'] += fin['volume_kwh']

                processed_sites.append({
                    "id": site.get('identity', {}).get('id'),
                    "name": fin['meta']['site_label'],
                    "ratio_pmc": fin['kpis']['pmc_eur_mwh'],
                    "conso_mwh": fin['volume_mwh'],
                    "budget": fin['budget_annual']
                })
            except: continue

        # Tri intelligent (évite les divisions par zéro)
        valid_sites = [s for s in processed_sites if s['conso_mwh'] > 1 and s['ratio_pmc'] > 0]
        sorted_sites = sorted(valid_sites, key=lambda x: x['ratio_pmc'])

        return {
            "global": {
                "budget_total": round(global_stats['total_budget'], 2),
                "volume_elec_mwh": round(global_stats['total_elec_kwh'] / 1000, 1),
                "volume_gas_mwh": round(global_stats['total_gas_kwh'] / 1000, 1),
                "sites_count": global_stats['nb_sites']
            },
            "green_league": {
                "top_performer": sorted_sites[0] if sorted_sites else None,
                "low_performer": sorted_sites[-1] if sorted_sites else None,
                "ranking": sorted_sites[:5]
            }
        }

    # =========================================================
    # 4. FONCTIONS SATELLITES (RESTAURÉES POUR VOS OUTILS)
    # =========================================================
    
    def analyze_load_curve(self, content, filename, power_subscribed=36):
        """ Appelé par Solar Studio & Audit """
        if physics:
            # Ingest lit d'abord le fichier
            if ingest:
                df, step, meta = ingest.parse_load_curve(content, filename)
                if df is not None:
                    return physics.compute_optimization(df, step, power_subscribed)
        return {"error": "Module Physics ou Ingest manquant"}

    def generate_dqe_structure(self, sites_data):
        """ Appelé par le générateur Excel DQE """
        rows = []
        for s in sites_data:
            fin = self.enrich_site_financials(s)
            rows.append({
                "PDL": s.get('identity', {}).get('id'),
                "Site": fin['meta']['site_label'],
                "Ville": fin['meta']['city'],
                "Conso (kWh)": fin['volume_kwh'],
                "Budget (€)": fin['budget_annual']
            })
        return pd.DataFrame(rows)

    def simulate_budget_from_bpu(self, bpu_content, current_sites):
        """ Appelé par le Comparateur """
        if not ingest: return {"error": "Ingest missing"}
        
        # 1. Lecture BPU
        df_bpu, is_gaz = ingest.parse_bpu_excel(bpu_content)
        if df_bpu is None or df_bpu.empty:
            return {"error": "BPU Illisible"}
            
        # 2. Simulation
        offer_price = float(df_bpu.iloc[0]['hph'])
        # Normalisation Prix Offre (Si > 2.0 -> /1000)
        if offer_price > 2.0: offer_price /= 1000.0
        
        total_savings = 0
        for s in current_sites:
            fin = self.enrich_site_financials(s)
            site_is_gas = "Gaz" in fin['meta']['energy_type']
            if site_is_gas == is_gaz:
                old_cost = fin['details']['commodity']
                new_cost = fin['volume_kwh'] * offer_price
                total_savings += (old_cost - new_cost)
                
        return {
            "success": True,
            "savings_total": round(total_savings, 2),
            "offer_price_detected": offer_price
        }
    
    def analyze_market_position(self, current_price, market_price, energy_type, segment="C5"):
        """ Appelé par Ops Market """
        diff = current_price - market_price
        status = "NEUTRE"
        color = "gray"
        
        if diff > 0.02: # Paye 2cts de plus que le marché
            status = "ALERTE"
            color = "red"
        elif diff < -0.01: # Paye moins cher
            status = "OPTIMISÉ"
            color = "green"
            
        return {"status": status, "color": color, "delta": round(diff, 4)}

    def calculate_benchmark(self, naf, surface, volume_mwh):
        """ Appelé par Audit """
        if physics:
            return physics.calculate_benchmark(naf, surface, volume_mwh)
        return {}

cortex = CortexEngine()
