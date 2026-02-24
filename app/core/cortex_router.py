import re
import io
import os
import json
import glob
import pandas as pd
from datetime import datetime

class CortexRouter:
    """
    CORTEX ROUTER V5 - CALCULATION ENGINE
    Reconnait le client ET calcule/sauvegarde le volume réel pour le Forecast.
    """

    def __init__(self):
        self.base_dir = os.getcwd()
        self.data_dir = os.path.join(self.base_dir, "data")
        self.pdl_mapping = {}
        self.refresh_database()

    def refresh_database(self):
        """Recharge la liste des clients et leurs chemins de fichier."""
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
                    
                    # Nettoyage
                    pdl = str(contract.get('pdl', '')).replace(' ', '').strip()
                    pce = str(contract.get('pce', '')).replace(' ', '').strip()
                    
                    # Détection Profil
                    profile = "retail"
                    typologie = data.get('location', {}).get('typologie', '').lower()
                    if "mairie" in typologie or "admin" in typologie: profile = "mairie"
                    if "usine" in typologie or "indus" in typologie: profile = "industrie"
                    if "residence" in typologie or "syndic" in typologie: profile = "syndic"

                    # Mapping : On stocke aussi le chemin du fichier pour pouvoir écrire dedans
                    info = {"client": client_name, "type": "ELEC", "profile": profile, "path": file_path}
                    
                    if pdl and len(pdl) > 5:
                        self.pdl_mapping[pdl] = info
                    if pce and len(pce) > 5:
                        info["type"] = "GAZ"
                        self.pdl_mapping[pce] = info
                        
            except Exception: pass
        
        print(f"✅ CORTEX ROUTER: {len(self.pdl_mapping)} PDL connectés.")

    def _extract_pdl_from_content(self, file_content: bytes, filename: str):
        """Scan intelligent (Deep Scan) + Détection du Header."""
        pdl = None
        header_row = 0
        df = None

        try:
            # CAS 1 : EXCEL
            if filename.endswith('.xlsx'):
                df = pd.read_excel(io.BytesIO(file_content), dtype=str)
                # Recherche Header & PDL
                for idx, row in df.head(20).iterrows():
                    row_str = " ".join([str(x) for x in row.values])
                    match = re.search(r'\d{14}', row_str)
                    if match and not match.group(0).startswith('202'):
                        pdl = match.group(0)
                        break
                return pdl, df, 0 # Excel gère ses headers différemment

            # CAS 2 : CSV (SGE)
            else:
                try: text = file_content.decode('utf-8')
                except: text = file_content.decode('latin-1')

                lines = text.splitlines()
                
                # 1. Trouver le PDL et la ligne d'en-tête
                for i, line in enumerate(lines[:30]):
                    # Recherche PDL brut
                    match = re.search(r'\d{14}', line)
                    if match and not match.group(0).startswith('202'):
                        pdl = match.group(0)
                    
                    # Recherche ligne d'en-tête (colonnes)
                    if "Valeur" in line or "Consommation" in line or "Nature" in line:
                        header_row = i
                        # Si on a le PDL et le header, on arrête
                        if pdl: break
                
                # Si pas de PDL trouvé dans les premières lignes, on cherche dans tout le début
                if not pdl:
                    match = re.search(r'\d{14}', text[:5000])
                    if match and not match.group(0).startswith('202'):
                        pdl = match.group(0)

                return pdl, io.BytesIO(file_content), header_row

        except Exception as e:
            print(f"Deep Scan Error: {e}")
            return None, None, 0

    def _process_and_save_volume(self, pdl, file_stream, header_row, filename):
        """Calcule le volume et met à jour le JSON client."""
        try:
            client_info = self.pdl_mapping.get(pdl)
            if not client_info: return "Client inconnu"

            # Lecture intelligente avec Pandas
            # On saute les lignes avant le header
            try:
                if filename.endswith('.xlsx'):
                    df = file_stream # Déjà chargé
                else:
                    df = pd.read_csv(file_stream, sep=';', skiprows=header_row, encoding='latin-1', on_bad_lines='skip')
            except:
                # Tentative avec séparateur virgule
                file_stream.seek(0)
                df = pd.read_csv(file_stream, sep=',', skiprows=header_row, encoding='utf-8', on_bad_lines='skip')

            # Recherche de la colonne Valeur
            val_col = None
            for col in df.columns:
                if "Valeur" in str(col) or "Conso" in str(col) or "P (W)" in str(col):
                    val_col = col
                    break
            
            if not val_col:
                return "Colonne 'Valeur' introuvable"

            # Nettoyage et Somme
            # SGE donne des Watts (puissance moyenne 10min). 
            # Volume (Wh) = Somme(W) * (10min / 60min)
            # Volume (kWh) = Volume (Wh) / 1000
            
            # Conversion numérique (gestion des virgules)
            if df[val_col].dtype == object:
                df[val_col] = df[val_col].astype(str).str.replace(',', '.').str.replace(r'\s+', '', regex=True)
            
            total_watts = pd.to_numeric(df[val_col], errors='coerce').sum()
            
            # Estimation Pas de temps (si > 4000 points par mois, c'est du 10min)
            # Hypothèse SGE standard : Pas 10 min
            volume_kwh = (total_watts * 10 / 60) / 1000
            volume_mwh = round(volume_kwh / 1000, 2)

            # Mise à jour du JSON Client
            json_path = client_info['path']
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Injection des données
            if 'kpis' not in data: data['kpis'] = {}
            data['kpis']['volume_mwh'] = volume_mwh
            
            if 'contract' not in data: data['contract'] = {}
            if 'consumption_details' not in data['contract']: data['contract']['consumption_details'] = {}
            data['contract']['consumption_details']['volume_annuel'] = int(volume_kwh)
            data['contract']['consumption_details']['last_upload'] = datetime.now().strftime("%d/%m/%Y")

            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)

            return f"Volume calculé : {volume_mwh} MWh (Sauvegardé)"

        except Exception as e:
            print(f"Erreur Calcul Volume: {e}")
            return "Erreur calcul volume"

    def analyze_file_stream(self, file_content: bytes, filename: str):
        """Orchestration Complète."""
        self.refresh_database()

        # 1. Deep Scan pour trouver le PDL et préparer la lecture
        pdl, stream, header_row = self._extract_pdl_from_content(file_content, filename)

        # 2. Fallback Nom Fichier
        if not pdl:
            match_filename = re.search(r'\d{14}', filename)
            if match_filename and not match_filename.group(0).startswith('202'):
                pdl = match_filename.group(0)
                stream = io.BytesIO(file_content) # Reset stream

        status = "REJECTED"
        message = "PDL introuvable."
        client_info = None
        
        if pdl:
            if pdl in self.pdl_mapping:
                client_info = self.pdl_mapping[pdl]
                
                # 3. CALCUL DU VOLUME ET SAUVEGARDE
                vol_msg = self._process_and_save_volume(pdl, stream, header_row, filename)
                
                status = "INGESTED"
                message = f"Client: {client_info['client']} | {vol_msg}"
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
        return {"sge_enedis": {"status": "ONLINE", "latency": "24ms"}, "adam_grdf": {"status": "ONLINE", "latency": "98ms"}}

router = CortexRouter()
