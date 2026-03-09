import firebase_admin
from firebase_admin import firestore
import traceback

class CortexDB:
    """Moteur de Base de Données NoSQL Enterprise-Grade (Firestore)."""
    
    def __init__(self):
        try:
            self.db = firestore.Client(project="energistrat-saas")
            print("🟢 CORTEX DB : Connexion Firestore FORCÉE sur energistrat-saas.")
        except Exception as e:
            print(f"🔴 ERREUR CRITIQUE CORTEX DB (FIRESTORE) : {e}")
            self.db = None

    # ==========================================
    # GESTION DES SITES (DATA UNITY)
    # ==========================================
    def get_all_sites(self) -> list:
        if not self.db: return list()
        try:
            docs = self.db.collection("Sites").stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"⚠️ Erreur get_all_sites : {e}")
            return list()

    def get_site(self, site_id: str) -> dict:
        if not self.db: return None
        try:
            doc = self.db.collection("Sites").document(str(site_id)).get()
            if doc.exists: return doc.to_dict()
            return None
        except Exception as e:
            print(f"⚠️ Erreur get_site ({site_id}) : {e}")
            return None

    def save_site(self, site_id: str, data: dict) -> bool:
        if not self.db: return False
        try:
            self.db.collection("Sites").document(str(site_id)).set(data, merge=True)
            return True
        except Exception as e:
            print(f"🔴 ERREUR D'ÉCRITURE FIRESTORE ({site_id}) : {e}")
            return False

    def delete_site(self, site_id: str) -> bool:
        if not self.db: return False
        try:
            self.db.collection("Sites").document(str(site_id)).delete()
            return True
        except Exception: return False

    # ==========================================
    # GESTION DES PROFILS UTILISATEURS (MULTI-TENANT)
    # ==========================================
    def get_user_profile(self, uid: str) -> dict:
        """Récupère les informations d'un utilisateur (ex: son Tenant ID / SIRET)"""
        if not self.db: return dict()
        try:
            doc = self.db.collection("Users").document(uid).get()
            if doc.exists: return doc.to_dict()
            return dict()
        except Exception: return dict()

    def save_user_profile(self, uid: str, data: dict) -> bool:
        """Sauvegarde les informations d'un utilisateur"""
        if not self.db: return False
        try:
            self.db.collection("Users").document(uid).set(data, merge=True)
            return True
        except Exception: return False

    # ==========================================
    # GESTION DES PARAMÈTRES SYSTÈME (SETTINGS)
    # ==========================================
    def get_setting(self, doc_name: str) -> dict:
        if not self.db: return dict()
        try:
            doc = self.db.collection("Settings").document(doc_name).get()
            if doc.exists: return doc.to_dict()
            return dict()
        except Exception: return dict()

    def save_setting(self, doc_name: str, data: dict) -> bool:
        if not self.db: return False
        try:
            self.db.collection("Settings").document(doc_name).set(data, merge=True)
            return True
        except Exception: return False

    # ==========================================
    # GESTION DE CORTEX SENTINEL (ALERTES)
    # ==========================================
    def get_sentinel_alerts(self) -> dict:
        default_resp = {"last_scan": "Jamais", "alert_count": 0, "alerts": list()}
        if not self.db: return default_resp
        try:
            doc = self.db.collection("System").document("Sentinel").get()
            if doc.exists: return doc.to_dict()
            return default_resp
        except Exception: return default_resp

    def save_sentinel_alerts(self, data: dict) -> bool:
        if not self.db: return False
        try:
            self.db.collection("System").document("Sentinel").set(data)
            return True
        except Exception: return False

db_service = CortexDB()
db = db_service
