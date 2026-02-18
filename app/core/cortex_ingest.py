import pandas as pd
import numpy as np
import io
import re
import logging
import csv
import chardet

# CONFIGURATION LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V55_MAX")

# DEPENDANCES OPTIONNELLES
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("PDFPlumber manquant : L'analyse des factures PDF sera désactivée.")

class CortexIngest:
    def __init__(self):
        self.version = "55.0 (Maximalist: Elec Expert + Gaz Expert + OPH + Legacy Support)"
        self.supported_formats = ['.csv', '.xlsx', '.xls', '.txt', '.pdf']
        
        # =========================================================
        # DICTIONNAIRE DE MAPPING UNIVERSEL (LE CERVEAU DU PARSER)
        # =========================================================
        self.COLUMN_MAPPING = {
            # 1. IDENTIFICATION
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REF_PDL", "REFERENCE"],
            "nom": ["NOM_SITE", "NOM", "ENTITE", "RAISON_SOCIALE", "CLIENT", "SITE", "ACCOUNT_NAME"],
            "siret": ["SIRET_SITE", "SIRET", "SIREN"],
            "naf": ["NAF", "CODE_NAF", "APE"],
            
            # 2. LOCALISATION
            "adresse": ["ADRESSE_SITE", "ADRESSE", "RUE", "LIGNE_ADRESSE", "ADDRESS"],
            "cp": ["CP", "CODE_POSTAL", "ZIP", "ZIP_CODE"],
            "ville": ["VILLE", "COMMUNE", "CITY", "TOWN"],
            "surface": ["SURFACE_M2", "SURFACE", "M2", "SHAB", "SU", "S_UTILE"],
            
            # 3. CONTRAT & TECH
            "segment": ["SEGMENT", "SEGMENT_GAZ", "TARIF", "CATEGORY"],
            "fournisseur": ["FOURNISSEUR", "PROVIDER", "SUPPLIER"],
            "date_fin": ["DATE_FIN", "ECHEANCE", "END_DATE"],
            "date_debut": ["DATE_DEBUT", "START_DATE"],
            "puissance": ["PUISSANCE_SOUSCRITE_MAX", "PUISSANCE", "PS_MAX", "CAR_MWH", "CAR", "P_SOUSCRITE"],
            "conso": ["VOLUME_ANNUEL_TOTAL", "CONSO_ANNUELLE", "VOLUME", "CJA_MWH_J", "CJA", "ESTIMATION"],
            "profil": ["PROFIL", "PROFILE"],
            "grd": ["GRD", "DISTRIBUTEUR"],
            
            # 4. DETAILS PUISSANCE ELEC (4 Postes - Expert)
            "ps_hph": ["PS_HPH", "P_HPH"], 
            "ps_hch": ["PS_HCH", "P_HCH"], 
            "ps_hpe": ["PS_HPE", "P_HPE"], 
            "ps_hce": ["PS_HCE", "P_HCE"],
            
            # 5. DETAILS CONSO ELEC (4 Postes - Expert)
            "conso_hph": ["CONSO_HPH", "C_HPH"], 
            "conso_hch": ["CONSO_HCH", "C_HCH"], 
            "conso_hpe": ["CONSO_HPE", "C_HPE"], 
            "conso_hce": ["CONSO_HCE", "C_HCE"],
            
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
        s = str(val).replace(' ', '').replace('\xa0', '').replace('€', '').replace('%', '').replace('kVA', '').replace('kW', '').replace('MWh', '')
        s = s.replace(',', '.')
        try: return float(s)
        except: return 0.0

    def _safe_int(self, val):
        return int(self._safe_float(val))

    def _safe_str_clean(self, val):
        """ Nettoie les notations scientifiques Excel (ex: 2,14E+13 -> 21400000000000) """
        if pd.isna(val) or val == '' or val is None: return ""
        s = str(val).replace(',', '.')
        try:
            # Si c'est un float qui ressemble à un entier (SIRET/PDL)
            if 'E+' in s or 'e+' in s:
                return str(int(float(s))) # Conversion scientifique -> entier -> string
            if '.' in s and s.replace('.', '').isdigit():
                return str(int(float(s))) # Enlève le .0 à la fin
            return s.strip()
        except:
            return str(val).strip()

    def _detect_encoding(self, buffer):
        """ Détecte l'encodage du fichier """
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
        Accepte CSV (tous séparateurs) et Excel (tous onglets).
        """
        sites = []
        df = None
        buffer = io.BytesIO(file_content)

        # 1. Lecture Robuste
        try:
            # Priorité Excel
            df = pd.read_excel(buffer)
        except:
            # Fallback CSV avec détection
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
        c_nom = self._find_col(cols, "nom")
        c_pdl = self._find_col(cols, "pdl")
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
        c_profil = self._find_col(cols, "profil")
        c_tarif_ach = self._find_col(cols, "tarif_acheminement")
        
        # Elec Détail
        c_ps_hph = self._find_col(cols, "ps_hph")
        c_ps_hch = self._find_col(cols, "ps_hch")
        c_ps_hpe = self._find_col(cols, "ps_hpe")
        c_ps_hce = self._find_col(cols, "ps_hce")
        
        c_c_hph = self._find_col(cols, "conso_hph")
        c_c_hch = self._find_col(cols, "conso_hch")
        c_c_hpe = self._find_col(cols, "conso_hpe")
        c_c_hce = self._find_col(cols, "conso_hce")
        
        # Prix & OPH
        c_p_hph = self._find_col(cols, "prix_hph")
        c_p_hch = self._find_col(cols, "prix_hch")
        c_p_hpe = self._find_col(cols, "prix_hpe")
        c_p_hce = self._find_col(cols, "prix_hce")
        c_abo = self._find_col(cols, "abonnement")
        c_tax = self._find_col(cols, "taxes")
        c_stock = self._find_col(cols, "stockage") 
        
        c_p1 = self._find_col(cols, "p1")
        c_p2 = self._find_col(cols, "p2")
        c_p3 = self._find_col(cols, "p3")
        c_dpe = self._find_col(cols, "dpe")
        c_tant = self._find_col(cols, "tantiemes")
        c_chauff = self._find_col(cols, "chauffage")
        c_cee = self._find_col(cols, "cee")

        # 3. Extraction
        for idx, row in df.iterrows():
            try:
                # Identification
                nom = str(row.get(c_nom, f'Site {idx}'))
                pdl = self._safe_str_clean(row.get(c_pdl, f'TMP{idx}'))
                siret = self._safe_str_clean(row.get(c_siret, ''))

                # Objet Site Standardisé
                site = {
                    "client_name": nom,
                    "identity": { 
                        "id": pdl, "site_name": nom, "siret": siret, 
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
                        "power": self._safe_float(row.get(c_puiss)),
                        "segment": str(row.get(c_seg, 'C5')),
                        "provider": str(row.get(c_prov, 'Inconnu')),
                        "annual_volume_estimated": self._safe_float(row.get(c_conso)),
                        "start_date": str(row.get(c_start, '')),
                        "end_date": str(row.get(c_end, '')),
                        "grd": str(row.get(c_grd, '')),
                        "profil": str(row.get(c_profil, '')),
                        "tarif_acheminement": str(row.get(c_tarif_ach, '')),
                        "power_details": {
                            "hph": self._safe_float(row.get(c_ps_hph)),
                            "hch": self._safe_float(row.get(c_ps_hch)),
                            "hpe": self._safe_float(row.get(c_ps_hpe)),
                            "hce": self._safe_float(row.get(c_ps_hce))
                        }
                    },
                    "consumption_details": {
                        "hph": self._safe_float(row.get(c_c_hph)),
                        "hch": self._safe_float(row.get(c_c_hch)),
                        "hpe": self._safe_float(row.get(c_c_hpe)),
                        "hce": self._safe_float(row.get(c_c_hce))
                    },
                    "pricing": {
                        "fix": str(self._safe_float(row.get(c_abo))),
                        "hph": str(self._safe_float(row.get(c_p_hph))),
                        "hch": str(self._safe_float(row.get(c_p_hch))),
                        "hpe": str(self._safe_float(row.get(c_p_hpe))),
                        "hce": str(self._safe_float(row.get(c_p_hce))),
                        "tax": str(self._safe_float(row.get(c_tax))),
                        "storage": str(self._safe_float(row.get(c_stock))), 
                        "p1_budget": self._safe_float(row.get(c_p1)),
                        "p2_budget": self._safe_float(row.get(c_p2)),
                        "p3_budget": self._safe_float(row.get(c_p3))
                    },
                    "technical": {
                        "dpe": str(row.get(c_dpe, 'D')),
                        "tantiemes": self._safe_float(row.get(c_tant, 0)),
                        "chauffage": str(row.get(c_chauff, 'Inconnu')),
                        "cee_eligible": str(row.get(c_cee, 'NON'))
                    }
                }
                sites.append(site)
            except Exception as e:
                logger.warning(f"Erreur extraction ligne {idx}: {e}")
                continue

        logger.info(f"Import {len(sites)} sites OK")
        return sites

    # =========================================================
    # 2. PARSING COURBE DE CHARGE (LEGACY ENEDIS / GRDF)
    # =========================================================
    def parse_load_curve(self, file_content, filename):
        """
        Lit les formats bruts des distributeurs (P10, CSV brut).
        """
        try:
            buffer = io.BytesIO(file_content)
            enc = self._detect_encoding(buffer)
            content_str = file_content.decode(enc, errors='ignore')
            
            # Regex PDL (Cherche 14 chiffres)
            pdl_match = re.search(r'(?<!\d)(\d{14})(?!\d)', content_str) or re.search(r'(?<!\d)(\d{14})(?!\d)', filename)
            pdl = pdl_match.group(1) if pdl_match else "Inconnu"
            
            # Lecture CSV robuste
            buffer.seek(0)
            # Skip metadata lines often found in Enedis files
            lines = content_str.split('\n')
            header_row = 0
            for i, line in enumerate(lines[:50]):
                if "DATE" in line.upper() or "HORODATAGE" in line.upper():
                    header_row = i
                    break
            
            buffer.seek(0)
            df = pd.read_csv(buffer, sep=';', encoding=enc, skiprows=header_row, on_bad_lines='skip', low_memory=False)
            
            # Si échec, test virgule
            if len(df.columns) < 2:
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=',', encoding=enc, skiprows=header_row, on_bad_lines='skip', low_memory=False)

            # Nettoyage Colonnes
            df.columns = [self._clean_header(c) for c in df.columns]
            
            # Recherche Colonnes Date/Valeur
            col_date = next((c for c in df.columns if "DATE" in c or "HORODATAGE" in c or "TIMESTAMP" in c), None)
            col_val = next((c for c in df.columns if "PUISSANCE" in c or "VALEUR" in c or "KWH" in c), None)
            
            if not col_date or not col_val: return None, 0, {}
            
            df = df.rename(columns={col_date: 'date', col_val: 'val'})
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
            df['val'] = pd.to_numeric(df['val'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
            df = df.dropna(subset=['date']).sort_values('date')
            
            if df.empty: return None, 0, {}
            
            # Pas de temps
            delta = (df['date'].iloc[1] - df['date'].iloc[0]).total_seconds() / 60
            time_step = int(delta) if delta > 0 else 10
            
            df['date_str'] = df['date'].dt.strftime('%d/%m %H:%M')
            
            return df, time_step, {"pdl": pdl}
        except Exception as e:
            logger.error(f"Load Curve Error: {e}")
            return None, 0, {}

    # =========================================================
    # 3. PARSING BPU (SIMULATION OFFRES)
    # =========================================================
    def parse_bpu_excel(self, file_content):
        try:
            buffer = io.BytesIO(file_content)
            xls = pd.ExcelFile(buffer)
            
            # Détection de l'onglet
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
