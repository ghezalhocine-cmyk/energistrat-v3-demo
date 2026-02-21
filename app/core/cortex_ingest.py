import pandas as pd
import numpy as np
import io
import logging
import chardet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V250")

class CortexIngest:
    def __init__(self):
        self.version = "250.0 (Legacy Structure + PDL Text Force)"
        
        self.COLUMN_MAPPING = {
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REFERENCE"],
            "site_label": ["NOM_SITE", "LIBELLE_PDL", "NOM_POINT_DE_LIVRAISON", "SITE", "LABEL"],
            "entity": ["ENTITE", "RAISON_SOCIALE", "CLIENT", "TITULAIRE", "NOM_CLIENT"],
            "adresse": ["ADRESSE_SITE", "ADRESSE", "RUE"],
            "ville": ["VILLE", "COMMUNE", "CITY"],
            "cp": ["CP", "CODE_POSTAL", "ZIP"],
            "siret": ["SIRET", "SIRET_SITE"],
            
            "conso": ["CAR_MWH", "VOLUME_ANNUEL", "CONSOMMATION", "VOLUME", "CONSO", "ESTIMATION", "VOL. ANNUEL"],
            "puissance": ["PUISSANCE", "PS", "P_SOUSCRITE", "KVA", "S MAX (KVA)"],
            "segment": ["SEGMENT", "SEGMENT_GAZ", "TARIF"],
            "fournisseur": ["FOURNISSEUR", "TITULAIRE"],
            "date_fin": ["DATE_FIN", "ECHEANCE"],
            
            # --- DETAILS 4 POSTES (PUISSANCE) ---
            "ps_hph": ["PS HPH", "PUISSANCE HPH", "P_HPH", "PS_HPH"],
            "ps_hch": ["PS HCH", "PUISSANCE HCH", "P_HCH", "PS_HCH"],
            "ps_hpe": ["PS HPE", "PUISSANCE HPE", "P_HPE", "PS_HPE"],
            "ps_hce": ["PS HCE", "PUISSANCE HCE", "P_HCE", "PS_HCE"],
            
            # --- DETAILS 4 POSTES (CONSO) ---
            "conso_hph": ["CONSO HPH", "C_HPH", "HP HAUTE", "CONSO_HPH"],
            "conso_hch": ["CONSO HCH", "C_HCH", "HC HAUTE", "CONSO_HCH"],
            "conso_hpe": ["CONSO HPE", "C_HPE", "HP BASSE", "CONSO_HPE"],
            "conso_hce": ["CONSO HCE", "C_HCE", "HC BASSE", "CONSO_HCE"],

            # --- DETAILS 4 POSTES (PRIX) ---
            "prix_hph": ["PRIX_HPH", "PRIX_UNITAIRE", "P1", "HPH", "PRIX"],
            "prix_hch": ["PRIX_HCH", "HCH"],
            "prix_hpe": ["PRIX_HPE", "HPE"],
            "prix_hce": ["PRIX_HCE", "HCE"],
            
            "abonnement": ["ABONNEMENT", "ABO", "FIXE", "PRIME_FIXE"],
            "taxes": ["TAXES", "CSPE", "TICGN"],
            "stockage": ["TERME_STOCK", "STOCKAGE", "TERME_STOCKAGE"]
        }
        self.NAME_BLACKLIST = ["CLIENT", "SITE", "INCONNU", "NAN", "NONE", "NOM_SITE", "0", ".", "COMMUNE", "MAIRIE", "SOCIETE"]

    def _clean_header(self, h):
        return str(h).upper().strip().replace('É', 'E').replace('È', 'E').replace(' ', '_').replace('.', '').replace('-', '_')

    def _find_col(self, df_cols, key):
        candidates = self.COLUMN_MAPPING.get(key, [])
        for col in df_cols:
            clean = self._clean_header(col)
            if clean in candidates: return col
            if len(key) > 3:
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
        """ NETTOYAGE PDL RENFORCÉ """
        if pd.isna(val) or val == '' or val is None: return ""
        s = str(val).replace(',', '.')
        # Gestion notation scientifique 3.00E+13 -> 30000000000000
        try:
            if 'E+' in s or 'e+' in s: 
                return str(int(float(s))) 
            if '.' in s: 
                return str(int(float(s)))
            return s.strip()
        except: return str(val).strip()

    def parse_mass_import_unified(self, file_content):
        sites = []
        df = None
        buffer = io.BytesIO(file_content)
        
        # LECTURE
        try:
            # Astuce : dtype=str force Pandas à tout lire en texte, évite la conversion scientifique auto
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
        if not c_pdl: return []

        # Mapping
        c_nom = self._find_col(cols, "site_label")
        c_entite = self._find_col(cols, "entity")
        c_addr = self._find_col(cols, "adresse")
        c_cp = self._find_col(cols, "cp")
        c_ville = self._find_col(cols, "ville")
        c_siret = self._find_col(cols, "siret")
        c_conso = self._find_col(cols, "conso")
        c_puiss = self._find_col(cols, "puissance")
        c_seg = self._find_col(cols, "segment")
        c_fourn = self._find_col(cols, "fournisseur")
        c_end = self._find_col(cols, "date_fin")
        
        # Détails 4 Postes (Puissance)
        c_ps_hph = self._find_col(cols, "ps_hph")
        c_ps_hch = self._find_col(cols, "ps_hch")
        c_ps_hpe = self._find_col(cols, "ps_hpe")
        c_ps_hce = self._find_col(cols, "ps_hce")
        
        # Détails 4 Postes (Conso)
        c_c_hph = self._find_col(cols, "conso_hph")
        c_c_hch = self._find_col(cols, "conso_hch")
        c_c_hpe = self._find_col(cols, "conso_hpe")
        c_c_hce = self._find_col(cols, "conso_hce")
        
        # Détails 4 Postes (Prix)
        c_p_hph = self._find_col(cols, "prix_hph")
        c_p_hch = self._find_col(cols, "prix_hch")
        c_p_hpe = self._find_col(cols, "prix_hpe")
        c_p_hce = self._find_col(cols, "prix_hce")
        
        c_abo = self._find_col(cols, "abonnement")
        c_tax = self._find_col(cols, "taxes")
        c_stock = self._find_col(cols, "stockage")

        for idx, row in df.iterrows():
            try:
                # 1. PDL (Nettoyage Scientifique)
                pdl = self._safe_str_clean(row.get(c_pdl, f"TMP_{idx}"))
                
                # 2. Nommage
                nom_brut = str(row.get(c_nom, "")).strip()
                entite_brut = str(row.get(c_entite, "")).strip()
                ville = str(row.get(c_ville, "")).strip()
                
                final_name = "Site Inconnu"
                is_nom_bad = not nom_brut or any(b in nom_brut.upper() for b in self.NAME_BLACKLIST)
                if not is_nom_bad: final_name = nom_brut
                elif entite_brut and not any(b in entite_brut.upper() for b in self.NAME_BLACKLIST): final_name = entite_brut
                elif ville: final_name = f"{ville} ({pdl[-4:]})"

                # 3. Conso & Unités
                raw_conso = self._safe_float(row.get(c_conso))
                conso_kwh = raw_conso
                if c_conso and "MWH" in str(c_conso).upper(): conso_kwh = raw_conso * 1000.0
                # Fix Decimal Force (Gaz)
                if conso_kwh > 10_000_000: conso_kwh = conso_kwh / 1000.0

                # 4. Énergie
                segment = str(row.get(c_seg, "")).upper()
                is_gas = False
                if "GAZ" in segment or "T1" in segment or "T2" in segment or "T3" in segment: is_gas = True
                elif c_pdl and "PCE" in str(c_pdl).upper(): is_gas = True
                energy_type = "gaz" if is_gas else "elec"

                site = {
                    "identity": { "id": pdl, "site_name": final_name, "entity_name": entite_brut, "siret": self._safe_str_clean(row.get(c_siret)) },
                    "location": { "address": str(row.get(c_addr, "")), "zip_code": self._safe_str_clean(row.get(c_cp, "")), "city": ville },
                    "contract": {
                        "pdl": pdl, "provider": str(row.get(c_fourn, "Inconnu")),
                        "segment": segment, "power": self._safe_float(row.get(c_puiss)),
                        "annual_volume_estimated": conso_kwh, "energy_type": energy_type,
                        "end_date": str(row.get(c_end, "")),
                        # STRUCTURE LEGACY EXACTE : power_details
                        "power_details": {
                            "hph": self._safe_float(row.get(c_ps_hph)), "hch": self._safe_float(row.get(c_ps_hch)),
                            "hpe": self._safe_float(row.get(c_ps_hpe)), "hce": self._safe_float(row.get(c_ps_hce))
                        },
                        "consumption_details": {
                            "hph": self._safe_float(row.get(c_c_hph)), "hch": self._safe_float(row.get(c_c_hch)),
                            "hpe": self._safe_float(row.get(c_c_hpe)), "hce": self._safe_float(row.get(c_c_hce))
                        }
                    },
                    # STRUCTURE LEGACY EXACTE : pricing
                    "pricing": {
                        "fix": self._safe_float(row.get(c_abo)),
                        "hph": self._safe_float(row.get(c_p_hph)), 
                        "hch": self._safe_float(row.get(c_p_hch)),
                        "hpe": self._safe_float(row.get(c_p_hpe)),
                        "hce": self._safe_float(row.get(c_p_hce)),
                        "tax": self._safe_float(row.get(c_tax)), 
                        "storage": self._safe_float(row.get(c_stock))
                    }
                }
                sites.append(site)
            except: continue
        return sites

    def parse_bpu_excel(self, file_content):
        # ... (Inchangé V130) ...
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
        # ... (Inchangé V130) ...
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
