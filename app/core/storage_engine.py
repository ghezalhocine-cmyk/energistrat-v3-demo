import json
import os
import datetime
from pathlib import Path
import logging

# CONFIGURATION DU CHEMIN
# Sur Cloud Run, ce chemin sera monté. En local, il se crée dans le projet.
DATA_ROOT = Path("/app/data") if os.path.exists("/app/data") else Path("data")
INDEX_FILE = DATA_ROOT / "master_index.json"
VAULT_FILE = DATA_ROOT / "system" / "secure_vault.json"

# Logger pour le debug production
logger = logging.getLogger("STORAGE_ENGINE")

class StorageEngine:
    def __init__(self):
        self.version = "3.2 (ERP Extension)"
        self.index = {}
        self._ensure_structure()
        self.load_index()

    def _ensure_structure(self):
        """Crée l'arborescence physique initiale."""
        dirs = [
            DATA_ROOT / "raw_uploads",
            DATA_ROOT / "raw_uploads" / "API",
            DATA_ROOT / "orgs",
            DATA_ROOT / "clients",   # NOUVEAU : Pour Settings V21
            DATA_ROOT / "partners",  # NOUVEAU : Pour Settings V22
            DATA_ROOT / "archives" / "INBOX",
            DATA_ROOT / "system"
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        if not INDEX_FILE.exists():
            initial_structure = {
                "meta": {"version": "3.1", "created": datetime.datetime.now().isoformat()},
                "organizations": {},
                "sub_accounts": {},
                "sites": {},
                "users": {}
            }
            with open(INDEX_FILE, 'w', encoding='utf-8') as f:
                json.dump(initial_structure, f, indent=2)

    def load_index(self):
        try:
            if INDEX_FILE.exists():
                with open(INDEX_FILE, 'r', encoding='utf-8') as f:
                    self.index = json.load(f)
            else:
                 self.index = {"sites": {}, "organizations": {}}
        except Exception as e:
            logger.error(f"[CRITICAL] Echec lecture Index: {e}")
            self.index = {"sites": {}, "organizations": {}}

    def save_index(self):
        try:
            temp_file = INDEX_FILE.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.index, f, indent=2)
            os.replace(temp_file, INDEX_FILE)
        except Exception as e:
            logger.error(f"Save Index Error: {e}")

    # --- AUDIT TRAIL (VOTRE CODE : PRÉSERVÉ) ---
    def log_audit(self, user_id: str, action: str, target_id: str, details: dict):
        log_entry = {
            "ts": datetime.datetime.now().isoformat(),
            "u": user_id,
            "act": action,
            "tgt": target_id,
            "d": details
        }
        month_str = datetime.datetime.now().strftime("%Y_%m")
        log_file = DATA_ROOT / "system" / f"audit_{month_str}.jsonl"
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass 

    # --- API CONNECTORS & VAULT (VOTRE CODE : PRÉSERVÉ) ---
    def save_api_raw_data(self, site_id: str, connector_id: str, raw_payload: dict):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        landing_path = DATA_ROOT / "raw_uploads" / "API" / site_id / today
        landing_path.mkdir(parents=True, exist_ok=True)
        filename = f"{int(datetime.datetime.now().timestamp())}_{connector_id}.json"
        
        final_path = landing_path / filename
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(raw_payload, f)
        return str(final_path)

    # --- EXTENSION ERP (NOUVEAU : SETTINGS V21 & V22) ---
    
    def save_client_settings(self, client_id: str, data: dict):
        """
        Sauvegarde la configuration complète d'un client (Settings V21).
        Stocke les sites, contrats, et hiérarchie.
        """
        try:
            # Nettoyage ID pour éviter injection chemin
            clean_id = "".join(x for x in client_id if x.isalnum() or x in "_-")
            client_dir = DATA_ROOT / "clients" / clean_id
            client_dir.mkdir(parents=True, exist_ok=True)
            
            # Ajout métadonnées
            data["_meta"] = {
                "updated_at": datetime.datetime.now().isoformat(),
                "version": self.version
            }
            
            file_path = client_dir / "settings.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            # Mise à jour de l'index maître (Référence légère)
            self.index["organizations"][clean_id] = {
                "name": data.get("identity", {}).get("name", "Inconnu"),
                "type": data.get("identity", {}).get("type", "company"),
                "path": str(file_path)
            }
            self.save_index()
            
            return {"success": True, "path": str(file_path)}
        except Exception as e:
            logger.error(f"Client Save Error: {e}")
            return {"success": False, "error": str(e)}

    def load_client_settings(self, client_id: str):
        """Charge la config client"""
        try:
            clean_id = "".join(x for x in client_id if x.isalnum() or x in "_-")
            file_path = DATA_ROOT / "clients" / clean_id / "settings.json"
            
            if not file_path.exists():
                return {"success": False, "error": "Client introuvable"}
                
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_partner_config(self, partner_id: str, data: dict):
        """
        Sauvegarde la config Partenaire (Settings V22).
        Stocke le branding, les marges et les grilles.
        """
        try:
            clean_id = "".join(x for x in partner_id if x.isalnum() or x in "_-")
            partner_dir = DATA_ROOT / "partners" / clean_id
            partner_dir.mkdir(parents=True, exist_ok=True)
            
            file_path = partner_dir / "config.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

# Instance Singleton
storage = StorageEngine()
