import os
import firebase_admin
from firebase_admin import credentials
from firebase_admin import auth as firebase_auth

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
                    firebase_admin.initialize_app(options={'projectId': 'energistrat-saas'})
            except Exception as e:
                print(f"🔴 ERREUR CRITIQUE INITIALISATION FIREBASE : {e}")

    def verify_token(self, id_token: str):
        try:
            # Vérification cryptographique absolue via le module Firebase
            decoded_token = firebase_auth.verify_id_token(id_token)
            
            uid = decoded_token.get('uid')
            email = str(decoded_token.get('email', 'inconnu@energistrat.com')).lower()
            
            # FIX V9 : Blindage du statut Admin pour débloquer Ops Nexus
            role = "USER"
            if "admin" in email or "ghezal" in email or "cortex" in email:
                role = "ADMIN"
                
            return {
                "uid": uid,
                "email": email,
                "role": role,
                "sub": email
            }
        except Exception as e:
            print(f"⚠️ Alerte Sécurité : Jeton Firebase invalide -> {e}")
            return None

auth_service = CortexAuth()
auth = auth_service
