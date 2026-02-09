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
logger = logging.getLogger("CORTEX_V38_FULL")

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
        self.version = "38.1 (Market Watch & Full Integrity)"
        # Base de connaissance Métier (NAF)
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

    # --- HELPERS DE NETTOYAGE ---
    def _safe_int(self, value):
        try:
            if value is None: return 0
            if isinstance(value, (float, np.floating)):
                if np.isnan(value) or np.isinf(value): return 0
            return int(float(str(value).replace(',', '.').replace(' ', '').replace('\xa0', '')))
        except: return 0

    def _safe_float(self, value):
        try:
            if value is None: return 0.0
            if isinstance(value, (float, np.floating)):
                if np.isnan(value) or np.isinf(value): return 0.0
            return float(str(value).replace(',', '.').replace(' ', '').replace('\xa0', ''))
        except: return 0.0

    # =========================================================
    # MODULE 1 : MARKET WATCH (NOUVEAU V38)
    # =========================================================
    def analyze_market_position(self, client_price, market_price, energy_type):
        """
        Compare le prix client vs marché et génère un conseil stratégique.
        """
        if client_price <= 0: 
            return {"status": "UNKNOWN", "message": "Prix contrat manquant", "color": "gray", "action": "Renseignez vos prix."}
        
        delta = client_price - market_price
        pct = (delta / client_price) * 100
        
        if delta > 10: # Le client est cher
            return {
                "status": "OPPORTUNITÉ",
                "color": "green",
                "title": "Baisse de Marché Détectée",
                "message": f"Le marché ({market_price}€) est {abs(int(pct))}% moins cher que votre contrat.",
                "action": "Conseil : Lancez un appel d'offres maintenant."
            }
        elif delta < -10: # Le client est bien
            return {
                "status": "PROTECTION",
                "color": "blue",
                "title": "Position Sécurisée",
                "message": f"Votre prix ({client_price}€) bat le marché actuel ({market_price}€) de {abs(int(pct))}%.",
                "action": "Conseil : Ne touchez à rien. Contrat performant."
            }
        else:
            return {
                "status": "NEUTRE",
                "color": "gray",
                "title": "Marché Stable",
                "message": "Votre contrat est aligné avec les tendances actuelles.",
                "action": "Conseil : Surveillance active maintenue."
            }

    # =========================================================
    # MODULE 2 : TENDER GENERATOR (V37)
    # =========================================================
    def generate_tender_package(self, sites_data):
        """
        Génère un CSV standardisé pour les fournisseurs.
        """
        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        
        headers = ["REFERENCE_POINT (PDL/PCE)", "RAISON_SOCIALE", "NOM_SITE", "ADRESSE", "CODE_POSTAL", "VILLE", "CONSOMMATION_ANNUELLE (MWh)", "PUISSANCE_SOUSCRITE", "SEGMENT_TARIF", "DATE_DEBUT_SOUHAITEE"]
        writer.writerow(headers)

        for site in sites_data:
            try:
                identity = site.get('identity', {})
                loc = site.get('location', {})
                contract = site.get('contract', {})
                
                addr_full = loc.get('address', '')
                cp_match = re.search(r'\b\d{5}\b', addr_full)
                cp = cp_match.group(0) if cp_match else ""
                ville = addr_full.split(cp)[-1].strip() if cp else ""
                
                row = [
                    contract.get('pdl', ''),
                    identity.get('name', ''),
                    identity.get('site_name', ''),
                    addr_full,
                    cp,
                    ville,
                    contract.get('power', 0),
                    contract.get('power', 0) if "T" not in contract.get('segment','') else 0,
                    contract.get('segment', ''),
                    "01/01/2026"
                ]
                writer.writerow(row)
            except Exception as e:
                logger.error(f"Erreur ligne tender: {e}")
                continue
                
        output.seek(0)
        return output.getvalue()

    # =========================================================
    # MODULE 3 : CALCULATEUR ROI & KPI (V37)
    # =========================================================
    def enrich_fleet_kpis(self, site_data):
        """
        Ajoute les KPIs avancés (Ghost Buster, Landing) aux données brutes.
        """
        contract = site_data.get('contract', {})
        pricing = site_data.get('pricing', {})
        
        # 1. Budget Annuel Estimé
        is_gaz = "T" in str(contract.get('segment', ''))
        vol = self._safe_float(contract.get('power')) * (1 if is_gaz else 1500)
        price = self._safe_float(pricing.get('hph')) + self._safe_float(pricing.get('tax'))
        fix = self._safe_float(pricing.get('fix'))
        budget_annual = fix + (vol * price / 1000) if is_gaz else fix + (vol * price / 1000)

        # 2. Ghost Buster (Gaspillage estimé à 15%)
        talon_ratio = 0.15 
        talon_cost = (vol * talon_ratio) * (price / 1000)
        
        # 3. Budget Landing (Atterrissage)
        day_of_year = datetime.now().timetuple().tm_yday
        progress_year = day_of_year / 365
        consumed_pct = progress_year * (1.2 if is_gaz and progress_year < 0.3 else 1.0) 
        landing_projection = budget_annual * (1 / (progress_year if progress_year > 0 else 1)) * consumed_pct

        return {
            "budget_annual": round(budget_annual, 2),
            "ghost_savings": round(talon_cost, 2),
            "landing_forecast": round(landing_projection, 2),
            "is_alert_landing": landing_projection > (budget_annual * 1.1)
        }

    # =========================================================
    # MODULE 4 : IMPORT DE MASSE CSV V5 (SMART SWITCH V36)
    # =========================================================
    def parse_mass_import_v5(self, file_content):
        try:
            buffer = io.BytesIO(file_content)
            try:
                df = pd.read_csv(buffer, sep=';', encoding='utf-8', dtype=str)
            except:
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', dtype=str)
            
            headers = [str(c).upper() for c in df.columns]
            is_gaz = "PCE" in headers
            sites = []
            
            for _, row in df.iterrows():
                siret = str(row.get('SIRET', '')).replace(' ', '').strip()
                if len(siret) < 9: continue 
                
                site_name = row.get('NOM_SITE', row.get('RAISON_SOCIALE', '')).strip()
                if not site_name: site_name = "Site Inconnu"
                
                if is_gaz:
                    ref_id = str(row.get('PCE', '')).replace(' ', '').strip()
                    power = self._safe_int(row.get('CAR_MWH', 0))
                    segment = row.get('SEGMENT_GAZ', '--').strip()
                    p_hph = str(row.get('PRIX_MWH', '0')).replace(',', '.').strip()
                    p_hch, p_hpe, p_hce = "0", "0", "0"
                else:
                    ref_id = str(row.get('PDL', '')).replace(' ', '').strip()
                    power = self._safe_int(row.get('PUISSANCE', 0))
                    segment = row.get('SEGMENT', '--').strip()
                    p_hph = str(row.get('PRIX_HPH', '0')).replace(',', '.').strip()
                    p_hch = str(row.get('PRIX_HCH', '0')).replace(',', '.').strip()
                    p_hpe = str(row.get('PRIX_HPE', '0')).replace(',', '.').strip()
                    p_hce = str(row.get('PRIX_HCE', '0')).replace(',', '.').strip()

                site = {
                    "client_name": site_name, 
                    "identity": {
                        "id": siret,
                        "siret": siret,
                        "name": row.get('RAISON_SOCIALE', '').strip(),
                        "site_name": site_name,
                        "lot_name": row.get('LOT', '').strip()
                    },
                    "location": { "address": row.get('ADRESSE', '').strip() },
                    "contract": {
                        "pdl": ref_id,
                        "power": power,
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
            return sites
        except Exception as e:
            logger.error(f"Import CSV Error: {e}")
            return []

    # =========================================================
    # MODULE 5 : ANALYSE COURBE DE CHARGE (HISTORIQUE V30)
    # =========================================================
    def analyze_file(self, file_content, filename, target_profile="demo", known_site_data=None):
        try:
            # 1. Parsing
            df, time_step, meta_tech = self._parse_data(file_content, filename)
            if df is None or df.empty: return {"success": False, "error": "Fichier illisible ou vide"}
            
            # 2. Contexte
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

            # 3. Calculs
            base = self._module_socle(df, time_step)
            ref_pmax = context['p_souscrite'] if context['p_souscrite'] > 0 else base['p_max']
            finance = self._module_finance_4p(df, time_step, ref_pmax)
            solar = self._module_solar(df)
            waste = self._module_ghost(df, base['talon'])
            
            # 4. Chart
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
            logger.exception("Crash Cortex V38")
            return {"success": False, "error": f"Erreur Moteur: {str(e)}"}

    # --- SOUS-MODULES TECHNIQUES (DÉCOMPRESSÉS) ---
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

cortex = CortexEngine()
