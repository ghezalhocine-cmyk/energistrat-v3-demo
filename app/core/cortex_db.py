import firebase_admin
from firebase_admin import firestore
import traceback

class CortexDB:
    """
    Moteur de Base de Données NoSQL Enterprise-Grade (Firestore).
    Gère le CRUD (Create, Read, Update, Delete) de la Data Unity ENERGISTRAT.
    """
    
    def __init__(self):
        try:
            # Récupère la connexion Firebase déjà authentifiée par cortex_auth
            self.db = firestore.client()
            print("🟢 CORTEX DB : Connexion Firestore établie avec succès.")
        except Exception as e:
            print(f"🔴 ERREUR CRITIQUE CORTEX DB (FIRESTORE) : {e}")
            self.db = None

    # ==========================================
    # GESTION DES SITES (DATA UNITY)
    # ==========================================
    def get_all_sites(self) -> list:
        """Récupère l'intégralité des sites (La Flotte)"""
        if not self.db: return[]
        try:
            docs = self.db.collection("Sites").stream()
            return[doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"⚠️ Erreur get_all_sites : {e}")
            return[]

    def get_site(self, site_id: str) -> dict:
        """Récupère un site spécifique par son ID"""
        if not self.db: return None
        try:
            doc_ref = self.db.collection("Sites").document(site_id)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
            return None
        except Exception as e:
            print(f"⚠️ Erreur get_site ({site_id}) : {e}")
            return None

    def save_site(self, site_id: str, data: dict) -> bool:
        """Sauvegarde ou met à jour un site (Merge)"""
        if not self.db: return False
        try:
            # L'option merge=True permet de ne mettre à jour que les champs modifiés
            # sans écraser le reste du document s'il existe déjà.
            self.db.collection("Sites").document(site_id).set(data, merge=True)
            return True
        except Exception as e:
            print(f"⚠️ Erreur save_site ({site_id}) : {e}")
            traceback.print_exc()
            return False

    def delete_site(self, site_id: str) -> bool:
        """Supprime un site de la Data Unity"""
        if not self.db: return False
        try:
            self.db.collection("Sites").document(site_id).delete()
            return True
        except Exception as e:
            print(f"⚠️ Erreur delete_site ({site_id}) : {e}")
            return False

    # ==========================================
    # GESTION DES PARAMÈTRES SYSTÈME (SETTINGS)
    # ==========================================
    def get_setting(self, doc_name: str) -> dict:
        """Récupère un paramètre système (M57, Carbon, RTE, Market)"""
        if not self.db: return {}
        try:
            doc = self.db.collection("Settings").document(doc_name).get()
            if doc.exists:
                return doc.to_dict()
            return {}
        except Exception as e:
            print(f"⚠️ Erreur get_setting ({doc_name}) : {e}")
            return {}

    def save_setting(self, doc_name: str, data: dict) -> bool:
        """Sauvegarde un paramètre système"""
        if not self.db: return False
        try:
            self.db.collection("Settings").document(doc_name).set(data, merge=True)
            return True
        except Exception as e:
            print(f"⚠️ Erreur save_setting ({doc_name}) : {e}")
            return False

    # ==========================================
    # GESTION DE CORTEX SENTINEL (ALERTES)
    # ==========================================
    def get_sentinel_alerts(self) -> dict:
        """Récupère les dernières alertes du daemon IA"""
        if not self.db: return {"last_scan": "Jamais", "alert_count": 0, "alerts":[]}
        try:
            doc = self.db.collection("System").document("Sentinel").get()
            if doc.exists:
                return doc.to_dict()
            return {"last_scan": "Jamais", "alert_count": 0, "alerts":[]}
        except Exception as e:
            print(f"⚠️ Erreur get_sentinel_alerts : {e}")
            return {"last_scan": "Jamais", "alert_count": 0, "alerts":
