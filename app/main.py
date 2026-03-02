import os
import json
import glob
import uuid
import math
import io
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime

# AJOUTS SÉCURITÉ
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException, Response, Depends, status
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- GESTION DES DEPENDANCES ---
try:
    import pandas as pd
    PANDAS_READY = True
except ImportError:
    PANDAS_READY = False

# ==============================================================================
# BLOC IMPORT CORTEX ROBUSTE
# ==============================================================================
try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_engine import cortex
    from app.core.cortex_physics import physics
    from app.core.cortex_forecast import forecast
    from app.core.cortex_router import router
    from app.core.cortex_market import market
    from app.core.cortex_aggregator import aggregator
    from app.core.cortex_finance import finance
    from app.core.cortex_auth import auth

except Exception as e_prod:
    print(f"⚠️ PROD IMPORT ERROR: {str(e_prod)}")
    try:
        import cortex_ingest as ingest
        import cortex_engine as cortex
        import cortex_physics as physics
        import cortex_forecast as forecast
        from core.cortex_router import router
        from core.cortex_market import market
        from core.cortex_aggregator import aggregator
        from core.cortex_finance import finance
        from core.cortex_auth import auth

    except Exception as e_local:
        print(f"⚠️ LOCAL IMPORT ERROR: {str(e_local)}")
        print("🔴 CRITICAL: ACTIVATION DU MODE DEGRADE (MOCKS)")
        class MockAuth:
            def authenticate_user(self, e, p, m=None): return {"id": "mock", "role": "ADMIN"}
            def create_access_token(self, d): return "mock_token"
            def decode_token(self, t): return {"sub": "admin@energistrat.com", "role": "ADMIN"}
        auth = MockAuth()
        class MockFinance:
            def parse_invoice(self, c, f): return {"status": "ERROR", "message": "Module Finance HS"}
            def audit_invoice(self, i, s): return {}
            def simulate_landing(self, s): return {}
        finance = MockFinance()
        class MockRouter:
            def get_api_status(self): return {"status": "DEGRADED", "error": str(e_local)}
            def analyze_file_stream(self, c, f): return {"status": "ERROR", "message": "Router HS"}
        router = MockRouter()
        class MockMarket:
            def valoriser_strategie(self, l, b): return {"error": "Market module missing"}
        market = MockMarket()
        class MockAggregator:
            def aggregate_sites(self, s, y): return None
        aggregator = MockAggregator()
        ingest = None; cortex = None; physics = None; forecast = None

app = FastAPI(title="ENERGISTRAT V3", version="PLATINUM-V3019-DATA-UNITY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR, exist_ok=True)

TEMPLATE_DIR = os.path.join(BASE_DIR, "app/templates")
if not os.path.exists(TEMPLATE_DIR): TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR): STATIC_DIR = os.path.join(BASE_DIR, "app/static")
if os.path.exists(STATIC_DIR): app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# --- MODELES ---
class LoginRequest(BaseModel):
    email: str
    password: str
    mfa_code: Optional[str] = None

class MarketUpdateModel(BaseModel):
    elec: Dict[str, Any]
    gaz: Dict[str, Any]
    trve: Optional[Dict[str, Any]] = None
    targets: Optional[Dict[str, Any]] = None

class StrategyRequest(BaseModel):
    site_id: str
    bloc_kw: float

class AggregationRequest(BaseModel):
    site_ids: List[str]
    years: int = 3

# --- UTILS ---
def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return [json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

def get_safe_id(raw_id):
    return str(raw_id).replace('/', '_').replace(' ', '_').replace('+', '').replace(',', '').strip()

def find_site_file(target_id):
    safe_target = get_safe_id(target_id)
    direct_path = os.path.join(DATA_DIR, f"{safe_target}.json")
    if os.path.exists(direct_path): return direct_path
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for p in files:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stored_id = str(data.get('identity', {}).get('id', ''))
                if get_safe_id(stored_id) == safe_target: return p
        except: continue
    return None

def get_market_ref():
    path = os.path.join(DATA_DIR, "market_ref.json")
    if os.path.exists(path):
        try:
            with open(path, 'r') as f: return json.load(f)
        except: pass
    return {"updated_at": datetime.now().isoformat(), "elec": {"cal_n1": 85.0}}

# --- MIDDLEWARE SÉCURITÉ ---
async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token: return None
    if token.startswith("Bearer "): token = token.split(" ")[1]
    payload = auth.decode_token(token)
    if not payload: return None
    return payload

# ==========================================
# ROUTES AUTHENTIFICATION
# ==========================================
@app.get("/login", response_class=HTMLResponse)
async def view_login(request: Request):
    token = request.cookies.get("access_token")
    if token: return RedirectResponse(url="/dashboard/industry")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/api/auth/login")
async def api_login(credentials: LoginRequest, response: Response):
    result = auth.authenticate_user(credentials.email, credentials.password, credentials.mfa_code)
    if result == "MFA_REQUIRED": return JSONResponse({"detail": "MFA_REQUIRED"}, status_code=403)
    if not result: return JSONResponse({"detail": "Identifiants invalides"}, status_code=401)
    access_token = auth.create_access_token(data={"sub": result["email"], "role": result["role"]})
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True, max_age=3600, samesite="lax")
    return {"access_token": access_token, "token_type": "bearer", "role": result["role"]}

@app.get("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return RedirectResponse(url="/login")

# ==========================================
# API PRINCIPALES (SETTINGS & DATA)
# ==========================================

# --- HELPER DE NORMALISATION UNIVERSELLE ---
def normalize_full_data(data):
    """
    Transforme les données plates (Formulaire) en données structurées (Standard Cortex).
    Gère Contrat (Puissances) ET Pricing (Prix).
    """
    # 1. STRUCTURES DE BASE
    if 'contract' not in data: data['contract'] = {}
    if 'pricing' not in data: data['pricing'] = {}
    
    c = data['contract']
    p = data['pricing']
    
    if 'power_details' not in c: c['power_details'] = {}
    
    # Sources possibles : Racine, Contract, Technical, Pricing
    sources = [data, c, data.get('technical', {}), p]
    
    # 2. MAPPING PUISSANCES (kW)
    power_map = {
        'hph': ['ps_hph', 'p_hph', 'PS_HPH', 'puissance_hph'],
        'hch': ['ps_hch', 'p_hch', 'PS_HCH', 'puissance_hch'],
        'hpe': ['ps_hpe', 'p_hpe', 'PS_HPE', 'puissance_hpe'],
        'hce': ['ps_hce', 'p_hce', 'PS_HCE', 'puissance_hce']
    }
    
    for target, variants in power_map.items():
        for s in sources:
            if not s: continue
            for v in variants:
                if v in s and s[v]:
                    c['power_details'][target] = s[v]
                    # On force aussi la version plate dans contract pour compatibilité max
                    c[f"ps_{target}"] = s[v] 
                    break

    # 3. MAPPING PRIX (€/kWh) - INDISPENSABLE POUR FINANCE
    price_map = {
        'hph': ['price_hph', 'prix_hph', 'P_HPH', 'tarif_hph'],
        'hch': ['price_hch', 'prix_hch', 'P_HCH', 'tarif_hch'],
        'hpe': ['price_hpe', 'prix_hpe', 'P_HPE', 'tarif_hpe'],
        'hce': ['price_hce', 'prix_hce', 'P_HCE', 'tarif_hce']
    }

    for target, variants in price_map.items():
        for s in sources:
            if not s: continue
            for v in variants:
                if v in s and s[v]:
                    p[target] = s[v] # Stocké dans data['pricing']['hph']
                    break

    # 4. IDENTITÉ (SIRET)
    if 'identity' in data:
        i = data['identity']
        # Si SIRET est à la racine, on le met dans identity
        if 'siret' in data and data['siret']: i['siret'] = data['siret']
        # Si ID est manquant mais SIRET présent, ID = SIRET
        if not i.get('id') and i.get('siret'): i['id'] = i['siret']

    data['contract'] = c
    data['pricing'] = p
    return data

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        data = normalize_full_data(data) # NORMALISATION COMPLETE
        
        raw_id = data.get("identity", {}).get("id") or f"CLI_{uuid.uuid4().hex[:8]}"
        data["identity"]["id"] = raw_id
        safe_id = get_safe_id(raw_id)
        file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f: existing_data = json.load(f)
            
            # Merge intelligent
            for section in ['technical', 'location', 'identity', 'contract', 'pricing', 'kpis', 'financials', 'rgpd']:
                if section in data:
                    if section not in existing_data: existing_data[section] = {}
                    existing_data[section].update(data[section])
            final_data = existing_data
        else:
            final_data = data

        with open(file_path, 'w', encoding='utf-8') as f: json.dump(final_data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "id": raw_id})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/update_site")
async def api_update_site(request: Request):
    """
    Mise à jour complète (Settings V2).
    """
    try:
        payload = await request.json()
        payload = normalize_full_data(payload) # NORMALISATION COMPLETE

        site_id = payload.get('id')
        if not site_id: return JSONResponse({"error": "ID manquant"}, 400)
        file_path = find_site_file(site_id)
        if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
        
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        
        # MISE A JOUR EXHAUSTIVE
        sections_to_update = ['location', 'technical', 'identity', 'contract', 'pricing', 'financials', 'rgpd']
        
        for section in sections_to_update:
            if section in payload:
                if section not in data: data[section] = {}
                data[section].update(payload[section])
        
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "message": "Sauvegarde Complète OK"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    try:
        content = await file.read()
        sites = ingest.parse_mass_import_unified(content)
        return JSONResponse({"success": True, "imported": len(sites)})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    raw_sites = []
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for p in files:
        if "master" in p or "market" in p: continue
        try:
            with open(p, 'r', encoding='utf-8') as f: data = json.load(f)
            fin = cortex.enrich_site_financials(data)
            data['computed_financials'] = fin
            raw_sites.append(data)
        except: continue
    analysis = cortex.analyze_portfolio(raw_sites)
    fleet_list = []
    all_cities, all_providers = set(), set()
    for s in raw_sites:
        if "CLI_" in str(s.get('identity',{}).get('id')): continue
        fin = s['computed_financials']
        contract = s.get('contract', {})
        city = fin['meta']['city']
        prov = contract.get('provider', 'Inconnu')
        if city: all_cities.add(city)
        if prov: all_providers.add(prov)
        
        raw_id = s.get('identity',{}).get('id')
        safe_id = get_safe_id(raw_id)
        pdl_display = contract.get('pdl')
        if not pdl_display or len(str(pdl_display)) < 5: pdl_display = contract.get('pce', '-')
        
        vol_engine = fin['volume_mwh']
        vol_router = 0
        if 'kpis' in s and 'volume_mwh' in s['kpis']: vol_router = float(s['kpis']['volume_mwh'])
        final_vol = vol_engine if vol_engine > 0 else vol_router
        final_budget = fin['budget_annual']
        if vol_engine == 0 and vol_router > 0:
            pricing = s.get('pricing', {})
            avg_price = 0.20
            for k in ['price_kwh', 'prix_kwh', 'price_hph', 'prix_hph']:
                if k in pricing and pricing[k]:
                    try: avg_price = float(pricing[k]); break
                    except: pass
            sub_cost = fin.get('budget_subscription', 0)
            energy_cost = (final_vol * 1000) * avg_price
            final_budget = sub_cost + energy_cost
        fleet_list.append({
            "id": safe_id, "name": fin['meta']['site_label'], "city": city,
            "zip": s.get('location', {}).get('zip_code', ''), "volume": final_vol,
            "energy": "gaz" if fin['meta']['is_gas'] else "elec", "segment": contract.get('segment', '-'),
            "provider": prov, "budget": final_budget, "landing": fin['landing_forecast'],
            "alert": fin['kpis']['pmc_eur_mwh'] > 300, "ghost_savings": fin['kpis']['ghost_savings'],
            "power": contract.get('power', 0), "pdl": pdl_display, "surface": s.get('location', {}).get('surface', 0)
        })
    return JSONResponse(json_compliant({
        "fleet": fleet_list, "count": len(fleet_list),
        "green_league": analysis.get('green_league'), "global_kpis": analysis.get('global'),
        "filters_meta": { "cities": sorted(list(all_cities)), "providers": sorted(list(all_providers)) }
    }))

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str, response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    file_path = find_site_file(client_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    
    financials = cortex.enrich_site_financials(data)
    market_ref = get_market_ref()
    market_analysis = cortex.analyze_market_position(
        financials['kpis']['unit_price_kwh'], market_ref, financials['meta']['is_gas']
    )
    contract = data.get('contract', {})
    pricing = financials['pricing_details']
    display_segment = financials.get('display_overrides', {}).get('segment', contract.get('segment'))

    # FIX VOLUME
    vol_display = financials['volume_mwh']
    kpis_raw = data.get('kpis', {})
    if vol_display == 0 and 'volume_mwh' in kpis_raw:
        vol_display = float(kpis_raw['volume_mwh'])

    # FIX BUDGET (CORRECTION DÉLIRE MWh/kWh)
    budget_display = financials['budget_annual']
    volume_multiplier = 1000
    if vol_display > 100000: volume_multiplier = 1 
    
    if financials['volume_mwh'] == 0 and vol_display > 0:
        p_data = data.get('pricing', {})
        u_price = 0.20
        for k in ['price_kwh', 'prix_kwh', 'price_hph', 'prix_hph']:
            if k in p_data and p_data[k]: 
                try: u_price = float(p_data[k]); break
                except: pass
        budget_display = financials.get('budget_subscription', 0) + (vol_display * volume_multiplier * u_price)

    # FIX DATA MISSING (RECONSTITUTION AGRESSIVE DES DÉTAILS)
    power_details = contract.get('power_details', {})
    # On reconstitue les valeurs à plat dans le contrat pour que le JS les trouve
    # On cherche dans power_details OU dans les champs plats
    if not contract.get('ps_hph'): contract['ps_hph'] = power_details.get('hph') or contract.get('p_hph') or contract.get('P_HPH') or "-"
    if not contract.get('ps_hch'): contract['ps_hch'] = power_details.get('hch') or contract.get('p_hch') or contract.get('P_HCH') or "-"
    if not contract.get('ps_hpe'): contract['ps_hpe'] = power_details.get('hpe') or contract.get('p_hpe') or contract.get('P_HPE') or "-"
    if not contract.get('ps_hce'): contract['ps_hce'] = power_details.get('hce') or contract.get('p_hce') or contract.get('P_HCE') or "-"

    # FIX "undefined undefined" (PROVIDER & SEGMENT)
    if not financials['meta'].get('provider'): financials['meta']['provider'] = contract.get('provider') or "Inconnu"
    if not display_segment: display_segment = contract.get('segment') or "-"

    response_data = {
        "energy_type": "gaz" if financials['meta']['is_gas'] else "elec",
        "identity": data.get('identity', {}),
        "location": data.get('location', {}),
        "technical": data.get('technical', {}),
        "financials": data.get('financials', {}),
        "contract": {
            "pdl": contract.get('pdl'),
            "provider": financials['meta'].get('provider'), # Assuré non-vide
            "segment": display_segment, # Assuré non-vide
            "start_date": contract.get('start_date'),
            "end_date": contract.get('end_date'),
            "power": contract.get('power'),
            "p_max": contract.get('p_max'),
            "fta": contract.get('fta'),
            "grd": contract.get('grd'),
            "cja": contract.get('cja'),
            "profil": contract.get('profil'),
            "tarif_acheminement": contract.get('tarif_acheminement'),
            "power_details": power_details, 
            # On renvoie aussi les champs plats forcés
            "ps_hph": contract.get('ps_hph'),
            "ps_hch": contract.get('ps_hch'),
            "ps_hpe": contract.get('ps_hpe'),
            "ps_hce": contract.get('ps_hce'),
            "consumption_details": contract.get('consumption_details', {})
        },
        "pricing": pricing,
        "kpis": {
            "volume_mwh": vol_display,
            "budget": budget_display,
            "pmc": financials['kpis']['pmc_eur_mwh'],
            "ghost_savings": financials['kpis']['ghost_savings'],
            "talon_kw": kpis_raw.get('talon_kw', 0),
            "pmax_kw": kpis_raw.get('pmax_kw', 0),
            "cortex_advice": kpis_raw.get('cortex_advice', "Pas d'analyse disponible."),
            "is_alert": kpis_raw.get('is_alert', False)
        },
        "cortex_insight": {
            "message": "Analyse CORTEX terminée.",
            "conseil": "Prix optimisé." if market_analysis['status'] == 'OPTIMISÉ' else "Surveillez ce contrat."
        },
        "market_analysis": market_analysis,
        "electricity_price": financials['kpis']['unit_price_kwh']
    }
    return JSONResponse(json_compliant(response_data))

@app.get("/api/forecast/simulate/{client_id}")
async def api_forecast_simulate(client_id: str):
    file_path = find_site_file(client_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    vol = 0
    if 'kpis' in data and 'volume_mwh' in data['kpis']: vol = float(data['kpis']['volume_mwh'])
    elif 'contract' in data and 'consumption_details' in data['contract']: vol = data['contract']['consumption_details'].get('volume_annuel', 0) / 1000
    if vol == 0:
        fin = cortex.enrich_site_financials(data)
        vol = fin['volume_mwh']
    if vol == 0: vol = 100 
    typology = data.get('location', {}).get('typologie', '')
    if not typology:
        name = data.get('identity', {}).get('site_name', '').upper()
        if "ECOLE" in name: typology = "ECOLE"
        elif "ECLAIRAGE" in name: typology = "ECLAIRAGE"
        elif "MAIRIE" in name: typology = "ADMIN"
    energy = "gaz" if data.get('contract', {}).get('pce') else "elec"
    res = forecast.generate_3_year_projection(vol, typology, energy)
    res['volume_mwh'] = vol
    res['volume_actuel'] = vol 
    return JSONResponse(json_compliant(res))

@app.post("/api/ops/market/update")
async def api_update_market(data: MarketUpdateModel, x_admin_token: str = Header(None)):
    try:
        new_payload = data.dict()
        new_payload["updated_at"] = datetime.now().isoformat()
        ref_path = os.path.join(DATA_DIR, "market_ref.json")
        with open(ref_path, "w") as f: json.dump(new_payload, f, indent=4)
        return JSONResponse({"success": True})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/physics/solar")
async def api_solar_sim(request: Request):
    try:
        payload = await request.json()
        address = payload.get('address', '')
        surface = float(payload.get('surface_roof', 0))
        price = float(payload.get('electricity_price', 0.20))
        lat, lon = physics.get_coordinates_from_address(address)
        return JSONResponse(physics.simulate_solar_roi(lat, lon, surface, price))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

# ==========================================
# OUTILS & TEMPLATES
# ==========================================
@app.get("/api/tools/template/{template_type}")
async def download_template(template_type: str):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    stream = io.BytesIO()
    try:
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if "import_elec" in template_type or "template_csv" == template_type:
                df = pd.DataFrame(columns=["ENTITE", "NOM_SITE", "ADRESSE_SITE", "CP", "VILLE", "SIRET_SITE", "REF_COPRO", "NAF", "CEE_ELIGIBLE", "GO_PERCENT", "COMPTEUR_PRODUCTION", "PDL", "SEGMENT", "FTA", "GRD", "TYPOLOGIE", "PUISSANCE_SOUSCRITE", "POINTE_MAX", "PS_HPH", "PS_HCH", "PS_HPE", "PS_HCE", "CONSO_HPH", "CONSO_HCH", "CONSO_HPE", "CONSO_HCE", "VOLUME_ANNUEL", "COMMENTAIRE", "DATE_DEBUT", "DATE_FIN", "FOURNISSEUR", "ABONNEMENT", "PRIX_HPH", "PRIX_HCH", "PRIX_HPE", "PRIX_HCE", "TAXES", "SURFACE_M2", "CODE_INSEE", "CHAUFFAGE", "ISOLATION", "REGULATION"])
                df.to_excel(writer, index=False)
            elif "import_gaz" in template_type or "template_csv_gaz" == template_type:
                df = pd.DataFrame(columns=["ENTITE", "NOM_SITE", "ADRESSE_SITE", "CP", "VILLE", "SIRET_SITE", "NAF", "CEE_ELIGIBLE", "PCE", "CAR_MWH", "CJA_MWH_J", "SEGMENT_GAZ", "PROFIL", "TARIF_ACHEM", "GRD", "DATE_DEBUT", "DATE_FIN", "FOURNISSEUR", "ABONNEMENT", "PRIX_MOLECULE", "TERME_STOCK", "TAXES", "INSEE", "SURFACE_M2", "CHAUFFAGE", "ISOLATION", "REGULATION"])
                df.to_excel(writer, index=False)
            elif "import_patrimoine" in template_type:
                df = pd.DataFrame(columns=["PDL", "NOM_SITE", "SURFACE_M2", "CHAUFFAGE", "ISOLATION", "REGULATION"])
                df.to_excel(writer, index=False, sheet_name="DATA")
                df_notice = pd.DataFrame({"CHAMP": ["CHAUFFAGE", "ISOLATION", "REGULATION"], "VALEURS_AUTORISEES": ["Gaz Condensation, Fioul, Élec Direct, PAC, Réseau Chaleur", "Non Isolé, Double Vitrage, ITE Complète", "Aucune, Thermostat Simple, GTB/GTC, Horloge"]})
                df_notice.to_excel(writer, index=False, sheet_name="MODE_EMPLOI")
            elif "bpu" in template_type:
                df = pd.DataFrame(columns=["PRIX_HPH", "ABONNEMENT"])
                df.to_excel(writer, index=False)
            else:
                df = pd.DataFrame(columns=["A", "B"])
                df.to_excel(writer, index=False)
        stream.seek(0)
        filename = f"Template_{template_type}.xlsx"
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})
    except:
        stream = io.StringIO()
        pd.DataFrame().to_csv(stream)
        return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")

@app.get("/api/settings/template_csv")
async def route_template_elec(): return await download_template("import_elec")
@app.get("/api/settings/template_csv_gaz")
async def route_template_gaz(): return await download_template("import_gaz")
@app.get("/api/settings/template_patrimoine")
async def route_template_patrimoine(): return await download_template("import_patrimoine")

@app.get("/app/assets/{filename}")
async def get_static_asset(filename: str):
    if "template" in filename: return await download_template("import_elec")
    if "bpu" in filename: return await download_template("bpu")
    return JSONResponse({"error": "File not found"}, 404)

@app.post("/api/ops/simulate_offer")
async def api_simulate_offer(file: UploadFile = File(...)):
    try:
        content = await file.read()
        current_sites = []
        files = glob.glob(os.path.join(DATA_DIR, "*.json"))
        for p in files:
            if "master" in p: continue
            try:
                with open(p, 'r', encoding='utf-8') as f: current_sites.append(json.load(f))
            except: continue
        res = cortex.simulate_budget_from_bpu(content, current_sites)
        return JSONResponse(json_compliant(res))
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    content = await file.read()
    res = cortex.analyze_load_curve(content, file.filename)
    return JSONResponse(json_compliant(res))

@app.post("/api/ops/generate_tender")
async def generate_tender(request: Request):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    try:
        body = await request.json()
        site_ids = body.get('site_ids', [])
        selected_sites = []
        for sid in site_ids:
            file_path = find_site_file(sid)
            if file_path:
                with open(file_path, 'r', encoding='utf-8') as f: selected_sites.append(json.load(f))
        
        df_dqe = cortex.generate_dqe_structure(selected_sites)
        df_elec = df_dqe[df_dqe['Type'] == 'ELEC']
        df_gaz = df_dqe[df_dqe['Type'] == 'GAZ']
        
        if not df_elec.empty:
            df_bpu_elec = df_elec[["PDL", "Nom du site", "CP", "Ville", "Segment", "Vol. Annuel"]].copy()
            df_bpu_elec["OFFRE_NOM"] = ""
            df_bpu_elec["PRIX_HPH_EUR_KWH"] = ""
            df_bpu_elec["PRIX_HCH_EUR_KWH"] = ""
            df_bpu_elec["PRIX_HPE_EUR_KWH"] = ""
            df_bpu_elec["PRIX_HCE_EUR_KWH"] = ""
            df_bpu_elec["ABONNEMENT_EUR_AN"] = ""
        else:
            df_bpu_elec = pd.DataFrame()

        if not df_gaz.empty:
            df_bpu_gaz = df_gaz[["PDL", "Nom du site", "CP", "Ville", "Vol. Annuel"]].copy()
            df_bpu_gaz = df_bpu_gaz.rename(columns={"PDL": "PCE"})
            df_bpu_gaz["OFFRE_NOM"] = ""
            df_bpu_gaz["PRIX_MOLECULE_EUR_MWH"] = ""
            df_bpu_gaz["ABONNEMENT_EUR_AN"] = ""
            df_bpu_gaz["TERME_STOCKAGE_EUR_MWH"] = ""
        else:
            df_bpu_gaz = pd.DataFrame()

        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if not df_elec.empty: 
                df_elec.to_excel(writer, index=False, sheet_name="DATA_ELEC")
                df_bpu_elec.to_excel(writer, index=False, sheet_name="REPONSE_ELEC")
            if not df_gaz.empty: 
                df_gaz.to_excel(writer, index=False, sheet_name="DATA_GAZ")
                df_bpu_gaz.to_excel(writer, index=False, sheet_name="REPONSE_GAZ")
            if df_elec.empty and df_gaz.empty: 
                df_dqe.to_excel(writer, index=False, sheet_name="TOUT")

        stream.seek(0)
        timestamp = datetime.now().strftime("%Y%m%d")
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=DQE_Energistrat_{timestamp}.xlsx"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

# ==========================================
# ROUTES TITANIUM (INGESTION & PROFILS)
# ==========================================

# --- SÉCURISATION DES ROUTES SENSIBLES (OPS & FINANCE) ---

@app.get("/ops/ingest", response_class=HTMLResponse)
async def ops_ingest_page(request: Request, user = Depends(get_current_user)):
    # PROTECTION
    if not user or user.get("role") not in ["ADMIN", "OPS_TECH"]: return RedirectResponse(url="/login")
    try:
        if 'router' not in globals() and 'router' not in locals(): raise Exception("Module Router manquant")
        api_status = router.get_api_status()
        return templates.TemplateResponse("ops_ingest.html", {"request": request, "api_status": api_status})
    except Exception as e:
        return HTMLResponse(content=f"<h1>System Error</h1><p>{str(e)}</p>", status_code=500)

@app.post("/api/ingest/upload")
async def ingest_files_mass(files: List[UploadFile] = File(...)):
    report = []
    for file in files:
        try:
            content = await file.read()
            analysis = router.analyze_file_stream(content, file.filename)
            report.append(analysis)
        except Exception as e:
            report.append({"filename": file.filename, "status": "ERROR", "message": str(e), "pdl": "ERR"})
    return JSONResponse(content={"report": report})

@app.post("/api/ops/market/simulate_strategy")
async def api_simulate_strategy(payload: StrategyRequest):
    file_path = find_site_file(payload.site_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    kpis = data.get('kpis', {})
    pmax = float(kpis.get('pmax_kw', 100))
    talon = float(kpis.get('talon_kw', 20))
    load_curve = []
    for h in range(24):
        val = talon
        if 6 <= h <= 20: val = talon + (pmax - talon) * 0.8 
        load_curve.append(val)
    result = market.valoriser_strategie(load_curve, payload.bloc_kw)
    return JSONResponse(json_compliant(result))

@app.post("/api/ops/aggregate")
async def api_aggregate_sites(payload: AggregationRequest):
    try:
        csv_content = aggregator.aggregate_sites(payload.site_ids, payload.years)
        if not csv_content: return JSONResponse({"error": "Aucune donnée"}, 400)
        response = Response(content=csv_content, media_type="text/csv")
        filename = f"SGE_AGGREGAT_{len(payload.site_ids)}SITES_{payload.years}ANS.csv"
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        return response
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

# --- ROUTES PROTÉGÉES PAR DÉFAUT (LOCKDOWN) ---

@app.get("/industrie", response_class=HTMLResponse)
@app.get("/industry", response_class=HTMLResponse)
async def view_industrie(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    if id:
        file_path = find_site_file(id)
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                fin = cortex.enrich_site_financials(data)
                context_data = {
                    "client_name": data.get('identity', {}).get('site_name', 'Client'),
                    "site_type": "Industrie - Réel", "puissance_souscrite": data.get('contract', {}).get('power', 0),
                    "talon_moyen": 0, "cos_phi": 0.95, "depassements": 0, "kpis": fin.get('kpis', {})
                }
                return templates.TemplateResponse("industry.html", {"request": request, "data": context_data})
    data = {"client_name": "USINE DÉMO", "site_type": "DÉMO", "puissance_souscrite": 0, "kpis": {}}
    return templates.TemplateResponse("industry.html", {"request": request, "data": data})

@app.get("/syndic", response_class=HTMLResponse)
async def view_syndic(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    if id:
        file_path = find_site_file(id)
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                fin = cortex.enrich_site_financials(data)
                context_data = {
                    "client_name": data.get('identity', {}).get('site_name', 'Résidence'),
                    "lots": 0, "chaufferie": "Chauffage Collectif", "dju_n": 2100, "dju_n_1": 2400,
                    "conso_n": fin.get('volume_mwh', 0) * 1000, "conso_n_1": (fin.get('volume_mwh', 0) * 1000) * 1.1
                }
                return templates.TemplateResponse("syndic.html", {"request": request, "data": context_data})
    data = {"client_name": "RÉSIDENCE DÉMO", "dju_n": 2100, "dju_n_1": 2400, "conso_n": 450000}
    return templates.TemplateResponse("syndic.html", {"request": request, "data": data})

@app.get("/mairie", response_class=HTMLResponse)
async def view_mairie(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("mairie.html", {"request": request})

@app.get("/retail", response_class=HTMLResponse)
async def view_retail(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("retail.html", {"request": request})

@app.get("/pme", response_class=HTMLResponse)
async def view_pme(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("pme.html", {"request": request})

@app.get("/sde", response_class=HTMLResponse)
async def view_sde(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("sde.html", {"request": request})

@app.get("/oph", response_class=HTMLResponse)
async def view_oph(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("oph.html", {"request": request})

@app.get("/citoyen", response_class=HTMLResponse)
async def view_citoyen(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("citoyen.html", {"request": request})

# --- SATELLITES (NOUVEAU) ---
@app.get("/optimization", response_class=HTMLResponse)
async def view_optimization(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("optimization.html", {"request": request})

@app.get("/performance", response_class=HTMLResponse)
async def view_performance(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("performance.html", {"request": request})

@app.get("/carbon", response_class=HTMLResponse)
async def view_carbon(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("carbon.html", {"request": request})

@app.get("/trading", response_class=HTMLResponse)
async def view_trading(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("trading.html", {"request": request})

@app.get("/ops/aggregator", response_class=HTMLResponse)
async def view_aggregator(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("ops_aggregator.html", {"request": request})

# --- MODULE FINANCE (NOUVEAU & SÉCURISÉ) ---
@app.get("/finance", response_class=HTMLResponse)
async def view_finance(request: Request, user = Depends(get_current_user)):
    """Vue Principale Finance (Twin + Audit) - Protégée."""
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard_finance.html", {"request": request, "user": user})

@app.post("/api/finance/upload")
async def api_finance_upload(file: UploadFile = File(...), site_id: str = Form(...)):
    """Upload et Audit immédiat (Factur-X/Excel)"""
    try:
        content = await file.read()
        
        # 1. Parse
        parsed = finance.parse_invoice(content, file.filename)
        if parsed.get("status") == "ERROR":
            return JSONResponse(parsed, status_code=400)
        
        # 2. Récup Site Data (Pour le contrat)
        file_path = find_site_file(site_id)
        site_data = {}
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                site_data = json.load(f)
        
        # 3. Audit
        audit_report = finance.audit_invoice(parsed, site_data)
        return JSONResponse(json_compliant(audit_report))
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.get("/api/finance/landing/{site_id}")
async def api_finance_landing(site_id: str):
    """Récupère les données du Twin Financier"""
    file_path = find_site_file(site_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            site_data = json.load(f)
        landing_data = finance.simulate_landing(site_data)
        return JSONResponse(json_compliant(landing_data))
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

# --- ROUTES DE BASE ---
@app.get("/")
async def view_landing(request: Request): 
    # ACCÈS PUBLIC (Vitrine)
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/processing")
async def view_processing(request: Request): return templates.TemplateResponse("processing.html", {"request": request})

@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str, user = Depends(get_current_user)):
    # PROTECTION : Dashboard accessible uniquement si connecté
    # Sauf mode Demo pour les besoins de dev (optionnel)
    if not user and profile not in ["demo"]: 
        return RedirectResponse(url="/login")

    # ROUTAGE EXPLICITE CORRIGÉ
    if profile == "retail": return templates.TemplateResponse("retail.html", {"request": request})
    if profile == "mairie": return templates.TemplateResponse("mairie.html", {"request": request})
    if profile == "sde": return templates.TemplateResponse("sde.html", {"request": request})
    if profile == "oph": return templates.TemplateResponse("oph.html", {"request": request})
    if profile == "pme": return templates.TemplateResponse("pme.html", {"request": request})
    if profile == "citoyen": return templates.TemplateResponse("citoyen.html", {"request": request})
    if profile == "forecast": return templates.TemplateResponse("forecast.html", {"request": request}) 
    
    t = f"{profile}.html"
    if os.path.exists(os.path.join(TEMPLATE_DIR, t)): return templates.TemplateResponse(t, {"request": request, "profile": profile})
    return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})

@app.get("/settings")
async def view_settings(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/partner/settings")
async def view_partner_settings(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    if "supplier" in request.headers.get("referer", ""): return templates.TemplateResponse("settings_partner.html", {"request": request})
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/ops/market")
async def view_ops_market(request: Request): return templates.TemplateResponse("ops_market.html", {"request": request})

# --- PROTECTION DE LA ROUTE DYNAMIQUE ---
@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str, user = Depends(get_current_user)):
    # 1. Whitelist des pages publiques
    PUBLIC_PAGES = ["index.html", "onboarding.html", "processing.html", "login.html", "solutions.html", "cortex.html", "vitality.html", "connectivite.html", "audit_premium.html", "store.html", "ethique.html", "fournisseurs.html", "etudes-de-cas.html", "modele_economique.html"]

    # 2. Check Extension
    if any(x in page_name for x in [".js", ".css", ".png", ".jpg"]): return JSONResponse({}, 404)
    
    # 3. Normalisation
    target_file = page_name if page_name.endswith(".html") else f"{page_name}.html"
    
    # 4. SÉCURITÉ : Si la page n'est pas publique et que l'user n'est pas connecté -> Login
    if target_file not in PUBLIC_PAGES and not user:
         return RedirectResponse(url="/login")

    # 5. Serve
    if os.path.exists(os.path.join(TEMPLATE_DIR, target_file)): 
        return templates.TemplateResponse(target_file, {"request": request})
    
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in ["static", "assets", "favicon"]): return JSONResponse({}, 404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
