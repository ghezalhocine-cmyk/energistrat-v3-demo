import re
import csv
import io
import pandas as pd # Nécessite pip install pandas openpyxl
from datetime import datetime

class CortexRouter:
    """
    CORTEX ROUTER V2 - SGE EDITION
    Capable de lire à l'intérieur des fichiers (Deep Inspection) pour trouver le PRM/PDL.
    """

    def __init__(self):
        # Simulation Base Clients (Mapping PDL -> UUID Client)
        self.pdl_mapping = {
            "30002000000000": {"client": "Usine SGE Test", "type": "ELEC_HTA", "profile": "industrie"},
            "12345678901234": {"client": "Retail Store Paris", "type": "ELEC", "profile": "retail"},
            "98765432109876": {"client": "Mairie de Lyon", "type": "GAZ", "profile": "public"},
        }

    def _extract_pdl_from_content(self, file_content: bytes, filename: str) -> str:
        """
        Tente de trouver un PRM/PDL (14 chiffres) à l'intérieur du fichier
        en gérant le format SGE (CSV point-virgule) ou Excel.
        """
        pdl = None
        
        try:
            # CAS 1 : Fichier Excel (.xlsx)
            if filename.endswith('.xlsx'):
                df = pd.read_excel(io.BytesIO(file_content), dtype=str)
                # Chercher une colonne qui ressemble à "Identifiant PRM"
                for col in df.columns:
                    if "Identifiant" in str(col) or "PRM" in str(col):
                        # Prendre la première valeur non vide
                        first_val = str(df[col].iloc[0])
                        clean_val = re.sub(r'\D', '', first_val) # Garder que les chiffres
                        if len(clean_val) >= 14:
                            return clean_val[:14]

            # CAS 2 : Fichier CSV (.csv) - Format SGE
            else:
                # On décode les bytes en string (souvent encodage latin-1 ou utf-8 pour SGE)
                try:
                    text_content = file_content.decode('utf-8')
                except UnicodeDecodeError:
                    text_content = file_content.decode('latin-1')

                # On lit les premières lignes
                lines = text_content.splitlines()
                
                # Recherche intelligente : on cherche le header puis la data
                header_index = -1
                pdl_col_index = 0
                
                for i, line in enumerate(lines[:20]): # Scan des 20 premières lignes
                    if "Identifiant" in line and "PRM" in line:
                        header_index = i
                        # Trouver l'index de la colonne (séparateur ; pour SGE)
                        headers = line.split(';')
                        for idx, h in enumerate(headers):
                            if "Identifiant" in h:
                                pdl_col_index = idx
                                break
                        break
                
                # Si header trouvé, on regarde la ligne d'après
                if header_index != -1 and len(lines) > header_index + 1:
                    data_line = lines[header_index + 1]
                    columns = data_line.split(';')
                    if len(columns) > pdl_col_index:
                        raw_pdl = columns[pdl_col_index]
                        # Nettoyage (enlever les guillemets éventuels ou espaces)
                        return re.sub(r'\D', '', raw_pdl)[:14]
                
                # FALLBACK : Regex brut sur tout le début du fichier si structure inconnue
                match = re.search(r'\d{14}', text_content[:1000])
                if match:
                    return match.group(0)

        except Exception as e:
            print(f"Erreur Deep Inspection: {e}")
            return None
        
        return None

    def analyze_file_stream(self, file_content: bytes, filename: str):
        """
        Analyse complète : Nom de fichier D'ABORD, Contenu ENSUITE.
        """
        # 1. Tentative via Nom de fichier (Rapide)
        pdl = None
        match_filename = re.search(r'\d{14}', filename)
        if match_filename:
            pdl = match_filename.group(0)
        
        # 2. Si échec, Tentative via Contenu (Deep Scan SGE)
        if not pdl:
            pdl = self._extract_pdl_from_content(file_content, filename)

        # 3. Résultat
        status = "REJECTED"
        message = "PDL introuvable (Nom ou Contenu)."
        client_info = None
        points = 0

        if pdl:
            if pdl in self.pdl_mapping:
                client_info = self.pdl_mapping[pdl]
                status = "INGESTED"
                # Estimation des points de mesure (taille / ~50 octets par ligne)
                points = int(len(file_content) / 50) 
                message = f"SGE Data -> {client_info['client']}"
            else:
                status = "UNKNOWN_PDL"
                message = f"PDL {pdl} détecté mais inconnu en base."
        
        return {
            "filename": filename,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "pdl": pdl if pdl else "N/A",
            "status": status,
            "message": message,
            "points_injected": points,
            "target_profile": client_info['profile'] if client_info else "N/A"
        }

    def get_api_status(self):
        return {
            "sge_enedis": {"status": "ONLINE", "latency": "24ms"},
            "adam_grdf": {"status": "ONLINE", "latency": "98ms"},
            "chorus_pro": {"status": "MAINTENANCE", "latency": "0ms"}
        }

router = CortexRouter()
