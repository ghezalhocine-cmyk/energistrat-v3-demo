import pandas as pd
import numpy as np
import io
import logging
import chardet
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V1000")

class CortexIngest:
    def __init__(self):
        self.version = "1000.0 (Integral: All Mappings Preserved)"
        
        # MAPPING EXHAUSTIF (GAZ + ELEC + EXPERT)
        self.COLUMN_MAPPING = {
            # 1. IDENTIFICATION
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REFERENCE", "REF_PDL"],
            "site_label": ["NOM_SITE", "LIBELLE_PDL", "NOM_POINT_DE_LIVRAISON", "SITE", "LABEL", "NOM"],
            "entity": ["ENTITE", "RAISON_SOCIALE", "CLIENT", "TITULAIRE", "NOM_CLIENT", "SOCIETE"],
            
            # 2. LOCALISATION
            "adresse": ["ADRESSE_SITE", "ADRESSE", "RUE", "LIGNE_ADRESSE"],
            "ville": ["VILLE", "COMMUNE", "CITY", "TOWN"],
            "cp": ["CP", "CODE_POSTAL", "ZIP", "ZIP_CODE"],
            "siret": ["SIRET", "SIRET_SITE", "SIREN"],
            
            # 3. DONNEES TECHNIQUES & CONTRAT
            "conso": ["CAR_MWH", "VOLUME_ANNUEL", "CONSOMMATION", "VOLUME", "CONSO", "ESTIMATION", "VOL. ANNUEL", "CJA"],
            "puissance": ["PUISSANCE", "PS", "P_SOUSCRITE", "KVA", "S MAX (KVA)"],
            "p_max": ["POINTE_MAX", "P_MAX", "PUISSANCE_ATTEINTE", "MAX_ATTEINTE"],
            "segment": ["SEGMENT", "SEGMENT_GAZ", "TARIF", "CATEGORIE"],
            "fournisseur": ["FOURNISSEUR", "TITULAIRE", "PROVIDER"],
            "fta": ["FTA", "FORMULE_TARIFAIRE", "OPTION"],
            "grd": ["GRD", "GESTIONNAIRE", "DISTRIBUTEUR"],
            "date_debut": ["DATE_DEBUT", "DEBUT_CONTRAT", "START_DATE"],
            "date_fin": ["DATE_FIN", "ECHEANCE", "FIN_CONTRAT", "END_DATE"],
            
            # 4. GAZ SPECIFIQUE (POUR AFFICHAGE DÉTAIL)
            "cja": ["CJA", "CJA_MWH_J", "CAPACITE_JOURNALIERE"],
            "profil": ["PROFIL", "PROFIL_GAZ"],
            "tarif_ach": ["TARIF_ACHEM", "TARIF_ACHEMINEMENT", "ATRT"],

            # 5. ELEC DETAILS (POUR DQE - 4 QUADRANTS)
            "ps_hph": ["PS HPH", "PUISSANCE HPH", "P_HPH", "PS_HPH"],
            "ps_hch": ["PS HCH", "PUISSANCE HCH", "P_HCH", "PS_HCH"],
            "ps_hpe": ["PS HPE", "PUISSANCE HPE", "P_HPE", "PS_HPE"],
            "ps_hce": ["PS HCE", "PUISSANCE HCE", "P_HCE", "PS_HCE"],
            
            "conso_hph": ["CONSO HPH", "C_HPH", "HP HAUTE", "CONSO_HPH"],
            "conso_hch": ["CONSO HCH", "C_HCH", "HC HAUTE", "CONSO_HCH"],
            "conso_hpe": ["CONSO HPE", "C_HPE", "HP BASSE", "CONSO_HPE"],
            "conso_hce": ["CONSO HCE", "C_HCE", "HC BASSE", "CONSO_HCE"],

            # 6. PRIX & BUDGET (TOUS LES POSTES)
            "prix_unitaire": ["PRIX_MOLECULE", "PRIX_HPH", "PRIX_UNITAIRE", "P1", "HPH", "PRIX"],
            "prix_hch": ["PRIX_HCH", "HCH"],
            "prix_hpe": ["PRIX_HPE", "HPE"],
            "prix_hce": ["PRIX_HCE", "HCE"],
            
            "abonnement": ["ABONNEMENT", "ABO", "FIXE", "PRIME_FIXE", "PART_FIXE"],
            "taxes": ["TAXES", "CSPE", "TICGN", "CTA"],
            "stockage": ["TERME_STOCK", "STOCKAGE", "TERME_STOCKAGE"]
        }
        
        # BLACKLIST STRICTE
        self.NAME_BLACKLIST = ["CLIENT", "SITE", "INCONNU", "NAN", "NONE", "NOM_SITE", "0", ".", "COMMUNE", "MAIRIE", "SOCIETE"]

    def _clean_header(self, h):
        return str(h).upper().strip().replace('É', 'E').replace('È', 'E').replace(' ', '_').replace('.', '').replace('-', '_')

    def _find_col(self, df_cols, key):
        candidates = self.COLUMN_MAPPING.get(key, [])
        for col in df_cols:
            clean = self._clean_header(col)
            # 1. Match Exact
            if clean in candidates: return col
            # 2. Match Partiel (Sauf pour les clés courtes/dangereuses)
            if len(key) > 3 and key not in ["prix_hph", "prix_hch", "prix_hpe", "prix_hce"]: 
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
        s = str(val).replace(',', '.')
        try:
            if 'E+' in s or 'e+' in s: return str(int(float(s))) 
            if '.' in s: return str(int(float(s)))
            return s.strip()
        except: return str(val).strip()

    def parse_mass_import_unified(self, file_content):
        sites = []
        df = None
        buffer = io.BytesIO(file_content)
        
        # STRATÉGIE DE LECTURE UNIVERSELLE (Excel -> CSV -> Latin1)
        try:
            df = pd.read_excel(buffer, dtype=str)
        except:
            try:
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', dtype=str, on_bad_lines='skip')
                if len(df.columns) < 2: raise ValueError()
            except:
                try:
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=',', encoding='utf-8', dtype=str, on_bad_lines='skip')
                except: return []

        if df is None or df.empty: return []

        cols = df.columns
        c_pdl = self._find_col(cols, "pdl")
        if not c_pdl: return [] # Pas de PDL = Pas de chocolat

        # Récupération de TOUTES les colonnes mappées
        c_nom = self._find_col(cols, "site_label")
        c_entite = self._find_col(cols, "entity")
        c_addr = self._find_col(cols, "adresse")
        c_cp = self._find_col(cols, "cp")
        c_ville = self._find_col(cols, "ville")
        c_siret = self._find_col(cols, "siret")
        c_conso = self._find_col(cols, "conso")
        c_puiss = self._find_col(cols, "puissance")
        c_pmax = self._find_col(cols, "p_max")
        c_seg = self._find_col(cols, "segment")
        c_fourn = self._find_col(cols, "fournisseur")
        c_fta = self._find_col(cols, "fta")
        c_grd = self._find_col(cols, "grd")
        c_start = self._find_col(cols, "date_debut")
        c_end = self._find_col(cols, "date_fin")
        
        # Gaz Tech
        c_cja = self._find_col(cols, "cja")
        c_profil = self._find_col(cols, "profil")
        c_tarif_ach = self._find_col(cols, "tarif_ach")

        # Elec Details (4 Postes)
        c_ps_hph = self._find_col(cols, "ps_hph")
        c_ps_hch = self._find_col(cols, "ps_hch")
        c_ps_hpe = self._find_col(cols, "ps_hpe")
        c_ps_hce = self._find_col(cols, "ps_hce")
        c_c_hph = self._find_col(cols, "conso_hph")
        c_c_hch = self._find_col(cols, "conso_hch")
        c_c_hpe = self._find_col(cols, "conso_hpe")
        c_c_hce = self._find_col(cols, "conso_hce")
        
        # Prix (4 Postes)
        c_p_hph = self._find_col(cols, "prix_hph")
        c_p_hch = self._find_col(cols, "prix_hch")
        c_p_hpe = self._find_col(cols, "prix_hpe")
        c_p_hce = self._find_col(cols, "prix_hce")
        
        c_abo = self._find_col(cols, "abonnement")
        c_tax = self._find_col(cols, "taxes")
        c_stock = self._find_col(cols, "stockage")

        for idx, row in df.iterrows():
            try:
                # 1. NETTOYAGE ID
                pdl = self._safe_str_clean(row.get(c_pdl, f"TMP_{idx}"))
                
                # 2. NOMMAGE INTELLIGENT
                nom_brut = str(row.get(c_nom, "")).strip()
                entite_brut = str(row.get(c_entite, "")).strip()
                ville = str(row.get(c_ville, "")).strip()
                
                final_name = "Site Inconnu"
                is_nom_bad = not nom_brut or any(b in nom_brut.upper() for b in self.NAME_BLACKLIST)
                if not is_nom_bad: final_name = nom_brut
                elif entite_brut and not any(b in entite_brut.upper() for b in self.NAME_BLACKLIST): final_name = entite_brut
                elif ville: final_name = f"{ville} ({pdl[-4:]})"

                # 3. CONVERSION UNITÉS (MWh -> kWh)
                raw_conso = self._safe_float(row.get(c_conso))
                conso_kwh = raw_conso
                if c_conso and "MWH" in str(c_conso).upper(): conso_kwh = raw_conso * 1000.0
                # Sécurité "Decimal Force" : Si > 10 GWh, c'est une erreur de virgule
                if conso_kwh > 10_000_000: conso_kwh = conso_kwh / 1000.0

                # 4. TYPAGE ÉNERGIE
                segment = str(row.get(c_seg, "")).upper()
                is_gas = False
                if "GAZ" in segment or "T1" in segment or "T2" in segment or "T3" in segment: is_gas = True
                elif c_pdl and "PCE" in str(c_pdl).upper(): is_gas = True
                energy_type = "gaz" if is_gas else "elec"

                # 5. PUISSANCE (Si Gaz, on prend la CAR si Puissance vide pour l'affichage)
                power_val = self._safe_float(row.get(c_puiss))
                if is_gas and power_val == 0: power_val = self._safe_float(row.get(c_conso))

                # 6. CONSTRUCTION OBJET COMPLET
                site = {
                    "identity": { 
                        "id": pdl, 
                        "site_name": final_name, 
                        "entity_name": entite_brut, 
                        "siret": self._safe_str_clean(row.get(c_siret)) 
                    },
                    "location": { 
                        "address": str(row.get(c_addr, "")), 
                        "zip_code": self._safe_str_clean(row.get(c_cp, "")), 
                        "city": ville 
                    },
                    "contract": {
                        "pdl": pdl, 
                        "provider": str(row.get(c_fourn, "Inconnu")),
                        "segment": segment, 
                        "power": power_val,
                        "p_max": self._safe_float(row.get(c_pmax)),
                        "annual_volume_estimated": conso_kwh, 
                        "energy_type": energy_type,
                        "fta": str(row.get(c_fta, "-")),
                        "grd": str(row.get(c_grd, "Enedis" if not is_gas else "GRDF")),
                        "start_date": str(row.get(c_start, "-")),
                        "end_date": str(row.get(c_end, "-")),
                        
                        # DONNEES TECHNIQUES GAZ
                        "cja": self._safe_float(row.get(c_cja)),
                        "profil": str(row.get(c_profil, "")),
                        "tarif_acheminement": str(row.get(c_tarif_ach, "")),
                        
                        # DETAILS ELEC 4 POSTES (Stockés pour le DQE)
                        "power_details": {
                            "hph": self._safe_float(row.get(c_ps_hph)), "hch": self._safe_float(row.get(c_ps_hch)),
                            "hpe": self._safe_float(row.get(c_ps_hpe)), "hce": self._safe_float(row.get(c_ps_hce))
                        },
                        "consumption_details": {
                            "hph": self._safe_float(row.get(c_c_hph)), "hch": self._safe_float(row.get(c_c_hch)),
                            "hpe": self._safe_float(row.get(c_c_hpe)), "hce": self._safe_float(row.get(c_c_hce))
                        }
                    },
                    "pricing": {
                        # TOUS LES PRIX SONT STOCKÉS
                        "hph": self._safe_float(row.get(c_p_hph)), 
                        "hch": self._safe_float(row.get(c_p_hch)),
                        "hpe": self._safe_float(row.get(c_p_hpe)),
                        "hce": self._safe_float(row.get(c_p_hce)),
                        "fix": self._safe_float(row.get(c_abo)),
                        "tax": self._safe_float(row.get(c_tax)), 
                        "storage": self._safe_float(row.get(c_stock))
                    }
                }
                sites.append(site)
            except: continue
        return sites

    def parse_bpu_excel(self, file_content):
        try:
            buffer = io.BytesIO(file_content)
            df = pd.read_excel(buffer, engine='openpyxl')
            cols = df.columns
            c_hph = self._find_col(cols, "prix_unitaire")
            if not c_hph:
                for c in cols:
                    try:
                        val = self._safe_float(df.iloc[0][c])
                        if 0.01 < val < 500: c_hph = c; break
                    except: continue
            if not c_hph: return None, False
            c_abo = self._find_col(cols, "abonnement")
            fix_val = 0.0
            if c_abo: fix_val = self._safe_float(df.iloc[0].get(c_abo, 0))
            prices = {"hph": self._safe_float(df.iloc[0].get(c_hph, 0)),"fix": fix_val}
            is_gaz = "GAZ" in str(df.columns).upper()
            return pd.DataFrame([prices]), is_gaz
        except: return None, False

    def parse_load_curve(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            enc = chardet.detect(buffer.read(10000))['encoding'] or 'utf-8'
            buffer.seek(0)
            try: df = pd.read_csv(buffer, sep=';', encoding=enc, on_bad_lines='skip')
            except: 
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=',', encoding=enc, on_bad_lines='skip')
            cols = [str(c).upper() for c in df.columns]
            col_date = next((c for c in df.columns if "DATE" in str(c).upper()), None)
            col_val = next((c for c in df.columns if "PUISSANCE" in str(c).upper() or "VALEUR" in str(c).upper()), None)
            if not col_date or not col_val: return None, 0, {}
            df = df.rename(columns={col_date: 'date', col_val: 'val'})
            df['val'] = df['val'].apply(self._safe_float)
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
            df = df.dropna()
            delta = (df['date'].iloc[1] - df['date'].iloc[0]).total_seconds() / 60
            return df, int(delta), {}
        except: return None, 0, {}

ingest = CortexIngest()
