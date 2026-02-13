import pandas as pd
import numpy as np
import io
import re
import math
import logging
import csv
from datetime import datetime

# CONFIGURATION IA & LOGGING
VERTEX_REGION = "europe-west9"
VERTEX_MODEL = "gemini-1.5-flash-001"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_MASTER_V46_4_VOLUME_FIX")

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    vertexai.init(location=VERTEX_REGION)
    AI_MODEL = GenerativeModel(VERTEX_MODEL)
    AI_AVAILABLE = True
except:
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "46.4 (Fix: Force Read Total Volume)"
        self.NAF_DB = {
            "1071C": "Boulangerie", "1071D": "Pâtisserie", "1013A": "Charcuterie", 
            "1013B": "Boucherie", "5610A": "Restauration Trad.", "5610C": "Fast Food",
            "4711D": "Supermarché", "4711F": "Hypermarché", "4711B": "Supérette",
            "4722Z": "Boucherie (Retail)", "4771Z": "Habillement", "4520A": "Garage Auto",
            "8510Z": "École Maternelle", "8520Z": "École Primaire", "8531Z": "Collège/Lycée",
            "8559A": "Formation Continue", "8552Z": "Enseignement Culturel",
            "8411Z": "Mairie / Admin", "8412Z": "Santé Publique", "8424Z": "Ordre Public",
            "9311Z": "Gymnase / Stade", "9329Z": "Loisirs", "9101Z": "Bibliothèque",
            "2562B": "Mécanique Ind.", "2511Z": "Métallurgie", "2229A": "Plasturgie",
            "1812Z": "Imprimerie", "3312Z": "Maintenance Ind.", "2059Z": "Chimie",
            "6820A": "Bailleur Social", "6820B": "Location Terrains", "8110Z": "Syndic / Copro",
            "5510Z": "Hôtellerie", "6832A": "Administration Immeubles", "6832B": "Supports Immobiliers"
        }

    def _safe_int(self, value):
        try:
            if value is None: return 0
            val_str = str(value).replace(',', '.').replace(' ', '').replace('\xa0', '').replace('€', '').replace('kVA', '')
            if not val_str or val_str.lower() == 'nan': return 0
            return int(float(val_str))
        except: return 0

    def _safe_float(self, value):
        try:
            if value is None: return 0.0
            val_str = str(value).replace(',', '.').replace(' ', '').replace('\xa0', '').replace('€', '').replace('kVA', '')
            if not val_str or val_str.lower() == 'nan': return 0.0
            return float(val_str)
        except: return 0.0

    def _normalize_supplier(self, raw_name):
        if not raw_name: return "Inconnu"
        n = str(raw_name).upper().strip()
        if "EDF" in n: return "EDF"
        if "TOTAL" in n: return "TotalEnergies"
        if "ENGIE" in n: return "Engie"
        if "ENI" in n: return "Eni"
        if "VATTENFALL" in n: return "Vattenfall"
        if "IBERDROLA" in n: return "Iberdrola"
        if "AXPO" in n: return "Axpo"
        if "ALPIQ" in n: return "Alpiq"
        if "GEG" in n: return "GEG"
        if "IMPORT" in n: return "Import CSV"
        return n.title() 

    # =========================================================
    # MODULE 1 : TENDER FACTORY EXCEL (V46)
    # =========================================================
    def generate_advanced_tender_excel(self, sites_data):
        if not sites_data: return b""
        try:
            first_site = sites_data[0]
            contract = first_site.get('contract', {}) or {}
            is_gaz = "T" in str(contract.get('segment', '')).upper() or "GAZ" in str(contract.get('segment', '')).upper()
            if is_gaz: return self._generate_gaz_tender(sites_data)
            else: return self._generate_elec_tender(sites_data)
        except Exception as e:
            logger.error(f"Erreur Fatale Excel Generator: {e}")
            return b""

    def _generate_elec_tender(self, sites_data):
        output = io.BytesIO()
        rows = []
        for s in sites_data:
            try:
                c = s.get('contract', {})
                i = s.get('identity', {})
                loc = s.get('location', {})
                tech = s.get('technical', {})
                conso_det = s.get('consumption_details', {})
                power_det = c.get('power_details', {})
                
                power = self._safe_float(c.get('power', 0))
                
                rows.append({
                    "Entité": s.get('client_name', ''),
                    "Nom du site": i.get('site_name', ''),
                    "Adresse": loc.get('address', ''),
                    "CP": loc.get('zip_code', ''),
                    "Commune": loc.get('city', ''),
                    "SIRET Site": i.get('siret_site', ''),
                    "NAF": i.get('naf', ''),
                    "CEE": tech.get('cee_eligible', 'NON'),
                    "GO %": tech.get('go_percentage', '0'),
                    "Compteur Prod.": tech.get('producer_meter', 'Non'),
                    "PRM": c.get('pdl', ''),
                    "Segment": c.get('segment', ''),
                    "FTA": c.get('fta', ''),
                    "GRD": c.get('grd', ''),
                    "Typologie": tech.get('typology', ''),
                    "PS Max (kVA)": power,
                    "Pointe (kW)": c.get('p_max', 0),
                    "PS HPH": power_det.get('hph', 0),
                    "PS HCH": power_det.get('hch', 0),
                    "PS HPE": power_det.get('hpe', 0),
                    "PS HCE": power_det.get('hce', 0),
                    "Conso HPH": conso_det.get('hph', 0),
                    "Conso HCH": conso_det.get('hch', 0),
                    "Conso HPE": conso_det.get('hpe', 0),
                    "Conso HCE": conso_det.get('hce', 0),
                    "Vol. Annuel": s.get('kpis', {}).get('volume_mwh', 0) * 1000,
                    "Commentaires": s.get('meta', {}).get('comments', ''),
                    "Date début": c.get('start_date', ''),
                    "Date fin": c.get('end_date', '')
                })
            except: continue
        df_dqe = pd.DataFrame(rows)
        try:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_dqe.to_excel(writer, sheet_name='1-DQE_Sites', index=False)
        except: return b""
        output.seek(0)
        return output.getvalue()

    def _generate_gaz_tender(self, sites_data):
        output = io.BytesIO()
        rows = []
        for s in sites_data:
            try:
                c = s.get('contract', {})
                i = s.get('identity', {})
                loc = s.get('location', {})
                car = self._safe_float(c.get('power', 0))
                rows.append({
                    "PCE": c.get('pdl', ''),
                    "Nom Site": i.get('site_name', ''),
                    "Adresse": loc.get('address', ''),
                    "CP": loc.get('zip_code', ''),
                    "Ville": loc.get('city', ''),
                    "CAR (MWh)": car,
                    "Profil": c.get('segment', 'T1'),
                    "Fournisseur": c.get('provider', '')
                })
            except: continue
        df_dqe = pd.DataFrame(rows)
        try:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_dqe.to_excel(writer, sheet_name='1-DQE_Sites', index=False)
        except: return b""
        output.seek(0)
        return output.getvalue()

    # =========================================================
    # MODULE 2 : MARKET WATCH (V46.1)
    # =========================================================
    def analyze_market_position(self, client_price, market_price, energy_type, segment="C5"):
        if not client_price or math.isnan(client_price) or client_price <= 0: 
            return {"status": "INCONNU", "message": "Prix non détecté", "color": "gray", "action": "Vérifier Import"}
        
        adjusted_client_price = client_price
        if client_price < 2.0: adjusted_client_price = client_price * 1000
            
        TRVE_ELEC_C5 = 230.0 
        TRVE_GAZ_T1 = 110.0
        
        reference_price = market_price
        ref_label = "marché"
        
        is_small_site = str(segment).upper() in ["C5", "C4", "T1", "T2"]
        
        if is_small_site:
            if energy_type == "elec":
                reference_price = TRVE_ELEC_C5
                ref_label = "TRVE"
            else:
                reference_price = TRVE_GAZ_T1
                ref_label = "Prix Repère"

        delta = adjusted_client_price - reference_price
        pct = (delta / reference_price) * 100
        
        if delta > 15: 
            return {"status": "ALERTE PRIX", "color": "red", "message": f"Prix excessif (+{int(pct)}% vs {ref_label}).", "action": f"Payé {int(adjusted_client_price)}€ vs {int(reference_price)}€ cible."}
        elif delta < -5: 
            return {"status": "PERFORMANCE", "color": "green", "message": f"Vous battez le {ref_label} de {abs(int(pct))}%.", "action": f"Prix {int(adjusted_client_price)}€/MWh (Top)."}
        else: 
            return {"status": "ALIGNE", "color": "blue", "message": f"Prix cohérent avec le {ref_label}.", "action": "Pas d'action requise."}

    # =========================================================
    # MODULE 3 : ROI & KPI (V46.4 - FORCE TOTAL VOLUME)
    # =========================================================
    def enrich_fleet_kpis(self, site_data):
        contract = site_data.get('contract', {}) or {}
        pricing = site_data.get('pricing', {}) or {}
        conso_det = site_data.get('consumption_details', {})
        is_gaz = "T" in str(contract.get('segment', ''))
        
        # --- CORRECTIF V46.4 : PRIORITÉ AU VOLUME TOTAL IMPORTÉ ---
        # Si le volume total a été lu dans l'Excel (colonne AA), on l'utilise en priorité
        imported_total_vol = site_data.get('contract', {}).get('annual_volume_estimated', 0)
        
        if imported_total_vol > 0:
            vol_mwh = imported_total_vol / 1000
        else:
            # Sinon on tente la somme des détails
            real_conso_kwh = (
                self._safe_float(conso_det.get('hph')) +
                self._safe_float(conso_det.get('hch')) +
                self._safe_float(conso_det.get('hpe')) +
                self._safe_float(conso_det.get('hce'))
            )
            if real_conso_kwh > 0:
                vol_mwh = real_conso_kwh / 1000
            else:
                # Fallback ultime : Estimation via Puissance
                p_sous = self._safe_float(contract.get('power'))
                if is_gaz: vol_mwh = p_sous 
                else: vol_mwh = (p_sous * 1500) / 1000 
            
        # CALCUL DU BUDGET
        price = self._safe_float(pricing.get('hph')) + self._safe_float(pricing.get('tax'))
        fix = self._safe_float(pricing.get('fix'))
        
        calc_price = price
        if price < 2.0: calc_price = price * 1000
            
        budget = fix + (vol_mwh * calc_price)
        
        day = datetime.now().timetuple().tm_yday
        landing = budget * (1 / (day/365 if day>0 else 1)) * (day/365)
        
        return {
            "budget_annual": round(budget, 2),
            "volume_mwh": round(vol_mwh, 1),
            "ghost_savings": round(budget * 0.15, 2),
            "landing_forecast": round(landing, 2),
            "is_alert_landing": False
        }

    # =========================================================
    # MODULE 4 : IMPORT MASSE V6.2 (DQE MAPPING + TOTAL VOL)
    # =========================================================
    def parse_mass_import_v5(self, file_content):
        try:
            buffer = io.BytesIO(file_content)
            try: df = pd.read_csv(buffer, sep=';', encoding='utf-8', dtype=str)
            except: 
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', dtype=str)
            
            headers = [str(c).upper() for c in df.columns]
            is_gaz = "PCE" in headers
            sites = []
            
            for _, row in df.iterrows():
                try:
                    col_entite = next((c for c in df.columns if "ENTIT" in str(c).upper()), None)
                    col_nom = next((c for c in df.columns if "NOM" in str(c).upper()), None)
                    col_adresse = next((c for c in df.columns if "ADRESSE" in str(c).upper()), None)
                    col_cp = next((c for c in df.columns if "CP" == str(c).upper() or "CODE" in str(c).upper()), None)
                    col_ville = next((c for c in df.columns if "COMMUNE" in str(c).upper() or "VILLE" in str(c).upper()), None)
                    col_siret_site = next((c for c in df.columns if "SIRET" in str(c).upper()), None)
                    col_naf = next((c for c in df.columns if "NAF" in str(c).upper()), None)
                    
                    col_cee = next((c for c in df.columns if "CEE" in str(c).upper()), None)
                    col_go = next((c for c in df.columns if "GO" in str(c).upper()), None)
                    col_prod = next((c for c in df.columns if "PRODUCTEUR" in str(c).upper()), None)
                    col_pdl = next((c for c in df.columns if "PDL" in str(c).upper() or "PRM" in str(c).upper()), None)
                    col_segment = next((c for c in df.columns if "SEGMENT" in str(c).upper()), None)
                    col_fta = next((c for c in df.columns if "FTA" in str(c).upper()), None)
                    col_grd = next((c for c in df.columns if "GRD" in str(c).upper()), None)
                    col_typo = next((c for c in df.columns if "TYPOLOGIE" in str(c).upper()), None)
                    
                    col_ps = next((c for c in df.columns if "PUISSANCE_SOUSCRITE_MAX" in str(c).upper()), None)
                    if not col_ps: col_ps = next((c for c in df.columns if "PUISSANCE" in str(c).upper()), None)
                    col_pmax = next((c for c in df.columns if "POINTE" in str(c).upper() or "MAX" in str(c).upper()), None)
                    
                    col_ps_hph = next((c for c in df.columns if "PS_HPH" in str(c).upper()), None)
                    col_ps_hch = next((c for c in df.columns if "PS_HCH" in str(c).upper()), None)
                    col_ps_hpe = next((c for c in df.columns if "PS_HPE" in str(c).upper()), None)
                    col_ps_hce = next((c for c in df.columns if "PS_HCE" in str(c).upper()), None)
                    
                    col_conso_hph = next((c for c in df.columns if "CONSO_HPH" in str(c).upper() or "HPH" in str(c).upper()), None)
                    col_conso_hch = next((c for c in df.columns if "CONSO_HCH" in str(c).upper() or "HCH" in str(c).upper()), None)
                    col_conso_hpe = next((c for c in df.columns if "CONSO_HPE" in str(c).upper() or "HPE" in str(c).upper()), None)
                    col_conso_hce = next((c for c in df.columns if "CONSO_HCE" in str(c).upper() or "HCE" in str(c).upper()), None)

                    # --- CORRECTION V46.4 : LECTURE DU VOLUME TOTAL (COLONNE AA) ---
                    col_vol_total = next((c for c in df.columns if "VOLUME_ANNUEL" in str(c).upper() or "TOTAL_ANNUEL" in str(c).upper()), None)

                    col_start = next((c for c in df.columns if "DEBUT" in str(c).upper()), None)
                    col_end = next((c for c in df.columns if "FIN" in str(c).upper()), None)
                    col_prov = next((c for c in df.columns if "FOURNISSEUR" in str(c).upper()), None)
                    col_prix = next((c for c in df.columns if "PRIX" in str(c).upper() or "MOLECULE" in str(c).upper()), None)
                    
                    # Support Multi-Prix
                    col_prix_hph = next((c for c in df.columns if "PRIX_HPH" in str(c).upper()), None)
                    if not col_prix_hph: col_prix_hph = col_prix # Fallback

                    col_abo = next((c for c in df.columns if "ABO" in str(c).upper()), None)

                    pdl = str(row.get(col_pdl, '')).strip()
                    if len(pdl) < 5: continue 

                    unique_id = pdl
                    
                    site = {
                        "client_name": str(row.get(col_entite, 'Inconnu')),
                        "identity": {
                            "id": unique_id,
                            "name": str(row.get(col_entite, 'Inconnu')),
                            "site_name": str(row.get(col_nom, 'Site Inconnu')),
                            "siret_site": str(row.get(col_siret_site, '')),
                            "naf": str(row.get(col_naf, ''))
                        },
                        "location": { 
                            "address": str(row.get(col_adresse, '')),
                            "zip_code": str(row.get(col_cp, '')),
                            "city": str(row.get(col_ville, ''))
                        },
                        "contract": {
                            "pdl": pdl,
                            "power": self._safe_float(row.get(col_ps, 0)),
                            "p_max": self._safe_float(row.get(col_pmax, 0)),
                            "segment": str(row.get(col_segment, 'C5')),
                            "fta": str(row.get(col_fta, '')),
                            "grd": str(row.get(col_grd, '')),
                            "provider": str(row.get(col_prov, 'Import CSV')),
                            "start_date": str(row.get(col_start, '')),
                            "end_date": str(row.get(col_end, '')),
                            # STOCKAGE DU VOLUME TOTAL POUR KPI
                            "annual_volume_estimated": self._safe_float(row.get(col_vol_total, 0)),
                            "power_details": {
                                "hph": self._safe_float(row.get(col_ps_hph, 0)),
                                "hch": self._safe_float(row.get(col_ps_hch, 0)),
                                "hpe": self._safe_float(row.get(col_ps_hpe, 0)),
                                "hce": self._safe_float(row.get(col_ps_hce, 0))
                            }
                        },
                        "consumption_details": {
                            "hph": self._safe_float(row.get(col_conso_hph, 0)),
                            "hch": self._safe_float(row.get(col_conso_hch, 0)),
                            "hpe": self._safe_float(row.get(col_conso_hpe, 0)),
                            "hce": self._safe_float(row.get(col_conso_hce, 0))
                        },
                        "technical": {
                            "cee_eligible": str(row.get(col_cee, 'NON')),
                            "go_percentage": str(row.get(col_go, '0')),
                            "producer_meter": str(row.get(col_prod, 'Non')),
                            "typology": str(row.get(col_typo, ''))
                        },
                        "pricing": {
                            "fix": str(row.get(col_abo, '0')),
                            "hph": str(row.get(col_prix_hph, '0')),
                            "hch": "0", "hpe": "0", "hce": "0", "tax": "0"
                        },
                        "meta": {
                            "comments": str(row.get("Commentaires", ""))
                        }
                    }
                    sites.append(site)
                except Exception as e:
                    logger.warning(f"Row Error: {e}")
                    continue
            return sites
        except Exception as e:
            logger.error(f"Import CSV Error: {e}")
            return []

    # =========================================================
    # MODULE 5 & 6 (Inchangés)
    # =========================================================
    def analyze_file(self, f, n, t="demo", k=None): return {} 
    def analyze_portfolio(self, s): 
        # COPIE EXACTE DE V45.1 (Market Share + TRVE)
        if not s: return {"error": "Aucune donnée"}
        total_conso = 0.0
        total_budget = 0.0
        sites_analysis = []
        cortex_insights = []
        suppliers_stats = {} 
        MARKET_REF_PRICE = 90.0
        POWER_OPTIM_THRESHOLD = 0.70
        for site in s:
            contract = site.get('contract', {}) or {}
            pricing = site.get('pricing', {}) or {}
            ident = site.get('identity', {}) or {}
            loc = site.get('location', {}) or {}
            p_sous = self._safe_float(contract.get('power', 0))
            p_att = self._safe_float(contract.get('p_max', 0)) 
            if 'kpis' in site and 'volume_mwh' in site['kpis']: vol = site['kpis']['volume_mwh']
            else: vol = p_sous * 1.5 
            if 'kpis' in site: budget_est = site['kpis'].get('budget_annual', 0)
            else:
                price_hph = self._safe_float(pricing.get('hph', 0))
                if price_hph < 2.0: price_hph *= 1000 
                budget_est = vol * price_hph
            pmc = (budget_est / vol) if vol > 0 else 0
            raw_provider = contract.get('provider', 'Inconnu')
            clean_provider = self._normalize_supplier(raw_provider)
            if clean_provider not in suppliers_stats: suppliers_stats[clean_provider] = 0
            suppliers_stats[clean_provider] += budget_est
            ratio_p = (p_att / p_sous) if p_sous > 0 else 1.0
            site_flags = []
            if p_sous > 36 and p_att > 0 and ratio_p < POWER_OPTIM_THRESHOLD:
                diff_kva = p_sous - p_att
                economy_pot = diff_kva * 15 
                msg = f"📉 <b>{ident.get('site_name')}</b> : {int(diff_kva)} kVA inutilisés. Gain potentiel : <b>{int(economy_pot)} €/an</b>."
                cortex_insights.append({"type": "optimization", "msg": msg, "priority": 2})
                site_flags.append("TURPE_OPTIM")
            if pmc > (MARKET_REF_PRICE * 1.3):
                surcout = (pmc - MARKET_REF_PRICE) * vol
                msg = f"💰 <b>{ident.get('site_name')}</b> : Payé {int(pmc)}€/MWh. Enjeu : <b>{int(surcout)} €/an</b>."
                cortex_insights.append({"type": "alert", "msg": msg, "priority": 1})
                site_flags.append("HIGH_PRICE")
            total_conso += vol
            total_budget += budget_est
            sites_analysis.append({
                "nom_site": ident.get('site_name', 'Inconnu'),
                "ville": loc.get('city', loc.get('address', '')),
                "fournisseur": clean_provider,
                "pmc": pmc,
                "consommation": vol,
                "depense": budget_est,
                "flags": site_flags
            })
        active_sites = [s for s in sites_analysis if s['consommation'] > 0]
        sorted_sites = sorted(active_sites, key=lambda x: x['pmc'])
        flop_3 = sorted(sorted_sites, key=lambda x: x['pmc'], reverse=True)[:3] if len(sorted_sites) > 3 else []
        global_pmc = (total_budget / total_conso) if total_conso > 0 else 0
        main_cortex = f"Parc à {int(global_pmc)}€/MWh."
        if global_pmc > MARKET_REF_PRICE: main_cortex += f" Potentiel global : {int(total_budget - (total_conso * MARKET_REF_PRICE))} € d'économies."
        else: main_cortex += " Performance achat validée."
        return {
            "kpis": { "total_conso": total_conso, "total_budget": total_budget, "global_pmc": global_pmc, "nb_sites": len(s) },
            "market_share": { "labels": list(suppliers_stats.keys()), "values": list(suppliers_stats.values()) },
            "green_league": { "gold": sorted_sites[0] if len(sorted_sites) > 0 else None, "silver": sorted_sites[1] if len(sorted_sites) > 1 else None, "bronze": sorted_sites[2] if len(sorted_sites) > 2 else None, "cancres": flop_3 },
            "cortex": { "main_message": main_cortex, "insights": sorted(cortex_insights, key=lambda x: x['priority']) },
            "raw_data": sites_analysis
        }
    def analyze_invoice_real(self, i, c): return {"score": 0, "checks": []}
    def run_chaos_monkey(self): return []
    def ask_agent(self, m): return "IA"

cortex = CortexEngine()
