import logging
import json
import os
import uuid
import pyotp  # Moteur MFA (Google Authenticator)
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from passlib.context import CryptContext
from jose import JWTError, jwt
from pathlib import Path

# --- CONFIGURATION SÉCURITÉ ---
# Dans une vraie prod, cette clé doit être dans une variable d'environnement
SECRET_KEY = os.getenv("CORTEX_SECRET_KEY", "H4RD_T0_GU3SS_SECRET_KEY_98765_SECURE_V3")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # Session de 1h (Renouvelable)

# Contexte de Hachage (Bcrypt est le standard robuste)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_AUTH_IAM")

# Chemin sécurisé de la base utilisateurs
# Séparé des données clients pour éviter les fuites accidentelles
AUTH_DB_PATH = Path(os.getcwd()) / "data" / "system" / "users_secure.json"

class CortexAuth:
    """
    CORTEX IAM ENGINE (Identity & Access Management)
    
    Responsabilités :
    1. Authentification (Login/Password Haché).
    2. Double Authentification (MFA via TOTP).
    3. Gestion des Sessions (JWT Tokens).
    4. Autorisation (RBAC Hiérarchique : SDE > Mairie > Site).
    """

    def __init__(self):
        self._ensure_db()

    def _ensure_db(self):
        """
        Initialise la base utilisateurs au premier démarrage.
        Crée le compte SUPER ADMIN par défaut (Bootstrap).
        """
        if not AUTH_DB_PATH.parent.exists():
            AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        if not AUTH_DB_PATH.exists():
            # Création du hash pour 'admin123' (Mot de passe temporaire)
            default_hash = pwd_context.hash("admin123")
            
            initial_db = {
                "meta": {"version": "3.0", "created": datetime.now().isoformat()},
                "users": {
                    "admin": {
                        "id": "u_admin_root",
                        "email": "admin@energistrat.com",
                        "hashed_password": default_hash,
                        "role": "ADMIN",
                        "scopes": ["*"], # "*" = Accès universel (God Mode)
                        "organization_id": "ENERGISTRAT_HQ",
                        "auth_provider": "local",
                        "mfa_enabled": False, # À activer d'urgence
                        "mfa_secret": None,
                        "active": True,
                        "created_at": datetime.now().isoformat()
                    }
                }
            }
            with open(AUTH_DB_PATH, "w") as f:
                json.dump(initial_db, f, indent=4)
            logger.warning("⚠️ SECURITY WARNING: Default Admin created. Change password immediately.")

    def _get_db(self):
        """Lecture sécurisée de la base JSON."""
        try:
            with open(AUTH_DB_PATH, "r") as f: return json.load(f)
        except Exception as e:
            logger.error(f"DB Read Error: {e}")
            return {"users": {}}

    def _save_db(self, db):
        """Écriture atomique (ou presque) de la base."""
        try:
            with open(AUTH_DB_PATH, "w") as f: json.dump(db, f, indent=4)
        except Exception as e:
            logger.error(f"DB Write Error: {e}")

    # =========================================================
    # 1. CORE AUTHENTICATION (LOGIN)
    # =========================================================

    def verify_password(self, plain_password, hashed_password):
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password):
        return pwd_context.hash(password)

    def authenticate_user(self, email, password, mfa_code=None):
        """
        Vérifie les identifiants et le code MFA si activé.
        Retourne : User Object, False, ou "MFA_REQUIRED".
        """
        db = self._get_db()
        user = None
        
        # Recherche par email (Scan)
        for u in db["users"].values():
            if u["email"].lower() == email.lower() and u.get("active", True):
                user = u
                break
        
        if not user: return False
        
        # Vérification Mot de Passe (si auth locale)
        if user.get("auth_provider") == "local":
            if not self.verify_password(password, user["hashed_password"]):
                return False

        # Vérification MFA (Double Facteur)
        if user.get("mfa_enabled", False):
            if not mfa_code:
                return "MFA_REQUIRED" # Signal au Front-End d'afficher le champ Code
            
            # Validation du code TOTP
            totp = pyotp.TOTP(user["mfa_secret"])
            if not totp.verify(mfa_code, valid_window=1): # Window=1 permet +/- 30sec de décalage
                return False

        return user

    # =========================================================
    # 2. GESTION DES TOKENS (JWT)
    # =========================================================

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Génère le badge d'accès crypté."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    def decode_token(self, token: str):
        """Vérifie la validité du badge."""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None

    # =========================================================
    # 3. GESTION MFA (ACTIVATION)
    # =========================================================

    def generate_mfa_secret(self):
        """Crée une clé secrète unique pour l'utilisateur."""
        return pyotp.random_base32()

    def enable_mfa(self, user_id, secret, validation_code):
        """Active la MFA après avoir vérifié que l'utilisateur a bien scanné le QR."""
        db = self._get_db()
        
        # Vérification du code test
        totp = pyotp.TOTP(secret)
        if not totp.verify(validation_code):
            return False
            
        # Si OK, on sauvegarde
        if user_id in db["users"]:
            db["users"][user_id]["mfa_secret"] = secret
            db["users"][user_id]["mfa_enabled"] = True
            self._save_db(db)
            return True
        return False

    # =========================================================
    # 4. RBAC & SCOPES (CLOISONNEMENT)
    # =========================================================

    def can_access_site(self, user: Dict, site_data: Dict) -> bool:
        """
        Vérifie si l'utilisateur a le droit de voir ce site spécifique.
        Logique "Poupées Russes" (SDE > Mairie > Site).
        """
        user_scopes = user.get("scopes", [])
        
        # 1. GOD MODE (Admin)
        if "*" in user_scopes: return True

        # Données du site
        site_org = site_data.get('identity', {}).get('organization_id', '') # Ex: SDE_38
        site_group = site_data.get('identity', {}).get('group_id', '')      # Ex: MAIRIE_LYON
        site_pdl = site_data.get('contract', {}).get('pdl', '')
        site_provider = site_data.get('contract', {}).get('provider', '').upper()

        for scope in user_scopes:
            # 2. NIVEAU ORGANISATION (SDE/OPH Siège)
            # Scope: "ORG:SDE_38" -> Accède à tout ce qui est SDE_38
            if scope.startswith("ORG:") and scope[4:] == site_org:
                return True
            
            # 3. NIVEAU GROUPE (Mairie/Agence)
            # Scope: "GROUP:MAIRIE_LYON" -> Accède à tout ce qui est MAIRIE_LYON
            if scope.startswith("GROUP:") and scope[4:] == site_group:
                return True
            
            # 4. NIVEAU SITE UNIQUE (Directeur d'école)
            # Scope: "19349..." -> Accède uniquement à ce PDL
            if scope == str(site_pdl):
                return True
            
            # 5. NIVEAU FOURNISSEUR (Partner)
            # Scope: "PROVIDER:EDF" -> Accède à tout site où provider == EDF
            if scope.startswith("PROVIDER:") and scope[9:].upper() in site_provider:
                return True

        return False

    # =========================================================
    # 5. ADMINISTRATION UTILISATEURS (CRUD)
    # =========================================================

    def create_user(self, email, password, role="CLIENT", scopes=[], org_id=None):
        """Création d'un nouvel utilisateur."""
        db = self._get_db()
        
        # Check doublon
        for u in db["users"].values():
            if u["email"] == email: return {"error": "Email déjà utilisé"}

        user_id = f"u_{uuid.uuid4().hex[:8]}"
        new_user = {
            "id": user_id,
            "email": email,
            "hashed_password": self.get_password_hash(password),
            "role": role,
            "scopes": scopes,
            "organization_id": org_id,
            "auth_provider": "local",
            "mfa_enabled": False,
            "mfa_secret": None,
            "active": True,
            "created_at": datetime.now().isoformat()
        }
        
        db["users"][user_id] = new_user
        self._save_db(db)
        return {"success": True, "user_id": user_id}

auth = CortexAuth()
