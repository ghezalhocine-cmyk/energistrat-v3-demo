import os
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

# CONFIGURATION DU LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_SGE_API_CONNECTOR")

class CortexSGE:
    """
    CORTEX SGE V1.0 (DATA CONNECT ENEDIS & GRDF ADIC)
    Moteur de synchronisation asynchrone "Zero-Click" pour l'ingestion des compteurs Linky/Gazpar.
    """

    def __init__(self):
        # Ces clés seront fournies par le portail API Enedis après signature du contrat.
        # Elles doivent être injectées via les variables d'environnement Cloud Run.
        self.enedis_client_id = os.getenv("ENEDIS_CLIENT_ID", "")
        self.enedis_client_secret = os.getenv("ENEDIS_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("ENEDIS_REDIRECT_URI", "https://energistrat.com/api/sge/callback")
        
        # URLs Officielles Enedis (Production)
        self.ENEDIS_AUTH_URL = "https://mon-compte-particulier.enedis.fr/dataconnect/v1/oauth2/authorize"
        self.ENEDIS_TOKEN_URL = "https://gw.prd.api.enedis.fr/v1/oauth2/token"
        self.ENEDIS_API_BASE = "https://gw.prd.api.enedis.fr/v4/metering_data"

    # =========================================================
    # 1. TUNNEL OAUTH2 (LE CONSENTEMENT CLIENT)
    # =========================================================
    def get_enedis_consent_url(self, pdl: str, state_context: str) -> str:
        """
        Génère l'URL officielle vers laquelle rediriger le client pour qu'il donne son mandat.
        Le 'state_context' permet de sécuriser la transaction et d'identifier l'utilisateur au retour.
        """
        if not self.enedis_client_id:
            return "/settings?error=api_keys_missing"

        params = {
            "client_id": self.enedis_client_id,
            "response_type": "code",
            "state": state_context,
            "duration": "P36M", # Mandat légal de 36 mois (3 ans)
            "scope": "meter_reading_load_curve", # Droit d'accéder à la courbe au pas de 10 min
            "redirect_uri": self.redirect_uri
        }
        
        # Si on connait déjà le PDL du client, on l'injecte pour lui faciliter la vie
        if pdl and len(pdl) == 14:
            params["usage_point_id"] = pdl

        url = f"{self.ENEDIS_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return url

    def exchange_code_for_token(self, auth_code: str) -> dict:
        """
        Échange le code d'autorisation (reçu après le consentement) contre un Access Token 
        et un Refresh Token (Crucial pour l'automatisation nocturne).
        """
        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "client_id": self.enedis_client_id,
            "client_secret": self.enedis_client_secret,
            "code": auth_code,
            "redirect_uri": self.redirect_uri
        }).encode('utf-8')

        req = urllib.request.Request(self.ENEDIS_TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    "success": True,
                    "access_token": result.get("access_token"),
                    "refresh_token": result.get("refresh_token"),
                    "expires_in": result.get("expires_in")
                }
        except Exception as e:
            logger.error(f"Échec de l'échange de jeton Enedis : {e}")
            return {"success": False, "error": str(e)}

    # =========================================================
    # 2. LE MOISSONNEUR (RÉCUPÉRATION DES DONNÉES)
    # =========================================================
    def fetch_load_curve(self, pdl: str, access_token: str, start_date: str, end_date: str) -> dict:
        """
        Attaque l'API Enedis pour télécharger la courbe de charge (La Data Unity pure).
        start_date et end_date au format YYYY-MM-DD
        """
        endpoint = f"{self.ENEDIS_API_BASE}/consumption_load_curve"
        params = {
            "usage_point_id": pdl,
            "start": start_date,
            "end": end_date
        }
        
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req) as response:
                payload = json.loads(response.read().decode('utf-8'))
                
                # Conversion du payload Enedis vers notre format interne CORTEX
                cortex_measurements = []
                for reading in payload.get('meter_reading', {}).get('interval_reading', []):
                    cortex_measurements.append({
                        "date": reading.get('date'),
                        "val": float(reading.get('value', 0))
                    })
                
                return {"success": True, "measurements": cortex_measurements}
                
        except urllib.error.HTTPError as e:
            error_data = e.read().decode('utf-8')
            logger.error(f"Erreur API Enedis (HTTP {e.code}) sur le PDL {pdl}: {error_data}")
            return {"success": False, "error": f"HTTP {e.code}", "details": error_data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================
    # 3. L'AUTOMATISATION NOCTURNE (ZERO-CLICK)
    # =========================================================
    def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Utilisé par le Cloud Scheduler de Google à 03h00 du matin.
        Prend le vieux jeton de la base de données, demande un nouveau jeton frais à Enedis
        sans aucune action du client, pour relancer le téléchargement quotidien.
        """
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": self.enedis_client_id,
            "client_secret": self.enedis_client_secret,
            "refresh_token": refresh_token
        }).encode('utf-8')

        req = urllib.request.Request(self.ENEDIS_TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return {
                    "success": True,
                    "access_token": result.get("access_token"),
                    "refresh_token": result.get("refresh_token") # Parfois le refresh token change aussi
                }
        except Exception as e:
            logger.error(f"Échec du refresh token : {e}")
            return {"success": False, "error": str(e)}

# Initialisation du Singleton
sge_engine = CortexSGE()
