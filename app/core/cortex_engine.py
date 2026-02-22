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
logger = logging.getLogger("CORTEX_ENGINE_V1101")

class CortexEngine:
    def __init__(self):
        self.version = "1101.0 (Fix: Prices & Gas Badge)"
        self.MARKET_DEFAULTS = {"elec": {"price": 0.18, "tax": 0.025}, "gas": {"price": 0.06, "tax": 0.008}}
        self.OPTIMAL_PRICE = {"elec": 0.12, "gas": 0.045} 

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
        
        # --- DÉTECTION ROBUSTE GAZ/ELEC ---
        energy_type_str = contract.get('energy_type', 'elec').lower()
        segment = str(contract.get('segment', '')).upper()
        grd = str(contract.get('grd', '')).upper()
        pdl = str(contract.get('pdl', ''))

        is_gas = False
        # 1. Check explicite string
        if 'gaz' in energy_type_str or 'gas' in energy_type_str: is_gas = True
        # 2. Check Segment (Force Gaz pour T1-T5)
        elif segment in ['T1', 'T2', 'T3', 'T4', 'TP']: is_gas = True
        # 3. Check GRD
        elif 'GRDF' in grd: is_gas = True
        # 4. Check Format PDL (PCE souvent court ou spécifique, mais moins fiable)
        
        # --- VOLUMETRIE ---
        vol_kwh = self._safe_float(contract.get('annual_volume_estimated'))
        
        # --- NORMALISATION PRIX (TOUT EN €/kWh POUR CALCUL) ---
        raw_price = self._safe_float(pricing.get('hph'))
        unit_price = raw_price
        
        # Règle de sécurité Unités
        if is_gas and raw_price > 2.0: unit_price = raw_price / 1000.0
        elif not is_gas and raw_price > 5.0: unit_price = raw_price / 1000.0
            
        is_estimated = False
        if unit_price <= 0.0001:
            unit_price = self.MARKET_DEFAULTS['gas']['price'] if is_gas else self.MARKET_DEFAULTS['elec']['price']
            is_estimated = True

        fixe = self._safe_float(pricing.get('fix'))
        commodity = vol_kwh * unit_price
        
        # Taxes & Stockage
        raw_tax = self._safe_float(pricing.get('tax'))
        if raw_tax > 0.5: raw_tax /= 1000.0 
        taxes = (vol_kwh * raw_tax) if raw_tax > 0 else (vol_kwh * self.MARKET_DEFAULTS['gas' if is_gas else 'elec']['tax'])
        
        raw_stock = self._safe_float(pricing.get('storage'))
        if raw_stock > 0.5: raw_stock /= 1000.0
        storage_cost = vol_kwh * raw_stock
        
        budget_ttc = commodity + fixe + taxes + storage_cost
        landing = budget_ttc * 1.02
        pmc_mwh = self._safe_div(budget_ttc, (vol_kwh / 1000))
        
        # Calcul du "Gaspillage"
        optimal = self.OPTIMAL_PRICE['gas'] if is_gas else self.OPTIMAL_PRICE['elec']
        ghost = max(0, (unit_price - optimal) * vol_kwh)

        # --- RECUPERATION DES PRIX SECONDAIRES (FIX BUG 0) ---
        p_hch = self._safe_float(pricing.get('hch'))
        p_hpe = self._safe_float(pricing.get('hpe'))
        p_hce = self._safe_float(pricing.get('hce'))
        
        # Si Elec et prix > 5, on convertit aussi les heures creuses/pleines
        if not is_gas:
            if p_hch > 5.0: p_hch /= 1000.0
            if p_hpe > 5.0: p_hpe /= 1000.0
            if p_hce > 5.0: p_hce /= 1000.0

        return {
            "meta": {
                "site_label": str(site_label).upper(),
                "city": loc.get('city', ''),
                "energy_type": "Gaz" if is_gas else "Électricité",
                "is_gas": is_gas
            },
            "volume_kwh": self._sanitize(round(vol_kwh, 0)),
            "volume_mwh": self._sanitize(round(vol_kwh / 1000, 2)),
            "budget_annual": self._sanitize(round(budget_ttc, 2)),
            "landing_forecast": self._sanitize(round(landing, 2)),
            "details": {
                "commodity": self._sanitize(round(commodity, 2)),
                "fix": self._sanitize(round(fixe, 2)),
                "taxes": self._sanitize(round(taxes, 2)),
                "storage": self._sanitize(round(storage_cost, 2))
            },
            "kpis": {
                "budget_annual": self._sanitize(round(budget_ttc, 2)),
                "volume_mwh": self._sanitize(round(vol_kwh / 1000, 2)),
                "pmc_eur_mwh": self._sanitize(round(pmc_mwh, 2)),
                "unit_price_kwh": unit_price,
                "is_estimated_price": is_estimated,
                "ghost_savings": self._sanitize(round(ghost, 2))
            },
            "pricing_details": {
                "hph": unit_price,
                "hch": p_hch, # FIX: On renvoie la valeur
                "hpe": p_hpe, # FIX: On renvoie la valeur
                "hce": p_hce, # FIX: On renvoie la valeur
                "fix": fixe,
                "tax": taxes,
                "storage": storage_cost
            }
        }

    def generate_dqe_structure(self, sites_data):
        rows = []
        for s in sites_data:
            if s.get('identity',{}).get('id') == "new_client": continue
            ident = s.get('identity', {})
            loc = s.get('location', {})
            con = s.get('contract', {})
            pow_det = con.get('power_details', {})
            con_det = con.get('consumption_details', {})
            energy = con.get('energy_type', 'elec')
            
            sum_conso = (
                self._safe_float(con_det.get('hph')) + 
                self._safe_float(con_det.get('hch')) + 
                self._safe_float(con_det.get('hpe')) + 
                self._safe_float(con_det.get('hce'))
            )
            vol_annuel = sum_conso if sum_conso > 0 else self._safe_float(con.get('annual_volume_estimated'))

            row = {
                "Type": "GAZ" if "gaz" in energy else "ELEC",
                "Entité": ident.get('entity_name', ''),
                "Nom du site": ident.get('site_name', ''),
                "Adresse": loc.get('address', ''),
                "CP": loc.get('zip_code', ''),
                "Ville": loc.get('city', ''),
                "PDL": ident.get('id', ''),
                "Segment": con.get('segment', ''),
                "FTA": con.get('fta', ''),
                "S Max (kVA)": con.get('power', 0),
                "PS HPH": pow_det.get('hph', 0), "PS HCH": pow_det.get('hch', 0), 
                "PS HPE": pow_det.get('hpe', 0), "PS HCE": pow_det.get('hce', 0),
                "Conso HPH": con_det.get('hph', 0), "Conso HCH": con_det.get('hch', 0), 
                "Conso HPE": con_det.get('hpe', 0), "Conso HCE": con_det.get('hce', 0),
                "Vol. Annuel": vol_annuel,
                "SIRET": ident.get('siret', '')
            }
            rows.append(row)
        return pd.DataFrame(rows)

    def analyze_portfolio(self, raw_sites_data):
        if not raw_sites_data: return {"global": {}, "green_league": []}
        processed = []
        stats = {"total_budget": 0, "total_elec": 0, "total_gas": 0, "nb": 0}
        for s in raw_sites_data:
            if "CLI_" in str(s.get('identity',{}).get('id')): continue
            try:
                fin = self.enrich_site_financials(s)
                if fin['volume_kwh'] <= 1: continue
                stats['nb'] += 1
                stats['total_budget'] += fin['budget_annual']
                if fin['meta']['is_gas']: stats['total_gas'] += fin['volume_kwh']
                else: stats['total_elec'] += fin['volume_kwh']
                
                processed.append({
                    "id": s.get('identity',{}).get('id'),
                    "nom_site": fin['meta']['site_label'],
                    "pmc": fin['kpis']['pmc_eur_mwh'],
                    "ghost_savings": fin['kpis']['ghost_savings'],
                    "budget": fin['budget_annual']
                })
            except: continue
            
        valid = [s for s in processed if s['budget'] > 100]
        sorted_sites = sorted(valid, key=lambda x: x['pmc'])
        cancres = sorted(valid, key=lambda x: x['pmc'], reverse=True)[:5]
        
        return {
            "global": {
                "budget_total": self._sanitize(round(stats['total_budget'], 2)),
                "volume_elec_mwh": self._sanitize(round(stats['total_elec'] / 1000, 1)),
                "volume_gas_mwh": self._sanitize(round(stats['total_gas'] / 1000, 1)),
                "sites_count": stats['nb']
            },
            "green_league": {
                "gold": sorted_sites[0] if len(sorted_sites) > 0 else None,
                "silver": sorted_sites[1] if len(sorted_sites) > 1 else None,
                "bronze": sorted_sites[2] if len(sorted_sites) > 2 else None,
                "cancres": cancres
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
        details = []
        total_current = 0
        total_sim = 0
        
        for s in current_sites:
            fin = self.enrich_site_financials(s)
            if fin['meta']['is_gas'] == is_gaz:
                vol = fin['volume_kwh']
                current_b = fin['details']['commodity']
                new_cost = vol * offer_price
                delta = current_b - new_cost
                
                total_current += fin['budget_annual']
                sim_budget = fin['details']['fix'] + fin['details']['taxes'] + fin['details']['storage'] + new_cost
                total_sim += sim_budget
                
                total_savings += delta
                details.append({
                    "site_name": fin['meta']['site_label'],
                    "volume": fin['volume_mwh'],
                    "current_budget": fin['budget_annual'],
                    "simulated_budget": sim_budget,
                    "delta_euro": delta,
                    "delta_pct": round((delta / fin['budget_annual']) * 100, 1) if fin['budget_annual'] > 0 else 0
                })
                
        return {
            "success": True, 
            "summary": {
                "total_current": total_current,
                "total_simulated": total_sim,
                "savings_euro": total_savings,
                "savings_pct": round((total_savings / total_current)*100, 1) if total_current > 0 else 0
            },
            "details": details
        }
    
    def calculate_benchmark(self, naf, surface, volume_mwh):
        if physics: return physics.calculate_benchmark(naf, surface, volume_mwh)
        return {}
    
    def analyze_market_position(self, current_price, market_ref, is_gas, segment="C5"):
        try:
            ref_price = 0.0
            if is_gas: ref_price = float(market_ref.get('gaz', {}).get('peg_n1', 40))
            else: ref_price = float(market_ref.get('elec', {}).get('cal_n1', 90))
            
            client_price_mwh = current_price
            if client_price_mwh < 2.0: client_price_mwh *= 1000.0
            
            if client_price_mwh <= 1.0: return {"status": "INCONNU", "message": "Prix non détecté", "color": "gray", "action": "-"}

            delta = client_price_mwh - ref_price
            pct = (delta / ref_price) * 100

            if delta > 15: return {"status": "ALERTE", "color": "red", "message": f"Prix élevé (+{int(pct)}%)", "action": f"Payé {int(client_price_mwh)}€ vs {int(ref_price)}€"}
            elif delta < -5: return {"status": "OPTIMISÉ", "color": "green", "message": "Performance Achat", "action": f"Sous le marché ({int(client_price_mwh)}€)"}
            else: return {"status": "NEUTRE", "color": "blue", "message": "Aligné marché", "action": f"Prix cohérent ({int(client_price_mwh)}€)"}
        except: return {"status": "ERREUR", "color": "gray", "message": "Données indisponibles", "action": "-"}

cortex = CortexEngine()
