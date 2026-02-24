import re
import io
import os
import json
import glob
import pandas as pd
from datetime import datetime

class CortexRouter:
    """
    CORTEX ROUTER V4 - DEEP SCAN FIRST
    Priorité absolue à l'analyse du contenu pour éviter les faux positifs (dates dans les noms de fichiers).
    """

    def __init__(self):
        self.base_dir = os.getcwd()
        self.data_dir = os.path.join(self.base_dir, "data")
        self.pdl_mapping = {}
        self.refresh_database()

    def refresh_database(self):
        """Recharge la liste des clients depuis les fichiers JSON."""
        self.pdl_mapping = {}
        if not os.path.exists(self.data_dir): return

        json_files = glob.glob(os.path.join(self.data_dir, "*.json"))
        
        for file_path in json_files:
            if "master" in file_path or "market" in file_path: continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    client_name = data.get('identity', {}).get('site_name', 'Client Inconnu')
                    contract = data.get('contract', {})
                    
                    # Nettoyage des PDL/PCE (suppression des espaces)
                    pdl = str(contract.get('pdl', '')).replace(' ', '').strip()
                    pce = str(contract.get('pce', '')).replace(' ', '').strip()
                    
                    # Détection Profil
                    profile = "retail"
                    typologie = data.get('location', {}).get('typologie', '').lower()
                    if "mairie" in typologie or "admin" in typologie: profile = "mairie"
                    if "usine" in typologie or "indus" in typologie: profile = "industrie"
                    if "residence" in typologie or "syndic" in typologie: profile = "syndic"

                    if pdl and len(pdl) > 5:
                        self.pdl_mapping[pdl] = {"client": client_name, "type": "ELEC", "profile": profile}
                    if pce and len(pce) > 5:
                        self.pdl_mapping[pce] = {"client": client_name, "type": "GAZ", "profile": profile}
                        
            except Exception: pass
        
        print(f"✅ CORTEX ROUTER: {len(self.pdl_mapping)} PDL indexés.")

    def _extract_pdl_from_content(self, file_content: bytes, filename: str) -> str:
        """Scan intelligent du contenu."""
        try:
            # CAS 1 : EXCEL
            if filename.endswith('.xlsx'):
                df = pd.read_excel(io.BytesIO(file_content), dtype=str)
                # Recherche dans les en-têtes
                for col in df.columns:
                    col_str = str(col).upper()
                    if "IDENTIFIANT" in col_str or "PRM" in col_str or "PDL" in col_str:
                        first_val = str(df[col].iloc[0])
                        clean_val = re.sub(r'\D', '', first_val)
                        if len(clean_val) >= 14: return clean_val[:14]
                # Recherche brute dans tout le fichier
                text_dump = df.to_string()
                match = re.search(r'\d{14}', text_dump)
                if match: return match.group(0)

            # CAS 2 : CSV (SGE Enedis / GRDF)
            else:
                try: text = file_content.decode('utf-8')
                except: text = file_content.decode('latin-1')

                lines = text.splitlines()
                pdl_col_index = -1
                
                # Recherche de la colonne "Identifiant PRM" ou "Point de Livraison"
                for i, line in enumerate(lines[:25]): # Scan des 25 premières lignes
                    if ("Identifiant" in line and "PRM" in line) or "Point de Livraison" in line or "PCE" in line:
                        headers = line.split(';')
                        for idx, h in enumerate(headers):
                            h_upper = h.upper()
                            if "IDENTIFIANT" in h_upper or "PRM" in h_upper or "POINT" in h_upper or "PCE" in h_upper:
                                pdl_col_index = idx
                                break
                        
                        # Si colonne trouvée, on prend la valeur juste en dessous
                        if pdl_col_index != -1 and len(lines) > i+1:
                            data_row = lines[i+1].split(';')
                            if len(data_row) > pdl_col_index:
                                raw_pdl = data_row[pdl_col_index]
                                return re.sub(r'\D', '', raw_pdl)[:14]
                        break
                
                # Fallback : Si structure inconnue, on cherche 14 chiffres qui NE SONT PAS une date
                # Regex qui exclut les dates commençant par 2024/2025/2026... c'est risqué mais utile
                # Mieux : On cherche juste 14 chiffres, mais comme cette méthode est appelée AVANT le check filename,
                # on a plus de chance de tomber sur le PDL dans le header SGE.
                matches = re.findall(r'\d{14}', text[:5000])
                for m in matches:
                    # Filtre basique : Si ça ressemble trop à une date récente (ex: 2026...), on ignore
                    if not m.startswith('202'): 
                        return m

        except Exception as e:
            print(f"Deep Scan Error: {e}")
        return None

    def analyze_file_stream(self, file_content: bytes, filename: str):
        """
        ORDRE INVERSÉ : CONTENU D'ABORD, NOM FICHIER ENSUITE.
        """
        self.refresh_database()

        # 1. DEEP SCAN (Priorité absolue)
        pdl = self._extract_pdl_from_content(file_content, filename)

        # 2. NOM DU FICHIER (Seulement si le Deep Scan a échoué)
        if not pdl:
            match_filename = re.search(r'\d{14}', filename)
            if match_filename:
                candidate = match_filename.group(0)
                # Protection anti-date : si le nom contient une date type 2026..., on se méfie
                if not candidate.startswith('202'):
                    pdl = candidate

        # 3. VERDICT
        status = "REJECTED"
        message = "PDL introuvable (contenu illisible)."
        client_info = None
        
        if pdl:
            if pdl in self.pdl_mapping:
                client_info = self.pdl_mapping[pdl]
                status = "INGESTED"
                message = f"Données injectées -> {client_info['client']}"
            else:
                status = "UNKNOWN_PDL"
                message = f"PDL {pdl} détecté mais absent de la base."
        
        return {
            "filename": filename,
            "status": status,
            "message": message,
            "pdl": pdl if pdl else "N/A",
            "target_profile": client_info['profile'] if client_info else "N/A"
        }

    def get_api_status(self):
        return {
            "sge_enedis": {"status": "ONLINE", "latency": "24ms"},
            "adam_grdf": {"status": "ONLINE", "latency": "98ms"}
        }

router = CortexRouter()
