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

logger = logging.getLogger("STORAGE_ENGINE")

class StorageEngine:
    def __init__(self):
        self.version = "3.5 (Precision Extraction)"
        self.index = {}
        self._ensure_structure()
        self.load_index()

    def _ensure_structure(self):
        dirs = [
            DATA_ROOT / "raw_uploads", DATA_ROOT / "raw_uploads" / "API",
            DATA_ROOT / "orgs", DATA_ROOT / "clients", DATA_ROOT / "partners",
            DATA_ROOT / "tickets", DATA_ROOT / "archives" / "INBOX", DATA_ROOT / "system"
        ]
        for d in dirs: d.mkdir(parents=True, exist_ok=True)

        if not INDEX_FILE.exists():
            initial = {"meta": {"version": "3.5", "created": datetime.datetime.now().isoformat()}, "organizations": {}, "sites": {}}
            with open(INDEX_FILE, 'w', encoding='utf-8') as f: json.dump(initial, f, indent=2)

    def load_index(self):
        try:
            if INDEX_FILE.exists():
                with open(INDEX_FILE, 'r', encoding='utf-8') as f: self.index = json.load(f)
            else: self.index = {"sites": {}, "organizations": {}}
        except Exception: self.index = {"sites": {}, "organizations": {}}

    def save_index(self):
        try:
            temp = INDEX_FILE.with_suffix('.tmp')
            with open(temp, 'w', encoding='utf-8') as f: json.dump(self.index, f, indent=2)
            os.replace(temp, INDEX_FILE)
        except Exception: pass

    # --- RECONCILIATION ENGINE (PRECISION V3.5) ---
    def find_site_by_pdl(self, pdl):
        """
        Cherche un PDL et extrait les métadonnées précises (NAF, Nom, Puissance).
        """
        if not pdl: return None
        
        clients_dir = DATA_ROOT / "clients"
        if not clients_dir.exists(): return None

        # Scan des dossiers clients
        for client_file in clients_dir.glob("*/settings.json"):
            try:
                with open(client_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Lecture structurée (Settings V21.9 Structure)
                    contract = data.get("contract", {})
                    stored_pdl = str(contract.get("pdl", "")).strip()
                    
                    # Comparaison robuste
                    if str(pdl) in stored_pdl:
                        identity = data.get("identity", {})
                        
                        # Extraction des champs réels
                        return {
                            "pdl": pdl,
                            "client_name": identity.get("name", "Client Inconnu"),
                            "power": contract.get("power", 0),
                            "segment": contract.get("segment", "Inconnu"),
                            # On renvoie le NAF capturé par l'API Gouv
                            "naf_label": identity.get("naf", "Métier Détecté") 
                        }
            except Exception as e:
                continue
        
        return None

    # --- ERP CLIENTS ---
    def save_client_settings(self, client_id, data):
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            path = DATA_ROOT / "clients" / cid
            path.mkdir(parents=True, exist_ok=True)
            data["_meta"] = {"updated_at": datetime.datetime.now().isoformat()}
            with open(path / "settings.json", 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
            self.index["organizations"][cid] = {"name": data.get("identity", {}).get("name"), "path": str(path)}
            self.save_index()
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    def load_client_settings(self, client_id):
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            path = DATA_ROOT / "clients" / cid / "settings.json"
            if not path.exists(): return {"success": False, "error": "Inconnu"}
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: return {"success": False, "error": str(e)}

    # --- PARTNERS ---
    def save_partner_config(self, pid, data):
        try:
            clean = "".join(x for x in pid if x.isalnum() or x in "_-")
            path = DATA_ROOT / "partners" / clean
            path.mkdir(parents=True, exist_ok=True)
            with open(path / "config.json", 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- TICKETING ---
    def create_ticket(self, data):
        try:
            tid = f"TK-{uuid.uuid4().hex[:6].upper()}"
            data.update({"id": tid, "status": "OPEN", "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
            with open(DATA_ROOT / "tickets" / f"{tid}.json", 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
            return {"success": True, "ticket": data}
        except Exception as e: return {"success": False, "error": str(e)}

    def list_tickets(self):
        try:
            tks = []
            tdir = DATA_ROOT / "tickets"
            if tdir.exists():
                for f in tdir.glob("*.json"):
                    with open(f, 'r', encoding='utf-8') as file: tks.append(json.load(file))
            return sorted(tks, key=lambda x: x['created_at'], reverse=True)
        except: return []

    # --- LEGACY ---
    def log_audit(self, u, a, t, d): pass
    def save_api_raw_data(self, s, c, p): return "mock"

storage = StorageEngine()
