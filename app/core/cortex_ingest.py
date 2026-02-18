import pandas as pd
import numpy as np
import io
import re
import logging
import csv
import chardet # Bibliothèque de détection d'encodage (Robustesse)

# CONFIGURATION LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_HEAVY")

# DEPENDANCES OPTIONNELLES
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("PDFPlumber manquant : L'analyse des factures PDF sera désactivée.")

class CortexIngest:
    def __init__(self):
        self.version = "52.0 (Heavy Duty Ingestion Engine)"
        self.supported_formats = ['.csv', '.xlsx', '.xls', '.txt', '.pdf']
        
        # Dictionnaire de Mapping des Colonnes (Le "Dico Universel")
        # Permet de reconnaître une colonne même si le client l'a mal nommée
        self.COLUMN_MAPPING = {
            # IDENTIFICATION
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "ID_SITE", "REF_PDL", "RÉFÉRENCE", "PCE"],
            "nom": ["NOM", "NOM_SITE", "RAISON_SOCIALE", "CLIENT", "ENTITE", "SITE"],
            # ADRESSE
            "adresse": ["ADRESSE", "RUE", "LIGNE_ADRESSE", "ADDRESS"],
            "cp": ["CP", "CODE_POSTAL", "ZIP", "ZIP_CODE"],
            "ville": ["VILLE", "COMMUNE", "CITY"],
            # TECHNIQUE
            "puissance": ["PUISSANCE", "PS", "P_SOUSCRITE", "PS_MAX", "CAR", "CAPACITE"],
            "conso": ["CONSO", "CONSOMMATION", "VOLUME", "ANNUEL", "ESTIMATION", "CJA"],
            "surface": ["SURFACE", "M2", "SHAB", "SU", "S_UTILE"],
            # OPH / HABITAT
            "p1": ["P1", "BUDGET_P1", "ENERGIE_EURO", "COUT_ENERGIE"],
            "p2": ["P2", "BUDGET_P2", "MAINTENANCE", "P2_FORFAIT"],
            "p3": ["P3", "BUDGET_P3", "GROS_ENTRETIEN"],
            "tantiemes": ["TANTIEMES", "PART", "MILLIEMES", "QUOTE_PART"],
            "dpe": ["DPE", "ETIQUETTE", "CLASSE_ENERGIE", "DIAGNOSTIC"],
            "chauffage": ["CHAUFFAGE", "TYPE_CHAUFFAGE", "SYSTEME_CHAUFFE"],
            # PRIX
            "prix_hph": ["PRIX_HPH", "PRIX_UNITAIRE", "HPH", "P_KWH"],
            "abonnement": ["ABONNEMENT", "ABO", "PRIME_FIXE", "PART_FIXE"]
        }

    # =========================================================
    # UTILITAIRES DE ROBUSTESSE (SAFETY FIRST)
    # =========================================================

    def _detect_encoding(self, buffer):
        """ Détecte l'encodage du fichier pour éviter les crashs UTF-8/Latin-1 """
        raw = buffer.read(10000)
        buffer.seek(0)
        result = chardet.detect(raw)
        return result['encoding'] or 'utf-8'

    def _detect_separator(self, line):
        """ Devine si le CSV est séparé par ; ou , ou \t """
        if line.count(';') > line.count(','): return ';'
        if line.count('\t') > line.count(';'): return '\t'
        return ','

    def _clean_header(self, header):
        """ Nettoie les entêtes pour correspondre au mapping """
        return str(header).upper().strip().replace(' ', '_').replace('.', '').replace('É', 'E').replace('È', 'E')

    def _find_col(self, df_cols, key):
        """ Cherche une colonne dans le DataFrame selon le mapping """
        candidates = self.COLUMN_MAPPING.get(key, [])
        for col in df_cols:
            clean_col = self._clean_header(col)
            # Match exact
            if clean_col in candidates: return col
            # Match partiel
            for cand in candidates:
                if cand in clean_col: return col
        return None

    def _safe_float(self, val):
        if pd.isna(val) or val == '': return 0.0
        s = str(val).replace(',', '.').replace(' ', '').replace('€', '').replace('%', '').replace('kVA', '')
        try: return float(s)
        except: return 0.0

    def _safe_int(self, val):
        return int(self._safe_float(val))

    # =========================================================
    # 1. MOTEUR D'IMPORT DE MASSE (LE "BROYEUR")
    # =========================================================
    def parse_mass_import_unified(self, file_content):
        """
        Lit n'importe quel fichier plat (Excel/CSV) et tente d'en extraire
        des objets 'Site' standardisés, quel que soit le format d'origine.
        """
        sites = []
        df = None
        buffer = io.BytesIO(file_content)

        # 1. TENTATIVE DE LECTURE (BRUTE FORCE)
        try:
            # Excel ?
            df = pd.read_excel(buffer)
        except:
            # CSV ?
            buffer.seek(0)
            enc = self._detect_encoding(buffer)
            try:
                # Lecture de la première ligne pour le séparateur
                first_line = buffer.readline().decode(enc)
                sep = self._detect_separator(first_line)
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=sep, encoding=enc, dtype=str, on_bad_lines='skip')
            except Exception as e:
                logger.error(f"Echec lecture CSV: {e}")
                return []

        if df is None or df.empty:
            logger.warning("Fichier vide ou illisible")
            return []

        # 2. MAPPING INTELLIGENT
        cols = df.columns
        # On cherche les colonnes clés
        c_nom = self._find_col(cols, "nom")
        c_pdl = self._find_col(cols, "pdl")
        c_addr = self._find_col(cols, "adresse")
        c_ville = self._find_col(cols, "ville")
        c_cp = self._find_col(cols, "cp")
        c_puiss = self._find_col(cols, "puissance")
        c_conso = self._find_col(cols, "conso")
        c_surf = self._find_col(cols, "surface")
        
        # Champs OPH
        c_p1 = self._find_col(cols, "p1")
        c_p2 = self._find_col(cols, "p2")
        c_p3 = self._find_col(cols, "p3")
        c_dpe = self._find_col(cols, "dpe")
        c_chauff = self._find_col(cols, "chauffage")
        c_tant = self._find_col(cols, "tantiemes")

        # Champs Prix
        c_hph = self._find_col(cols, "prix_hph")
        c_abo = self._find_col(cols, "abonnement")

        # 3. EXTRACTION LIGNE A LIGNE
        for idx, row in df.iterrows():
            try:
                # Données obligatoires (ou presque)
                pdl_val = str(row[c_pdl]) if c_pdl else f"SITE_{idx}"
                nom_val = str(row[c_nom]) if c_nom else "Site Inconnu"
                
                # Nettoyage PDL (Garder que les chiffres)
                pdl_clean = re.sub(r'[^0-9]', '', pdl_val)
                if not pdl_clean: pdl_clean = f"TEMP_{idx}"

                # Construction de l'objet Site Standardisé
                site = {
                    "client_name": nom_val,
                    "identity": {
                        "id": pdl_clean,
                        "site_name": nom_val,
                        "siret": "", 
                        "naf": "6820A" # Par défaut OPH/Immo si import masse
                    },
                    "location": {
                        "address": str(row[c_addr]) if c_addr else "",
                        "zip_code": str(row[c_cp]) if c_cp else "",
                        "city": str(row[c_ville]) if c_ville else "",
                        "surface": self._safe_float(row.get(c_surf))
                    },
                    "contract": {
                        "pdl": pdl_clean,
                        "power": self._safe_float(row.get(c_puiss)),
                        "segment": "C5", # Sera recalculé par Cortex
                        "provider": "Inconnu", # A détecter
                        "annual_volume_estimated": self._safe_float(row.get(c_conso))
                    },
                    "technical": {
                        "chauffage": str(row[c_chauff]) if c_chauff else "Inconnu",
                        "dpe": str(row[c_dpe]) if c_dpe else "D",
                        "tantiemes": self._safe_int(row.get(c_tant))
                    },
                    "pricing": {
                        "p1_budget": self._safe_float(row.get(c_p1)),
                        "p2_budget": self._safe_float(row.get(c_p2)),
                        "p3_budget": self._safe_float(row.get(c_p3)),
                        "hph": str(self._safe_float(row.get(c_hph))),
                        "fix": str(self._safe_float(row.get(c_abo)))
                    }
                }
                sites.append(site)

            except Exception as e:
                logger.error(f"Erreur ligne {idx}: {e}")
                continue # On ne plante pas l'import pour une ligne pourrie

        logger.info(f"Import terminé : {len(sites)} sites extraits.")
        return sites

    # =========================================================
    # 2. PARSING COURBE DE CHARGE (ENEDIS P10 / GRDF)
    # =========================================================
    def parse_load_curve(self, file_content, filename):
        """
        Analyseur spécifique pour les fichiers de courbes de charge.
        Gère le format P10 Enedis (Point 10 minutes) et les CSV GRDF.
        """
        try:
            buffer = io.BytesIO(file_content)
            enc = self._detect_encoding(buffer)
            content_str = file_content.decode(enc, errors='ignore')
            
            # RECHERCHE DU PDL (REGEX)
            # Cherche une suite de 14 chiffres isolée
            pdl_match = re.search(r'(?<!\d)(\d{14})(?!\d)', content_str)
            pdl = pdl_match.group(1) if pdl_match else "Inconnu"
            
            # LECTURE DU DATA FRAME
            buffer.seek(0)
            # On saute les lignes de métadonnées souvent présentes chez Enedis
            # On cherche la ligne d'entête
            lines = content_str.split('\n')
            header_row = 0
            for i, line in enumerate(lines[:50]): # Scan des 50 premières lignes
                if "DATE" in line.upper() or "HORODATAGE" in line.upper():
                    header_row = i
                    break
            
            buffer.seek(0)
            df = pd.read_csv(buffer, sep=';', encoding=enc, skiprows=header_row, on_bad_lines='skip', low_memory=False)
            
            # NETTOYAGE COLONNES
            df.columns = [self._clean_header(c) for c in df.columns]
            
            # IDENTIFICATION DES COLONNES CLEFS
            col_date = next((c for c in df.columns if "DATE" in c or "HORODATAGE" in c), None)
            col_val = next((c for c in df.columns if "PUISSANCE" in c or "VALEUR" in c or "KWH" in c), None)
            
            if not col_date or not col_val:
                logger.error("Colonnes Date/Valeur introuvables dans la courbe")
                return None, 0, {}
            
            # FORMATAGE DES DONNÉES
            df = df.rename(columns={col_date: 'date', col_val: 'val'})
            
            # Conversion Date (Robuste)
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
            df = df.dropna(subset=['date']).sort_values('date')
            
            # Conversion Valeur
            df['val'] = pd.to_numeric(df['val'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
            
            if df.empty: return None, 0, {}
            
            # CALCUL DU PAS DE TEMPS (10min, 30min, 60min ?)
            if len(df) > 1:
                delta = (df['date'].iloc[1] - df['date'].iloc[0]).total_seconds() / 60
                time_step = int(delta)
            else:
                time_step = 10 # Par défaut
                
            # Stringification pour JSON
            df['date_str'] = df['date'].dt.strftime('%d/%m %H:%M')
            
            meta = {
                "pdl": pdl,
                "start_date": df['date'].min().isoformat(),
                "end_date": df['date'].max().isoformat(),
                "points": len(df),
                "step_min": time_step
            }
            
            return df, time_step, meta

        except Exception as e:
            logger.error(f"Load Curve Parsing Error: {e}")
            return None, 0, {}

    # =========================================================
    # 3. PARSING BPU (OFFRE LAB)
    # =========================================================
    def parse_bpu_excel(self, file_content):
        """
        Lit les fichiers de réponse aux appels d'offres (BPU).
        """
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
                # Fallback : prend la première feuille
                df = pd.read_excel(xls, sheet_name=0)
                
            return df, is_gaz
            
        except Exception as e:
            logger.error(f"BPU Parsing Error: {e}")
            return None, False

# INSTANCE EXPORTÉE
ingest = CortexIngest()
