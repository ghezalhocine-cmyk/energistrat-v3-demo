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
            return [doc.to_dict() for doc in docs]
        except Exception as e:
            print(f"⚠️ Erreur get_all_sites : {e}")
            return
