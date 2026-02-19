import pandas as pd
import numpy as np
import io
import re
import logging
import csv
import chardet

# CONFIGURATION LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V70_FULL")

class CortexIngest:
    def __init__(self):
        self.version = "70.0 (Titanium: Full Legacy Support + Gas Fix)"
        
        # =========================================================
        # DICTIONNAIRE DE MAPPING UNIVERSEL (COMPLET)
        # =========================================================
        self.COLUMN_MAPPING = {
            # 1. IDENTIFICATION
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REF_PDL", "REFERENCE"],
            "nom": ["NOM_SITE", "NOM", "ENTITE", "RAISON_SOCIALE", "CLIENT", "SITE", "ACCOUNT_NAME", "LIBELLE"],
            "siret": ["SIRET_SITE", "SIRET", "SIREN"],
            "naf": ["NAF", "CODE_NAF", "APE"],
            
            # 2. LOCALISATION
            "adresse": ["ADRESSE_SITE", "ADRESSE", "RUE", "LIGNE_ADRESSE", "ADDRESS"],
            "cp": ["CP", "CODE_POSTAL", "ZIP", "ZIP_CODE"],
            "ville": ["VILLE", "COMMUNE", "CITY", "TOWN"],
            "surface": ["SURFACE_M2", "SURFACE", "M2", "SHAB", "SU", "S_UTILE"],
            
            # 3. CONTRAT & TECH
            "segment": ["SEGMENT", "SEGMENT_GAZ", "TARIF", "CATEGORY"],
            "fournisseur": ["FOURNISSEUR", "PROVIDER", "SUPPLIER", "TITULAIRE"],
            "date_fin": ["DATE_FIN", "ECHEANCE", "END_DATE"],
            "date_debut": ["DATE_DEBUT", "START_DATE"],
            "puissance": ["PUISSANCE_SOUSCRITE_MAX", "PUISSANCE", "PS_MAX", "CAR_MWH", "CAR", "P_SOUSCRITE", "KVA"],
            
            # --- FIX GAZ CRITIQUE ---
            "conso": ["VOLUME_ANNUEL_TOTAL", "CONSO_ANNUELLE", "VOLUME", "CJA_MWH_J", "CJA", "ESTIMATION", "CAR_MWH", "CONSOMMATION"],
            
            "profil": ["PROFIL", "PROFILE"],
            "grd": ["GRD", "DISTRIBUTEUR"],
            
            # 4. PRIX & BUDGET
            "abonnement": ["ABONNEMENT", "ABO", "PRIME_FIXE", "PART_FIXE", "TERME_FIXE"],
            # --- FIX PRIX GAZ ---
            "prix_hph": ["PRIX_HPH", "PRIX_UNITAIRE", "PRIX_MOLECULE_MWH", "PRIX_MOLECULE", "HPH", "P1"], 
            "taxes": ["TAXES", "CSPE", "TICGN", "CTA"],
            
            # 5. CHAMPS TECHNIQUES ADDITIONNELS
            "type_fluide": ["ENERGIE", "FLUIDE", "TYPE", "ENERGY_TYPE"],
            "unite": ["UNITE", "UNIT", "U_MESURE", "UNIT_CONSO"]
        }

    # =========================================================
    # UTILITAIRES DE ROBUSTESSE (NE PAS SUPPRIMER)
    # =========================================================

    def _clean_header(self, header):
        """ Nettoyage agressif des entêtes """
        return str(header).upper().strip().replace(' ', '_').replace('.', '').replace('É', 'E').replace('È', 'E').replace('-', '_')

    def _find_col(self, df_cols, key):
        """ Recherche floue intelligente """
        candidates = self.COLUMN_MAPPING.get(key, [])
        # 1. Match Exact
        for col in df_cols:
            clean = self._clean_header(col)
            if clean in candidates: return col 
        # 2. Match Partiel
        for col in df_cols:
            clean = self._clean_header(col)
            for cand in candidates:
                if cand in clean: return col 
        return None

    def _safe_float(self, val):
        """ Conversion blindée (Anti-NaN) """
        if pd.isna(val) or val == '' or val is None: return 0.0
        s = str(val).replace(' ', '').replace('\xa0', '').replace('€', '').replace('%', '').replace('kVA', '').replace('kW', '').replace('MWh', '').replace('kWh', '')
        s = s.replace(',', '.')
        try: return float(s)
        except: return 0.0

    def _safe_str_clean(self, val):
        """ Nettoie les notations scientifiques et ID """
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
        Gère la conversion MWh -> kWh pour le Gaz.
        """
        sites = []
        df = None
        buffer = io.BytesIO(file_content)

        # 1. Lecture Robuste (Excel > CSV ; > CSV ,)
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
                except: return []

        if df is None or df.empty: return []

        cols = df.columns
        
        # 2. Mapping des Colonnes
        c_pdl = self._find_col(cols, "pdl")
        c_site_label = self._find_col(cols, "nom")
        c_addr = self._find_col(cols, "adresse")
        c_cp = self._find_col(cols, "cp")
        c_ville = self._find_col(cols, "ville")
        
        c_conso = self._find_col(cols, "conso")
        c_puiss = self._find_col(cols, "puissance")
        c_seg = self._find_col(cols, "segment")
        c_prov = self._find_col(cols, "fournisseur")
        
        c_prix = self._find_col(cols, "prix_hph")
        c_abo = self._find_col(cols, "abonnement")
        c_tax = self._find_col(cols, "taxes")

        # 3. Extraction Ligne par Ligne
        for idx, row in df.iterrows():
            try:
                # A. IDENTIFICATION
                pdl = self._safe_str_clean(row.get(c_pdl, f'TMP{idx}'))
                site_name = str(row.get(c_site_label, 'Site Inconnu')).strip()
                if not site_name or site_name.lower() == 'nan': site_name = "Site Inconnu"

                # B. LOGIQUE GAZ / ELEC
                raw_seg = str(row.get(c_seg, '')).upper()
                is_gas = False
                # Détection par Segment (T1, T2...) ou par Nom de colonne (PCE) ou par PDL (GI)
                if "GAZ" in raw_seg or "T1" in raw_seg or "T2" in raw_seg or "T3" in raw_seg: is_gas = True
                elif c_pdl and "PCE" in str(c_pdl).upper(): is_gas = True
                elif "GI" in pdl: is_gas = True
                
                energy_type = "gaz" if is_gas else "elec"

                # C. NORMALISATION CONSO (LE FIX GAZ EST ICI)
                raw_conso = self._safe_float(row.get(c_conso))
                conso_kwh = raw_conso
                
                # Si la colonne s'appelle CAR_MWH ou contient MWH -> x1000
                col_name_conso = str(c_conso).upper() if c_conso else ""
                if "MWH" in col_name_conso:
                    conso_kwh = raw_conso * 1000.0
                elif "WH" in col_name_conso and "KWH" not in col_name_conso:
                    conso_kwh = raw_conso / 1000.0

                # D. CONSTRUCTION OBJET
                site = {
                    "identity": { 
                        "id": pdl, 
                        "site_name": site_name,
                        "entity_name": site_name 
                    },
                    "location": {
                        "address": str(row.get(c_addr, '')),
                        "zip_code": self._safe_str_clean(row.get(c_cp, '')),
                        "city": str(row.get(c_ville, ''))
                    },
                    "contract": {
                        "pdl": pdl,
                        "energy_type": energy_type,
                        "power": self._safe_float(row.get(c_puiss)),
                        "segment": raw_seg,
                        "provider": str(row.get(c_prov, 'Inconnu')),
                        "annual_volume_estimated": conso_kwh, # TOUJOURS EN KWH
                        "unit": "kWh"
                    },
                    "pricing": {
                        "fix": self._safe_float(row.get(c_abo)),
                        "hph": self._safe_float(row.get(c_prix)), # Peut être en €/MWh (45.50) ou €/kWh (0.045)
                        "tax": self._safe_float(row.get(c_tax))
                    }
                }
                sites.append(site)
            except Exception as e:
                continue

        return sites

    # =========================================================
    # 2. PARSING COURBE DE CHARGE (POUR PHYSICS / SATELLITES)
    # =========================================================
    def parse_load_curve(self, file_content, filename):
        """
        Lit les formats bruts des distributeurs (Enedis/GRDF).
        Nécessaire pour le module Solar et Audit.
        """
        try:
            buffer = io.BytesIO(file_content)
            enc = self._detect_encoding(buffer)
            buffer.seek(0)
            
            # Lecture CSV avec détection de séparateur
            try: df = pd.read_csv(buffer, sep=';', encoding=enc, on_bad_lines='skip', low_memory=False)
            except: 
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=',', encoding=enc, on_bad_lines='skip', low_memory=False)

            # Nettoyage Colonnes
            df.columns = [self._clean_header(c) for c in df.columns]
            
            # Recherche Colonnes Date/Valeur
            col_date = next((c for c in df.columns if "DATE" in c or "HORODATAGE" in c), None)
            col_val = next((c for c in df.columns if "PUISSANCE" in c or "VALEUR" in c or "KWH" in c), None)
            
            if not col_date or not col_val: return None, 0, {}
            
            df = df.rename(columns={col_date: 'date', col_val: 'val'})
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
            df['val'] = pd.to_numeric(df['val'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0)
            df = df.dropna(subset=['date']).sort_values('date')
            
            if df.empty: return None, 0, {}
            
            # Pas de temps
            delta = (df['date'].iloc[1] - df['date'].iloc[0]).total_seconds() / 60
            
            return df, int(delta), {}
        except Exception as e:
            logger.error(f"Load Curve Error: {e}")
            return None, 0, {}

    # =========================================================
    # 3. PARSING BPU (POUR COMPARATEUR)
    # =========================================================
    def parse_bpu_excel(self, file_content):
        """
        Lit un fichier BPU (Grille de prix) pour la simulation.
        """
        try:
            buffer = io.BytesIO(file_content)
            df = pd.read_excel(buffer)
            
            cols = df.columns
            c_hph = self._find_col(cols, "prix_hph")
            c_abo = self._find_col(cols, "abonnement")
            
            if not c_hph: return None, False
            
            # Prend la première ligne comme référence
            prices = {
                "hph": self._safe_float(df.iloc[0].get(c_hph, 0)),
                "fix": self._safe_float(df.iloc[0].get(c_abo, 0))
            }
            
            is_gaz = "GAZ" in str(df.columns).upper()
            return pd.DataFrame([prices]), is_gaz
        except: return None, False

ingest = CortexIngest()
