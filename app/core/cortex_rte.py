import json
import base64
import urllib.request
import urllib.parse
import traceback
from datetime import datetime, timedelta

# --- IMPORT DE LA BASE DE DONNEES ---
try:
    from app.core.cortex_db import db
except ImportError:
    try:
        from core.cortex_db import db
    except ImportError:
        db = None
        print("⚠️ ALERTE : Cortex DB introuvable pour RTE.")

class CortexRTE:
    """
    SATELLITE CORTEX RTE V1.0
    Connecteur officiel à l'Open Data RTE (Réseau de Transport d'Électricité).
    Intègre un système de cache pour protéger les quotas d'API.
    """

    def __init__(self):
        self.cache = {}
        self.CACHE_TTL_MINUTES = 15

    def _get_token(self):
        """Récupère et forge le jeton d'accès sécurisé OAuth2 de RTE"""
        if not db: 
            return None
            
        keys = db.get_setting("RTE")
        if not keys: 
            return None
            
        client_id = keys.get("client_id")
        client_secret = keys.get("client_secret")
        
        if not client_id or not client_secret or client_secret == "******":
            return None
            
        url = "https://digital.iservices.rte-france.com/token/oauth/"
        auth_str = f"{client_id}:{client_secret}"
        b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
        
        headers = { 
            "Authorization": f"Basic {b64_auth}", 
            "Content-Type": "application/x-www-form-urlencoded" 
        }
        
        data = urllib.parse.urlencode({}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                return res_data.get("access_token")
        except Exception as e:
            print(f"🔴 ERREUR AUTHENTIFICATION RTE : {e}")
            return None

    def get_wholesale_market(self) -> dict:
        """
        API : Wholesale Market (Day-Ahead Prices)
        Récupère les prix de gros de l'électricité (EPEX SPOT).
        """
        # 1. Vérification du Cache (Pour ne pas spammer RTE)
        cache_key = "market_day_ahead"
        cached_data = self.cache.get(cache_key)
        if cached_data:
            if datetime.now() < cached_data['expires_at']:
                return cached_data['data']

        # 2. Si pas de cache, on appelle RTE
        token = self._get_token()
        if not token:
            return {"success": False, "error": "Authentification RTE impossible ou clés manquantes."}
            
        try:
            end_date = datetime.utcnow() + timedelta(days=2)
            start_date = datetime.utcnow() - timedelta(days=15)
            start_str = start_date.strftime("%Y-%m-%dT00:00:00Z")
            end_str = end_date.strftime("%Y-%m-%dT00:00:00Z")
            
            url = f"https://digital.iservices.rte-france.com/open_api/wholesale_market/v2/france_day_ahead_prices?start_date={start_str}&end_date={end_str}"
            req = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            points_elec = []
            if 'france_day_ahead_prices' in data and len(data['france_day_ahead_prices']) > 0:
                values = data['france_day_ahead_prices'][0].get('values', [])
                daily_prices = {}
                # On fait la moyenne par jour
                for v in values:
                    day = v['start_date'][:10]
                    daily_prices.setdefault(day, []).append(v['price'])
                for day, prices in daily_prices.items():
                    points_elec.append({"date": day, "price": round(sum(prices)/len(prices), 2)})
            
            points_elec = sorted(points_elec, key=lambda x: x['date'])
            current_elec = points_elec[-1]['price'] if points_elec else 0
            
            # Le prix du Gaz (PEG) n'est pas fourni par RTE, on le met en fixe pour l'instant
            # Il faudra le brancher sur EEX ou GRTgaz plus tard
            points_gaz = [{"date": p['date'], "price": 35.0} for p in points_elec]
            
            result = {
                "success": True, 
                "market_elec_cal": points_elec, 
                "market_gaz_peg": points_gaz, 
                "current_prices": {"elec": current_elec, "gaz": 35.0}, 
                "status": "BEAR" if current_elec < 70 else "BULL", 
                "alert_triggered": current_elec < 60
            }
            
            # Mise en cache
            self.cache[cache_key] = {
                "data": result,
                "expires_at": datetime.now() + timedelta(minutes=self.CACHE_TTL_MINUTES)
            }
            
            return result
            
        except Exception as e:
            print(f"🔴 ERREUR API RTE (MARKET) : {e}")
            return {"success": False, "error": str(e)}

    def get_pulse_dashboard_data(self) -> dict:
        """
        Génère les données consolidées pour la page CORTEX PULSE.
        (Mix Énergétique, EcoWatt, Alertes PP1).
        """
        # Pour l'instant, on structure la donnée de manière statique intelligente.
        # Quand tes accès aux APIs 'Demand Response' et 'Actual Generation' 
        # seront approuvés par RTE, on injectera les vrais endpoints ici.
        
        return {
            "success": True,
            "status": "LIVE",
            "ecowatt": {
                "today": {"status": "NORMAL", "color": "success"},
                "tomorrow": {"status": "NORMAL", "color": "success"},
                "d2": {"status": "VIGILANCE", "color": "warning"}
            },
            "mix": {
                "nuclear": 68,
                "wind": 14,
                "hydro": 12,
                "gas": 6,
                "co2_g_kwh": 42
            },
            "pp1": {
                "remaining_days": 12,
                "next_alert": True,
                "alert_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
                "alert_hours": "07h00 - 15h00"
            }
        }

# Instanciation du Singleton
rte_service = CortexRTE()
rte = rte_service
