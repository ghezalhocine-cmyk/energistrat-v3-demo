import pandas as pd
import numpy as np
import io
import re
import logging
import csv
import chardet

# CONFIGURATION LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V56_DIAMOND")

# DEPENDANCES OPTIONNELLES
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("PDFPlumber manquant : L'analyse des factures PDF sera désactivée.")

class CortexIngest:
    def __init__(self):
        self.version = "56.0 (Diamond Protocol: Unit Norm + Gas Detection + Site Identity)"
        self.supported_formats = ['.csv', '.xlsx', '.xls', '.txt', '.pdf']
        
        # =========================================================
        # DICTIONNAIRE DE MAPPING UNIVERSEL (LE CERVEAU DU PARSER)
        # =========================================================
        self.COLUMN_MAPPING = {
            # 1. IDENTIFICATION & FLUIDE (CORRECTION CRITIQUE)
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REF_PDL", "REFERENCE"],
            "type_fluide": ["ENERGIE", "FLUIDE", "TYPE", "ENERGY_TYPE"], # NOUVEAU
            "unite": ["UNITE", "UNIT", "U_MESURE", "UNIT_CONSO"], # NOUVEAU
            
            # 2. IDENTITÉ (SÉPARATION SITE / ENTITÉ)
            "site_label": ["NOM_SITE", "LIBELLE_SITE", "SITE_LABEL", "NOM_POINT_DE_LIVRAISON", "SITE"],
            "entity_name": ["RAISON_SOCIALE", "CLIENT", "ENTITE", "SOCIETE", "ACCOUNT_NAME", "TITULAIRE"],
            "siret": ["SIRET_SITE", "SIRET", "SIREN"],
            "naf": ["NAF", "CODE_NAF", "APE"],
            
            # 3. LOCALISATION
            "adresse": ["ADRESSE_SITE", "ADRESSE", "RUE", "LIGNE_ADRESSE", "ADDRESS"],
            "cp": ["CP", "CODE_POSTAL", "ZIP", "ZIP_CODE"],
            "ville": ["VILLE", "COMMUNE", "CITY", "TOWN"],
            "surface": ["SURFACE_M2", "SURFACE", "M2", "SHAB", "SU", "S_UTILE"],
            
            # 4. CONTRAT & TECH
            "segment": ["SEGMENT", "SEGMENT_GAZ", "TARIF", "CATEGORY"],
            "fournisseur": ["FOURNISSEUR", "PROVIDER", "SUPPLIER"],
            "date_fin": ["DATE_FIN", "ECHEANCE", "END_DATE"],
            "date_debut": ["DATE_DEBUT", "START_DATE"],
            "puissance": ["PUISSANCE_SOUSCRITE_MAX", "PUISSANCE", "PS_MAX", "CAR_MWH", "CAR", "P_SOUSCRITE"],
            "conso": ["VOLUME_ANNUEL_TOTAL", "CONSO_ANNUELLE", "VOLUME", "CJA_MWH_J", "CJA", "ESTIMATION", "CONSOMMATION"],
            "profil": ["PROFIL", "PROFILE"],
            "grd": ["GRD", "DISTRIBUTEUR"],
            
            # 5. DETAILS PUISSANCE ELEC (4 Postes - Expert)
            "ps_hph": ["PS_HPH", "P_HPH"], 
            "ps_hch": ["PS_HCH", "P_HCH"], 
            "ps_hpe": ["PS_HPE", "P_HPE"], 
            "ps_hce": ["PS_HCE", "P_HCE"],
            
            # 6. PRIX & BUDGET
            "abonnement": ["ABONNEMENT", "ABO", "PRIME_FIXE", "PART_FIXE"],
            "prix_hph": ["PRIX_HPH", "PRIX_UNITAIRE", "PRIX_MOLECULE_MWH", "PRIX_MOLECULE", "HPH"], 
            "prix_hch": ["PRIX_HCH", "HCH"], 
            "prix_hpe": ["PRIX_HPE", "HPE"], 
            "prix_hce": ["PRIX_Hce", "HCE"],
            "taxes": ["TAXES", "CSPE", "TICGN", "CTA"],
            "stockage": ["TERME_STOCKAGE", "TERME_STOCKAGE_CPB", "STOCKAGE"], # Specifique Gaz
            "tarif_acheminement": ["TARIF_ACHEMINEMENT", "ATRT", "TURPE"],
            
            # 7. OPH / HABITAT / SOCIAL
            "p1": ["BUDGET_P1", "P1", "COUT_ENERGIE", "CHARGES_RECUPERABLES"], 
            "p2": ["BUDGET_P2", "P2", "MAINTENANCE", "P2_FORFAIT"],
            "p3": ["BUDGET_P3", "P3", "GROS_ENTRETIEN"],
            "tantiemes": ["TANTIEMES", "PART_COPRO", "MILLIEMES"], 
            "dpe": ["DPE", "ETIQUETTE", "CLASSE_ENERGIE"],
            "chauffage": ["CHAUFFAGE", "TYPE_CHAUFFAGE", "SYSTEME_CHAUFFE"],
            "cee": ["CEE_ELIGIBLE", "PRIME_CEE"]
        }

    # =========================================================
    # UTILITAIRES DE ROBUSTESSE (SAFETY FIRST)
    # =========================================================

    def _clean_header(self, header):
        """ Nettoyage agressif des entêtes pour matcher le dico """
        return str(header).upper().strip().replace(' ', '_').replace('.', '').replace('É', 'E').replace('È', 'E').replace('-', '_')

    def _find_col(self, df_cols, key):
        """ Recherche floue intelligente """
        candidates = self.COLUMN_MAPPING.get(key, [])
        # 1. Match Exact (Nettoyé)
        for col in df_cols:
            clean = self._clean_header(col)
            if clean in candidates: return col 
        # 2. Match Partiel (Contient)
        for col in df_cols:
            clean = self._clean_header(col)
            for cand in candidates:
                if cand in clean: return col 
        return None

    def _safe_float(self, val):
        """ Conversion blindée en float """
        if pd.isna(val) or val == '' or val is None: return 0.0
        # Gère 1 000,50 et 1.000,50 et les symboles
        s = str(val).replace(' ', '').replace('\xa0', '').replace('€', '').replace('%', '').replace('kVA', '').replace('kW', '').replace('MWh', '').replace('kWh', '')
        s = s.replace(',', '.')
        try: return float(s)
        except: return 0.0

    def _safe_str_clean(self, val):
        """ Nettoie les notations scientifiques Excel (ex: 2,14E+13 -> 21400000000000) """
        if pd.isna(val) or val == '' or val is None: return ""
        s = str(val).replace(',', '.')
        try:
            if 'E+' in s or 'e+' in s:
                return str(int(float(s))) 
            if '.' in s and s.replace('.', '').isdigit():
                return str(int(float(s))) 
            return s.strip()
        except:
            return str(val).strip()

    def _detect_encoding(self, buffer):
        raw = buffer.read(20000)
        buffer.seek(0)
        result = chardet.detect(raw)
        return result['encoding'] or 'utf-8'

    # =========================================================
    # 1. IMPORT UNIFIÉ (ELEC + GAZ + OPH + INDUSTRIE)
    # =========================================================
    def parse_mass_import_unified(self, file_content):
        """
        Le Moteur d'Ingestion Principal.
        FIX: Normalise les unités et sépare Gaz/Elec.
        """
        sites = []
        df = None
        buffer = io.BytesIO(file_content)

        # 1. Lecture Robuste
        try:
            df = pd.read_excel(buffer)
        except:
            buffer.seek(0)
            enc = self._detect_encoding(buffer)
            buffer.seek(0)
            try: df = pd.read_csv(buffer, sep=';', encoding=enc, dtype=str, on_bad_lines='skip')
            except: 
                buffer.seek(0)
                try: df = pd.read_csv(buffer, sep=',', encoding=enc, dtype=str, on_bad_lines='skip')
                except:
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep='\t', encoding=enc, dtype=str, on_bad_lines='skip')

        if df is None or df.empty:
            logger.error("Echec lecture fichier : Format non reconnu")
            return []

        cols = df.columns
        logger.info(f"Colonnes détectées : {list(cols)}")
        
        # 2. Mapping des Colonnes (Automatique)
        c_pdl = self._find_col(cols, "pdl")
        c_fluide = self._find_col(cols, "type_fluide")
        c_unite = self._find_col(cols, "unite") # FIX UNITÉS
        
        # Identité
        c_site_label = self._find_col(cols, "site_label")
        c_entity = self._find_col(cols, "entity_name")
        # Fallback ancien mapping si colonnes spécifiques absentes
        if not c_site_label: c_site_label = self._find_col(cols, "site_label") # Cherche encore "NOM_SITE"
        if not c_entity: c_entity = c_site_label # Si pas d'entité, on prend le site par défaut

        c_addr = self._find_col(cols, "adresse")
        c_cp = self._find_col(cols, "cp")
        c_ville = self._find_col(cols, "ville")
        c_siret = self._find_col(cols, "siret")
        c_naf = self._find_col(cols, "naf")
        c_surf = self._find_col(cols, "surface")
        
        c_puiss = self._find_col(cols, "puissance")
        c_conso = self._find_col(cols, "conso")
        c_seg = self._find_col(cols, "segment")
        c_prov = self._find_col(cols, "fournisseur")
        c_end = self._find_col(cols, "date_fin")
        c_start = self._find_col(cols, "date_debut")
        c_grd = self._find_col(cols, "grd")
        
        # Prix
        c_abo = self._find_col(cols, "abonnement")
        c_tax = self._find_col(cols, "taxes")
        c_p_hph = self._find_col(cols, "prix_hph") # Prix unitaire générique

        # 3. Extraction
        for idx, row in df.iterrows():
            try:
                # A. IDENTIFICATION & FLUIDE
                pdl = self._safe_str_clean(row.get(c_pdl, f'TMP{idx}'))
                
                # Détection Gaz vs Elec (Logique Heuristique)
                raw_fluide = str(row.get(c_fluide, '')).upper()
                is_gas = False
                if 'GAZ' in raw_fluide or 'GAS' in raw_fluide:
                    is_gas = True
                elif 'PCE' in str(c_pdl).upper(): # Si la colonne s'appelle PCE
                    is_gas = True
                elif len(pdl) != 14 and pdl.isdigit(): # PDL Elec = 14 chiffres. PCE souvent différent ou string GI
                    pass # Pas concluant mais indice
                
                energy_type = 'gas' if is_gas else 'elec'

                # B. NORMALISATION UNITÉS (Wh/MWh -> kWh)
                raw_conso = self._safe_float(row.get(c_conso))
                raw_unit = str(row.get(c_unite, '')).upper()
                
                conso_kwh = raw_conso
                if 'MWH' in raw_unit:
                    conso_kwh = raw_conso * 1000.0
                elif 'WH' in raw_unit and 'KWH' not in raw_unit:
                    conso_kwh = raw_conso / 1000.0
                
                # C. NOMMAGE (Traçabilité)
                site_name = str(row.get(c_site_label, ''))
                entity_name = str(row.get(c_entity, ''))
                
                if not site_name and entity_name: site_name = entity_name
                if not site_name: site_name = f"Site {pdl}"

                # Objet Site Standardisé (Format attendu par CortexEngine)
                site = {
                    "client_name": entity_name, # Pour la facturation
                    "identity": { 
                        "id": pdl, 
                        "site_label": site_name, # VRAI NOM DU SITE
                        "entity_name": entity_name, # VRAIE ENTITÉ
                        "siret": self._safe_str_clean(row.get(c_siret, '')), 
                        "naf": str(row.get(c_naf, '')) 
                    },
                    "location": {
                        "address": str(row.get(c_addr, '')),
                        "zip_code": self._safe_str_clean(row.get(c_cp, '')),
                        "city": str(row.get(c_ville, '')),
                        "surface": self._safe_float(row.get(c_surf))
                    },
                    "contract": {
                        "pdl": pdl,
                        "energy_type": energy_type, # CHAMP CRITIQUE RAJOUTÉ
                        "power": self._safe_float(row.get(c_puiss)),
                        "segment": str(row.get(c_seg, '')),
                        "provider": str(row.get(c_prov, 'Inconnu')),
                        "annual_volume_estimated": conso_kwh, # VALEUR NORMALISÉE
                        "unit": "kWh", # TOUJOURS kWh
                        "start_date": str(row.get(c_start, '')),
                        "end_date": str(row.get(c_end, '')),
                        "grd": str(row.get(c_grd, ''))
                    },
                    "pricing": {
                        "fix": self._safe_float(row.get(c_abo)),
                        "unit_price_ht": self._safe_float(row.get(c_p_hph)), # Prix moyen ou HPH
                        "tax": self._safe_float(row.get(c_tax))
                    }
                }
                sites.append(site)
            except Exception as e:
                logger.warning(f"Erreur extraction ligne {idx}: {e}")
                continue

        logger.info(f"Import {len(sites)} sites OK. (Dont Gaz détectés via logique heuristique)")
        return sites

    # =========================================================
    # 2. PARSING COURBE DE CHARGE (LEGACY) - INCHANGÉ
    # =========================================================
    def parse_load_curve(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            enc = self._detect_encoding(buffer)
            content_str = file_content.decode(enc, errors='ignore')
            pdl_match = re.search(r'(?<!\d)(\d{14})(?!\d)', content_str) or re.search(r'(?<!\d)(\d{14})(?!\d)', filename)
            pdl = pdl_match.group(1) if pdl_match else "Inconnu"
            
            buffer.seek(0)
            lines = content_str.split('\n')
            header_row = 0
            for i, line in enumerate(lines[:50]):
                if "DATE" in line.upper() or "HORODATAGE" in line.upper():
                    header_row = i
                    break
            
            buffer.seek(0)
            df = pd.read_csv(buffer, sep=';', encoding=enc, skiprows=header_row, on_bad_lines='skip', low_memory=False)
            if len(df.columns) < 2:
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=',', encoding=enc, skiprows=header_row, on_bad_lines='skip', low_memory=False)

            df.columns = [self._clean_header(c) for c in df.columns]
            col_date = next((c for c in df.columns if "DATE" in c or "HORODATAGE" in c), None)
            col_val = next((c for c in df.columns if "PUISSANCE" in c or "VALEUR" in c or "KWH" in c), None)
            
            if not col_date or not col_val: return None, 0, {}
            
            df = df.rename(columns={col_date: 'date', col_val: 'val'})
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
            df['val'] = pd.to_numeric(df['val'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
            df = df.dropna(subset=['date']).sort_values('date')
            
            if df.empty: return None, 0, {}
            delta = (df['date'].iloc[1] - df['date'].iloc[0]).total_seconds() / 60
            time_step = int(delta) if delta > 0 else 10
            
            return df, time_step, {"pdl": pdl}
        except Exception as e:
            logger.error(f"Load Curve Error: {e}")
            return None, 0, {}

    def parse_bpu_excel(self, file_content):
        # ... (Code BPU existant conservé) ...
        try:
            buffer = io.BytesIO(file_content)
            xls = pd.ExcelFile(buffer)
            sheet_elec = next((s for s in xls.sheet_names if "ELEC" in s.upper()), None)
            sheet_gaz = next((s for s in xls.sheet_names if "GAZ" in s.upper()), None)
            is_gaz = False
            df = None
            if sheet_gaz:
                df = pd.read_excel(xls, sheet_name=sheet_gaz)
                is_gaz = True
            elif sheet_elec:
                df = pd.read_excel(xls, sheet_name=sheet_elec)
                is_gaz = False
            else:
                df = pd.read_excel(xls, sheet_name=0)
            return df, is_gaz
        except: return None, False

ingest = CortexIngest()
