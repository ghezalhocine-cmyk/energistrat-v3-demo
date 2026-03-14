import firebase_admin
from firebase_admin import credentials, firestore
import traceback

class CortexDB:
    """
    CORTEX DB V12.6 - Moteur de Base de Données NoSQL Enterprise-Grade.
    Gère la Data Unity, le CRM 3D, le LMS Academy, le CPQ et le Trading Floor.
    """
    
    def __init__(self):
        try:
            if not firebase_admin._apps:
                firebase_admin.initialize_app()
            self.db = firestore.client()
            print("🟢 CORTEX DB : Connexion firebase_admin.firestore RÉUSSIE (V12.6).")
        except Exception as e:
            print(f"🔴 ERREUR CRITIQUE CORTEX DB (FIRESTORE) : {e}")
            self.db = None

    # ==========================================
    # GESTION DES SITES (DATA UNITY & JUMEAUX SGE)
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

    def get_company_sites(self, company_id: str) -> list:
        """Requête Haute Performance : Récupère uniquement les sites d'une Entité Légale"""
        if not self.db: return list()
        try:
            docs = self.db.collection("Sites").where("identity.tenant_id", "==", company_id).stream()
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"⚠️ Erreur get_company_sites : {e}")
            return list()

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
    # GESTION DES PROFILS UTILISATEURS
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
    # MOTEUR CRM V12.6 (3D, PIPELINES & CONTACTS)
    # ==========================================
    def _get_crm_docs(self, collection_name: str) -> list:
        if not self.db: return list()
        try:
            docs = self.db.collection(collection_name).stream()
            res = []
            for doc in docs:
                d = doc.to_dict()
                d["id"] = doc.id
                res.append(d)
            return res
        except Exception as e:
            print(f"⚠️ Erreur CRM_FETCH ({collection_name}) : {e}")
            return list()

    def _save_crm_doc(self, collection_name: str, doc_id: str, data: dict) -> bool:
        if not self.db: return False
        try:
            self.db.collection(collection_name).document(doc_id).set(data, merge=True)
            return True
        except Exception as e:
            print(f"🔴 Erreur CRM_SAVE ({collection_name}/{doc_id}) : {e}")
            return False

    def _get_crm_doc(self, collection_name: str, doc_id: str) -> dict:
        if not self.db: return dict()
        try:
            doc = self.db.collection(collection_name).document(doc_id).get()
            if doc.exists:
                d = doc.to_dict()
                d["id"] = doc.id
                return d
            return dict()
        except Exception: return dict()

    # --- LEADS (Legacy) ---
    def get_all_leads(self) -> list: 
        if not self.db: return list()
        try:
            docs = self.db.collection("Settings").stream()
            leads =[]
            for doc in docs:
                if str(doc.id).startswith("LEAD_"):
                    data = doc.to_dict()
                    data["id"] = str(doc.id)
                    leads.append(data)
            return leads
        except Exception: return list()

    def get_lead(self, lead_id: str) -> dict: return self._get_crm_doc("CRM_Leads", lead_id)
    def save_lead(self, lead_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Leads", lead_id, data)
    def delete_lead(self, lead_id: str) -> bool:
        try: self.db.collection("CRM_Leads").document(lead_id).delete(); return True
        except: return False

    # --- COMPANIES (Tête de Groupe & Entité Légale) ---
    def get_all_companies(self) -> list: return self._get_crm_docs("CRM_Companies")
    def get_company(self, comp_id: str) -> dict: return self._get_crm_doc("CRM_Companies", comp_id)
    def save_company(self, comp_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Companies", comp_id, data)

    # --- CONTACTS ---
    def get_all_contacts(self) -> list: return self._get_crm_docs("CRM_Contacts")
    def get_contact(self, contact_id: str) -> dict: return self._get_crm_doc("CRM_Contacts", contact_id)
    def save_contact(self, contact_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Contacts", contact_id, data)
    
    def get_company_contacts(self, company_id: str) -> list:
        """Requête Haute Performance : Récupère les contacts d'un compte précis"""
        if not self.db: return list()
        try:
            docs = self.db.collection("CRM_Contacts").where("company_id", "==", company_id).stream()
            return [{"id": d.id, **d.to_dict()} for d in docs]
        except Exception: return list()

    # --- DEALS (Pipelines) ---
    def get_all_deals(self) -> list: return self._get_crm_docs("CRM_Deals")
    def get_deal(self, deal_id: str) -> dict: return self._get_crm_doc("CRM_Deals", deal_id)
    def save_deal(self, deal_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Deals", deal_id, data)

    # --- PRODUCTS (Catalogue V1) ---
    def get_all_products(self) -> list: return self._get_crm_docs("CRM_Products")
    def save_product(self, prod_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Products", prod_id, data)
    def delete_product(self, prod_id: str) -> bool:
        if not self.db: return False
        try: self.db.collection("CRM_Products").document(prod_id).delete(); return True
        except: return False

    # --- ACTIVITIES (Historique & Notes) ---
    def get_deal_activities(self, deal_id: str) -> list:
        if not self.db: return list()
        try:
            docs = self.db.collection("CRM_Activities").where("deal_id", "==", deal_id).stream()
            return sorted([{"id": d.id, **d.to_dict()} for d in docs], key=lambda x: x.get("timestamp", ""), reverse=True)
        except: return list()
    def save_activity(self, act_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Activities", act_id, data)

    # --- TASKS ---
    def get_user_tasks(self, owner_id: str) -> list:
        if not self.db: return list()
        try:
            docs = self.db.collection("CRM_Tasks").where("owner_id", "==", owner_id).stream()
            return sorted([{"id": d.id, **d.to_dict()} for d in docs], key=lambda x: x.get("due_date", ""))
        except: return list()
    def save_task(self, task_id: str, data: dict) -> bool: return self._save_crm_doc("CRM_Tasks", task_id, data)

    # ==========================================
    # CORTEX SENTINEL (ALERTES SGE)
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

    # ==========================================
    # MODULE LMS ACADEMY (CORTEX V12.4)
    # ==========================================
    def get_all_lms_modules(self) -> list:
        return self._get_crm_docs("LMS_Modules")

    def save_lms_module(self, mod_id: str, data: dict) -> bool:
        return self._save_crm_doc("LMS_Modules", mod_id, data)

    def get_all_lms_questions(self) -> list:
        return self._get_crm_docs("LMS_Questions")

    def save_lms_question(self, q_id: str, data: dict) -> bool:
        return self._save_crm_doc("LMS_Questions", q_id, data)

    def get_user_lms_progress(self, uid: str) -> dict:
        default_progress = {
            "uid": uid, "xp": 0, "level": 1, "badges": [],
            "completed_modules":[], "srs_queue": {}
        }
        if not self.db: return default_progress
        try:
            doc = self.db.collection("LMS_Progress").document(uid).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
            return default_progress
        except Exception: return default_progress

    def save_user_lms_progress(self, uid: str, data: dict) -> bool:
        return self._save_crm_doc("LMS_Progress", uid, data)

    # ==========================================
    # DEAL DESK CPQ & TRADING FLOOR (V12.6)
    # ==========================================
    def get_cpq_basket(self, deal_id: str) -> dict:
        """Récupère le panier de cotation multi-énergies (Sites C5, C4, Gaz)"""
        return self._get_crm_doc("CPQ_Baskets", deal_id)

    def save_cpq_basket(self, deal_id: str, data: dict) -> bool:
        """Sauvegarde l'état du panier du commercial"""
        return self._save_crm_doc("CPQ_Baskets", deal_id, data)

    def get_active_trading_tickets(self) -> list:
        """Récupère les demandes de cotations (Carnet d'ordres) pour le Middle-Office"""
        if not self.db: return list()
        try:
            # On exclut les tickets déjà couverts (HEDGED) ou expirés (EXPIRED) pour la vue active
            docs = self.db.collection("Trading_Tickets").where("status", "in",["REQUESTED", "PRICED", "HEDGE_PENDING"]).stream()
            return sorted([{"id": d.id, **d.to_dict()} for d in docs], key=lambda x: x.get("created_at", ""), reverse=True)
        except Exception: return list()

    def save_trading_ticket(self, ticket_id: str, data: dict) -> bool:
        """Crée ou met à jour un ticket de communication Vente <-> Achat"""
        return self._save_crm_doc("Trading_Tickets", ticket_id, data)

    def update_trading_ticket_status(self, ticket_id: str, new_status: str) -> bool:
        """Mise à jour rapide du statut (ex: passage à HEDGED)"""
        if not self.db: return False
        try:
            self.db.collection("Trading_Tickets").document(ticket_id).update({
                "status": new_status,
                "updated_at": datetime.now().isoformat()
            })
            return True
        except Exception: return False

db_service = CortexDB()
db = db_service
