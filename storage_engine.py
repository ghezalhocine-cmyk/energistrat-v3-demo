# storage_engine.py V7.1
# GESTIONNAIRE DE DONNÉES STRUCTURÉES & AGRÉGATION
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
        # On stocke les KPI clés directement dans l'index pour une lecture rapide
        entry = {
            "date": datetime.now().isoformat(),
            "type": file_type,
            "path": full_path,
            "kpi_summary": {
                "conso": data.get('kpi', {}).get('conso_totale', 0),
                "pmax": data.get('kpi', {}).get('p_max', 0)
            },
            "token": data.get('meta', {}).get('token')
        }
        
        self.index["clients"][safe_client]["sites"][safe_site].append(entry)
        self._save_index()
        
        return full_path, entry

    def get_client_structure(self):
        """Retourne l'arbre des clients et sites existants"""
        return self.index["clients"]

    # --- NOUVEAUTÉ V7.1 : MOTEUR D'AGRÉGATION ---
    def aggregate_client_data(self, client_slug):
        """
        Calcule les totaux (Conso, Puissance) pour tout un groupe client.
        """
        safe_client = "".join([c for c in client_slug if c.isalnum() or c in '-_']).upper()
        
        if safe_client not in self.index["clients"]:
            return {"success": False, "error": "Client introuvable"}

        total_conso = 0
        total_pmax = 0
        sites_details = []
        
        client_data = self.index["clients"][safe_client]
        
        # On parcourt chaque site du client
        for site_name, history in client_data["sites"].items():
            if not history:
                continue
                
            # On prend la dernière analyse en date (la plus récente)
            latest_entry = history[-1]
            kpi = latest_entry.get("kpi_summary", {})
            
            conso = kpi.get("conso", 0)
            pmax = kpi.get("pmax", 0)
            
            # Agrégation
            total_conso += int(conso)
            total_pmax += float(pmax)
            
            sites_details.append({
                "site": site_name,
                "conso": conso,
                "pmax": pmax,
                "last_update": latest_entry.get("date")
            })

        return {
            "success": True,
            "client": safe_client,
            "site_count": len(sites_details),
            "global_conso": total_conso,
            "global_pmax": round(total_pmax, 2),
            "sites": sites_details
        }

# Instance unique
db = StorageEngine()
