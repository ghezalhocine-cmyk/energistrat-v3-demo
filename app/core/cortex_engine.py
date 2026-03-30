import pandas as pd
import numpy as np
import json
import logging
from typing import Dict, Any

# Imports robustes des modules satellites
try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_physics import physics
except ImportError:
    # Fallback pour environnement local
    try:
        from core.cortex_ingest import ingest
        from core.cortex_physics import physics
    except ImportError:
        ingest = None
        physics = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_ENGINE_FULL_SAFE")

class CortexEngine:
    """
    CORTEX ENGINE V3.3 - SAFETY EDITION
    Moteur central de calcul.
    Cette version inclut toutes les fonctions historiques pour éviter toute régression,
    ainsi que les simulateurs stratégiques du Décisions Lab.
    """

    def __init__(self):
        self.version = "Titanium 3.3 (Full Safety & Simulation)"
        
        # RÉFÉRENCES MARCHÉ (TRVE = Elec, PEG = Gaz)
        self.MARKET_DEFAULTS = {
            "elec": {
                "price": 0.18, 
                "tax": 0.025, 
                "trve_ref": 0.225
            }, 
            "gas": {
                "price": 0.045, 
                "tax": 0.00844, 
                "peg_ref": 0.065
            }
        }
        # PRIX CIBLES POUR CALCUL GASPILLAGE (GHOST SAVINGS)
        self.OPTIMAL_PRICE = {
            "elec": 0.12, 
            "gas": 0.045
        } 

    # --- UTILITAIRES INTERNES ---
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

    # --- FONCTION PRINCIPALE : CALCUL FINANCIER ---
    def enrich_site_financials(self, site_data):
        """
        Calcule les KPIs financiers d'un site (Budget, Coûts, Taxes).
        Utilisé par le Dashboard et l'Export.
        """
        ident = site_data.get('identity', {})
        contract = site_data.get('contract', {})
        pricing = site_data.get('pricing', {})
        loc = site_data.get('location', {})
        
        # 1. IDENTIFICATION
        site_label = ident.get('site_name', 'Site Inconnu')
        if not site_label or site_label == "Site Inconnu":
            site_label = f"{loc.get('city', 'Site')} ({str(contract.get('pdl', ''))[-4:]})"
        
        # 2. NETTOYAGE SEGMENT
        raw_segment = str(contract.get('segment', '')).upper()
        if " | " in raw_segment:
            segment = raw_segment.split(" | ")[0].strip()
        else:
            segment = raw_segment

        grd = str(contract.get('grd', '')).upper()
        
        # 3. DÉTECTION ÉNERGIE (ROBUSTE)
        energy_type_str = contract.get('energy_type', 'elec').lower()
        is_gas = False
        if 'gaz' in energy_type_str or 'gas' in energy_type_str: is_gas = True
        elif segment in['T1', 'T2', 'T3', 'T4', 'TP']: is_gas = True
        elif 'GRDF' in grd: is_gas = True
        
        # 4. VOLUMÉTRIE
        vol_kwh = 0
        if 'kpis' in site_data and 'volume_mwh' in site_data['kpis']:
             vol_router = float(site_data['kpis']['volume_mwh'])
             if vol_router > 0:
                 vol_kwh = vol_router * 1000
        
        if vol_kwh == 0:
            vol_kwh = self._safe_float(contract.get('annual_volume_estimated'))
            
        if vol_kwh == 0:
            details = contract.get('consumption_details', {})
            vol_kwh = (
                self._safe_float(details.get('conso_hph')) +
                self._safe_float(details.get('conso_hch')) +
                self._safe_float(details.get('conso_hpe')) +
                self._safe_float(details.get('conso_hce'))
            )

        # 5. PRIX UNITAIRE & CONVERSIONS
        raw_price = self._safe_float(pricing.get('hph'))
        unit_price = raw_price
        
        if is_gas and raw_price > 2.0: unit_price = raw_price / 1000.0
        elif not is_gas and raw_price > 5.0: unit_price = raw_price / 1000.0
            
        is_estimated = False
        if unit_price <= 0.0001:
            unit_price = self.MARKET_DEFAULTS['gas']['price'] if is_gas else self.MARKET_DEFAULTS['elec']['price']
            is_estimated = True

        # 6. CALCUL DU BUDGET
        fixe = self._safe_float(pricing.get('fix'))
        commodity = vol_kwh * unit_price
        
        # 7. LOGIQUE DE SANCTUARISATION
        if is_gas:
            stored_tax = self._safe_float(pricing.get('tax'))
            stored_stock = self._safe_float(pricing.get('storage'))
            
            STD_TAX_KWH = 0.00844 
            STD_STOCK_KWH = 0.0007 
            
            if vol_kwh > 0 and stored_tax < 1.0: taxes_total = vol_kwh * STD_TAX_KWH
            elif stored_tax > 1.0: taxes_total = stored_tax 
            else: taxes_total = vol_kwh * STD_TAX_KWH

            if vol_kwh > 0 and stored_stock < 0.1: storage_total = vol_kwh * STD_STOCK_KWH
            elif stored_stock > 0.1: storage_total = stored_stock
            else: storage_total = vol_kwh * STD_STOCK_KWH
        else:
            raw_tax = self._safe_float(pricing.get('tax'))
            if raw_tax > 0.5: raw_tax_kwh = raw_tax / 1000.0
            else: raw_tax_kwh = raw_tax
            
            if raw_tax_kwh < 0.001: raw_tax_kwh = self.MARKET_DEFAULTS['elec']['tax']
            taxes_total = vol_kwh * raw_tax_kwh
            
            raw_stock = self._safe_float(pricing.get('storage'))
            storage_total = vol_kwh * (raw_stock / 1000.0 if raw_stock > 0.5 else raw_stock)
        
        budget_ttc = commodity + fixe + taxes_total + storage_total
        landing = budget_ttc * 1.02 
        pmc_mwh = self._safe_div(budget_ttc, (vol_kwh / 1000))
        
        optimal = self.OPTIMAL_PRICE['gas'] if is_gas else self.OPTIMAL_PRICE['elec']
        ghost = max(0, (unit_price - optimal) * vol_kwh)

        # 8. PRIX SECONDAIRES
        p_hch = self._safe_float(pricing.get('hch'))
        p_hpe = self._safe_float(pricing.get('hpe'))
        p_hce = self._safe_float(pricing.get('hce'))
        if not is_gas:
            if p_hch > 5.0: p_hch /= 1000.0
            if p_hpe > 5.0: p_hpe /= 1000.0
            if p_hce > 5.0: p_hce /= 1000.0

        # 9. UX HACK : RECONSTRUCTION DU SEGMENT
        naf_code = ident.get('naf', '')
        insee_code = ident.get('insee', '')
        ref_copro = ident.get('ref_copro', '')
        
        display_segment = segment
        extras =[]
        if naf_code and "NAF" not in segment: extras.append(f"NAF:{naf_code}")
        if insee_code and "INSEE" not in segment: extras.append(f"INSEE:{insee_code}")
        if ref_copro and "COPRO" not in segment: extras.append(f"COPRO:{ref_copro}")
        
        if extras: display_segment = f"{segment} | {' '.join(extras)}"

        ref_market_price = self.MARKET_DEFAULTS['gas']['peg_ref'] if is_gas else self.MARKET_DEFAULTS['elec']['trve_ref']

        return {
            "meta": {
                "site_label": str(site_label).upper(),
                "city": loc.get('city', ''),
                "energy_type": "Gaz" if is_gas else "Électricité",
                "is_gas": is_gas,
                "provider": contract.get('provider', 'Inconnu'),
                "naf": naf_code,
                "insee": insee_code,
                "ref_copro": ref_copro
            },
            "volume_kwh": self._sanitize(round(vol_kwh, 0)),
            "volume_mwh": self._sanitize(round(vol_kwh / 1000, 2)),
            "budget_annual": self._sanitize(round(budget_ttc, 2)),
            "landing_forecast": self._sanitize(round(landing, 2)),
            "details": {
                "commodity": self._sanitize(round(commodity, 2)),
                "fix": self._sanitize(round(fixe, 2)),
                "taxes": self._sanitize(round(taxes_total, 2)),
                "storage": self._sanitize(round(storage_total, 2))
            },
            "kpis": {
                "budget_annual": self._sanitize(round(budget_ttc, 2)),
                "volume_mwh": self._sanitize(round(vol_kwh / 1000, 2)),
                "pmc_eur_mwh": self._sanitize(round(pmc_mwh, 2)),
                "unit_price_kwh": unit_price,
                "ref_market_price_kwh": ref_market_price,
                "is_estimated_price": is_estimated,
                "ghost_savings": self._sanitize(round(ghost, 2))
            },
            "pricing_details": {
                "hph": unit_price,
                "hch": p_hch,
                "hpe": p_hpe,
                "hce": p_hce,
                "fix": fixe,
                "tax": taxes_total,
                "storage": storage_total
            },
            "display_overrides": {
                "segment": display_segment
            }
        }

    # --- FONCTION DQE ---
    def generate_dqe_structure(self, sites_list):
        rows =[]
        for site in sites_list:
            try:
                ident = site.get('identity', {})
                loc = site.get('location', {})
                cont = site.get('contract', {})
                
                fin = self.enrich_site_financials(site)
                kpis = fin['kpis']
                
                pce = cont.get('pce')
                pdl = cont.get('pdl')
                if not pdl and ident.get('id') and len(str(ident.get('id'))) == 14 and str(ident.get('id')).isdigit():
                    pdl = ident.get('id')

                is_gas = pce and len(str(pce)) > 5
                
                cons_det = cont.get('consumption_details', {})
                vol_annuel_kwh = kpis['volume_mwh'] * 1000
                
                c_hph = self._safe_float(cons_det.get('conso_hph', 0))
                c_hch = self._safe_float(cons_det.get('conso_hch', 0))
                c_hpe = self._safe_float(cons_det.get('conso_hpe', 0))
                c_hce = self._safe_float(cons_det.get('conso_hce', 0))
                
                if (c_hph + c_hch + c_hpe + c_hce) == 0 and vol_annuel_kwh > 0:
                    c_hph = vol_annuel_kwh * 0.40
                    c_hch = vol_annuel_kwh * 0.30
                    c_hpe = vol_annuel_kwh * 0.20
                    c_hce = vol_annuel_kwh * 0.10
                
                row = {
                    "Type": "GAZ" if is_gas else "ELEC",
                    "Entité": ident.get('name', ''),
                    "Nom du site": ident.get('site_name', 'Site Sans Nom'),
                    "Adresse": loc.get('address', ''),
                    "CP": loc.get('zip_code', ''),     
                    "Ville": loc.get('city', ''),      
                    "PDL": pce if is_gas else pdl,     
                    "Segment": cont.get('segment', ''),
                    "FTA": cont.get('fta', ''),
                    "PS Max (kVA)": cont.get('power', 0),
                    "PS HPH": cont.get('power_details', {}).get('ps_hph', 0),
                    "PS HCH": cont.get('power_details', {}).get('ps_hch', 0),
                    "PS HPE": cont.get('power_details', {}).get('ps_hpe', 0),
                    "PS HCE": cont.get('power_details', {}).get('ps_hce', 0),
                    "Conso HPH": int(c_hph),
                    "Conso HCH": int(c_hch),
                    "Conso HPE": int(c_hpe),
                    "Conso HCE": int(c_hce),
                    "Vol. Annuel": int(vol_annuel_kwh),
                    "SIRET": ident.get('siret', ''),
                    "NAF": ident.get('naf', ''),
                    "INSEE": "", 
                    "REF_COPRO": ident.get('lot_name', '')
                }
                rows.append(row)
            except Exception as e:
                logger.error(f"Erreur ligne DQE pour {site.get('identity', {}).get('id')}: {e}")
                continue

        return pd.DataFrame(rows) if pd else None

    def analyze_market_position(self, current_price, market_ref, is_gas):
        ref = market_ref['gaz']['peg_n1'] if is_gas else market_ref['elec']['cal_n1']
        status = "OPTIMISÉ"
        if current_price > ref * 1.2: status = "RISQUE"
        return {"status": status, "market_ref": ref, "delta_pct": 0}

    def analyze_portfolio(self, sites):
        return {"global": {}, "green_league":[]}

    # --- COMPARATEUR BPU ---
    def simulate_budget_from_bpu(self, bpu_content, current_sites):
        if not ingest: return {"error": "Ingest missing"}
        
        result_tuple = ingest.parse_bpu_excel(bpu_content)
        if not result_tuple or not isinstance(result_tuple, tuple):
            return {"error": "Format BPU non reconnu"}
            
        price_map = result_tuple[0]
        is_bpu_gaz = result_tuple[1]
        
        if not price_map: return {"error": "BPU Illisible ou vide"}
        
        total_savings = 0
        details =[]
        total_current = 0
        total_sim = 0
        
        for s in current_sites:
            fin = self.enrich_site_financials(s)
            if fin['meta']['is_gas'] != is_bpu_gaz: continue
            
            pdl = str(s.get('identity', {}).get('id', ''))
            
            offer_data = price_map.get(pdl)
            if not offer_data: offer_data = price_map.get("default")
            if not offer_data: continue 
            
            offer_price = offer_data['hph']
            offer_fix = offer_data['fix']
            if offer_price > 2.0: offer_price /= 1000.0
            
            if is_bpu_gaz:
                new_commodity = fin['volume_kwh'] * offer_price
            else:
                consos = s.get('contract', {}).get('consumption_details', {})
                v_hph = self._safe_float(consos.get('conso_hph', 0))
                v_hch = self._safe_float(consos.get('conso_hch', 0))
                v_hpe = self._safe_float(consos.get('conso_hpe', 0))
                v_hce = self._safe_float(consos.get('conso_hce', 0))
                
                if (v_hph + v_hch + v_hpe + v_hce) == 0: v_hph = fin['volume_kwh']
                
                p_hph = offer_price
                p_hch = offer_data.get('hch', p_hph)
                p_hpe = offer_data.get('hpe', p_hph)
                p_hce = offer_data.get('hce', p_hph)
                
                if p_hch > 2.0: p_hch /= 1000.0
                if p_hpe > 2.0: p_hpe /= 1000.0
                if p_hce > 2.0: p_hce /= 1000.0
                
                new_commodity = (v_hph * p_hph) + (v_hch * p_hch) + (v_hpe * p_hpe) + (v_hce * p_hce)

            new_fix = offer_fix if offer_fix > 0 else fin['details']['fix']
            cost_stock = fin['details']['storage'] 

            sim_budget = new_fix + fin['details']['taxes'] + cost_stock + new_commodity
            current_budget = fin['budget_annual']
            delta = current_budget - sim_budget
            
            total_current += current_budget
            total_sim += sim_budget
            total_savings += delta
            
            details.append({
                "site_name": fin['meta']['site_label'],
                "volume": fin['volume_mwh'],
                "current_budget": current_budget,
                "simulated_budget": sim_budget,
                "delta_euro": delta,
                "delta_pct": round((delta / current_budget) * 100, 1) if current_budget > 0 else 0
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

    def simulate_solar_roi(self, lat, lon, surface, price):
        if physics: return physics.simulate_solar_roi(lat, lon, surface, price)
        return {"error": "Module Solaire indisponible"}

    def analyze_load_curve(self, content, filename):
        if physics and ingest:
            df, step, meta = ingest.parse_load_curve(content, filename)
            if df is not None: return physics.compute_optimization(df, step, 36)
        return {"success": True, "chart": {"labels": [], "values":[]}, "kpi": {}}

    # =========================================================
    # SIMULATEURS DÉCISIONS LAB (TURPE / EXTINCTION / SUBVENTIONS)
    # =========================================================
    def simulate_turpe(self, ps_current: float, pmax: float, ps_target: float) -> Dict[str, Any]:
        try:
            diff = ps_current - ps_target
            savings = diff * 15  # Prime fixe estimée
            warning = ""
            
            if ps_target < pmax:
                penalty = (pmax - ps_target) * 20
                savings -= penalty
                warning = f"Risque de dépassement / disjonction l'hiver. Pénalité estimée : {round(penalty)} €"
            elif ps_target == ps_current:
                warning = "Abonnement Actuel."
                
            return {
                "savings_eur": savings,
                "is_profitable": savings > 0,
                "warning_message": warning
            }
        except Exception as e:
            return {"error": str(e)}

    def simulate_extinction(self, ghost_savings: float, surface: float, pct_reduction: float) -> Dict[str, Any]:
        try:
            savings = ghost_savings * (pct_reduction / 100.0)
            capex = surface * 15.0 if surface > 0 else 2500.0
            roi_months = (capex / savings) * 12 if savings > 0 else 999.0
            
            return {
                "savings_eur": savings,
                "capex_eur": capex,
                "roi_months": round(roi_months, 1),
                "is_profitable": roi_months < 36
            }
        except Exception as e:
            return {"error": str(e)}

    def simulate_subventions(self, cout_travaux: float, aides_api: float) -> Dict[str, Any]:
        try:
            total_aides = aides_api
            if total_aides == 0 and cout_travaux > 0:
                total_aides = cout_travaux * 0.30 # Fonds Vert par défaut
                
            if total_aides > cout_travaux:
                total_aides = cout_travaux # Plafond légal 100%
                
            reste = cout_travaux - total_aides
            pct = (total_aides / cout_travaux) * 100 if cout_travaux > 0 else 0
            
            return {
                "total_aides_eur": total_aides,
                "reste_a_charge_eur": reste,
                "pct_financement": round(pct, 1)
            }
        except Exception as e:
            return {"error": str(e)}


cortex = CortexEngine()
