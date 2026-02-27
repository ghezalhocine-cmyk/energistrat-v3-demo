import pandas as pd
import numpy as np
import json
import logging

# Imports robustes
try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_physics import physics
except ImportError:
    ingest = None
    physics = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_ENGINE_MASTER")

class CortexEngine:
    def __init__(self):
        self.version = "1120.0 (Master Gold: Retail + Mairie + Forecast)"
        
        # RÉFÉRENCES MARCHÉ
        self.MARKET_DEFAULTS = {
            "elec": {"price": 0.18, "tax": 0.025, "trve_ref": 0.225}, 
            "gas": {"price": 0.045, "tax": 0.00844, "peg_ref": 0.065}
        }
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
        """
        Cœur du calcul financier. Appelé pour chaque site.
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
        
        # 3. DÉTECTION ÉNERGIE
        energy_type_str = contract.get('energy_type', 'elec').lower()
        is_gas = False
        if 'gaz' in energy_type_str or 'gas' in energy_type_str: is_gas = True
        elif segment in ['T1', 'T2', 'T3', 'T4', 'TP']: is_gas = True
        elif 'GRDF' in grd: is_gas = True
        
        # 4. VOLUMÉTRIE (PRIORITÉ AU ROUTEUR TITANIUM SI DISPO)
        vol_kwh = self._safe_float(contract.get('annual_volume_estimated'))
        
        # FIX TITANIUM : Si KPI Routeur existe, on l'utilise
        if 'kpis' in site_data and 'volume_mwh' in site_data['kpis']:
            vol_router = float(site_data['kpis']['volume_mwh'])
            if vol_router > 0: vol_kwh = vol_router * 1000

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
        
        # 7. LOGIQUE DE SANCTUARISATION (TAXES)
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

        # 9. UX HACK : SEGMENT
        naf_code = ident.get('naf', '')
        insee_code = ident.get('insee', '')
        ref_copro = ident.get('ref_copro', '')
        
        display_segment = segment
        extras = []
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

    def generate_dqe_structure(self, sites_data):
        """ 
        Génère les données pour l'export Excel DQE (Tender).
        CORRECTIF TITANIUM : Récupération des champs manuels (Ville, CP, Conso détaillée)
        """
        rows = []
        for s in sites_data:
            if s.get('identity',{}).get('id') == "new_client": continue
            ident = s.get('identity', {})
            loc = s.get('location', {})
            con = s.get('contract', {})
            pow_det = con.get('power_details', {})
            con_det = con.get('consumption_details', {})
            energy = con.get('energy_type', 'elec')
            
            # --- FIX TITANIUM : Récupération intelligente des volumes ---
            sum_conso = (
                self._safe_float(con_det.get('hph')) + 
                self._safe_float(con_det.get('hch')) + 
                self._safe_float(con_det.get('hpe')) + 
                self._safe_float(con_det.get('hce'))
            )
            # Si pas de détail, on prend le volume annuel estimé
            if sum_conso > 0:
                vol_annuel = sum_conso
            else:
                vol_annuel = self._safe_float(con.get('annual_volume_estimated'))
                
            # Si toujours 0, on regarde si le Routeur a calculé un KPI
            if vol_annuel == 0 and 'kpis' in s and 'volume_mwh' in s['kpis']:
                vol_annuel = float(s['kpis']['volume_mwh']) * 1000

            # --- FIX TITANIUM : Récupération intelligente du PDL ---
            pdl = ident.get('id', '') # Par défaut l'ID
            if con.get('pdl') and len(str(con.get('pdl'))) > 5: pdl = con.get('pdl')
            if con.get('pce') and len(str(con.get('pce'))) > 5: pdl = con.get('pce')

            row = {
                "Type": "GAZ" if "gaz" in energy else "ELEC",
                "Entité": ident.get('name', ''), # Raison Sociale
                "Nom du site": ident.get('site_name', ''),
                "Adresse": loc.get('address', ''),
                "CP": loc.get('zip_code', ''), # FIX: Récupère bien le CP
                "Ville": loc.get('city', ''),  # FIX: Récupère bien la Ville
                "PDL": pdl,                    # FIX: Le bon PDL
                "Segment": con.get('segment', ''),
                "FTA": con.get('fta', ''),
                "S Max (kVA)": con.get('power', 0),
                "PS HPH": pow_det.get('ps_hph', 0), "PS HCH": pow_det.get('ps_hch', 0), 
                "PS HPE": pow_det.get('ps_hpe', 0), "PS HCE": pow_det.get('ps_hce', 0),
                "Conso HPH": con_det.get('hph', 0), "Conso HCH": con_det.get('hch', 0), 
                "Conso HPE": con_det.get('hpe', 0), "Conso HCE": con_det.get('hce', 0),
                "Vol. Annuel": vol_annuel,
                "SIRET": ident.get('siret', ''),
                "NAF": ident.get('naf', ''),
                "INSEE": ident.get('insee', ''),
                "REF_COPRO": ident.get('lot_name', '') # Mappe Lot vers Ref Copro
            }
            rows.append(row)
        return pd.DataFrame(rows)

    def analyze_portfolio(self, raw_sites_data):
        """ Analyse globale pour la Green League et les KPIs Fleet """
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
        """ Appelle le moteur physique pour analyser une courbe de charge """
        if physics and ingest:
            df, step, meta = ingest.parse_load_curve(content, filename)
            if df is not None: return physics.compute_optimization(df, step, power_subscribed)
        return {"error": "Missing Modules"}

    def simulate_budget_from_bpu(self, bpu_content, current_sites):
        """
        MOTEUR DU COMPARATEUR DQE (RETAIL & MAIRIE)
        Gère le format 'Tuple' renvoyé par l'Ingest V16+
        """
        if not ingest: return {"error": "Ingest missing"}
        
        # APPEL INGEST : Récupère (Map des prix, Booléen Gaz)
        result_tuple = ingest.parse_bpu_excel(bpu_content)
        
        # Vérification de sécurité Tuple
        if not result_tuple or not isinstance(result_tuple, tuple):
            return {"error": "Format BPU non reconnu"}
            
        price_map = result_tuple[0]
        is_bpu_gaz = result_tuple[1]
        
        if not price_map: return {"error": "BPU Illisible ou vide"}
        
        total_savings = 0
        details = []
        total_current = 0
        total_sim = 0
        
        for s in current_sites:
            fin = self.enrich_site_financials(s)
            
            # On ne compare que les sites de la même énergie que le BPU
            if fin['meta']['is_gas'] != is_bpu_gaz: continue
            
            pdl = str(s.get('identity', {}).get('id', ''))
            
            # Recherche du prix spécifique pour ce PDL
            offer_data = price_map.get(pdl)
            if not offer_data:
                # Fallback : Prix par défaut (première ligne du BPU)
                offer_data = price_map.get("default")
            
            if not offer_data: continue # Impossible de simuler ce site
            
            offer_price = offer_data['hph']
            offer_fix = offer_data['fix']
            
            # Règle MWh -> kWh
            if offer_price > 2.0: offer_price /= 1000.0
            
            # --- CALCUL DU BUDGET SIMULÉ ---
            
            if is_bpu_gaz:
                # GAZ : Prix unique molécule
                vol = fin['volume_kwh']
                new_commodity = vol * offer_price
            else:
                # ELEC : 4 Postes si dispos dans le BPU
                p_hph = offer_price
                p_hch = offer_data.get('hch', p_hph)
                p_hpe = offer_data.get('hpe', p_hph)
                p_hce = offer_data.get('hce', p_hph)
                
                # Conversion kWh
                if p_hch > 2.0: p_hch /= 1000.0
                if p_hpe > 2.0: p_hpe /= 1000.0
                if p_hce > 2.0: p_hce /= 1000.0
                
                # Volumes par poste (si dispos dans le site)
                consos = s.get('contract', {}).get('consumption_details', {})
                v_hph = self._safe_float(consos.get('hph', 0))
                v_hch = self._safe_float(consos.get('hch', 0))
                v_hpe = self._safe_float(consos.get('hpe', 0))
                v_hce = self._safe_float(consos.get('hce', 0))
                
                # Si pas de détail conso, tout en HPH
                if (v_hph + v_hch + v_hpe + v_hce) == 0:
                    v_hph = fin['volume_kwh']
                
                new_commodity = (v_hph * p_hph) + (v_hch * p_hch) + (v_hpe * p_hpe) + (v_hce * p_hce)

            # Abo & Stockage (Si fourni dans BPU, sinon on garde l'actuel)
            new_fix = offer_fix if offer_fix > 0 else fin['details']['fix']
            
            new_stock_price = offer_data.get('stock', 0)
            if new_stock_price > 0:
                if is_bpu_gaz and new_stock_price > 0.5: new_stock_price /= 1000.0
                cost_stock = fin['volume_kwh'] * new_stock_price
            else:
                cost_stock = fin['details']['storage']

            # Reconstitution Budget Total Simulé
            sim_budget = new_fix + fin['details']['taxes'] + cost_stock + new_commodity
            
            # Comparaison
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
