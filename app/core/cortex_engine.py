import pandas as pd
import numpy as np
import logging
from datetime import datetime

# Import des modules frères avec sécurité
try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_physics import physics
except ImportError:
    # Fallback pour mode dégradé ou test unitaire
    ingest = None
    physics = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_ENGINE_V56_DIAMOND")

class CortexEngine:
    def __init__(self):
        self.version = "56.0 (Diamond: Multi-Fluid & Safe Math)"
        # Valeurs de marché par défaut (Backup si données manquantes)
        self.MARKET_DEFAULTS = {
            "elec": {"price": 0.15, "tax": 0.05}, # €/kWh
            "gas": {"price": 0.06, "tax": 0.02}   # €/kWh
        }

    def _safe_float(self, value, default=0.0):
        try:
            if value is None: return default
            return float(value)
        except: return default

    def _safe_div(self, num, den):
        if den is None or den == 0 or pd.isna(den): return 0.0
        return num / den

    # =========================================================
    # 1. CALCULATEUR FINANCIER (LE CŒUR DU SYSTÈME)
    # =========================================================
    def enrich_site_financials(self, site_data):
        """
        Prend un site brut (Ingest) et calcule son budget précis.
        Gère Elec / Gaz / OPH.
        """
        # Récupération des blocs de données
        ident = site_data.get('identity', {})
        contract = site_data.get('contract', {})
        pricing = site_data.get('pricing', {})
        
        # A. Détection du Type
        energy_type = contract.get('energy_type', 'elec').lower()
        is_gas = 'gaz' in energy_type or 'gas' in energy_type
        
        # B. Volume (Normalisé en kWh par Ingest)
        vol_kwh = self._safe_float(contract.get('annual_volume_estimated'))
        if vol_kwh == 0:
            # Estimation de secours basée sur la puissance
            p_max = self._safe_float(contract.get('power'))
            vol_kwh = p_max * 1500 if is_gas else p_max * 1000 # Heuristique grossière
        
        # C. Prix Unitaire (Normalisé en €/kWh par Ingest)
        # Ingest envoie unit_price_ht. S'il est vide, on prend hph.
        unit_price = self._safe_float(pricing.get('unit_price_ht'))
        if unit_price == 0:
            unit_price = self._safe_float(pricing.get('hph'))
        
        # Fallback Marché si prix manquant (Évite budget 0)
        is_estimated_price = False
        if unit_price == 0:
            unit_price = self.MARKET_DEFAULTS['gas']['price'] if is_gas else self.MARKET_DEFAULTS['elec']['price']
            is_estimated_price = True

        # D. Composantes Fixes & Taxes
        abonnement = self._safe_float(pricing.get('fix'))
        taxes = self._safe_float(pricing.get('tax'))
        
        # E. Calculs OPH (P1/P2/P3) - Prioritaire si présent
        p1 = self._safe_float(pricing.get('p1_budget'))
        p2 = self._safe_float(pricing.get('p2_budget'))
        p3 = self._safe_float(pricing.get('p3_budget'))
        
        budget_total = 0.0
        budget_details = {}

        if p1 > 0:
            # Mode OPH / Multi-technique
            budget_total = p1 + p2 + p3
            budget_details = {"commodity": p1, "services": p2 + p3, "taxes": 0} # Simplifié
        else:
            # Mode Fourniture Pure (Elec/Gaz)
            commodity_cost = vol_kwh * unit_price
            budget_total = commodity_cost + abonnement + taxes
            budget_details = {
                "commodity": round(commodity_cost, 2),
                "grid_fix": round(abonnement, 2),
                "taxes": round(taxes, 2)
            }

        # F. Ratios & KPI
        surface = self._safe_float(site_data.get('location', {}).get('surface'))
        ratio_m2 = self._safe_div(budget_total, surface)
        
        # Prix moyen complet (€/MWh pour affichage standard métier)
        pmc_mwh = self._safe_div(budget_total, (vol_kwh / 1000)) 

        return {
            "volume_kwh": round(vol_kwh, 0),
            "volume_mwh": round(vol_kwh / 1000, 2),
            "budget_annual": round(budget_total, 2),
            "details": budget_details,
            "kpis": {
                "ratio_eur_m2": round(ratio_m2, 2),
                "pmc_eur_mwh": round(pmc_mwh, 2),
                "is_estimated_price": is_estimated_price
            },
            "meta": {
                "energy_type": "Gaz" if is_gas else "Électricité",
                "site_label": ident.get('site_label', 'Site Inconnu'),
                "city": site_data.get('location', {}).get('city', '')
            }
        }

    # =========================================================
    # 2. ANALYSE PORTEFEUILLE (GREEN LEAGUE)
    # =========================================================
    def analyze_portfolio(self, raw_sites_data):
        """
        Agrège les données, calcule les totaux et génère le classement.
        """
        if not raw_sites_data:
            return {"kpis": {"total_budget": 0}, "green_league": [], "message": "Aucune donnée"}

        processed_sites = []
        global_stats = {
            "total_elec_kwh": 0, "total_gas_kwh": 0,
            "total_budget": 0, "nb_sites": 0,
            "missing_data_count": 0
        }

        for site in raw_sites_data:
            # 1. Enrichissement financier
            fin = self.enrich_site_financials(site)
            
            # 2. Agrégation
            global_stats['nb_sites'] += 1
            global_stats['total_budget'] += fin['budget_annual']
            
            if fin['meta']['energy_type'] == 'Gaz':
                global_stats['total_gas_kwh'] += fin['volume_kwh']
            else:
                global_stats['total_elec_kwh'] += fin['volume_kwh']
                
            if fin['kpis']['is_estimated_price']:
                global_stats['missing_data_count'] += 1

            # 3. Structure pour le Frontend (Bento Cards)
            processed_sites.append({
                "id": site.get('identity', {}).get('id'),
                "name": fin['meta']['site_label'], # Vrai nom du site !
                "city": fin['meta']['city'],
                "type": fin['meta']['energy_type'],
                "conso_mwh": fin['volume_mwh'],
                "budget": fin['budget_annual'],
                "ratio_pmc": fin['kpis']['pmc_eur_mwh'],
                "score": self._calculate_score(fin['kpis']['pmc_eur_mwh'], fin['meta']['energy_type'])
            })

        # 4. Green League (Tri par performance énergétique/achat)
        # On exclut les tout petits sites (< 1 MWh) pour éviter les aberrations statistiques
        valid_sites = [s for s in processed_sites if s['conso_mwh'] > 1]
        sorted_sites = sorted(valid_sites, key=lambda x: x['ratio_pmc']) # Du moins cher au plus cher

        return {
            "global": {
                "budget_total": round(global_stats['total_budget'], 2),
                "volume_elec_mwh": round(global_stats['total_elec_kwh'] / 1000, 1),
                "volume_gas_mwh": round(global_stats['total_gas_kwh'] / 1000, 1),
                "sites_count": global_stats['nb_sites'],
                "data_quality": "High" if global_stats['missing_data_count'] == 0 else "Medium"
            },
            "green_league": {
                "top_performer": sorted_sites[0] if sorted_sites else None,
                "low_performer": sorted_sites[-1] if sorted_sites else None,
                "ranking": sorted_sites
            },
            "sites": processed_sites
        }

    def _calculate_score(self, pmc, energy_type):
        """ Note sur 100 basée sur le prix moyen constaté """
        # Benchmarks (Mockés pour l'instant)
        target = 60 if energy_type == 'Gaz' else 140 # €/MWh cible
        
        if pmc <= 0: return 0
        score = 100 - (abs(pmc - target) / target * 50)
        return max(0, min(100, int(score)))

    # =========================================================
    # 3. ORCHESTRATION PHYSICS (PONT VERS LE 3ème CERVEAU)
    # =========================================================
    def analyze_load_curve(self, content, filename, contract_power=0):
        """
        Appelle le module Physics pour analyser la courbe de charge.
        """
        if not physics or not ingest:
            return {"error": "Modules Physics/Ingest non chargés"}

        # 1. Ingest lit le fichier brut
        df, step, meta = ingest.parse_load_curve(content, filename)
        if df is None: return {"success": False, "error": "Fichier illisible"}

        # 2. Physics calcule
        # Appel sécurisé aux méthodes de Physics
        try:
            # On suppose que Physics a une méthode d'entrée publique
            result = physics.compute_optimization(df, step, contract_power)
            return {"success": True, "data": result}
        except AttributeError:
            # Fallback si méthode non trouvée (Code Physics pas encore à jour)
            return {"success": False, "error": "Physics module outdated"}

    # =========================================================
    # 4. GENERATEUR EXCEL (DQE)
    # =========================================================
    def generate_dqe_structure(self, sites_data):
        """
        Prépare les données pour l'export Excel DQE.
        """
        rows = []
        for s in sites_data:
            fin = self.enrich_site_financials(s)
            rows.append({
                "PDL/PCE": s.get('identity', {}).get('id'),
                "Nom Site": fin['meta']['site_label'],
                "Type": fin['meta']['energy_type'],
                "Ville": fin['meta']['city'],
                "Volume (kWh)": fin['volume_kwh'],
                "Puissance (kVA/kW)": s.get('contract', {}).get('power'),
                "Budget Actuel (€)": fin['budget_annual']
            })
        return pd.DataFrame(rows)

cortex = CortexEngine()
