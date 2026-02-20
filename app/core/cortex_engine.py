import pandas as pd
import numpy as np
import logging

try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_physics import physics
except ImportError:
    ingest = None
    physics = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_ENGINE_V85_DQE_FIX")

class CortexEngine:
    def __init__(self):
        self.version = "85.0 (Diamond: DQE Mask Compliance)"
        self.MARKET_DEFAULTS = {"elec": {"price": 0.18, "tax": 0.05}, "gas": {"price": 0.08, "tax": 0.02}}

    def _safe_float(self, value, default=0.0):
        try:
            if value is None or pd.isna(value): return default
            return float(value)
        except: return default

    def _safe_div(self, num, den):
        n, d = self._safe_float(num), self._safe_float(den)
        return n / d if d != 0 else 0.0
    
    def _sanitize(self, val):
        if pd.isna(val) or np.isinf(val): return 0.0
        return val

    def enrich_site_financials(self, site_data):
        ident = site_data.get('identity', {})
        contract = site_data.get('contract', {})
        pricing = site_data.get('pricing', {})
        loc = site_data.get('location', {})
        
        site_label = ident.get('site_name', 'Site Inconnu')
        if not site_label or site_label == "Site Inconnu":
            site_label = f"{loc.get('city', 'Site')} ({str(contract.get('pdl', ''))[-4:]})"
        
        energy_type = contract.get('energy_type', 'elec').lower()
        is_gas = 'gaz' in energy_type or 'gas' in energy_type
        
        vol_kwh = self._safe_float(contract.get('annual_volume_estimated'))
        raw_price = self._safe_float(pricing.get('hph'))
        unit_price = raw_price / 1000.0 if raw_price > 2.0 else raw_price
        
        is_estimated = False
        if unit_price <= 0.001:
            unit_price = self.MARKET_DEFAULTS['gas']['price'] if is_gas else self.MARKET_DEFAULTS['elec']['price']
            is_estimated = True

        fixe = self._safe_float(pricing.get('fix'))
        commodity = vol_kwh * unit_price
        file_tax = self._safe_float(pricing.get('tax'))
        tax_rate = self.MARKET_DEFAULTS['gas']['tax'] if is_gas else self.MARKET_DEFAULTS['elec']['tax']
        taxes = file_tax if file_tax > 0 else (vol_kwh * tax_rate)
        
        budget_ttc = commodity + fixe + taxes
        landing = budget_ttc * 1.02
        pmc_mwh = self._safe_div(budget_ttc, (vol_kwh / 1000))

        return {
            "meta": {
                "site_label": str(site_label).upper(),
                "city": loc.get('city', ''),
                "energy_type": "Gaz" if is_gas else "Électricité"
            },
            "volume_kwh": self._sanitize(round(vol_kwh, 0)),
            "volume_mwh": self._sanitize(round(vol_kwh / 1000, 2)),
            "budget_annual": self._sanitize(round(budget_ttc, 2)),
            "landing_forecast": self._sanitize(round(landing, 2)),
            "details": {
                "commodity": self._sanitize(round(commodity, 2)),
                "fix": self._sanitize(round(fixe, 2)),
                "taxes": self._sanitize(round(taxes, 2))
            },
            "kpis": {
                "pmc_eur_mwh": self._sanitize(round(pmc_mwh, 2)),
                "is_estimated_price": is_estimated
            }
        }

    def analyze_portfolio(self, raw_sites_data):
        if not raw_sites_data: return {"global": {}, "green_league": []}
        processed = []
        stats = {"total_budget": 0, "total_elec": 0, "total_gas": 0, "nb": 0}
        
        for s in raw_sites_data:
            try:
                fin = self.enrich_site_financials(s)
                stats['nb'] += 1
                stats['total_budget'] += fin['budget_annual']
                if "Gaz" in fin['meta']['energy_type']: stats['total_gas'] += fin['volume_kwh']
                else: stats['total_elec'] += fin['volume_kwh']
                processed.append({
                    "id": s.get('identity',{}).get('id'),
                    "name": fin['meta']['site_label'],
                    "ratio_pmc": fin['kpis']['pmc_eur_mwh'],
                    "conso_mwh": fin['volume_mwh'],
                    "budget": fin['budget_annual']
                })
            except: continue
            
        valid = [s for s in processed if s['conso_mwh'] > 1 and s['ratio_pmc'] > 0]
        sorted_sites = sorted(valid, key=lambda x: x['ratio_pmc'])
        
        return {
            "global": {
                "budget_total": self._sanitize(round(stats['total_budget'], 2)),
                "volume_elec_mwh": self._sanitize(round(stats['total_elec'] / 1000, 1)),
                "volume_gas_mwh": self._sanitize(round(stats['total_gas'] / 1000, 1)),
                "sites_count": stats['nb']
            },
            "green_league": {
                "top_performer": sorted_sites[0] if sorted_sites else None,
                "low_performer": sorted_sites[-1] if sorted_sites else None,
                "ranking": sorted_sites[:5]
            }
        }

    def analyze_load_curve(self, content, filename, power_subscribed=36):
        if physics and ingest:
            df, step, meta = ingest.parse_load_curve(content, filename)
            if df is not None: return physics.compute_optimization(df, step, power_subscribed)
        return {"error": "Missing Modules"}

    def simulate_budget_from_bpu(self, bpu_content, current_sites):
        if not ingest: return {"error": "Ingest missing"}
        df_bpu, is_gaz = ingest.parse_bpu_excel(bpu_content)
        if df_bpu is None: return {"error": "BPU Illisible"}
        offer_price = float(df_bpu.iloc[0]['hph'])
        if offer_price > 2.0: offer_price /= 1000.0
        total_savings = 0
        for s in current_sites:
            fin = self.enrich_site_financials(s)
            if ("Gaz" in fin['meta']['energy_type']) == is_gaz:
                old_cost = fin['details']['commodity']
                new_cost = fin['volume_kwh'] * offer_price
                total_savings += (old_cost - new_cost)
        return {"success": True, "savings_total": self._sanitize(round(total_savings, 2))}
    
    # --- FIX DQE : MASQUE CONFORME ---
    def generate_dqe_structure(self, sites_data):
        rows = []
        for s in sites_data:
            ident = s.get('identity', {})
            loc = s.get('location', {})
            con = s.get('contract', {})
            pricing = s.get('pricing', {})
            
            # Mapping STRICT basé sur votre screenshot
            row = {
                "Entité": ident.get('entity_name', ''),
                "Nom du site": ident.get('site_name', ''),
                "Adresse": loc.get('address', ''),
                "CP": loc.get('zip_code', ''),
                "Ville": loc.get('city', ''),
                "INSEE": "", # Donnée non dispo dans import standard
                "SIRET": ident.get('siret', ''),
                "PDL": ident.get('id', ''),
                "Segment": con.get('segment', ''),
                "FTA": "CU", # Par défaut
                "S Max (kVA)": con.get('power', 0),
                # Colonnes vides pour remplissage manuel ou futures données
                "PS HPH": con.get('power', 0), "PS HCH": con.get('power', 0), "PS HPE": con.get('power', 0), "PS HCE": con.get('power', 0),
                "Conso HPH": "", "Conso HCH": "", "Conso HPE": "", "Conso HCE": "",
                "Vol. Annuel": con.get('annual_volume_estimated', 0)
            }
            rows.append(row)
        return pd.DataFrame(rows)
    
    def calculate_benchmark(self, naf, surface, volume_mwh):
        if physics: return physics.calculate_benchmark(naf, surface, volume_mwh)
        return {}

cortex = CortexEngine()
