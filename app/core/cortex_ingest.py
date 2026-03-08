import pandas as pd
import numpy as np
import io
import logging
import chardet
import re
import uuid
from datetime import datetime

try:
    from app.core.cortex_db import db
except ImportError:
    try:
        from core.cortex_db import db
    except ImportError:
        db = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_INGEST_V7.2")

class CortexIngest:
    def __init__(self):
        self.version = "7.2 (Anti-Scientific Notation)"
        self.COLUMN_MAPPING = {
            "pdl":["PDL", "POINT_DE_LIVRAISON", "PRM", "PCE", "ID_SITE", "REFERENCE", "REF_PDL"],
            "site_label":["NOM_SITE", "LIBELLE_PDL", "NOM_POINT_DE_LIVRAISON", "SITE", "LABEL", "NOM"],
            "entity":["ENTITE", "RAISON_SOCIALE", "CLIENT", "TITULAIRE", "NOM_CLIENT", "SOCIETE"],
            "siret": ["SIRET", "SIRET_SITE", "SIREN"],
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
            "fta": ["FTA", "FORMULE_TARIFAIRE", "OPTION"],
            "cja":["CJA", "CJA_MWH_J", "CAPACITE_JOURNALIERE"],
            "profil": ["PROFIL", "PROFIL_GAZ"],
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
            "conso_hph":["CONSO HPH", "C_HPH", "HP HAUTE", "CONSO_HPH"],
            "conso_hch":["CONSO HCH", "C_HCH", "HC HAUTE", "CONSO_HCH"],
            "conso_hpe":["CONSO HPE", "C_HPE", "HP BASSE", "CONSO_HPE"],
            "conso_hce":["CONSO HCE", "C_HCE", "HC BASSE", "CONSO_HCE"],
            "prix_unitaire":["PRIX_MOLECULE", "PRIX_HPH", "PRIX_UNITAIRE", "P1", "HPH", "PRIX"],
            "prix_hch":["PRIX_HCH", "HCH"],
            "prix_hpe": ["PRIX_HPE", "HPE"],
            "prix_hce": ["PRIX_HCE", "HCE"],
            "abonnement": ["ABONNEMENT", "ABO", "FIXE", "PRIME_FIXE", "PART_FIXE"],
            "taxes": ["TAXES", "CSPE", "TICGN", "CTA"],
            "stockage":["TERME_STOCK", "STOCKAGE", "TERME_STOCKAGE"]
        }
        self.NAME_BLACKLIST =["CLIENT", "SITE", "INCONNU", "NAN", "NONE", "NOM_SITE", "0", ".", "COMMUNE", "MAIRIE", "SOCIETE"]

    def _clean_header(self, h):
        return str(h).upper().strip().replace('É', 'E').replace('È', 'E').replace(' ', '_').replace('.', '').replace('-', '_')

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
        """ Nettoyeur IA : Détruit la notation scientifique d'Excel (ex: 3,00E+13 -> 30000000000000) """
        if pd.isna(val) or val == '' or val is None: return ""
        s = str(val).upper().replace(',', '.').strip()
        
        # FIX EXCEL : Désamorçage de la notation scientifique (E+13)
        if 'E+' in s:
            try:
                # Convertit "3.0E+13" en nombre réel, puis en entier, puis en texte
                return str(int(float(s)))
            except:
                pass
                
        # Cas classique : suppression des ".0" à la fin d'un SIRET
        if s.endswith('.0'):
            s = s[:-2]
            
        return s

    def parse_mass_import_unified(self, file_content):
        sites =[]
        df = None
        buffer = io.BytesIO(file_content)
        try: df = pd.read_excel(buffer, dtype=str)
        except:
            try: buffer.seek(0); df = pd.read_csv(buffer, sep=';', encoding='latin-1', dtype=str, on_bad_lines='skip')
            except:
                try: buffer.seek(0); df = pd.read_csv(buffer, sep=',', encoding='utf-8', dtype=str, on_bad_lines='skip')
                except: return []

        if df is None or df.empty: return[]

        cols = df.columns
        c_pdl = self._find_col(cols, "pdl")
        c_siret = self._find_col(cols, "siret")
        
        if not c_pdl and not c_siret: 
            return []

        c_nom = self._find_col(cols, "site_label")
        c_entite = self._find_col(cols, "entity")
        c_addr = self._find_col(cols, "adresse")
        c_cp = self._find_col(cols, "cp")
        c_ville = self._find_col(cols, "ville")
        c_ref_copro = self._find_col(cols, "ref_copro")
        c_naf = self._find_col(cols, "naf") 
        c_insee = self._find_col(cols, "insee") 
        c_surface = self._find_col(cols, "surface")
        c_typologie = self._find_col(cols, "typologie")
        c_chauff = self._find_col(cols, "chauffage")
        c_isol = self._find_col(cols, "isolation")
        c_regul = self._find_col(cols, "regulation")
        c_fourn = self._find_col(cols, "fournisseur")
        
        c_conso = self._find_col(cols, "conso")
        c_puiss = self._find_col(cols, "puissance")
        c_pmax = self._find_col(cols, "p_max")
        c_seg = self._find_col(cols, "segment")

        for idx, row in df.iterrows():
            try:
                # Création d'un ID Absolu (Priorité au PDL, sinon SIRET, sinon ID généré)
                pdl = self._safe_str_clean(row.get(c_pdl, "")) if c_pdl else ""
                siret = self._safe_str_clean(row.get(c_siret, "")) if c_siret else ""
                site_id = pdl if pdl else (siret if siret else f"GEN_{uuid.uuid4().hex[:8]}")
                
                nom_brut = str(row.get(c_nom, "")).strip() if c_nom else ""
                ville = str(row.get(c_ville, "")).strip() if c_ville else ""
                final_name = nom_brut if nom_brut else f"Site {site_id}"

                segment = str(row.get(c_seg, "")).upper() if c_seg else ""
                is_gas = False
                if "GAZ" in segment or "T1" in segment or "T2" in segment or "T3" in segment: is_gas = True
                elif "PCE" in str(c_pdl).upper(): is_gas = True
                energy_type = "gaz" if is_gas else "elec"
                
                provider_excel = self._safe_str_clean(row.get(c_fourn, "")) if c_fourn else "Inconnu"

                # STRUCTURE PARFAITE V7
                site = {
                    "identity": { 
                        "id": site_id, 
                        "site_name": final_name, 
                        "siret": siret,
                        "ref_copro": self._safe_str_clean(row.get(c_ref_copro)) if c_ref_copro else "",
                        "naf": self._safe_str_clean(row.get(c_naf)) if c_naf else ""
                    },
                    "location": { 
                        "address": str(row.get(c_addr, "")) if c_addr else "", 
                        "zip_code": self._safe_str_clean(row.get(c_cp, "")) if c_cp else "", 
                        "city": ville,
                        "surface": self._safe_float(row.get(c_surface)) if c_surface else 0.0,
                        "typologie": self._safe_str_clean(row.get(c_typologie)) if c_typologie else ""
                    },
                    "contract": {
                        "pdl": pdl, 
                        "provider": provider_excel,
                        "segment": segment, 
                        "power": self._safe_float(row.get(c_puiss)) if c_puiss else 0.0,
                        "energy_type": energy_type
                    }
                }
                
                if db:
                    db.save_site(site_id, site)
                sites.append(site)
            except Exception as e: print(f"Erreur Ligne CSV: {e}")
        return sites

    def parse_load_curve(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            enc = chardet.detect(buffer.read(10000))['encoding'] or 'utf-8'
            buffer.seek(0)
            try: df = pd.read_csv(buffer, sep=';', encoding=enc, on_bad_lines='skip')
            except: 
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=',', encoding=enc, on_bad_lines='skip')
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
