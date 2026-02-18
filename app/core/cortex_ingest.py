import pandas as pd
import numpy as np
import io
import re
import logging
import csv
import chardet

# CONFIGURATION
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V54")

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

class CortexIngest:
    def __init__(self):
        self.version = "54.0 (Universal: Elec Expert + Gaz Expert + OPH)"
        
        # MAPPING INTELLIGENT (Dictionnaire de Synonymes)
        self.COLUMN_MAPPING = {
            # IDENTIFICATION
            "pdl": ["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE"],
            "nom": ["NOM_SITE", "NOM", "ENTITE", "RAISON_SOCIALE", "CLIENT"],
            "siret": ["SIRET_SITE", "SIRET"],
            "naf": ["NAF", "CODE_NAF"],
            
            # LOCALISATION
            "adresse": ["ADRESSE_SITE", "ADRESSE", "RUE"],
            "cp": ["CP", "CODE_POSTAL"],
            "ville": ["VILLE", "COMMUNE"],
            "surface": ["SURFACE_M2", "SURFACE", "M2", "SHAB"],
            
            # CONTRAT & TECH
            "segment": ["SEGMENT", "SEGMENT_GAZ", "TARIF"],
            "fournisseur": ["FOURNISSEUR", "PROVIDER"],
            "date_fin": ["DATE_FIN", "ECHEANCE"],
            "puissance": ["PUISSANCE_SOUSCRITE_MAX", "PUISSANCE", "PS_MAX", "CAR_MWH", "CAR"], # CAR est la ref puissance gaz
            "conso": ["VOLUME_ANNUEL_TOTAL", "CONSO_ANNUELLE", "VOLUME", "CJA_MWH_J", "CAR_MWH"], # CAR aussi utilisé comme ref volume
            
            # DETAILS PUISSANCE ELEC (4 Postes)
            "ps_hph": ["PS_HPH"], "ps_hch": ["PS_HCH"], "ps_hpe": ["PS_HPE"], "ps_hce": ["PS_HCE"],
            
            # DETAILS CONSO ELEC (4 Postes)
            "conso_hph": ["CONSO_HPH"], "conso_hch": ["CONSO_HCH"], "conso_hpe": ["CONSO_HPE"], "conso_hce": ["CONSO_HCE"],
            
            # PRIX & BUDGET
            "abonnement": ["ABONNEMENT", "ABO", "PRIME_FIXE"],
            "prix_hph": ["PRIX_HPH", "PRIX_MOLECULE_MWH", "PRIX_MOLECULE"], # HPH sert de base unique pour le gaz
            "prix_hch": ["PRIX_HCH"], "prix_hpe": ["PRIX_HPE"], "prix_hce": ["PRIX_HCE"],
            "taxes": ["TAXES", "CSPE", "TICGN"],
            "stockage": ["TERME_STOCKAGE", "TERME_STOCKAGE_CPB", "STOCKAGE"], # Specifique Gaz
            
            # OPH / HABITAT (Colonnes à ajouter manuellement dans l'Excel si besoin)
            "p1": ["BUDGET_P1", "P1", "COUT_ENERGIE"], 
            "p2": ["BUDGET_P2", "P2", "MAINTENANCE"],
            "tantiemes": ["TANTIEMES", "PART_COPRO"], 
            "dpe": ["DPE", "ETIQUETTE"]
        }

    # --- UTILITAIRES DE NETTOYAGE ---
    def _clean_header(self, header):
        return str(header).upper().strip().replace(' ', '_').replace('.', '').replace('É', 'E')

    def _find_col(self, df_cols, key):
        candidates = self.COLUMN_MAPPING.get(key, [])
        for col in df_cols:
            clean = self._clean_header(col)
            if clean in candidates: return col 
            for cand in candidates:
                if cand in clean: return col 
        return None

    def _safe_float(self, val):
        if pd.isna(val) or val == '': return 0.0
        # Gère 1 000,50 et 1.000,50
        s = str(val).replace(' ', '').replace('\xa0', '').replace('€', '').replace('%', '').replace('kVA', '')
        s = s.replace(',', '.')
        try: return float(s)
        except: return 0.0

    def _safe_str_clean(self, val):
        """ Nettoie les notations scientifiques Excel (ex: 2,14E+13 -> 21400000000000) """
        if pd.isna(val) or val == '': return ""
        s = str(val).replace(',', '.')
        try:
            if 'E+' in s or ('e+' in s):
                return str(int(float(s))) # Conversion scientifique -> entier -> string
            if '.' in s and s.replace('.', '').isdigit():
                return str(int(float(s))) # Enlève le .0 à la fin
            return s.strip()
        except:
            return str(val).strip()

    # =========================================================
    # IMPORT UNIFIÉ (ELEC + GAZ + OPH)
    # =========================================================
    def parse_mass_import_unified(self, file_content):
        sites = []
        df = None
        buffer = io.BytesIO(file_content)

        # 1. Lecture Robuste
        try:
            df = pd.read_excel(buffer) # Priorité Excel
        except:
            buffer.seek(0)
            enc = chardet.detect(buffer.read())['encoding'] or 'utf-8'
            buffer.seek(0)
            try: df = pd.read_csv(buffer, sep=';', encoding=enc, dtype=str)
            except: df = pd.read_csv(buffer, sep=',', encoding=enc, dtype=str)

        if df is None or df.empty: return []

        cols = df.columns
        
        # 2. Mapping des Colonnes
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
        c_stock = self._find_col(cols, "stockage") # Gaz
        
        c_p1 = self._find_col(cols, "p1")
        c_p2 = self._find_col(cols, "p2")
        c_dpe = self._find_col(cols, "dpe")
        c_tant = self._find_col(cols, "tantiemes")

        # 3. Extraction
        for _, row in df.iterrows():
            try:
                # Identification
                nom = str(row.get(c_nom, 'Site Inconnu'))
                pdl = self._safe_str_clean(row.get(c_pdl, '000'))
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
                        "end_date": str(row.get(c_end, '')),
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
                        "storage": str(self._safe_float(row.get(c_stock))), # Gaz Specific
                        "p1_budget": self._safe_float(row.get(c_p1)),
                        "p2_budget": self._safe_float(row.get(c_p2))
                    },
                    "technical": {
                        "dpe": str(row.get(c_dpe, 'D')),
                        "tantiemes": self._safe_float(row.get(c_tant, 0))
                    }
                }
                sites.append(site)
            except Exception as e:
                continue

        logger.info(f"Import {len(sites)} sites OK")
        return sites

    # --- LOAD CURVE (Legacy) ---
    def parse_load_curve(self, content, filename):
        try:
            content_str = content.decode('latin-1', errors='ignore')
            pdl_match = re.search(r'\b(\d{14})\b', content_str)
            pdl = pdl_match.group(1) if pdl_match else "Inconnu"
            df = pd.read_csv(io.StringIO(content_str), sep=';', on_bad_lines='skip', low_memory=False)
            df.columns = [str(c).upper().strip() for c in df.columns]
            col_date = next((c for c in df.columns if "DATE" in c), None)
            col_val = next((c for c in df.columns if "PUISSANCE" in c), None)
            if not col_date or not col_val: return None, 0, {}
            df = df.rename(columns={col_date: 'date', col_val: 'val'})
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
            df = df.dropna().sort_values('date')
            df['date_str'] = df['date'].dt.strftime('%d/%m %H:%M')
            return df, 10, {"pdl": pdl}
        except: return None, 0, {}

    # --- BPU (Legacy) ---
    def parse_bpu_excel(self, content):
        try:
            return pd.read_excel(io.BytesIO(content), sheet_name=0), False
        except: return None, False

ingest = CortexIngest()
