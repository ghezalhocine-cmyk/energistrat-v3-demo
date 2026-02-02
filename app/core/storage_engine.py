import json
import os
import datetime
from pathlib import Path

# CONFIGURATION DU CHEMIN
# Sur Cloud Run, ce chemin sera monté. En local, il se crée dans le projet.
DATA_ROOT = Path("/app/data") if os.path.exists("/app/data") else Path("data")
INDEX_FILE = DATA_ROOT / "master_index.json"
VAULT_FILE = DATA_ROOT / "system" / "secure_vault.json"

class StorageEngine:
    def __init__(self):
        self.index = {}
        self._ensure_structure()
        self.load_index()

    def _ensure_structure(self):
        """Crée l'arborescence physique initiale."""
        dirs = [
            DATA_ROOT / "raw_uploads",
            DATA_ROOT / "raw_uploads" / "API",
            DATA_ROOT / "orgs",
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
            print(f"[CRITICAL] Echec lecture Index: {e}")
            self.index = {"sites": {}, "organizations": {}}

    def save_index(self):
        temp_file = INDEX_FILE.with_suffix('.tmp')
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, indent=2)
        os.replace(temp_file, INDEX_FILE)

    # --- AUDIT TRAIL ---
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

    # --- API CONNECTORS & VAULT ---
    def save_api_raw_data(self, site_id: str, connector_id: str, raw_payload: dict):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        landing_path = DATA_ROOT / "raw_uploads" / "API" / site_id / today
        landing_path.mkdir(parents=True, exist_ok=True)
        filename = f"{int(datetime.datetime.now().timestamp())}_{connector_id}.json"
        
        # Conversion string pour path safe
        final_path = landing_path / filename
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(raw_payload, f)
        return str(final_path)

# Instance Singleton
storage = StorageEngine()
