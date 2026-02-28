import json
import os
import datetime
import uuid
from pathlib import Path
import logging
import shutil

# CONFIGURATION DU CHEMIN (EVOLUTION V4.3 : CHEMIN ABSOLU ROBUSTE)
DATA_ROOT = Path(os.getcwd()) / "data"

# Initialisation Sécurisée du Root
try:
    if not DATA_ROOT.exists():
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
except Exception as e:
    print(f"[STORAGE] Attention : Fallback local suite erreur {e}")
    DATA_ROOT = Path("data")
    DATA_ROOT.mkdir(exist_ok=True)

INDEX_FILE = DATA_ROOT / "master_index.json"
VAULT_FILE = DATA_ROOT / "system" / "secure_vault.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("STORAGE_ENGINE_V4_5_PLATINUM")

class StorageEngine:
    """
    CORTEX STORAGE ENGINE
    Gestion centralisée des I/O, du RGPD et du Coffre-fort numérique.
    """
    def __init__(self):
        self.version = "4.5 (Finance Extension)"
        self.index = {}
        self._ensure_structure()
        self.load_index()

    def _ensure_structure(self):
        # RESTAURATION DE TOUS LES DOSSIERS HISTORIQUES (ANTI-REGRESSION)
        dirs = [
            DATA_ROOT / "raw_uploads", 
            DATA_ROOT / "raw_uploads" / "API",
            DATA_ROOT / "orgs", 
            DATA_ROOT / "clients", 
            DATA_ROOT / "partners",
            DATA_ROOT / "tickets", 
            DATA_ROOT / "archives" / "INBOX", 
            DATA_ROOT / "system",
            DATA_ROOT / "mandats", # Coffre RGPD
            DATA_ROOT / "invoices" # NOUVEAU : Coffre Factures (Finance)
        ]
        for d in dirs: 
            d.mkdir(parents=True, exist_ok=True)

        if not INDEX_FILE.exists():
            initial = {
                "meta": {"version": "4.5", "created": datetime.datetime.now().isoformat()}, 
                "organizations": {}, 
                "sites": {}
            }
            with open(INDEX_FILE, 'w', encoding='utf-8') as f: 
                json.dump(initial, f, indent=2)

    def load_index(self):
        try:
            if INDEX_FILE.exists():
                with open(INDEX_FILE, 'r', encoding='utf-8') as f: 
                    self.index = json.load(f)
            else: 
                self.index = {"sites": {}, "organizations": {}}
        except Exception: 
            self.index = {"sites": {}, "organizations": {}}

    def save_index(self):
        try:
            temp = INDEX_FILE.with_suffix('.tmp')
            with open(temp, 'w', encoding='utf-8') as f: 
                json.dump(self.index, f, indent=2)
            os.replace(temp, INDEX_FILE)
        except Exception: pass

    # --- RECONCILIATION ENGINE (SCAN PLAT) ---
    def find_site_by_pdl(self, pdl):
        """Recherche un site via son PDL dans tous les fichiers JSON."""
        if not pdl: return None
        # Recherche rapide dans l'index si disponible (Optimisation future)
        
        # Scan fichiers
        for client_file in DATA_ROOT.glob("*.json"):
            if "master_index" in client_file.name or "market_ref" in client_file.name: continue
            try:
                with open(client_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    contract = data.get("contract", {})
                    # Nettoyage pour comparaison
                    stored_pdl = str(contract.get("pdl", "")).replace(" ", "").strip()
                    target_pdl = str(pdl).replace(" ", "").strip()
                    
                    if target_pdl in stored_pdl:
                        identity = data.get("identity", {})
                        location = data.get("location", {})
                        return {
                            "id": data.get("identity", {}).get("id"),
                            "pdl": stored_pdl,
                            "client_name": identity.get("site_name") or identity.get("name", "Client Inconnu"),
                            "power": contract.get("power", 0),
                            "segment": contract.get("segment", "Inconnu"),
                            "address": location.get("address", ""),
                            "path": str(client_file),
                            "reconciled": True
                        }
            except Exception: continue
        return None

    # --- ERP CLIENTS (ECRITURE PLATE) ---
    def save_client_settings(self, client_id, data):
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            if not cid: cid = f"site_{uuid.uuid4().hex[:8]}"
            path = DATA_ROOT / f"{cid}.json"
            
            # Préservation des données RGPD existantes si non fournies
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                        if "rgpd" in existing and "rgpd" not in data:
                            data["rgpd"] = existing["rgpd"]
                        # Preservation des mesures si on ne fait qu'une update settings
                        if "measurements" in existing and "measurements" not in data:
                            data["measurements"] = existing["measurements"]
                except: pass

            data["_meta"] = {"updated_at": datetime.datetime.now().isoformat()}
            
            if "client_name" not in data:
                data["client_name"] = data.get("identity", {}).get("site_name") or data.get("identity", {}).get("name") or cid

            with open(path, 'w', encoding='utf-8') as f: 
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            self.index["sites"][cid] = {"name": data.get("client_name"), "path": str(path)}
            self.save_index()
            
            return {"success": True, "id": cid, "path": str(path)}
        except Exception as e: 
            logger.error(f"Save Error: {e}")
            return {"success": False, "error": str(e)}

    def get_client_settings(self, client_id):
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            path = DATA_ROOT / f"{cid}.json"
            if not path.exists(): return None
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: 
            logger.error(f"Load Error: {e}")
            return None

    # --- MODULE RGPD & MANDATS ---
    def save_mandate_file(self, client_id, file_content, filename):
        """Stocke le PDF signé dans un coffre sécurisé."""
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            vault_dir = DATA_ROOT / "mandats" / cid
            vault_dir.mkdir(parents=True, exist_ok=True)
            
            clean_name = f"MANDAT_{datetime.datetime.now().strftime('%Y%m%d')}_{filename}"
            file_path = vault_dir / clean_name
            
            with open(file_path, "wb") as f: f.write(file_content)
            return {"success": True, "path": str(file_path)}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- MODULE FINANCE (EXTENSION POUR FACTURES) ---
    def save_invoice_file(self, client_id, file_content, filename):
        """
        Stocke la facture PDF pour audit ultérieur.
        """
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            vault_dir = DATA_ROOT / "invoices" / cid
            vault_dir.mkdir(parents=True, exist_ok=True)
            
            # Nommage : FACTURE_2026-03-01_NomFichier.pdf
            clean_name = f"FACTURE_{datetime.datetime.now().strftime('%Y-%m-%d')}_{filename}"
            file_path = vault_dir / clean_name
            
            with open(file_path, "wb") as f: f.write(file_content)
            return {"success": True, "path": str(file_path)}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- ADMINISTRATION ---
    def delete_client(self, client_id):
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            path = DATA_ROOT / f"{cid}.json"
            if path.exists():
                os.remove(path)
                if cid in self.index["sites"]:
                    del self.index["sites"][cid]
                    self.save_index()
                # Nettoyage Mandats & Factures
                shutil.rmtree(DATA_ROOT / "mandats" / cid, ignore_errors=True)
                shutil.rmtree(DATA_ROOT / "invoices" / cid, ignore_errors=True)
                return {"success": True}
            return {"success": False, "error": "Not found"}
        except Exception as e: return {"success": False, "error": str(e)}

    # --- PARTNERS & TICKETING ---
    def save_partner_config(self, pid, data):
        try:
            clean = "".join(x for x in pid if x.isalnum() or x in "_-")
            path = DATA_ROOT / "partners" / clean
            path.mkdir(parents=True, exist_ok=True)
            with open(path / "config.json", 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
            return {"success": True}
        except Exception as e: return {"success": False, "error": str(e)}

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

storage = StorageEngine()
