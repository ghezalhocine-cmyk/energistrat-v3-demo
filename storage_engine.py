# storage_engine.py V7.0
# GESTIONNAIRE DE DONNÉES STRUCTURÉES
import os
import json
import shutil
from datetime import datetime

DATA_ROOT = "data_store"
INDEX_FILE = os.path.join(DATA_ROOT, "master_index.json")

class StorageEngine:
    def __init__(self):
        # Initialisation de l'arborescence
        if not os.path.exists(DATA_ROOT):
            os.makedirs(DATA_ROOT)
        
        # Création/Chargement de l'index maître (Simule une BDD)
        if not os.path.exists(INDEX_FILE):
            self.index = {"clients": {}, "last_update": None}
            self._save_index()
        else:
            with open(INDEX_FILE, 'r') as f:
                self.index = json.load(f)

    def _save_index(self):
        self.index["last_update"] = datetime.now().isoformat()
        with open(INDEX_FILE, 'w') as f:
            json.dump(self.index, f, indent=4)

    def save_analysis(self, client_slug, site_name, data, file_type="SGE"):
        """
        Sauvegarde une analyse de manière structurée :
        data_store / [CLIENT] / [SITE] / [DATE]_[TYPE].json
        """
        # 1. Normalisation
        safe_client = "".join([c for c in client_slug if c.isalnum() or c in '-_']).upper()
        safe_site = "".join([c for c in site_name if c.isalnum() or c in '-_']).upper()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 2. Création Arborescence Physique
        client_path = os.path.join(DATA_ROOT, safe_client)
        site_path = os.path.join(client_path, safe_site)
        os.makedirs(site_path, exist_ok=True)
        
        # 3. Nom du fichier physique
        filename = f"{timestamp}_{file_type}.json"
        full_path = os.path.join(site_path, filename)
        
        # 4. Écriture du JSON
        with open(full_path, 'w') as f:
            json.dump(data, f)
            
        # 5. Mise à jour de l'INDEX (Logique BDD)
        if safe_client not in self.index["clients"]:
            self.index["clients"][safe_client] = {"sites": {}}
            
        if safe_site not in self.index["clients"][safe_client]["sites"]:
            self.index["clients"][safe_client]["sites"][safe_site] = []
            
        # On ajoute l'entrée dans l'historique du site
        entry = {
            "date": datetime.now().isoformat(),
            "type": file_type,
            "path": full_path,
            "kpi_summary": {
                "conso": data.get('kpi', {}).get('conso_totale'),
                "pmax": data.get('kpi', {}).get('p_max')
            },
            "token": data.get('meta', {}).get('token')
        }
        
        self.index["clients"][safe_client]["sites"][safe_site].append(entry)
        self._save_index()
        
        return full_path, entry

    def get_client_structure(self):
        """Retourne l'arbre des clients et sites existants"""
        return self.index["clients"]

# Instance unique
db = StorageEngine()
