import pandas as pd
import numpy as np
import io
import logging
import chardet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V71_IDENTITY")

class CortexIngest:
    def __init__(self):
        self.version = "71.0 (Fix: Site Name Priority + Comparator)"
        
        self.COLUMN_MAPPING = {
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REFERENCE"],
            # Isole le NOM PHYSIQUE
            "site_label": ["NOM_SITE", "LIBELLE_PDL", "NOM_POINT_DE_LIVRAISON", "SITE", "LABEL"],
            # Isole le NOM JURIDIQUE
            "entity": ["ENTITE", "RAISON_SOCIALE", "CLIENT", "TITULAIRE", "NOM_CLIENT"],
            
            "adresse": ["ADRESSE_SITE", "ADRESSE", "RUE"],
            "ville": ["VILLE", "COMMUNE", "CITY"],
            "cp": ["CP", "CODE_POSTAL", "ZIP"],
            
            # FIX GAZ MWh
            "conso": ["CAR_MWH", "VOLUME_ANNUEL", "CONSOMMATION", "VOLUME", "CONSO", "ESTIMATION"],
            "puissance": ["PUISSANCE", "PS", "P_SOUSCRITE", "KVA"],
            "segment": ["SEGMENT", "SEGMENT_GAZ", "TARIF"],
            "fournisseur": ["FOURNISSEUR", "TITULAIRE"],
            
            # PRIX
            "prix_unitaire": ["PRIX_MOLECULE", "PRIX_HPH", "PRIX_UNITAIRE", "P1", "HPH"],
            "abonnement": ["ABONNEMENT", "ABO", "FIXE", "PRIME_FIXE"],
            "taxes": ["TAXES", "CSPE", "TICGN"]
        }

    def _clean_header(self, h):
        return str(h).upper().strip().replace('É', 'E').replace('È', 'E').replace(' ', '_').replace('.', '').replace('-', '_')

    def _find_col(self, df_cols, key):
        candidates = self.COLUMN_MAPPING.get(key, [])
        for col in df_cols:
            clean = self._clean_header(col)
            if clean in candidates: return col
            for cand in candidates:
                if cand in clean: return col
        return None

    def _safe_float(self, val):
        if pd.isna(val) or val == '' or val is None: return 0.0
        s = str(val).strip().replace('€', '').replace('%', '').replace(' ', '').replace('\xa0', '').replace('EUR', '')
        s = s.replace(',', '.')
        try: return float(s)
        except: return 0.0

    def parse_mass_import_unified(self, file_content):
        sites = []
        df = None
        
        try:
            buffer = io.BytesIO(file_content)
            df = pd.read_excel(buffer)
        except:
            try:
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', on_bad_lines='skip')
                if len(df.columns) < 2:
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=',', encoding='utf-8', on_bad_lines='skip')
            except: return []

        if df is None or df.empty: return []

        cols = df.columns
        
        # MAPPING PRÉCIS
        c_pdl = self._find_col(cols, "pdl")
        c_nom_site = self._find_col(cols, "site_label") # Priorité 1
        c_entite = self._find_col(cols, "entity")       # Priorité 2
        
        c_addr = self._find_col(cols, "adresse")
        c_ville = self._find_col(cols, "ville")
        c_cp = self._find_col(cols, "cp")
        
        c_conso = self._find_col(cols, "conso")
        c_puiss = self._find_col(cols, "puissance")
        c_seg = self._find_col(cols, "segment")
        c_fourn = self._find_col(cols, "fournisseur")
        
        c_prix = self._find_col(cols, "prix_unitaire")
        c_abo = self._find_col(cols, "abonnement")
        c_tax = self._find_col(cols, "taxes")

        for idx, row in df.iterrows():
            try:
                pdl = str(row.get(c_pdl, f"TMP_{idx}")).replace('.0', '').strip()
                
                # --- LOGIQUE IDENTITÉ (FIX SITE NAME) ---
                # On cherche d'abord le NOM_SITE, sinon l'ENTITE, sinon "Site Inconnu"
                nom_brut = str(row.get(c_nom_site, "")).strip()
                entite_brut = str(row.get(c_entite, "")).strip()
                
                if nom_brut and nom_brut.lower() != "nan":
                    final_name = nom_brut
                elif entite_brut and entite_brut.lower() != "nan":
                    final_name = entite_brut
                else:
                    final_name = "Site Inconnu"

                # --- LOGIQUE UNITÉS ---
                raw_conso = self._safe_float(row.get(c_conso))
                conso_kwh = raw_conso
                if c_conso and "MWH" in str(c_conso).upper():
                    conso_kwh = raw_conso * 1000.0

                # --- DÉTECTION ÉNERGIE ---
                segment = str(row.get(c_seg, "")).upper()
                is_gas = False
                if "GAZ" in segment or "T1" in segment or "T2" in segment or "T3" in segment: is_gas = True
                elif c_pdl and "PCE" in str(c_pdl).upper(): is_gas = True
                energy_type = "gaz" if is_gas else "elec"

                site = {
                    "identity": { 
                        "id": pdl, 
                        "site_name": final_name, # Ici on a le bon nom !
                        "entity_name": entite_brut if entite_brut else final_name
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
                        "annual_volume_estimated": conso_kwh,
                        "energy_type": energy_type
                    },
                    "pricing": {
                        "hph": self._safe_float(row.get(c_prix)),
                        "fix": self._safe_float(row.get(c_abo)),
                        "tax": self._safe_float(row.get(c_tax))
                    }
                }
                sites.append(site)
            except: continue

        return sites

    def parse_bpu_excel(self, file_content):
        """ Parser BPU assoupli pour le comparateur """
        try:
            buffer = io.BytesIO(file_content)
            df = pd.read_excel(buffer)
            cols = df.columns
            
            # Recherche élargie pour le prix
            c_hph = self._find_col(cols, "prix_unitaire")
            # Si pas trouvé, on cherche n'importe quoi avec "HPH" ou "PRIX"
            if not c_hph:
                c_hph = next((c for c in cols if "HPH" in str(c).upper() or "PRIX" in str(c).upper()), None)
                
            c_abo = self._find_col(cols, "abonnement")
            if not c_abo:
                c_abo = next((c for c in cols if "ABO" in str(c).upper() or "FIX" in str(c).upper()), None)
            
            if not c_hph: return None, False
            
            prices = {
                "hph": self._safe_float(df.iloc[0].get(c_hph, 0)),
                "fix": self._safe_float(df.iloc[0].get(c_abo, 0))
            }
            is_gaz = "GAZ" in str(df.columns).upper()
            return pd.DataFrame([prices]), is_gaz
        except: return None, False

    def parse_load_curve(self, file_content, filename):
        # ... (Code Legacy inchangé pour courbe de charge) ...
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
