import pandas as pd
import numpy as np
import io
import logging
import chardet
import re
import uuid
import zipfile
import math
from datetime import datetime, timedelta

try:
    from app.core.cortex_db import db
except ImportError:
    try:
        from core.cortex_db import db
    except ImportError:
        db = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V13_3")

class CortexIngest:
    """
    CORTEX INGEST V13.3 (LA FUSION ULTIME)
    Ingestion massive de matrices Excel (36 col) et Courbes SGE.
    Auto-Extract ZIP, Pas Dynamique (PT5M), Calcul Cos Phi et Annualisation (LTM).
    """
    def __init__(self):
        self.version = "13.3.0 (Enterprise Data Engine)"
        self.COLUMN_MAPPING = {
            # --- MAPPING COURBES SGE ---
            "horodate":["HORODATE", "DATE", "TEMPS", "HORODATAGE"],
            "valeur":["VALEUR", "SOUTIRAGE", "PUISSANCE", "ENERGIE"],
            "unite":["UNITE", "UNIT", "UNITÃ©", "UNITÉ"],
            "pas":["PAS", "INTERVALLE", "RESOLUTION"],
            "grandeur":["GRANDEUR PHY", "GRANDEUR PHYSIQUE", "NATURE"],
            # --- MAPPING MATRICE EXCEL (36 COLONNES) ---
            "pdl":["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REFERENCE", "REF_PDL"],
            "site_label":["NOM_SITE", "LIBELLE_PDL", "NOM_POINT_DE_LIVRAISON", "SITE", "LABEL", "NOM"],
            "entity":["ENTITE", "RAISON_SOCIALE", "CLIENT", "TITULAIRE", "NOM_CLIENT", "SOCIETE"],
            "siret":["SIRET", "SIRET_SITE", "SIREN"],
            "ref_copro":["REF_COPRO", "IMMATRICULATION", "REGISTRE_COPRO", "MATRICULE"],
            "naf":["NAF", "CODE_NAF", "APE", "CODE_APE"], 
            "insee":["INSEE", "CODE_INSEE", "CODE_COMMUNE"], 
            "adresse":["ADRESSE_SITE", "ADRESSE", "RUE", "LIGNE_ADRESSE"],
            "ville":["VILLE", "COMMUNE", "CITY", "TOWN"],
            "cp":["CP", "CODE_POSTAL", "ZIP", "ZIP_CODE"],
            "surface":["SURFACE", "M2", "SQM", "SURFACE_M2", "SURFACE_PLANCHER"],
            "typologie":["TYPOLOGIE", "USAGE", "TYPE_BATIMENT", "ACTIVITE"],
            "fournisseur":["FOURNISSEUR", "TITULAIRE", "PROVIDER", "MARCHE", "NOM_FOURNISSEUR"],
            "chauffage":["CHAUFFAGE", "TYPE_CHAUFFAGE", "ENERGIE_CHAUFFAGE", "SYSTEME_CVC"],
            "isolation":["ISOLATION", "TYPE_ISOLATION", "VITRAGE", "PERFORMANCE_ENVELOPPE"],
            "regulation":["REGULATION", "GTB", "GTC", "PILOTAGE"],
            "compteur_prod":["COMPTEUR_PRODUCTION", "PRODUCTEUR", "INJECTION", "COMPTEUR_PROD"],
            "puissance":["PUISSANCE", "PS", "P_SOUSCRITE", "KVA", "S MAX (KVA)", "PUISSANCE_SOUSCRITE"],
            "p_max":["POINTE_MAX", "P_MAX", "PUISSANCE_ATTEINTE", "MAX_ATTEINTE"],
            "fta":["FTA", "FORMULE_TARIFAIRE", "OPTION"],
            "cja":["CJA", "CJA_MWH_J", "CAPACITE_JOURNALIERE"],
            "profil":["PROFIL", "PROFIL_GAZ"],
            "tarif_ach":["TARIF_ACHEM", "TARIF_ACHEMINEMENT", "ATRT"],
            "conso":["CAR_MWH", "VOLUME_ANNUEL", "CONSOMMATION", "VOLUME", "CONSO", "ESTIMATION", "VOL. ANNUEL", "CJA"],
            "segment":["SEGMENT", "SEGMENT_GAZ", "TARIF", "CATEGORIE"],
            "grd":["GRD", "GESTIONNAIRE", "DISTRIBUTEUR"],
            "date_debut":["DATE_DEBUT", "DEBUT_CONTRAT", "START_DATE"],
            "date_fin":["DATE_FIN", "ECHEANCE", "FIN_CONTRAT", "END_DATE"],
            "ps_hph":["PS HPH", "PUISSANCE HPH", "P_HPH", "PS_HPH", "PS_HPH"],
            "ps_hch":["PS HCH", "PUISSANCE HCH", "P_HCH", "PS_HCH", "PS_HCH"],
            "ps_hpe":["PS HPE", "PUISSANCE HPE", "P_HPE", "PS_HPE", "PS_HPE"],
            "ps_hce":["PS HCE", "PUISSANCE HCE", "P_HCE", "PS_HCE", "PS_HCE"],
            "prix_unitaire":["PRIX_MOLECULE", "PRIX_HPH", "PRIX_UNITAIRE", "P1", "HPH", "PRIX"],
            "prix_hch":["PRIX_HCH", "HCH"],
            "prix_hpe":["PRIX_HPE", "HPE"],
            "prix_hce":["PRIX_HCE", "HCE"],
            "abonnement":["ABONNEMENT", "ABO", "FIXE", "PRIME_FIXE", "PART_FIXE"],
            "taxes":["TAXES", "CSPE", "TICGN", "CTA"],
            "stockage":["TERME_STOCK", "STOCKAGE", "TERME_STOCKAGE"]
        }

    def _clean_header(self, h):
        return str(h).upper().strip().replace('É', 'E').replace('È', 'E').replace('Ã©', 'E').replace(' ', '_').replace('.', '').replace('-', '_')

    def _find_col(self, df_cols, key):
        candidates = self.COLUMN_MAPPING.get(key,[])
        for col in df_cols:
            clean = self._clean_header(col)
            if clean in candidates: return col
            if len(key) > 3 and key not in["prix_hph", "prix_hch", "prix_hpe", "prix_hce"]: 
                for cand in candidates:
                    if cand in clean: return col
        return None

    def _safe_float(self, val):
        if pd.isna(val) or val == '' or val is None: return 0.0
        s = str(val).strip().replace('€', '').replace('%', '').replace(' ', '').replace('\xa0', '').replace('EUR', '')
        s = s.replace(',', '.')
        try: return float(s)
        except: return 0.0

    def _safe_str_clean(self, val):
        if pd.isna(val) or val == '' or val is None: return ""
        s = str(val).upper().replace(',', '.').strip()
        if 'E+' in s:
            try: return str(int(float(s)))
            except: pass
        if s.endswith('.0'): s = s[:-2]
        return s

    def extract_files_from_payload(self, file_content: bytes, filename: str):
        """ Détecte et extrait les ZIP en RAM, ou retourne le fichier CSV/XLSX brut """
        extracted =[]
        if filename.lower().endswith('.zip'):
            try:
                with zipfile.ZipFile(io.BytesIO(file_content)) as z:
                    for name in z.namelist():
                        if name.lower().endswith(('.csv', '.xlsx', '.xls')):
                            extracted.append((name, z.read(name)))
            except Exception as e:
                logger.error(f"Erreur décompression ZIP: {e}")
        else:
            extracted.append((filename, file_content))
        return extracted

    def extract_pdl_xray(self, content_bytes: bytes, filename: str, forced_id: str = None) -> str:
        """ Rayons X : Cherche le PDL dans la War Room, l'en-tête du fichier ou le titre """
        if forced_id: return forced_id
        
        try:
            head = content_bytes[:4000].decode('utf-8', errors='ignore')
            sci_match = re.search(r'(3[\.,]00\d{2})E\+13', head, re.IGNORECASE)
            if sci_match:
                clean_sci = sci_match.group(1).replace(',', '').replace('.', '')
                return clean_sci.ljust(14, '0')
            matches = re.findall(r'\b(?!202\d)(\d{14})\b', head)
            if matches: return matches[0]
        except: pass
        
        pdl_match = re.search(r'\b(?!202\d)(\d{14})\b', filename.upper())
        if pdl_match: return pdl_match.group(1)
        return None

    # =========================================================
    # 1. ANALYSE DE LA MATRICE EXCEL (L'Héritage)
    # =========================================================
    def parse_mass_import_unified(self, file_content):
        sites =[]
        df = None
        buffer = io.BytesIO(file_content)
        try: df = pd.read_excel(buffer, dtype=str)
        except:
            try: buffer.seek(0); df = pd.read_csv(buffer, sep=';', encoding='latin-1', dtype=str, on_bad_lines='skip')
            except:
                try: buffer.seek(0); df = pd.read_csv(buffer, sep=',', encoding='utf-8', dtype=str, on_bad_lines='skip')
                except: return[]

        if df is None or df.empty: return[]

        cols = df.columns
        c_pdl = self._find_col(cols, "pdl")
        c_siret = self._find_col(cols, "siret")
        
        if not c_pdl and not c_siret: return[]

        # Mapping des 36 colonnes
        c_nom = self._find_col(cols, "site_label")
        c_addr = self._find_col(cols, "adresse")
        c_cp = self._find_col(cols, "cp")
        c_ville = self._find_col(cols, "ville")
        c_ref_copro = self._find_col(cols, "ref_copro")
        c_naf = self._find_col(cols, "naf") 
        c_surface = self._find_col(cols, "surface")
        c_typologie = self._find_col(cols, "typologie")
        c_fourn = self._find_col(cols, "fournisseur")
        c_puiss = self._find_col(cols, "puissance")
        c_seg = self._find_col(cols, "segment")

        for idx, row in df.iterrows():
            try:
                pdl = self._safe_str_clean(row.get(c_pdl, "")) if c_pdl else ""
                siret = self._safe_str_clean(row.get(c_siret, "")) if c_siret else ""
                site_id = pdl if pdl else (siret if siret else f"GEN_{uuid.uuid4().hex[:8]}")
                
                nom_brut = str(row.get(c_nom, "")).strip() if c_nom else ""
                final_name = nom_brut if nom_brut else f"Site {site_id}"
                segment = str(row.get(c_seg, "")).upper() if c_seg else ""
                
                is_gas = "GAZ" in segment or "T1" in segment or "T2" in segment or "T3" in segment or "PCE" in str(c_pdl).upper()
                energy_type = "gaz" if is_gas else "elec"

                site = {
                    "identity": { "id": site_id, "site_name": final_name, "siret": siret, "ref_copro": self._safe_str_clean(row.get(c_ref_copro)) if c_ref_copro else "", "naf": self._safe_str_clean(row.get(c_naf)) if c_naf else "" },
                    "location": { "address": str(row.get(c_addr, "")) if c_addr else "", "zip_code": self._safe_str_clean(row.get(c_cp, "")) if c_cp else "", "city": str(row.get(c_ville, "")).strip() if c_ville else "", "surface": self._safe_float(row.get(c_surface)) if c_surface else 0.0, "typologie": self._safe_str_clean(row.get(c_typologie)) if c_typologie else "" },
                    "contract": { "pdl": pdl, "provider": self._safe_str_clean(row.get(c_fourn, "")) if c_fourn else "Inconnu", "segment": segment, "power": self._safe_float(row.get(c_puiss)) if c_puiss else 0.0, "energy_type": energy_type }
                }
                
                if db: db.save_site(site_id, site)
                sites.append(site)
            except Exception as e: logger.error(f"Erreur Matrice: {e}")
        return sites

    # =========================================================
    # 2. MOTEUR D'INGESTION GLOBAL (LE TAPIS ROULANT)
    # =========================================================
    def process_smart_upload(self, file_content: bytes, filename: str, forced_site_id: str = None):
        """ Déplie les ZIP, aiguille vers Excel ou SGE, calcule le Cos Phi et l'Annualisation """
        files = self.extract_files_from_payload(file_content, filename)
        report =[]

        for fname, fcontent in files:
            fname_up = fname.upper()
            
            # A. MATRICE EXCEL
            if not ("ENEDIS" in fname_up or "GRDF" in fname_up or "CDC" in fname_up):
                imported = self.parse_mass_import_unified(fcontent)
                if imported: report.append({"filename": fname, "status": "INGESTED", "message": f"{len(imported)} compteurs synchronisés via Matrice."})
                else: report.append({"filename": fname, "status": "ERROR", "message": "Matrice Excel/CSV non reconnue ou vide."})
                continue

            # B. COURBES DE CHARGE SGE / ENEDIS
            try:
                pdl = self.extract_pdl_xray(fcontent, fname, forced_site_id)
                if not pdl:
                    report.append({"filename": fname, "status": "ERROR", "message": "PDL (14 chiffres) introuvable dans le fichier ou le titre."})
                    continue

                # Encodage & Parsing
                enc = 'utf-8'
                try: enc = chardet.detect(fcontent[:10000])['encoding'] or 'utf-8'
                except: pass

                df = None
                buffer = io.BytesIO(fcontent)
                for sep in [';', '\t', ',']:
                    buffer.seek(0)
                    try:
                        temp_df = pd.read_csv(buffer, sep=sep, encoding=enc, on_bad_lines='skip', engine='python')
                        if len(temp_df.columns) > 3: 
                            df = temp_df
                            break
                    except: continue

                if df is None or df.empty:
                    report.append({"filename": fname, "status": "ERROR", "message": "Fichier CSV Enedis illisible ou corrompu."})
                    continue

                col_date = self._find_col(df.columns, 'horodate')
                col_val = self._find_col(df.columns, 'valeur')
                col_unit = self._find_col(df.columns, 'unite')
                col_pas = self._find_col(df.columns, 'pas')
                col_grandeur = self._find_col(df.columns, 'grandeur')

                if not col_date or not col_val:
                    report.append({"filename": fname, "status": "ERROR", "message": "Colonnes Horodate/Valeur introuvables."})
                    continue

                df = df.rename(columns={col_date: 'date', col_val: 'val'})
                df['val'] = df['val'].apply(self._safe_float)
                
                is_watt = False
                if col_unit and not df[col_unit].dropna().empty:
                    if "W" in str(df[col_unit].dropna().iloc[0]).upper() and "KW" not in str(df[col_unit].dropna().iloc[0]).upper() and "MW" not in str(df[col_unit].dropna().iloc[0]).upper():
                        is_watt = True
                if is_watt: df['val'] = df['val'] / 1000.0

                # Séparation Active (PA) vs Réactive (PR)
                df_pa = df
                df_pr = pd.DataFrame()
                if col_grandeur:
                    df['grandeur_clean'] = df[col_grandeur].astype(str).str.upper()
                    df_pa = df[df['grandeur_clean'].str.contains('PA|ACTI', na=False)]
                    df_pr = df[df['grandeur_clean'].str.contains('PR|REACT', na=False)]
                    if df_pa.empty: df_pa = df

                # Time Parsing
                df_pa['date'] = pd.to_datetime(df_pa['date'], dayfirst=True, errors='coerce', utc=True)
                df_pa = df_pa.dropna(subset=['date', 'val']).sort_values(by='date')
                
                if df_pa.empty: continue

                # DÉTECTION DU PAS DYNAMIQUE (PT5M, PT10M...)
                delta_minutes = 10.0 
                if col_pas and not df_pa[col_pas].dropna().empty:
                    pas_match = re.search(r'PT(\d+)M', str(df_pa[col_pas].dropna().iloc[0]).upper())
                    if pas_match: delta_minutes = float(pas_match.group(1))
                else:
                    if len(df_pa) > 1:
                        calc_delta = (df_pa['date'].iloc[1] - df_pa['date'].iloc[0]).total_seconds() / 60.0
                        if calc_delta > 0: delta_minutes = calc_delta

                # CALCULS : Pmax, Volume & Cos Phi
                pmax_kw = float(df_pa['val'].max())
                total_kwh_brut = float(df_pa['val'].sum() * (delta_minutes / 60.0))
                
                # ANNUALISATION LTM (Pour éviter les 3 GWh sur 2 ans)
                days_covered = (df_pa['date'].iloc[-1] - df_pa['date'].iloc[0]).days
                if days_covered < 1: days_covered = 1
                volume_mwh_annuel = (total_kwh_brut / 1000.0)
                
                if abs(days_covered - 365) > 15:
                    volume_mwh_annuel = (volume_mwh_annuel / days_covered) * 365.0

                cos_phi = 1.0
                if not df_pr.empty:
                    df_pr['val'] = df_pr['val'].apply(self._safe_float)
                    if is_watt: df_pr['val'] = df_pr['val'] / 1000.0
                    total_kvarh = float(df_pr['val'].sum() * (delta_minutes / 60.0))
                    if total_kwh_brut > 0:
                        cos_phi = total_kwh_brut / math.sqrt((total_kwh_brut**2) + (total_kvarh**2))

                # SAUVEGARDE EN BASE 3D (Hot Data)
                if db:
                    site_data = db.get_site(pdl) or {}
                    if 'identity' not in site_data: site_data['identity'] = {'id': pdl, 'site_name': f"Site {pdl}"}
                    if 'contract' not in site_data: site_data['contract'] = {'pdl': pdl}
                    if 'kpis' not in site_data: site_data['kpis'] = {}
                    
                    site_data['kpis']['volume_mwh'] = round(volume_mwh_annuel, 2)
                    site_data['kpis']['pmax_kw'] = round(pmax_kw, 2)
                    site_data['kpis']['cos_phi'] = round(cos_phi, 3)
                    site_data['kpis']['has_load_curve'] = True
                    
                    db.save_site(pdl, site_data)

                    # Cold Data Logic : En V13, les 50000 points bruts vont dans LoadCurves_Archive
                    try:
                        archive_ref = db.db.collection("LoadCurves_Archive").document(pdl)
                        archive_ref.set({"last_update": datetime.now().isoformat(), "days_covered": days_covered, "pas_minutes": delta_minutes}, merge=True)
                    except: pass

                report.append({
                    "filename": fname, "status": "INGESTED", 
                    "message": f"Courbe SGE ({pdl}) : {round(volume_mwh_annuel, 1)} MWh (Annualisé), Pmax {round(pmax_kw)} kW, CosΦ {round(cos_phi, 2)}"
                })

            except Exception as e:
                report.append({"filename": fname, "status": "ERROR", "message": f"Erreur critique: {str(e)}"})

        return report

ingest = CortexIngest()
# --- END OF FILE cortex_ingest.py ---
