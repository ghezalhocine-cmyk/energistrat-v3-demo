import json
import base64
import urllib.request
import urllib.parse
import urllib.error
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

class CortexRTE:
    """
    SATELLITE CORTEX RTE V13.2 (Haute Résilience)
    Connecteur officiel à l'Open Data RTE.
    Tolérant aux pannes, fix Heure d'Été (UTC) et publication Spot.
    """

    def __init__(self):
        self.cache = {}
        self.CACHE_TTL_MINUTES = 15

    def _get_token(self):
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
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"
        }
        data = urllib.parse.urlencode({}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                return res_data.get("access_token")
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode('utf-8')
            print(f"🔴 ERREUR AUTH RTE (HTTP {e.code}) : {err_msg}")
            return None
        except Exception as e:
            print(f"🔴 ERREUR RÉSEAU RTE : {e}")
            return None

    def _fetch_rte_api(self, token: str, endpoint: str):
        """Helper générique pour appeler une API RTE avec le token"""
        base_url = "https://digital.iservices.rte-france.com/open_api"
        req = urllib.request.Request(f"{base_url}{endpoint}", headers={'Authorization': f'Bearer {token}'})
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            print(f"⚠️ API RTE REJETÉE [{endpoint}] (HTTP {e.code}) : Vérifiez vos souscriptions sur le portail RTE.")
            return None
        except Exception as e:
            print(f"🔴 ERREUR FETCH RTE [{endpoint}] : {e}")
            return None

    # ========================================================
    # 1. API : WHOLESALE MARKET (DAY-AHEAD)
    # ========================================================
    def get_wholesale_market(self) -> dict:
        cache_key = "market_day_ahead"
        if self.cache.get(cache_key) and datetime.now() < self.cache[cache_key]['expires_at']:
            return self.cache[cache_key]['data']

        token = self._get_token()
        fallback_data = {"success": True, "market_elec_cal": [], "market_gaz_peg":[], "current_prices": {"elec": 85.00, "gaz": 35.00}, "status": "BEAR", "alert_triggered": False, "is_fallback": True}
        
        if not token: 
            return fallback_data
            
        try:
            # FIX V13.2 : Utilisation stricte de l'UTC (Z) pour le fuseau horaire 
            # et de la règle des 11h UTC (13h Paris) pour éviter l'Erreur 400 (Day-Ahead non publié).
            now = datetime.utcnow()
            
            if now.hour >= 11:
                end_date = now + timedelta(days=1) # Après 11h UTC, on peut demander la cotation de demain
            else:
                end_date = now # Avant 11h UTC, le Day-Ahead de demain n'est pas encore fixé par l'EPEX
                
            start_date = now - timedelta(days=15)
            
            # Formatage strict ISO 8601 en UTC (Z) -> C'est ce qui corrige le bug d'Heure d'Été
            start_str = start_date.strftime("%Y-%m-%dT00:00:00Z")
            end_str = end_date.strftime("%Y-%m-%dT00:00:00Z")
            
            data = self._fetch_rte_api(token, f"/wholesale_market/v2/france_day_ahead_prices?start_date={urllib.parse.quote(start_str)}&end_date={urllib.parse.quote(end_str)}")
            
            if not data: 
                return fallback_data

            points_elec =[]
            if 'france_day_ahead_prices' in data and len(data['france_day_ahead_prices']) > 0:
                values = data['france_day_ahead_prices'][0].get('values',[])
                daily_prices = {}
                for v in values:
                    day = v['start_date'][:10]
                    daily_prices.setdefault(day,[]).append(v['price'])
                for day, prices in daily_prices.items():
                    points_elec.append({"date": day, "price": round(sum(prices)/len(prices), 2)})
            
            points_elec = sorted(points_elec, key=lambda x: x['date'])
            current_elec = points_elec[-1]['price'] if points_elec else fallback_data['current_prices']['elec']
            points_gaz = [{"date": p['date'], "price": 35.0} for p in points_elec]
            
            result = {
                "success": True, 
                "market_elec_cal": points_elec, 
                "market_gaz_peg": points_gaz, 
                "current_prices": {"elec": current_elec, "gaz": 35.0}, 
                "status": "BEAR" if current_elec < 70 else "BULL", 
                "alert_triggered": current_elec < 60, 
                "is_fallback": False
            }
            self.cache[cache_key] = {"data": result, "expires_at": datetime.now() + timedelta(minutes=self.CACHE_TTL_MINUTES)}
            return result
        except Exception as e: 
            print(f"Exception complète Wholesale: {e}")
            return fallback_data

    # ========================================================
    # 2. LE MOTEUR COMPLET PULSE (ECOWATT, PP1, MIX)
    # ========================================================
    def get_pulse_dashboard_data(self) -> dict:
        """Génère le dashboard complet en interrogeant les 3 APIs."""
        cache_key = "pulse_dashboard"
        if self.cache.get(cache_key) and datetime.now() < self.cache[cache_key]['expires_at']:
            return self.cache[cache_key]['data']

        token = self._get_token()
        
        fallback_data = {
            "success": True, "status": "LIVE", "is_fallback": True,
            "ecowatt": { "today": {"status": "NORMAL", "color": "success"}, "tomorrow": {"status": "NORMAL", "color": "success"}, "d2": {"status": "VIGILANCE", "color": "warning"} },
            "mix": { "nuclear": 68, "wind": 14, "hydro": 12, "gas": 6, "co2_g_kwh": 42 },
            "pp1": { "remaining_days": 12, "next_alert": True, "alert_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"), "alert_hours": "07h00 - 15h00" }
        }
        if not token: 
            return fallback_data

        try:
            # A. API ECOWATT V5 (Format spécifique)
            eco_data = {"today": {"status": "NORMAL"}, "tomorrow": {"status": "NORMAL"}, "d2": {"status": "NORMAL"}}
            eco_response = self._fetch_rte_api(token, "/ecowatt/v5/signals")
            if eco_response and 'signals' in eco_response:
                for sig in eco_response['signals']:
                    s_val = "NORMAL" if sig['dvalue'] == 1 else ("VIGILANCE" if sig['dvalue'] == 2 else "ALERTE")
                    if "Aujourd'hui" in sig.get('message', ''): eco_data['today']['status'] = s_val
                    elif "Demain" in sig.get('message', ''): eco_data['tomorrow']['status'] = s_val

            # B. API ACTUAL GENERATION (Mix)
            mix_data = {"nuclear": 0, "wind": 0, "hydro": 0, "gas": 0, "co2_g_kwh": 0}
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(hours=2)
            # Generation veut du Z strict
            s_str = start_date.strftime("%Y-%m-%dT%H:00:00Z")
            e_str = end_date.strftime("%Y-%m-%dT%H:00:00Z")
            
            gen_response = self._fetch_rte_api(token, f"/actual_generation/v1/actual_generations_per_production_type?start_date={urllib.parse.quote(s_str)}&end_date={urllib.parse.quote(e_str)}")
            if gen_response and 'actual_generations_per_production_type' in gen_response:
                total_mw = 0
                for gen in gen_response['actual_generations_per_production_type']:
                    type_prod = gen.get('production_type', '')
                    if gen.get('values') and len(gen['values']) > 0:
                        val_mw = gen['values'][-1].get('value', 0)
                        if val_mw > 0:
                            total_mw += val_mw
                            if type_prod == 'NUCLEAR': mix_data['nuclear'] = val_mw
                            elif type_prod == 'WIND': mix_data['wind'] = val_mw
                            elif type_prod == 'HYDRO': mix_data['hydro'] = val_mw
                            elif type_prod in['FOSSIL_GAS', 'FOSSIL_HARD_COAL']: mix_data['gas'] += val_mw
                
                if total_mw > 0:
                    mix_data['nuclear'] = int((mix_data['nuclear'] / total_mw) * 100)
                    mix_data['wind'] = int((mix_data['wind'] / total_mw) * 100)
                    mix_data['hydro'] = int((mix_data['hydro'] / total_mw) * 100)
                    mix_data['gas'] = int((mix_data['gas'] / total_mw) * 100)
                    mix_data['co2_g_kwh'] = 35 + (mix_data['gas'] * 4) 

            # C. API DEMAND RESPONSE (PP1)
            pp1_data = { "remaining_days": 15, "next_alert": False, "alert_date": "", "alert_hours": "" }
            pp1_response = self._fetch_rte_api(token, "/demand_response_signal/v2/signals")
            if pp1_response and 'signals' in pp1_response:
                for sig in pp1_response['signals']:
                    if sig.get('type') == 'PP1':
                        pp1_data['next_alert'] = True
                        pp1_data['alert_date'] = sig.get('start_date', '')[:10]
                        pp1_data['alert_hours'] = "07h00 - 15h00"
                        break

            # Si le mix est à 0 (RTE n'a pas répondu à cette API précise), on utilise le fallback
            if mix_data['nuclear'] == 0:
                return fallback_data

            result = {
                "success": True, "status": "LIVE", "is_fallback": False,
                "ecowatt": eco_data,
                "mix": mix_data,
                "pp1": pp1_data
            }
            self.cache[cache_key] = {"data": result, "expires_at": datetime.now() + timedelta(minutes=self.CACHE_TTL_MINUTES)}
            return result

        except Exception as e:
            print(f"🔴 ERREUR PULSE ENGINE : {e}. Passage en Fallback.")
            return fallback_data

rte_service = CortexRTE()
rte = rte_service
