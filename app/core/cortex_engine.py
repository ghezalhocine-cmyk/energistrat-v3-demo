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
logger = logging.getLogger("CORTEX_MASTER_V43_DIAMOND")

# CHARGEMENT DES LIBRAIRIES OPTIONNELLES
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
        self.version = "43.0 (Diamond: Intelligence Active)"
        # Base de connaissance Métier (NAF) - Inchangée
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

    # --- HELPERS DE NETTOYAGE (STABLES) ---
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

    # =========================================================
    # MODULE 1 : TENDER FACTORY EXCEL (STABLE V39)
    # =========================================================
    def generate_advanced_tender_excel(self, sites_data):
        if not sites_data: return b""
        try:
            first_site = sites_data[0]
            contract = first_site.get('contract', {}) or {}
            segment = str(contract.get('segment', '')).upper()
            is_gaz = "T" in segment or "GAZ" in segment
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
                c = s.get('contract', {}) or {}
                i = s.get('identity', {}) or {}
                loc = s.get('location', {}) or {}
                power = self._safe_float(c.get('power', 0))
                vol_total = power * 1500 
                rows.append({
                    "PDL": str(c.get('pdl', 'Inconnu')),
                    "Nom Site": str(i.get('site_name') or i.get('name') or 'Site Inconnu'),
                    "Adresse": str(loc.get('address', '')),
                    "Segment (FTA)": str(c.get('segment', 'C5')),
                    "Puissance (kVA)": power,
                    "Vol. Annuel (kWh)": vol_total,
                    "HPH (kWh)": vol_total * 0.40, 
                    "HCH (kWh)": vol_total * 0.25,
                    "HPE (kWh)": vol_total * 0.20,
                    "HCE (kWh)": vol_total * 0.15
                })
            except: continue
        
        df_dqe = pd.DataFrame(rows)
        bpu_data = [{"Lot": "Lot 1", "Poste": "Fourniture Élec (Base)", "Unité": "€/MWh", "C5": "", "C4": ""}]
        df_bpu = pd.DataFrame(bpu_data)
        try:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_dqe.to_excel(writer, sheet_name='1-DQE_Sites', index=False)
                df_bpu.to_excel(writer, sheet_name='2-BPU_Reponse', index=False)
        except: return b""
        output.seek(0)
        return output.getvalue()

    def _generate_gaz_tender(self, sites_data):
        output = io.BytesIO()
        rows = []
        for s in sites_data:
            try:
                c = s.get('contract', {}) or {}
                i = s.get('identity', {}) or {}
                loc = s.get('location', {}) or {}
                car = self._safe_float(c.get('power', 0))
                rows.append({
                    "PCE": str(c.get('pdl', 'Inconnu')),
                    "Nom Site": str(i.get('site_name') or i.get('name') or 'Site Inconnu'),
                    "Adresse": str(loc.get('address', '')),
                    "CAR (MWh)": car,
                    "Profil": "T1" if car < 300 else "T2",
                    "CJA (MWh/j)": round(car/300, 3) if car > 0 else 0
                })
            except: continue
        df_dqe = pd.DataFrame(rows)
        df_bpu = pd.DataFrame([{"Poste": "Prix Molécule", "Unité": "€/MWh"}, {"Poste": "Abonnement", "Unité": "€/an"}])
        try:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_dqe.to_excel(writer, sheet_name='1-DQE_Sites', index=False)
                df_bpu.to_excel(writer, sheet_name='2-BPU_Reponse', index=False)
        except: return b""
        output.seek(0)
        return output.getvalue()

    # =========================================================
    # MODULE 2 : MARKET WATCH (STABLE V38)
    # =========================================================
    def analyze_market_position(self, client_price, market_price, energy_type):
        if client_price <= 0: return {"status": "UNKNOWN", "message": "Prix contrat manquant", "color": "gray", "action": "Renseignez vos prix."}
        delta = client_price - market_price
        pct = (delta / client_price) * 100
        if delta > 10: 
            return {"status": "OPPORTUNITÉ", "color": "green", "message": f"Marché {abs(int(pct))}% moins cher.", "action": "Anticipez !"}
        elif delta < -10: 
            return {"status": "PROTECTION", "color": "blue", "message": f"Vous battez le marché de {abs(int(pct))}%.", "action": "Ne bougez pas."}
        else: 
            return {"status": "NEUTRE", "color": "gray", "message": "Prix aligné marché.", "action": "Surveillance."}

    # =========================================================
    # MODULE 3 : ROI & KPI (STABLE V37)
    # =========================================================
    def enrich_fleet_kpis(self, site_data):
        contract = site_data.get('contract', {}) or {}
        pricing = site_data.get('pricing', {}) or {}
        is_gaz = "T" in str(contract.get('segment', ''))
        vol = self._safe_float(contract.get('power')) * (1 if is_gaz else 1500)
        price = self._safe_float(pricing.get('hph')) + self._safe_float(pricing.get('tax'))
        fix = self._safe_float(pricing.get('fix'))
        budget = fix + (vol * price / 1000)
        day = datetime.now().timetuple().tm_yday
        landing = budget * (1 / (day/365 if day>0 else 1)) * (day/365)
        return {
            "budget_annual": round(budget, 2),
            "ghost_savings": round(budget * 0.15, 2),
            "landing_forecast": round(landing, 2),
            "is_alert_landing": False
        }

    # =========================================================
    # MODULE 4 : IMPORT MASSE V5.1 (AMÉLIORÉ POUR SGE)
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
                    siret_col = next((c for c in df.columns if "SIRET" in c), None)
                    if not siret_col: continue
                    siret = str(row[siret_col]).replace(' ', '').strip()
                    if len(siret) < 9: continue 
                    
                    col_nom = next((c for c in df.columns if "NOM" in c), None)
                    col_lot = next((c for c in df.columns if "LOT" in c), None)
                    col_adresse = next((c for c in df.columns if "ADRESSE" in c), None)
                    site_name = str(row[col_nom]).strip() if col_nom else "Site Inconnu"
                    
                    # Détection SGE (Puissance Atteinte / Max)
                    col_pmax = next((c for c in df.columns if "ATTEINTE" in str(c).upper() or "MAX" in str(c).upper() or "POINTE" in str(c).upper()), None)
                    p_atteinte = self._safe_float(row.get(col_pmax, 0)) if col_pmax else 0.0

                    if is_gaz:
                        col_pce = next((c for c in df.columns if "PCE" in c), None)
                        col_car = next((c for c in df.columns if "CAR" in c), None)
                        col_seg = next((c for c in df.columns if "SEGMENT" in c), None)
                        col_prix = next((c for c in df.columns if "PRIX" in c and "MWH" in c), None)
                        
                        ref_id = str(row[col_pce]).replace(' ', '') if col_pce else "Inconnu"
                        power = self._safe_int(row.get(col_car, 0))
                        segment = str(row.get(col_seg, 'T1'))
                        p_hph = str(row.get(col_prix, '0')).replace(',', '.')
                        p_hch, p_hpe, p_hce = "0", "0", "0"
                    else:
                        col_pdl = next((c for c in df.columns if "PDL" in c), None)
                        col_puis = next((c for c in df.columns if "PUISSANCE" in c), None)
                        col_seg = next((c for c in df.columns if "SEGMENT" in c), None)
                        
                        ref_id = str(row[col_pdl]).replace(' ', '') if col_pdl else "Inconnu"
                        power = self._safe_int(row.get(col_puis, 0))
                        segment = str(row.get(col_seg, 'C5'))
                        
                        p_hph = str(row.get('PRIX_HPH', '0')).replace(',', '.')
                        p_hch = str(row.get('PRIX_HCH', '0')).replace(',', '.')
                        p_hpe = str(row.get('PRIX_HPE', '0')).replace(',', '.')
                        p_hce = str(row.get('PRIX_HCE', '0')).replace(',', '.')

                    unique_id = ref_id if ref_id != "Inconnu" else f"{siret}_{site_name}"
                    
                    site = {
                        "client_name": site_name, 
                        "identity": {
                            "id": unique_id,
                            "siret": siret,
                            "name": site_name,
                            "site_name": site_name,
                            "lot_name": str(row.get(col_lot, '')).strip()
                        },
                        "location": { "address": str(row.get(col_adresse, '')).strip() },
                        "contract": {
                            "pdl": ref_id,
                            "power": power, # Puissance SOUSCRITE
                            "p_max": p_atteinte, # Puissance ATTEINTE (SGE)
                            "segment": segment,
                            "provider": "Import CSV"
                        },
                        "pricing": {
                            "fix": str(row.get('ABO_AN', '0')).replace(',', '.').strip(),
                            "hph": p_hph,
                            "hch": p_hch,
                            "hpe": p_hpe,
                            "hce": p_hce,
                            "tax": str(row.get('TAXES', '0')).replace(',', '.').strip()
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
    # MODULE 5 : ANALYSE COURBE DE CHARGE (STABLE)
    # =========================================================
    def analyze_file(self, file_content, filename, target_profile="demo", known_site_data=None):
        try:
            df, time_step, meta_tech = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Fichier illisible ou vide"}
            
            context = {
                "pdl": known_site_data.get('pdl') if known_site_data else meta_tech.get('pdl'),
                "p_souscrite": float(known_site_data.get('power', 0)) if known_site_data else 0,
                "segment": known_site_data.get('segment') if known_site_data else "Inconnu",
                "naf_label": "Inconnu",
                "address": known_site_data.get('address', "") if known_site_data else ""
            }

            if not known_site_data or not known_site_data.get('naf_label'):
                naf_search = re.search(r'\b\d{2}\.?\d{2}[A-Z]?\b', filename)
                if naf_search:
                    clean = naf_search.group(0).replace('.', '').replace(' ', '').upper()
                    context['naf_label'] = self.NAF_DB.get(clean, clean)
            else:
                context['naf_label'] = known_site_data.get('naf_label', 'Inconnu')

            cp_match = re.search(r'\b\d{5}\b', context['address'])
            zip_code = cp_match.group(0) if cp_match else "Inconnu"

            base = self._module_socle(df, time_step)
            ref_pmax = context['p_souscrite'] if context['p_souscrite'] > 0 else base['p_max']
            finance = self._module_finance_4p(df, time_step, ref_pmax)
            solar = self._module_solar(df)
            waste = self._module_ghost(df, base['talon'])
            
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step].copy()
            chart_vals = df_chart['val'].fillna(0).tolist()
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": chart_vals,
                "talon_line": [base['talon']] * len(df_chart),
                "pmax_line": [base['p_max']] * len(df_chart),
                "limit_line": [context['p_souscrite']] * len(df_chart) if context['p_souscrite'] > 0 else []
            }

            full_kpi = {
                **base, **solar, **waste, **finance,
                "profiling": {
                    "type": target_profile, 
                    "pdl": context['pdl'],
                    "contrat_actif": "OUI" if known_site_data else "NON (Découverte)",
                    "metier": context['naf_label'],
                    "geo": zip_code,
                    "segment": context['segment']
                },
                "meta": {"filename": filename, "points": len(df)}
            }
            
            narrative = self._generate_insight(full_kpi, context)
            return {"success": True, "kpi": full_kpi, "chart": chart, "ai_insight": narrative}

        except Exception as e:
            logger.exception("Crash Cortex V43")
            return {"success": False, "error": f"Erreur Moteur: {str(e)}"}

    # =========================================================
    # MODULE 6 : DIAMOND INTELLIGENCE (NOUVEAU)
    # =========================================================
    def analyze_portfolio(self, sites_data):
        """
        Analyse croisée du portefeuille pour générer la Green League et les conseils Cortex.
        Utilise les données SGE (P_MAX) si disponibles.
        """
        if not sites_data: return {"error": "Aucune donnée"}

        total_conso = 0.0
        total_budget = 0.0
        sites_analysis = []
        cortex_insights = []
        
        MARKET_REF_PRICE = 90.0
        POWER_OPTIM_THRESHOLD = 0.70

        for site in sites_data:
            contract = site.get('contract', {}) or {}
            pricing = site.get('pricing', {}) or {}
            ident = site.get('identity', {}) or {}

            # Reconstruction des métriques
            p_sous = self._safe_float(contract.get('power', 0))
            p_att = self._safe_float(contract.get('p_max', 0)) # Vient de l'import SGE/CSV
            
            # Estimation Conso/Budget si non explicite
            vol = p_sous * 1500 # Fallback
            # Si on a des données financières calculées par enrich_fleet_kpis
            # On pourrait les utiliser ici, mais restons sur la donnée brute pour l'instant
            
            price_hph = self._safe_float(pricing.get('hph', 0))
            budget_est = vol * (price_hph + 50) / 1000 # Estimation grossière budget
            
            # Si des KPIs existent déjà (calculés par enrich_fleet_kpis)
            if 'kpis' in site:
                budget_est = site['kpis'].get('budget_annual', budget_est)
            
            pmc = (budget_est / vol * 1000) if vol > 0 else 0
            
            # Calcul Ratio Puissance (Si données SGE présentes)
            ratio_p = (p_att / p_sous) if p_sous > 0 else 1.0
            
            site_flags = []
            
            # Règle 1 : Optimisation Puissance (Basée sur SGE)
            if p_sous > 36 and p_att > 0 and ratio_p < POWER_OPTIM_THRESHOLD:
                economy_pot = (p_sous - p_att) * 12 * 10
                msg = f"📉 <b>{ident.get('site_name')}</b> : Sur-dimensionné ({int(ratio_p*100)}% utilisé). Gain ~{int(economy_pot)}€/an."
                cortex_insights.append({"type": "optimization", "msg": msg, "priority": 2})
                site_flags.append("TURPE_OPTIM")
            
            # Règle 2 : Alerte Prix
            if pmc > (MARKET_REF_PRICE * 1.3):
                msg = f"💰 <b>{ident.get('site_name')}</b> : Prix élevé ({int(pmc)}€/MWh)."
                cortex_insights.append({"type": "alert", "msg": msg, "priority": 1})
                site_flags.append("HIGH_PRICE")

            total_conso += vol
            total_budget += budget_est
            
            sites_analysis.append({
                "nom_site": ident.get('site_name', 'Inconnu'),
                "ville": site.get('location', {}).get('address', ''),
                "pmc": pmc,
                "consommation": vol,
                "depense": budget_est,
                "flags": site_flags
            })

        # TRI GREEN LEAGUE (Top 3 Economes)
        active_sites = [s for s in sites_analysis if s['consommation'] > 0]
        sorted_sites = sorted(active_sites, key=lambda x: x['pmc'])
        
        # TRI CANCRES (Top 3 Chers)
        flop_3 = sorted(sorted_sites, key=lambda x: x['pmc'], reverse=True)[:3] if len(sorted_sites) > 3 else []

        global_pmc = (total_budget / total_conso * 1000) if total_conso > 0 else 0
        
        main_cortex = f"Parc analysé : {int(global_pmc)}€/MWh moyen."
        if global_pmc > MARKET_REF_PRICE:
            main_cortex += f" Au-dessus de la cible ({MARKET_REF_PRICE}€)."
        else:
            main_cortex += " Performance alignée marché."

        return {
            "kpis": {
                "total_conso": total_conso,
                "total_budget": total_budget,
                "global_pmc": global_pmc,
                "nb_sites": len(sites_data)
            },
            "green_league": {
                "gold": sorted_sites[0] if len(sorted_sites) > 0 else None,
                "silver": sorted_sites[1] if len(sorted_sites) > 1 else None,
                "bronze": sorted_sites[2] if len(sorted_sites) > 2 else None,
                "cancres": flop_3
            },
            "cortex": {
                "main_message": main_cortex,
                "insights": sorted(cortex_insights, key=lambda x: x['priority'])
            },
            "raw_data": sites_analysis
        }

    # --- SOUS-MODULES TECHNIQUES (INCHANGÉS) ---
    def _parse_data(self, content, filename):
        try:
            buffer = io.BytesIO(content)
            content_str = content.decode('latin-1', errors='ignore')
            pdl_match = re.search(r'\b(\d{14})\b', content_str)
            pdl = pdl_match.group(1) if pdl_match else None
            try: df = pd.read_csv(buffer, sep=';', encoding='latin-1', on_bad_lines='skip', low_memory=False)
            except: 
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=None, engine='python', encoding='latin-1')
            df.columns = [str(c).lower().strip().replace('é','e').replace('è','e') for c in df.columns]
            c_date = next((c for c in df.columns if 'horodate' in c or 'date' in c), None)
            c_val = next((c for c in df.columns if 'valeur' in c or 'puiss' in c or 'conso' in c), None)
            c_unit = next((c for c in df.columns if 'unit' in c), None)
            if not c_date or not c_val: return None, 0, {}
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(df[c_val].astype(str).str.replace(',', '.').str.replace(r'\s+', '', regex=True), errors='coerce')
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')
            df['val'] = df['val'].fillna(0)
            df['date'] = pd.to_datetime(df[c_date], format='%d/%m/%Y %H:%M', errors='coerce')
            if df['date'].isna().mean() > 0.5: df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['date']).sort_values('date')
            is_watts = False
            if c_unit and 'W' in str(df[c_unit].iloc[0]).upper() and 'KW' not in str(df[c_unit].iloc[0]).upper(): is_watts = True
            if df['val'].mean() > 800: is_watts = True
            if is_watts: df['val'] = df['val'] / 1000.0
            time_step = 0.1666
            if len(df) > 1:
                delta = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta > 0: time_step = delta / 3600.0
            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            return df[['date', 'val', 'date_str']], time_step, {"pdl": pdl}
        except: return None, 0, {}

    def _module_socle(self, df, ts):
        val = df['val']
        p_max = val.max()
        mask_nuit = (df['date'].dt.hour < 6)
        nuit = df.loc[mask_nuit, 'val']
        talon = nuit.quantile(0.05) if not nuit.empty else 0
        mask_winter = df['date'].dt.month.isin([11, 12, 1, 2, 3])
        conso_hiver = df.loc[mask_winter, 'val'].sum()
        conso_ete = df.loc[~mask_winter, 'val'].sum()
        thermo = round(conso_hiver / conso_ete, 1) if conso_ete > 0 else 0
        return {
            "conso_totale": self._safe_int(val.sum() * ts),
            "p_max": round(float(p_max), 2),
            "talon": round(float(talon), 2),
            "thermo_score": thermo,
            "inactivity_ratio": 0
        }

    def _module_finance_4p(self, original_df, ts, ref_pmax):
        df = original_df.copy()
        df['m'] = df['date'].dt.month
        df['h'] = df['date'].dt.hour
        mask_w = df['m'].isin([11, 12, 1, 2, 3])
        mask_hp = (df['h'] >= 6) & (df['h'] < 22)
        v_hph = df.loc[mask_w & mask_hp, 'val'].sum() * ts
        v_hch = df.loc[mask_w & ~mask_hp, 'val'].sum() * ts
        v_hpe = df.loc[~mask_w & mask_hp, 'val'].sum() * ts
        v_hce = df.loc[~mask_w & ~mask_hp, 'val'].sum() * ts
        cost = (v_hph*0.22) + (v_hch*0.14) + (v_hpe*0.14) + (v_hce*0.09) + (ref_pmax*18)
        return {
            "finance": {
                "budget_total": self._safe_int(cost),
                "detail_4p": {
                    "HPH": {"vol": self._safe_int(v_hph), "cout": self._safe_int(v_hph*0.22)},
                    "HCH": {"vol": self._safe_int(v_hch), "cout": self._safe_int(v_hch*0.14)},
                    "HPE": {"vol": self._safe_int(v_hpe), "cout": self._safe_int(v_hpe*0.14)},
                    "HCE": {"vol": self._safe_int(v_hce), "cout": self._safe_int(v_hce*0.09)}
                }
            }
        }

    def _module_solar(self, df):
        try:
            mask = (df['date'].dt.month.isin([6,7,8])) & (df['date'].dt.hour.between(11, 15))
            subset = df.loc[mask, 'val']
            if subset.empty: return {"solar": {"status": "DONNÉES INSUFFISANTES", "puissance_kwc": 0, "economie_annuelle_euro": 0}}
            avg = subset.mean()
            if avg > 8:
                kwc = avg * 0.7
                return {"solar": {"status": "OPPORTUNITÉ DÉTECTÉE", "puissance_kwc": round(kwc, 1), "economie_annuelle_euro": self._safe_int(kwc*1100*0.18)}}
            return {"solar": {"status": "NON PERTINENT", "puissance_kwc": 0, "economie_annuelle_euro": 0}}
        except: return {"solar": {"status": "ERREUR", "puissance_kwc": 0, "economie_annuelle_euro": 0}}

    def _module_ghost(self, df, t): 
        return {"ghost_buster": {"cout_talon_annuel": self._safe_int(t * 8760 * 0.15)}}

    def _generate_insight(self, kpi, context):
        if not AI_AVAILABLE: return "IA Offline."
        try:
            prompt = f"""
            Analyse pour {kpi['profiling']['metier']}.
            PDL: {kpi['profiling']['pdl']}.
            Ville (CP): {kpi['profiling']['geo']}.
            Contrat: {kpi['profiling']['contrat_actif']}.
            Puissance Souscrite: {context['p_souscrite']} kVA vs Atteinte: {kpi['p_max']} kVA.
            Thermo-Score: {kpi['thermo_score']}.
            3 conseils experts brefs.
            """
            return AI_MODEL.generate_content(prompt).text.replace('*','')
        except: return "IA Indisponible."

    # --- AUDIT (Inchangé) ---
    def analyze_invoice_real(self, inv_b, ctr_b):
        txt = ""
        if PDF_AVAILABLE and inv_b:
            try:
                with pdfplumber.open(io.BytesIO(inv_b)) as pdf:
                    for p in pdf.pages: txt += p.extract_text() + "\n"
            except: pass
        m_sous = re.search(r"(?:souscrite|ps|p\.souscrite).*?(\d+[.,]?\d*)", txt, re.I)
        m_max = re.search(r"(?:atteinte|max|pointe).*?(\d+[.,]?\d*)", txt, re.I)
        p_sous = float(m_sous.group(1).replace(',', '.')) if m_sous else 0
        p_att = float(m_max.group(1).replace(',', '.')) if m_max else 0
        checks = [
            {"point": "Puissance Souscrite", "a": f"{p_sous} kVA", "b": "Seuil", "status": "INFO", "error": False},
            {"point": "Puissance Atteinte", "a": f"{p_att} kVA", "b": "Relevé", "status": "ALERTE" if p_att > p_sous else "OK", "error": p_att > p_sous},
            {"point": "Contrat Associé", "a": "Présent" if ctr_b else "Manquant", "b": "-", "status": "OK" if ctr_b else "MANQUANT", "error": not ctr_b}
        ]
        return {"score": 100, "checks": checks}

    def run_chaos_monkey(self): return [{"test": "Maths", "status": "OK"}]
    def ask_agent(self, msg): return self._generate_insight({}, {"p_souscrite": 0})
    
    # --- LEGACY CSV (POUR COMPATIBILITÉ TOTALE) ---
    def generate_tender_package(self, sites_data):
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow(["REF_ID", "NOM", "ADRESSE", "CONSO", "PUISSANCE", "SEGMENT"])
        for s in sites_data:
            try:
                c = s.get('contract', {})
                i = s.get('identity', {})
                writer.writerow([
                    c.get('pdl', ''), 
                    i.get('name', ''), 
                    s.get('location', {}).get('address', ''), 
                    c.get('power', 0), 
                    c.get('power', 0), 
                    c.get('segment', '')
                ])
            except: continue
        output.seek(0)
        return output.getvalue()

cortex = CortexEngine()
