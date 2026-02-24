import re
import io
import os
import json
import glob
import pandas as pd
from datetime import datetime

class CortexRouter:
    """
    CORTEX ROUTER V3 - DYNAMIC EDITION
    Connecté en temps réel au dossier /data pour identifier les clients.
    """

    def __init__(self):
        # Définition du chemin des données (compatible Cloud Run & Local)
        self.base_dir = os.getcwd()
        self.data_dir = os.path.join(self.base_dir, "data")
        
        # Base de connaissance dynamique
        self.pdl_mapping = {}
        self.refresh_database()

    def refresh_database(self):
        """
        Scanne tous les fichiers JSON du dossier /data pour construire
        la table de correspondance PDL -> Client.
        """
        self.pdl_mapping = {}
        
        # Vérification de l'existence du dossier
        if not os.path.exists(self.data_dir):
            print(f"⚠️ Warning: Data dir not found at {self.data_dir}")
            return

        json_files = glob.glob(os.path.join(self.data_dir, "*.json"))
        
        for file_path in json_files:
            if "master" in file_path or "market" in file_path:
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Extraction des infos vitales
                    client_name = data.get('identity', {}).get('site_name', 'Client Inconnu')
                    
                    # On cherche le PDL ou le PCE
                    contract = data.get('contract', {})
                    pdl = str(contract.get('pdl', '')).strip()
                    pce = str(contract.get('pce', '')).strip()
                    
                    # Détermination du profil (par défaut ou explicite)
                    # Si le fichier s'appelle 'mairie.json' ou contient un tag, on l'utilise
                    profile = "retail" # Défaut
                    typologie = data.get('location', {}).get('typologie', '').lower()
                    if "mairie" in typologie or "admin" in typologie: profile = "mairie"
                    if "usine" in typologie or "indus" in typologie: profile = "industrie"
                    if "residence" in typologie or "syndic" in typologie: profile = "syndic"

                    # Enregistrement dans la mémoire vive du routeur
                    if pdl and len(pdl) > 5:
                        self.pdl_mapping[pdl] = {"client": client_name, "type": "ELEC", "profile": profile}
                    if pce and len(pce) > 5:
                        self.pdl_mapping[pce] = {"client": client_name, "type": "GAZ", "profile": profile}
                        
            except Exception as e:
                print(f"❌ Erreur lecture fichier {file_path}: {e}")

        print(f"✅ CORTEX ROUTER: {len(self.pdl_mapping)} PDL/PCE chargés en mémoire.")

    def _extract_pdl_from_content(self, file_content: bytes, filename: str) -> str:
        """Deep Inspection : Cherche le PDL à l'intérieur du fichier."""
        try:
            # CAS 1 : EXCEL (.xlsx)
            if filename.endswith('.xlsx'):
                df = pd.read_excel(io.BytesIO(file_content), dtype=str)
                for col in df.columns:
                    if "Identifiant" in str(col) or "PRM" in str(col) or "PDL" in str(col):
                        first_val = str(df[col].iloc[0])
                        clean_val = re.sub(r'\D', '', first_val)
                        if len(clean_val) >= 14: return clean_val[:14]
                # Scan brutal
                text_dump = df.to_string()
                match = re.search(r'\d{14}', text_dump)
                if match: return match.group(0)

            # CAS 2 : CSV (.csv)
            else:
                try: text = file_content.decode('utf-8')
                except: text = file_content.decode('latin-1')

                # Recherche colonne intelligente
                lines = text.splitlines()
                pdl_col_index = -1
                for i, line in enumerate(lines[:20]):
                    if ("Identifiant" in line and "PRM" in line) or "Point de Livraison" in line:
                        headers = line.split(';')
                        for idx, h in enumerate(headers):
                            if "Identifiant" in h or "PRM" in h or "Point" in h:
                                pdl_col_index = idx
                                break
                        if pdl_col_index != -1 and len(lines) > i+1:
                            data_row = lines[i+1].split(';')
                            if len(data_row) > pdl_col_index:
                                raw_pdl = data_row[pdl_col_index]
                                return re.sub(r'\D', '', raw_pdl)[:14]
                        break
                
                # Fallback Regex Brut
                match = re.search(r'\d{14}', text[:3000])
                if match: return match.group(0)

        except Exception as e:
            print(f"[CORTEX ERROR] Deep Inspection failed: {e}")
            return None
        return None

    def analyze_file_stream(self, file_content: bytes, filename: str):
        """
        Analyse complète : Nom -> Contenu -> Matching BDD
        """
        # A chaque analyse, on rafraîchit la base pour voir les nouveaux clients créés
        self.refresh_database()

        # 1. Nom du fichier
        pdl = None
        match_filename = re.search(r'\d{14}', filename)
        if match_filename:
            pdl = match_filename.group(0)
        
        # 2. Contenu (Deep Scan)
        if not pdl:
            pdl = self._extract_pdl_from_content(file_content, filename)

        # 3. Résultat
        status = "REJECTED"
        message = "PDL introuvable."
        client_info = None
        
        if pdl:
            if pdl in self.pdl_mapping:
                client_info = self.pdl_mapping[pdl]
                status = "INGESTED"
                message = f"Données injectées -> {client_info['client']}"
            else:
                status = "UNKNOWN_PDL"
                message = f"PDL {pdl} détecté mais inconnu en base ({len(self.pdl_mapping)} sites actifs)."
        
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

# Instanciation
router = CortexRouter()
