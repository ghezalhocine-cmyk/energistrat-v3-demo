import os
import firebase_admin
from firebase_admin import credentials
from firebase_admin import auth as firebase_auth  # FIX : Création de l'Alias pour éviter le crash

class CortexAuth:
    """Moteur d'Authentification Enterprise-Grade via Google Firebase"""
    
    def __init__(self):
        if not firebase_admin._apps:
            key_path = os.path.join(os.getcwd(), "serviceAccountKey.json")
            try:
                if os.path.exists(key_path):
                    print("🟢 CORTEX AUTH : Clé locale détectée.")
                    cred = credentials.Certificate(key_path)
                    firebase_admin.initialize_app(cred)
                else:
                    print("🟡 CORTEX AUTH : Mode Cloud Run (ADC).")
                    # Initialisation avec l'ID Projet pour que la vérification des tokens fonctionne
                    firebase_admin.initialize_app(options={'projectId': 'energistrat-saas'})
            except Exception as e:
                print(f"🔴 ERREUR CRITIQUE INITIALISATION FIREBASE : {e}")

    def verify_token(self, id_token: str):
        try:
            # Vérification cryptographique absolue via le module Firebase authentique
            decoded_token = firebase_auth.verify_id_token(id_token)
            
            uid = decoded_token.get('uid')
            email = decoded_token.get('email', 'inconnu@energistrat.com')
            
            # Attribution des rôles
            role = "USER"
            if "admin" in email.lower() or "ghezal" in email.lower() or "cortex" in email.lower():
                role = "ADMIN"
                
            return {
                "uid": uid,
                "email": email,
                "role": role,
                "sub": email
            }
        except Exception as e:
            print(f"⚠️ Alerte Sécurité : Jeton Firebase invalide ou erreur interne -> {e}")
            return None

# Export du service pour que main.py l'utilise
auth_service = CortexAuth()
auth = auth_service
