import json
import os
import datetime
import uuid
from pathlib import Path
import logging
import shutil

# --- IMPORT CLOUD STORAGE (NOUVEAU) ---
import firebase_admin
from firebase_admin import storage

# CONFIGURATION DU CHEMIN (CACHE TEMPORAIRE POUR CLOUD RUN)
DATA_ROOT = Path(os.getcwd()) / "data"

# Initialisation Sécurisée du Root Local (Fallback)
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
logger = logging.getLogger("STORAGE_ENGINE_V10_CLOUD_NATIVE")

class StorageEngine:
    """
    CORTEX STORAGE ENGINE V10 (FIREBASE CLOUD STORAGE)
    Gestion centralisée des I/O, du RGPD et du Coffre-fort numérique.
    """
    def __init__(self):
        self.version = "10.0 (Firebase Cloud Storage Edition)"
        self.index = {}
        self._ensure_structure()
        self.load_index()
        
        # INITIALISATION DU BUCKET FIREBASE STORAGE
        self.bucket = None
        try:
            # Sécurité anti-crash si initiale déjà faite par cortex_auth
            if not firebase_admin._apps:
                firebase_admin.initialize_app(options={'projectId': 'energistrat-saas'})
            
            # Connexion au bucket officiel Firebase
            self.bucket = storage.bucket("energistrat-saas.appspot.com")
            logger.info("🟢 CORTEX STORAGE : Connecté au bucket energistrat-saas.appspot.com")
        except Exception as e:
            logger.error(f"🔴 CORTEX STORAGE : Impossible de se connecter à Firebase Storage. Fallback local activé. Erreur: {e}")

    def _ensure_structure(self):
        # RESTAURATION DE TOUS LES DOSSIERS HISTORIQUES (ANTI-REGRESSION / CACHE CLOUD RUN)
        dirs = [
            DATA_ROOT / "raw_uploads", 
            DATA_ROOT / "raw_uploads" / "API",
            DATA_ROOT / "orgs", 
            DATA_ROOT / "clients", 
            DATA_ROOT / "partners",
            DATA_ROOT / "tickets", 
            DATA_ROOT / "archives" / "INBOX", 
            DATA_ROOT / "system",
            DATA_ROOT / "mandats", # Cache Coffre RGPD
            DATA_ROOT / "invoices" # Cache Coffre Factures (Finance)
        ]
        for d in dirs: 
            d.mkdir(parents=True, exist_ok=True)

        if not INDEX_FILE.exists():
            initial = {
                "meta": {"version": self.version, "created": datetime.datetime.now().isoformat()}, 
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

    # ==========================================
    # MODULE RGPD & MANDATS (CLOUD STORAGE)
    # ==========================================
    def save_mandate_file(self, client_id, file_content, filename):
        """Stocke le PDF signé dans le Cloud Google (Chiffré) avec un fallback local."""
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            clean_name = f"MANDAT_{datetime.datetime.now().strftime('%Y%m%d')}_{filename}"
            
            cloud_url = None
            if self.bucket:
                blob_path = f"mandats/{cid}/{clean_name}"
                blob = self.bucket.blob(blob_path)
                c_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"
                blob.upload_from_string(file_content, content_type=c_type)
                
                # Génération URL Signée (Validité 7 Jours pour consultation Client/Admin)
                cloud_url = blob.generate_signed_url(version="v4", expiration=datetime.timedelta(days=7), method="GET")
                logger.info(f"[GCS] Mandat RGPD sécurisé dans le cloud : {blob_path}")

            # Cache local Cloud Run (Pour accès immédiat par d'autres fonctions Python)
            vault_dir = DATA_ROOT / "mandats" / cid
            vault_dir.mkdir(parents=True, exist_ok=True)
            file_path = vault_dir / clean_name
            with open(file_path, "wb") as f: f.write(file_content)
            
            return {
                "success": True, 
                "path": str(file_path),
                "cloud_url": cloud_url,
                "message": "Cloud Storage OK" if cloud_url else "Local Cache Only"
            }
        except Exception as e: 
            return {"success": False, "error": str(e)}

    # ==========================================
    # MODULE FINANCE / FACTURES (CLOUD STORAGE)
    # ==========================================
    def save_invoice_file(self, client_id, file_content, filename):
        """Stocke la facture PDF pour audit OCR ultérieur dans le Cloud Google."""
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            clean_name = f"FACTURE_{datetime.datetime.now().strftime('%Y-%m-%d')}_{filename}"
            
            cloud_url = None
            if self.bucket:
                blob_path = f"invoices/{cid}/{clean_name}"
                blob = self.bucket.blob(blob_path)
                c_type = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"
                blob.upload_from_string(file_content, content_type=c_type)
                
                # Génération URL Signée (Validité 7 Jours pour affichage dans le Dashboard)
                cloud_url = blob.generate_signed_url(version="v4", expiration=datetime.timedelta(days=7), method="GET")
                logger.info(f"[GCS] Facture sécurisée dans le cloud : {blob_path}")

            # Cache local Cloud Run (Essentiel pour le Parser OCR qui a besoin du fichier physique)
            vault_dir = DATA_ROOT / "invoices" / cid
            vault_dir.mkdir(parents=True, exist_ok=True)
            file_path = vault_dir / clean_name
            with open(file_path, "wb") as f: f.write(file_content)
            
            return {
                "success": True, 
                "path": str(file_path),
                "cloud_url": cloud_url,
                "message": "Cloud Storage OK" if cloud_url else "Local Cache Only"
            }
        except Exception as e: 
            return {"success": False, "error": str(e)}

    # ==========================================
    # --- RECONCILIATION ENGINE (SCAN PLAT LEGACY) ---
    # ==========================================
    def find_site_by_pdl(self, pdl):
        """Recherche un site via son PDL dans les fichiers JSON locaux (Legacy)."""
        if not pdl: return None
        for client_file in DATA_ROOT.glob("*.json"):
            if "master_index" in client_file.name or "market_ref" in client_file.name: continue
            try:
                with open(client_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    contract = data.get("contract", {})
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

    # ==========================================
    # --- ERP CLIENTS LEGACY (ANTI-REGRESSION) ---
    # ==========================================
    def save_client_settings(self, client_id, data):
        """⚠️ Legacy: Les nouveaux enregistrements doivent passer par cortex_db.py (Firestore)"""
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            if not cid: cid = f"site_{uuid.uuid4().hex[:8]}"
            path = DATA_ROOT / f"{cid}.json"
            
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                        if "rgpd" in existing and "rgpd" not in data: data["rgpd"] = existing["rgpd"]
                        if "measurements" in existing and "measurements" not in data: data["measurements"] = existing["measurements"]
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

    def delete_client(self, client_id):
        try:
            cid = "".join(x for x in client_id if x.isalnum() or x in "_-")
            path = DATA_ROOT / f"{cid}.json"
            
            # Suppression GCS si existant
            if self.bucket:
                try:
                    blobs = self.bucket.list_blobs(prefix=f"invoices/{cid}/")
                    for blob in blobs: blob.delete()
                    blobs_m = self.bucket.list_blobs(prefix=f"mandats/{cid}/")
                    for blob in blobs_m: blob.delete()
                except Exception as e:
                    logger.warning(f"Impossible de supprimer les fichiers Cloud de {cid}: {e}")

            if path.exists():
                os.remove(path)
                if cid in self.index["sites"]:
                    del self.index["sites"][cid]
                    self.save_index()
                shutil.rmtree(DATA_ROOT / "mandats" / cid, ignore_errors=True)
                shutil.rmtree(DATA_ROOT / "invoices" / cid, ignore_errors=True)
                return {"success": True}
            return {"success": False, "error": "Not found"}
        except Exception as e: return {"success": False, "error": str(e)}

    # ==========================================
    # --- PARTNERS & TICKETING LEGACY ---
    # ==========================================
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
