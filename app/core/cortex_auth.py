import os
import firebase_admin
from firebase_admin import credentials, auth

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
                    # On force l'ID de ton projet pour que Cloud Run ne se perde pas
                    firebase_admin.initialize_app(options={'projectId': 'energistrat-saas'})
            except Exception as e:
                print(f"🔴 ERREUR CRITIQUE INITIALISATION FIREBASE : {e}")

    def verify_token(self, id_token: str):
        try:
            # Vérification cryptographique absolue via Firebase
            decoded_token = auth.verify_id_token(id_token)
            
            uid = decoded_token.get('uid')
            email = decoded_token.get('email', 'inconnu@energistrat.com')
            
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
            print(f"⚠️ Alerte Sécurité : Jeton Firebase invalide -> {e}")
            return None

auth_service = CortexAuth()
auth = auth_service
