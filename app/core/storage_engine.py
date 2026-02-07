import json
import os
import datetime
import uuid
from pathlib import Path
import logging

# CONFIGURATION DU CHEMIN
DATA_ROOT = Path("/app/data") if os.path.exists("/app/data") else Path("data")
INDEX_FILE = DATA_ROOT / "master_index.json"
VAULT_FILE = DATA_ROOT / "system" / "secure_vault.json"

# Logger pour le debug production
logger = logging.getLogger("STORAGE_ENGINE")

class StorageEngine:
    def __init__(self):
        self.version = "3.3 (Ticketing Real)"
        self.index = {}
        self._ensure_structure()
        self.load_index()

    def _ensure_structure(self):
        """Crée l'arborescence physique initiale."""
        dirs = [
            DATA_ROOT / "raw_uploads",
            DATA_ROOT / "raw_uploads" / "API",
            DATA_ROOT / "orgs",
            DATA_ROOT / "clients",   # ERP V21
            DATA_ROOT / "partners",  # ERP V22
            DATA_ROOT / "tickets",   # SUPPORT V21.3
            DATA_ROOT / "archives" / "INBOX",
            DATA_ROOT / "system"
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

        if not INDEX_FILE.exists():
            initial_structure = {
                "meta": {"version": "3.3", "created": datetime.datetime.now().isoformat()},
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

    # --- AUDIT TRAIL (LEGACY) ---
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

    # --- API CONNECTORS (LEGACY) ---
    def save_api_raw_data(self, site_id: str, connector_id: str, raw_payload: dict):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        landing_path = DATA_ROOT / "raw_uploads" / "API" / site_id / today
        landing_path.mkdir(parents=True, exist_ok=True)
        filename = f"{int(datetime.datetime.now().timestamp())}_{connector_id}.json"
        
        final_path = landing_path / filename
        with open(final_path, 'w', encoding='utf-8') as f:
            json.dump(raw_payload, f)
        return str(final_path)

    # --- EXTENSION ERP (SETTINGS V21) ---
    def save_client_settings(self, client_id: str, data: dict):
        try:
            clean_id = "".join(x for x in client_id if x.isalnum() or x in "_-")
            client_dir = DATA_ROOT / "clients" / clean_id
            client_dir.mkdir(parents=True, exist_ok=True)
            
            data["_meta"] = {"updated_at": datetime.datetime.now().isoformat()}
            
            file_path = client_dir / "settings.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            # Update Index
            self.index["organizations"][clean_id] = {
                "name": data.get("identity", {}).get("name", "Inconnu"),
                "path": str(file_path)
            }
            self.save_index()
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def load_client_settings(self, client_id: str):
        try:
            clean_id = "".join(x for x in client_id if x.isalnum() or x in "_-")
            file_path = DATA_ROOT / "clients" / clean_id / "settings.json"
            if not file_path.exists(): return {"success": False, "error": "Client introuvable"}
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: return {"success": False, "error": str(e)}

    # --- EXTENSION PARTNER (SETTINGS V22) ---
    def save_partner_config(self, partner_id: str, data: dict):
        try:
            clean_id = "".join(x for x in partner_id if x.isalnum() or x in "_-")
            partner_dir = DATA_ROOT / "partners" / clean_id
            partner_dir.mkdir(parents=True, exist_ok=True)
            
            with open(partner_dir / "config.json", 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- EXTENSION SUPPORT (TICKETING V21.3) ---
    def create_ticket(self, data):
        try:
            ticket_id = f"TK-{uuid.uuid4().hex[:6].upper()}"
            data.update({"id": ticket_id, "status": "OPEN", "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
            
            with open(DATA_ROOT / "tickets" / f"{ticket_id}.json", 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            return {"success": True, "ticket": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_tickets(self):
        try:
            tickets = []
            ticket_dir = DATA_ROOT / "tickets"
            if ticket_dir.exists():
                for f in ticket_dir.glob("*.json"):
                    with open(f, 'r', encoding='utf-8') as file: tickets.append(json.load(file))
            return sorted(tickets, key=lambda x: x['created_at'], reverse=True)
        except Exception: return []

# Instance Singleton
storage = StorageEngine()
