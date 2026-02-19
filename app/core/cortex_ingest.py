import pandas as pd
import numpy as np
import io
import re
import logging
import chardet

# CONFIGURATION LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V60_ARMOR")

class CortexIngest:
    def __init__(self):
        self.version = "60.0 (Armor Plating: Anti-NaN + Unit Normalizer)"
        
        # MAPPING INTELLIGENT DES COLONNES
        self.MAPPING = {
            "ref": ["PDL", "PCE", "POINT_DE_LIVRAISON", "REFERENCE", "ID", "PRM"],
            "nom": ["NOM", "SITE", "CLIENT", "RAISON_SOCIALE", "LIBELLE"],
            "conso": ["CONSOMMATION", "VOLUME", "CONSO", "ESTIMATION", "CJA", "CAR"],
            "puissance": ["PUISSANCE", "PS", "P_SOUSCRITE", "KVA"],
            "adresse": ["ADRESSE", "RUE", "LIGNE_ADRESSE"],
            "ville": ["VILLE", "COMMUNE", "CITY"],
            "cp": ["CP", "CODE_POSTAL", "ZIP"],
            "segment": ["SEGMENT", "TARIF", "CATEGORIE"],
            "fournisseur": ["FOURNISSEUR", "TITULAIRE"],
            "prix_unitaire": ["PRIX_HPH", "PRIX_UNITAIRE", "P1", "P_MOLECULE"],
            "abonnement": ["ABONNEMENT", "ABO", "FIXE", "PRIME_FIXE"]
        }

    # =========================================================
    # 1. OUTILS DE NETTOYAGE (LE COEUR DU FIX)
    # =========================================================

    def _clean_header(self, h):
        """ Normalise les entêtes (UPPER, sans accents, sans espaces) """
        return str(h).upper().strip().replace('É', 'E').replace('È', 'E').replace(' ', '_').replace('.', '').replace('-', '_')

    def _find_col(self, df_cols, key):
        """ Trouve la colonne correspondante dans le fichier Excel """
        candidates = self.MAPPING.get(key, [])
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
        """
        TRANSFORME TOUT EN CHIFFRE.
        Gère : "1 200,50 €", "NaN", None, " - ", "1.200"
        """
        if pd.isna(val) or val == '' or val is None:
            return 0.0
        
        s = str(val).strip()
        # Enlever symboles monétaires et espaces insécables
        s = s.replace('€', '').replace('%', '').replace(' ', '').replace('\xa0', '').replace('EUR', '')
        # Gérer la virgule décimale
        s = s.replace(',', '.')
        
        try:
            return float(s)
        except:
            return 0.0

    def _normalize_energy_unit(self, val, explicit_unit=""):
        """
        Convertit tout en kWh.
        Corrige les millions d'euros sur le Gaz.
        """
        val = self._safe_float(val)
        unit = str(explicit_unit).upper()
        
        # Si unité explicite MWh -> x1000
        if "MWH" in unit:
            return val * 1000.0
        # Si unité explicite Wh -> /1000
        if "WH" in unit and "KWH" not in unit:
            return val / 1000.0
            
        # HEURISTIQUE (Si pas d'unité)
        # Si conso > 500 000 pour un petit site, c'est probablement du Wh
        # Si conso < 50, c'est probablement du MWh (sauf si site vide)
        # (Désactivé pour éviter les faux positifs, on suppose kWh par défaut sauf si MWh détecté)
        
        return val # Par défaut kWh

    # =========================================================
    # 2. PARSER PRINCIPAL (IMPORT MASSIF)
    # =========================================================
    def parse_mass_import_unified(self, file_content):
        """
        Lit Excel/CSV et renvoie une structure JSON propre pour le Cortex Engine.
        """
        sites = []
        df = None
        
        # A. CHARGEMENT ROBUSTE
        try:
            buffer = io.BytesIO(file_content)
            df = pd.read_excel(buffer) # Tentative Excel
        except:
            try:
                buffer.seek(0)
                # Tentative CSV (Point virgule)
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', on_bad_lines='skip')
                if len(df.columns) < 2:
                    buffer.seek(0)
                    # Tentative CSV (Virgule)
                    df = pd.read_csv(buffer, sep=',', encoding='utf-8', on_bad_lines='skip')
            except Exception as e:
                logger.error(f"Echec lecture fichier: {e}")
                return []

        if df is None or df.empty: return []

        # B. MAPPING DES COLONNES
        cols = df.columns
        c_ref = self._find_col(cols, "ref")
        c_nom = self._find_col(cols, "nom")
        c_conso = self._find_col(cols, "conso")
        c_addr = self._find_col(cols, "adresse")
        c_ville = self._find_col(cols, "ville")
        c_cp = self._find_col(cols, "cp")
        c_seg = self._find_col(cols, "segment")
        c_fourn = self._find_col(cols, "fournisseur")
        c_puiss = self._find_col(cols, "puissance")
        c_prix = self._find_col(cols, "prix_unitaire")
        c_abo = self._find_col(cols, "abonnement")
        
        # C. EXTRACTION LIGNE PAR LIGNE
        for idx, row in df.iterrows():
            try:
                # 1. Nettoyage Données
                pdl = str(row.get(c_ref, f"TMP_{idx}")).replace('.0', '').strip()
                nom = str(row.get(c_nom, "Site Inconnu")).strip()
                
                # 2. Gestion Conso & Unités (FIX GAZ)
                raw_conso = row.get(c_conso, 0)
                # On regarde si une colonne "Unité" existe à côté
                unit_col = next((c for c in cols if "UNIT" in str(c).upper()), "")
                unit_val = str(row.get(unit_col, "")) if unit_col else ""
                
                conso_kwh = self._normalize_energy_unit(raw_conso, unit_val)
                
                # 3. Détection Gaz vs Elec
                # Si PDL commence par 'GI' ou '0' ou si Segment contient 'T' -> Gaz
                is_gas = False
                segment = str(row.get(c_seg, "")).upper()
                if "GAZ" in segment or "T1" in segment or "T2" in segment or "T3" in segment or "T4" in segment:
                    is_gas = True
                elif "GAZ" in str(c_ref).upper(): # Si la colonne s'appelle "PCE GAZ"
                    is_gas = True
                
                energy_type = "gaz" if is_gas else "elec"

                # 4. Construction Objet
                site = {
                    "identity": {
                        "id": pdl,
                        "site_name": nom, # Le nom s'affiche enfin !
                        "entity_name": nom
                    },
                    "location": {
                        "address": str(row.get(c_addr, "")),
                        "city": str(row.get(c_ville, "")),
                        "zip_code": str(row.get(c_cp, "")).replace('.0', '')
                    },
                    "contract": {
                        "pdl": pdl,
                        "provider": str(row.get(c_fourn, "Inconnu")),
                        "segment": segment,
                        "power": self._safe_float(row.get(c_puiss)),
                        "annual_volume_estimated": conso_kwh, # En kWh propre
                        "energy_type": energy_type
                    },
                    "pricing": {
                        "hph": self._safe_float(row.get(c_prix)), # Prix unitaire
                        "fix": self._safe_float(row.get(c_abo)),
                        "tax": 0.0 # Sera calculé par Engine
                    }
                }
                sites.append(site)
            except Exception as e:
                logger.warning(f"Erreur ligne {idx}: {e}")
                continue

        return sites

    # =========================================================
    # 3. PARSER BPU (POUR LE COMPARATEUR)
    # =========================================================
    def parse_bpu_excel(self, file_content):
        """
        Lit un fichier BPU (Grille de prix) pour la simulation.
        """
        try:
            buffer = io.BytesIO(file_content)
            df = pd.read_excel(buffer)
            
            # Recherche des colonnes clés
            cols = df.columns
            c_hph = self._find_col(cols, "prix_unitaire")
            c_abo = self._find_col(cols, "abonnement")
            
            if not c_hph:
                return None, False # Echec lecture
                
            # On prend la première ligne de prix trouvée
            prices = {
                "hph": self._safe_float(df.iloc[0].get(c_hph, 0)),
                "fix": self._safe_float(df.iloc[0].get(c_abo, 0))
            }
            
            # Détection Gaz
            is_gaz = "GAZ" in str(df.columns).upper()
            
            # On renvoie un DataFrame simplifié ou un dict
            return pd.DataFrame([prices]), is_gaz
            
        except Exception as e:
            logger.error(f"BPU Error: {e}")
            return None, False

    # =========================================================
    # 4. PARSER COURBE DE CHARGE (PHYSICS)
    # =========================================================
    def parse_load_curve(self, file_content, filename):
        """ Lit les CSV Enedis (Point virgule, date, puissance) """
        try:
            buffer = io.BytesIO(file_content)
            # Détection encodage
            enc = chardet.detect(buffer.read(10000))['encoding'] or 'utf-8'
            buffer.seek(0)
            
            df = pd.read_csv(buffer, sep=';', encoding=enc, on_bad_lines='skip')
            
            # Recherche Colonnes
            cols = [str(c).upper() for c in df.columns]
            col_date = next((c for c in df.columns if "DATE" in str(c).upper() or "HORODATAGE" in str(c).upper()), None)
            col_val = next((c for c in df.columns if "PUISSANCE" in str(c).upper() or "VALEUR" in str(c).upper()), None)
            
            if not col_date or not col_val: return None, 0, {}
            
            # Nettoyage
            df = df.rename(columns={col_date: 'date', col_val: 'val'})
            df['val'] = df['val'].apply(self._safe_float) # Utilise le nettoyeur universel
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
            df = df.dropna()
            
            # Pas de temps
            delta = (df['date'].iloc[1] - df['date'].iloc[0]).total_seconds() / 60
            
            return df, int(delta), {}
            
        except Exception as e:
            logger.error(f"Load Curve Error: {e}")
            return None, 0, {}

ingest = CortexIngest()
