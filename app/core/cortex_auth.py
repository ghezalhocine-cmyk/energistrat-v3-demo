import os
import firebase_admin
from firebase_admin import credentials, auth

class CortexAuth:
    """Moteur d'Authentification Enterprise-Grade via Google Firebase"""
    
    def __init__(self):
        # Évite l'erreur de double-initialisation sur les redémarrages de Cloud Run
        if not firebase_admin._apps:
            # Recherche de la clé maître locale (Mode Développement ou Cloud Run non-natif)
            key_path = os.path.join(os.getcwd(), "serviceAccountKey.json")
            
            try:
                if os.path.exists(key_path):
                    print("🟢 CORTEX AUTH : Clé de service détectée. Initialisation sécurisée.")
                    cred = credentials.Certificate(key_path)
                    firebase_admin.initialize_app(cred)
                else:
                    print("🟡 CORTEX AUTH : Clé locale introuvable. Tentative IAM Default (GCP).")
                    # Si déployé sur Cloud Run nativement, Google gère les identifiants tout seul
                    firebase_admin.initialize_app()
            except Exception as e:
                print(f"🔴 ERREUR CRITIQUE INITIALISATION FIREBASE : {e}")

    def verify_token(self, id_token: str):
        """
        Vérifie cryptographiquement le jeton Firebase envoyé par le client (login.html).
        S'assure que le jeton n'est pas expiré, qu'il est signé par Google, et qu'il appartient à ce projet.
        """
        try:
            # Vérification absolue via les serveurs de Google
            decoded_token = auth.verify_id_token(id_token)
            
            uid = decoded_token.get('uid')
            email = decoded_token.get('email', 'inconnu@energistrat.com')
            
            # Attribution des rôles (Role-Based Access Control)
            role = "USER"
            if "admin" in email.lower() or "ghezal" in email.lower() or "cortex" in email.lower():
                role = "ADMIN"
                
            return {
                "uid": uid,
                "email": email,
                "role": role,
                "sub": email,
                "firebase_data": decoded_token
            }
        except Exception as e:
            print(f"⚠️ Alerte Sécurité : Jeton Firebase invalide ou expiré -> {e}")
            return None

# Instanciation du Singleton de sécurité
auth_service = CortexAuth()
auth = auth_service
