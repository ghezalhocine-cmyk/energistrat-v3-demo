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
            return[doc.to_dict() for doc in docs]
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
    def get_all_users(self) -> list:
        if not self.db: return list()
        try:
            docs = self.db.collection("Users").stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"⚠️ Erreur get_all_users : {e}")
            return list()

    def get_user_profile(self, uid: str) -> dict:
        if not self.db: return dict()
        try:
            doc = self.db.collection("Users").document(uid).get()
            if doc.exists: return doc.to_dict()
            return dict()
        except Exception: return dict()

    def save_user_profile(self, uid: str, data: dict) -> bool:
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
    # NOUVEAU MOTEUR CRM V12 (RELATIONNEL)
    # ==========================================
    
    def _get_crm_docs(self, collection_name: str) -> list:
        """Méthode interne générique pour extraire une collection CRM"""
        if not self.db: return list()
        try:
            docs = self.db.collection(collection_name).stream()
            res =[]
            for doc in docs:
                d = doc.to_dict()
                d["id"] = doc.id
                res.append(d)
            return res
        except Exception as e:
            print(f"⚠️ Erreur CRM_FETCH ({collection_name}) : {e}")
            return list()

    def _save_crm_doc(self, collection_name: str, doc_id: str, data: dict) -> bool:
        """Méthode interne générique pour sauver un doc CRM"""
        if not self.db: return False
        try:
            self.db.collection(collection_name).document(doc_id).set(data, merge=True)
            return True
        except Exception as e:
            print(f"🔴 Erreur CRM_SAVE ({collection_name}/{doc_id}) : {e}")
            return False

    def _get_crm_doc(self, collection_name: str, doc_id: str) -> dict:
        """Méthode interne générique pour lire un doc CRM"""
        if not self.db: return dict()
        try:
            doc = self.db.collection(collection_name).document(doc_id).get()
            if doc.exists:
                d = doc.to_dict()
                d["id"] = doc.id
                return d
            return dict()
        except Exception: return dict()

    # --- LEADS (Vivier brut) ---
    def get_all_leads(self) -> list: return self._get_crm_docs("CRM_Leads")
    def get_lead(self, lead_id: str) -> dict: return self._get_crm_doc("CRM_Leads", lead_id)
    def save_lead(self, lead_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Leads", lead_id, data)
    def delete_lead(self, lead_id: str) -> bool:
        try: self.db.collection("CRM_Leads").document(lead_id).delete(); return True
        except: return False

    # --- COMPANIES (Comptes Clients/Groupes) ---
    def get_all_companies(self) -> list: return self._get_crm_docs("CRM_Companies")
    def get_company(self, comp_id: str) -> dict: return self._get_crm_doc("CRM_Companies", comp_id)
    def save_company(self, comp_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Companies", comp_id, data)

    # --- CONTACTS (Annuaire Humain) ---
    def get_all_contacts(self) -> list: return self._get_crm_docs("CRM_Contacts")
    def get_contact(self, contact_id: str) -> dict: return self._get_crm_doc("CRM_Contacts", contact_id)
    def save_contact(self, contact_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Contacts", contact_id, data)

    # --- DEALS (Opportunités / Kanban) ---
    def get_all_deals(self) -> list: return self._get_crm_docs("CRM_Deals")
    def get_deal(self, deal_id: str) -> dict: return self._get_crm_doc("CRM_Deals", deal_id)
    def save_deal(self, deal_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Deals", deal_id, data)

    # --- PRODUCTS (Catalogue CPQ) ---
    def get_all_products(self) -> list: return self._get_crm_docs("CRM_Products")
    def save_product(self, prod_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Products", prod_id, data)

    # --- ACTIVITIES (Timeline: Emails, Appels, Notes) ---
    def get_deal_activities(self, deal_id: str) -> list:
        if not self.db: return list()
        try:
            docs = self.db.collection("CRM_Activities").where("deal_id", "==", deal_id).stream()
            return sorted([{"id": d.id, **d.to_dict()} for d in docs], key=lambda x: x.get("timestamp", ""), reverse=True)
        except: return list()
    def save_activity(self, act_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Activities", act_id, data)

    # --- TASKS (Agenda) ---
    def get_user_tasks(self, owner_id: str) -> list:
        if not self.db: return list()
        try:
            docs = self.db.collection("CRM_Tasks").where("owner_id", "==", owner_id).stream()
            return sorted([{"id": d.id, **d.to_dict()} for d in docs], key=lambda x: x.get("due_date", ""))
        except: return list()
    def save_task(self, task_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Tasks", task_id, data)

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
