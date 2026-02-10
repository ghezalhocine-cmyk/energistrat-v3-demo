import json
import os
import datetime
import uuid
from pathlib import Path
import logging

# CONFIGURATION DU CHEMIN
# Force le chemin absolu pour Cloud Run
DATA_ROOT = Path("/app/data")
if not DATA_ROOT.exists():
    # Fallback local
    DATA_ROOT = Path("data")
    DATA_ROOT.mkdir(exist_ok=True)

INDEX_FILE = DATA_ROOT / "master_index.json"
VAULT_FILE = DATA_ROOT / "system" / "secure_vault.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("STORAGE_ENGINE_V4")

class StorageEngine:
    def __init__(self):
        self.version = "4.0 (Flat Storage for Fleet Dashboard)"
        self.index = {}
        self._ensure_structure()
        self.load_index()

    def _ensure_structure(self):
        # On garde les dossiers annexes, mais les clients iront à la racine
        dirs = [
            DATA_ROOT / "partners",
            DATA_ROOT / "tickets", 
            DATA_ROOT / "system"
        ]
        for d in dirs: d.mkdir(parents=True, exist_ok=True)

        if not INDEX_FILE.exists():
            initial = {"meta": {"version": "4.0", "created": datetime.datetime.now().isoformat()}, "organizations": {}, "sites": {}}
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

    # --- RECONCILIATION ENGINE (MISE A JOUR V4.0 - FLAT SCAN) ---
    def find_site_by_pdl(self, pdl):
        """
        Cherche un PDL dans la structure PLATE (/app/data/*.json).
        """
        if not pdl: return None
        
        # Scan de tous les JSON à la racine
        for client_file in DATA_ROOT.glob("*.json"):
            # Ignore les fichiers système
            if "master_index" in client_file.name or "market_ref" in client_file.name: continue
            
            try:
                with open(client_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Lecture structurée
                    contract = data.get("contract", {})
                    stored_pdl = str(contract.get("pdl", "")).strip()
                    
                    # Comparaison
                    if str(pdl) in stored_pdl:
                        identity = data.get("identity", {})
                        location = data.get("location", {})
                        
                        return {
                            "pdl": pdl,
                            "client_name": identity.get("site_name") or identity.get("name", "Client Inconnu"),
                            "power": contract.get("power", 0),
                            "segment": contract.get("segment", "Inconnu"),
                            "naf_label": identity.get("naf", "Métier Détecté"),
                            "address": location.get("address", ""),
                            "reconciled": True
                        }
            except Exception:
                continue
        
        return None

    # --- ERP CLIENTS (MISE A JOUR V4.0 - FLAT WRITE) ---
    def save_client_settings(self, client_id, data):
        """
        Sauvegarde le client à la RACINE pour être visible par le Dashboard Fleet.
        """
        try:
            # Nettoyage ID
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            if not cid: cid = f"site_{uuid.uuid4().hex[:8]}"

            # Chemin PLAT : /app/data/{id}.json
            path = DATA_ROOT / f"{cid}.json"
            
            data["_meta"] = {"updated_at": datetime.datetime.now().isoformat()}
            
            with open(path, 'w', encoding='utf-8') as f: 
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            # Mise à jour index (optionnel mais propre)
            self.index["sites"][cid] = {"name": data.get("identity", {}).get("site_name"), "path": str(path)}
            self.save_index()
            
            return {"success": True, "id": cid, "path": str(path)}
        except Exception as e: 
            logger.error(f"Save Error: {e}")
            return {"success": False, "error": str(e)}

    def get_client_settings(self, client_id):
        """
        Récupère un client depuis la racine.
        Renommé de 'load_client_settings' pour compatibilité main.py V40.
        """
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            path = DATA_ROOT / f"{cid}.json"
            
            if not path.exists(): 
                # Tentative de fallback (Ancienne structure dossier)
                old_path = DATA_ROOT / "clients" / cid / "settings.json"
                if old_path.exists():
                    with open(old_path, 'r', encoding='utf-8') as f: return json.load(f)
                return None
            
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: 
            logger.error(f"Load Error: {e}")
            return None

    # --- PARTNERS (INCHANGÉ) ---
    def save_partner_config(self, pid, data):
        try:
            clean = "".join(x for x in pid if x.isalnum() or x in "_-")
            path = DATA_ROOT / "partners" / clean
            path.mkdir(parents=True, exist_ok=True)
            with open(path / "config.json", 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- TICKETING (INCHANGÉ) ---
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
