import os
import json
import glob
import uuid
import math
import io
import traceback
import urllib.request
import urllib.parse
import base64
import asyncio # AJOUT CORTEX : Pour le Daemon Sentinel
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta # AJOUT CORTEX : Pour le calcul des dates RTE

# AJOUTS SÉCURITÉ : Depends, status, RedirectResponse, BackgroundTasks
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException, Response, Depends, status, BackgroundTasks
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
# BLOC IMPORT CORTEX ROBUSTE (EVOLUTION ANTI-CRASH)
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
        
        class MockCortex:
            def enrich_site_financials(self, data): return {"volume_mwh": 0, "budget_annual": 0, "meta": {"is_gas": False, "site_label": "Mock", "city": "Mock"}, "kpis": {"pmc_eur_mwh": 0, "ghost_savings": 0}}
            def analyze_portfolio(self, sites): return {"global": {}, "green_league": {}}
            def simulate_budget_from_bpu(self, b, s): return {}
            def analyze_load_curve(self, c, n): return {}
            def generate_dqe_structure(self, s): return pd.DataFrame() if PANDAS_READY else None
        cortex = MockCortex()
        
        ingest = None; physics = None; forecast = None

app = FastAPI(title="ENERGISTRAT V3", version="EMPIRE-V4.6-RTE-OPEN-DATA")

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

# --- MODELES DE DONNEES ---
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

class M57SettingsModel(BaseModel):
    bp_elec: float = 0.0
    bp_gaz: float = 0.0
    consumed_elec: float = 0.0
    consumed_gaz: float = 0.0
    bp_irve: float = 0.0
    consumed_irve: float = 0.0
    bp_enr: float = 0.0
    consumed_enr: float = 0.0

class CarbonSettingsModel(BaseModel):
    baseline_year: int = 2010
    baseline_kwh_sqm: float = 0.0

class RTESettingsModel(BaseModel):
    client_id: str = ""
    client_secret: str = ""

# ==============================================================================
# DAEMON CORTEX SENTINEL 
# ==============================================================================
async def run_sentinel_scan():
    print("[CORTEX SENTINEL] Démarrage du scan de mouvements et dérives...")
    alerts =[]
    try:
        files = glob.glob(os.path.join(DATA_DIR, "*.json"))
        for p in files:
            if any(x in p for x in["master_", "market_", "m57_", "carbon_", "rte_", "sentinel_"]): continue
            try:
                with open(p, 'r', encoding='utf-8') as f: data = json.load(f)
                if cortex is None: continue
                fin = cortex.enrich_site_financials(data)
                identity = data.get('identity', {})
                contract = data.get('contract', {})
                vol = fin.get('volume_mwh', 0)
                budget = fin.get('budget_annual', 0)
                ghost = fin.get('kpis', {}).get('ghost_savings', 0)
                city = data.get('location', {}).get('city', 'Inconnue')
                name = identity.get('site_name') or identity.get('name', 'Site Inconnu')
                pdl = contract.get('pdl') or contract.get('pce') or identity.get('id', 'N/A')
                action = ""; motif = ""; color = ""
                if vol > 0 and budget == 0:
                    action = "🟢 Entrée Orpheline"; motif = "Raccordement détecté (volume actif) mais hors marché public."; color = "text-success bg-success/10 border-success/30"
                elif vol == 0 and budget > 0:
                    action = "🔴 Sortie de Parc"; motif = "Facturation active (Abonnement) mais conso nulle."; color = "text-alert bg-alert/10 border-alert/30"
                elif budget > 0 and ghost > (budget * 0.4):
                    action = "🟡 Dérive Majeure"; motif = f"Surconsommation (Talon). Gaspillage estimé à {int(ghost)} €/an."; color = "text-gold bg-gold/10 border-gold/30"
                if action:
                    alerts.append({"id": identity.get("id", ""), "city": city, "name": name, "pdl": pdl, "action": action, "motif": motif, "color": color, "timestamp": datetime.now().isoformat()})
            except Exception: continue

        system_dir = os.path.join(DATA_DIR, "system")
        os.makedirs(system_dir, exist_ok=True)
        with open(os.path.join(system_dir, "sentinel_alerts.json"), 'w', encoding='utf-8') as f:
            json.dump({"last_scan": datetime.now().isoformat(), "alert_count": len(alerts), "alerts": alerts}, f, indent=4, ensure_ascii=False)
        print(f"[CORTEX SENTINEL] Scan terminé. {len(alerts)} anomalies.")
        return len(alerts)
    except Exception as e: return 0

async def sentinel_daemon_loop():
    await asyncio.sleep(10)
    while True:
        await run_sentinel_scan()
        await asyncio.sleep(43200)

@app.on_event("startup")
async def startup_event():
    print("🚀 [ENERGISTRAT V3] Lancement des daemons CORTEX...")
    asyncio.create_task(sentinel_daemon_loop())

# --- FONCTIONS UTILITAIRES ---
def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return[json_compliant(v) for v in data]
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
                if get_safe_id(str(data.get('identity', {}).get('id', ''))) == safe_target: return p
        except: continue
    return None

def get_market_ref():
    path = os.path.join(DATA_DIR, "market_ref.json")
    if os.path.exists(path):
        try:
            with open(path, 'r') as f: return json.load(f)
        except: pass
    return {"updated_at": datetime.now().isoformat(), "elec": { "cal_n1": 85.0 }, "gaz": { "peg_n1": 35.0 }, "trve": { "elec_c5": 230.0 }, "targets": { "c5": 190.0 }}

async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token: return None
    if token.startswith("Bearer "): token = token.split(" ")[1]
    payload = auth.decode_token(token)
    if not payload: return None
    return payload

def get_rte_token(client_id, client_secret):
    url = "https://digital.iservices.rte-france.com/token/oauth/"
    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    headers = { "Authorization": f"Basic {b64_auth}", "Content-Type": "application/x-www-form-urlencoded" }
    data = urllib.parse.urlencode({}).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data.get("access_token")
    except Exception: return None

# ==========================================
# AUTHENTIFICATION
# ==========================================
@app.get("/login", response_class=HTMLResponse)
async def view_login(request: Request):
    if request.cookies.get("access_token"): return RedirectResponse(url="/ops_nexus")
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
# API CORTEX SENTINEL
# ==========================================
@app.get("/api/ops/sentinel/alerts")
async def get_sentinel_alerts():
    path = os.path.join(DATA_DIR, "system", "sentinel_alerts.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: pass
    return {"last_scan": "Jamais", "alert_count": 0, "alerts":[]}

@app.post("/api/ops/sentinel/run")
async def trigger_sentinel_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_sentinel_scan)
    return JSONResponse({"success": True, "message": "Scan Sentinel déclenché."})

# ==========================================
# API DEAL DESK 
# ==========================================
@app.post("/api/dealdesk/analyze")
async def api_dealdesk_analyze(request: Request):
    body = await request.json()
    query = str(body.get('query', '')).strip().lower()
    if not query: return JSONResponse({"success": False, "error": "Requête vide."})
        
    site_data = None
    for p in glob.glob(os.path.join(DATA_DIR, "*.json")):
        if any(x in p for x in["master_", "market_", "m57_", "carbon_", "rte_", "sentinel_"]): continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if query == str(data.get('contract', {}).get('pdl', '')).strip() or query == str(data.get('contract', {}).get('pce', '')).strip() or query in str(data.get('identity', {}).get('site_name', '')).strip().lower():
                    site_data = data; break
        except: continue
        
    if not site_data: return JSONResponse({"success": False, "error": "PDL/Nom introuvable dans la Data Unity."})
        
    try:
        fin = cortex.enrich_site_financials(site_data)
        vol = fin.get('volume_mwh', 0)
        if vol == 0 and 'kpis' in site_data and 'volume_mwh' in site_data['kpis']: vol = float(site_data['kpis']['volume_mwh'])
    except: vol = 0
    
    power = float(site_data.get('contract', {}).get('power', 0))
    pdl_val = site_data.get('contract', {}).get('pdl') or site_data.get('contract', {}).get('pce', 'N/A')
    siret = site_data.get('identity', {}).get('siret', '')
    original_name = site_data.get('identity', {}).get('site_name', 'Client Inconnu')

    legal_info = {"is_micro": False, "regime": "CODE_COMMERCE", "nom": original_name, "siret": siret}
    if siret or original_name != "Client Inconnu":
        try:
            url = f"https://recherche-entreprises.api.gouv.fr/search?q={urllib.parse.quote(siret if siret else original_name)}&page=1&per_page=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'Energistrat/1.0'})
            with urllib.request.urlopen(req, timeout=3) as response:
                gov_data = json.loads(response.read().decode('utf-8'))
                if gov_data.get('results') and len(gov_data['results']) > 0:
                    comp = gov_data['results'][0]
                    if comp.get('tranche_effectif_salarie', '00') in['00', '01', '02', '03'] or comp.get('tranche_effectif_salarie') is None:
                        legal_info['is_micro'] = True; legal_info['regime'] = "CODE_CONSOMMATION"
                    legal_info['nom'] = comp.get('nom_complet', original_name)
                    legal_info['siret'] = comp.get('siege', {}).get('siret', siret)
        except: pass

    segment = "B2B_HEAVY" if vol > 5000 else ("C4_MID" if power > 36 or vol > 250 else "C5_MASS")
    return JSONResponse({"success": True, "site": { "name": legal_info['nom'], "pdl": pdl_val, "volume": round(vol, 2), "power": power }, "legal": legal_info, "segment": segment})

# ==========================================
# API SUBVENTIONS & CERFA
# ==========================================
@app.get("/api/tools/subventions")
async def api_subventions_analyze(user = Depends(get_current_user)):
    raw_sites =[]
    for p in glob.glob(os.path.join(DATA_DIR, "*.json")):
        if any(x in p for x in["master", "market", "m57", "carbon", "rte", "sentinel"]): continue
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if cortex: data['computed_financials'] = cortex.enrich_site_financials(data)
                raw_sites.append(data)
        except: continue

    cee_price_mwh = 6.50
    results =[]; total_enveloppe = 0

    for s in raw_sites:
        if "CLI_" in str(s.get('identity',{}).get('id')): continue
        fin = s.get('computed_financials', {}); loc = s.get('location', {}); contract = s.get('contract', {}); kpis = s.get('kpis', {})
        surface = float(loc.get('surface', 0)); city = str(loc.get('city', '')).upper()
        vol = float(fin.get('volume_mwh', 0))
        if vol == 0: vol = float(kpis.get('volume_mwh', 0))
        pdl = str(contract.get('pdl') or contract.get('pce') or "Inconnu")
        name = fin.get('meta', {}).get('site_label', 'Site Inconnu')
        is_gas = fin.get('meta', {}).get('is_gas', False)
        raw_id = s.get('identity', {}).get('id', ''); safe_id = get_safe_id(raw_id)
        
        if surface == 0:
            results.append({"id": safe_id, "pdl": pdl, "name": name, "city": city, "status": "MISSING_DATA", "reason": "Surface manquante."})
            continue
        zone_factor = 1.3 if any(x in city for x in['LILLE', 'PARIS', 'STRASBOURG', 'LYON', 'NANCY', 'REIMS', 'METZ']) else (0.8 if any(x in city for x in['MARSEILLE', 'NICE', 'MONTPELLIER', 'TOULON', 'PERPIGNAN', 'NIMES']) else 1.0)
        zone_name = "H1" if zone_factor == 1.3 else ("H3" if zone_factor == 0.8 else "H2")
        aides =[]
        ghost = float(fin.get('kpis', {}).get('ghost_savings', 0))
        if surface >= 500 and ghost > (vol * 0.1):
            prime_coup_de_pouce = ((surface * 250 * zone_factor) / 1000) * cee_price_mwh * 1.5 
            aides.append({"code": "BAT-TH-116", "nom": "Coup de Pouce GTB", "details": f"Surface ({surface}m²) × Forfait × Zone {zone_name}", "montant": round(prime_coup_de_pouce)})
            total_enveloppe += prime_coup_de_pouce
        if (vol * 1000) / surface > 300 if surface > 0 else False:
            prime = (((surface * 0.3) * 1400 * zone_factor) / 1000) * cee_price_mwh
            aides.append({"code": "BAT-EN-101", "nom": "Isolation Thermique Toiture", "details": f"Surface estimée ({round(surface * 0.3)}m²) × 1400 kWhc × Zone {zone_name}", "montant": round(prime)})
            total_enveloppe += prime
        if is_gas and vol > 500:
            prime = vol * 25
            aides.append({"code": "ADEME-CHALEUR", "nom": "Fonds Chaleur", "details": f"Substitution {round(vol)} MWh fossile × 25€", "montant": round(prime)})
            total_enveloppe += prime
        if len(aides) > 0: results.append({ "id": safe_id, "pdl": pdl, "name": name, "city": city, "status": "ELIGIBLE", "aides": aides, "total_site": sum(a['montant'] for a in aides) })
        else: results.append({ "id": safe_id, "pdl": pdl, "name": name, "city": city, "status": "NON_ELIGIBLE", "reason": "Site optimisé." })
    return JSONResponse({"success": True, "results": results, "total_enveloppe": round(total_enveloppe)})

@app.get("/api/tools/cerfa/{site_id}/{aide_code}", response_class=HTMLResponse)
async def generate_cerfa_pdf(site_id: str, aide_code: str, user = Depends(get_current_user)):
    if not user: return HTMLResponse("Non autorisé", status_code=401)
    file_path = find_site_file(site_id)
    if not file_path: return HTMLResponse(f"<h1>Erreur</h1><p>Site introuvable.</p>", status_code=404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    identity = data.get('identity', {}); loc = data.get('location', {}); contract = data.get('contract', {})
    company_name = str(identity.get('site_name') or identity.get('name') or 'NON RENSEIGNÉ')
    siret = str(identity.get('siret') or 'NON RENSEIGNÉ')
    address = str(loc.get('address') or 'NON RENSEIGNÉ')
    city = str(loc.get('city') or 'NON RENSEIGNÉ')
    surface = str(loc.get('surface') or 'NON RENSEIGNÉ')
    naf = str(identity.get('naf') or 'NON RENSEIGNÉ')
    pdl_val = str(contract.get('pdl') or contract.get('pce') or 'NON RENSEIGNÉ')
    cerfa_num = "15404*01"; titre_travaux = "OPÉRATION STANDARDISÉE"; fiche_name = aide_code
    if "116" in aide_code: titre_travaux = "MISE EN PLACE D'UN SYSTÈME DE GESTION TECHNIQUE DU BÂTIMENT (GTB)"; fiche_name = "BAT-TH-116"
    elif "101" in aide_code: titre_travaux = "ISOLATION DE COMBLES OU DE TOITURES"; fiche_name = "BAT-EN-101"
    html_content = f"""
    <!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>CERFA_{fiche_name}_{pdl_val}</title>
    <style>@page {{ size: A4; margin: 15mm; }} body {{ font-family: Helvetica, Arial, sans-serif; font-size: 12px; }} h2 {{ background: #e0e0e0; padding: 5px; border: 1px solid black; }} .form-row {{ display: flex; border: 1px solid black; border-top: none; }} .form-label {{ width: 40%; padding: 8px; border-right: 1px solid black; font-weight: bold; background: #f9f9f9; }} .form-value {{ width: 60%; padding: 8px; font-family: monospace; }}</style></head>
    <body onload="setTimeout(function(){{ window.print(); }}, 500);">
    <div style="display:flex; justify-content:space-between; border-bottom:2px solid black; padding-bottom:10px; margin-bottom:20px;">
    <div style="border:1px solid black; padding:10px; text-align:center; font-weight:bold; font-size:10px;">Liberté<br>Égalité<br>Fraternité<br><br>RÉPUBLIQUE FRANÇAISE</div>
    <div style="text-align:center; flex:1;"><h1>ATTESTATION SUR L'HONNEUR</h1><p>Opérations d'économies d'énergie (CEE)</p></div>
    <div style="border:1px solid black; padding:10px; text-align:center; font-weight:bold;">CERFA<br>N° {cerfa_num}</div>
    </div>
    <h2>A - BÉNÉFICIAIRE</h2><div class="form-row" style="border-top:1px solid black;"><div class="form-label">Raison Sociale</div><div class="form-value">{company_name.upper()}</div></div>
    <div class="form-row"><div class="form-label">N° SIRET</div><div class="form-value">{siret}</div></div>
    <h2>B - LIEU DES TRAVAUX</h2><div class="form-row" style="border-top:1px solid black;"><div class="form-label">Adresse</div><div class="form-value">{address} - {city.upper()}</div></div>
    <div class="form-row"><div class="form-label">PDL / PCE</div><div class="form-value">{pdl_val}</div></div><div class="form-row"><div class="form-label">Surface</div><div class="form-value">{surface} m²</div></div>
    <h2>C - OPÉRATION</h2><div class="form-row" style="border-top:1px solid black;"><div class="form-label">Fiche CEE</div><div class="form-value">{fiche_name}</div></div><div class="form-row"><div class="form-label">Nature</div><div class="form-value">{titre_travaux}</div></div>
    <div style="margin-top:30px; border:1px solid black; padding:15px;"><b>Je soussigné(e) atteste sur l'honneur l'exactitude des informations. ENERGISTRAT est mandaté.</b></div>
    <div style="margin-top:20px; display:flex; justify-content:space-between;"><div style="border:1px dashed gray; width:45%; height:100px; padding:10px;">Fait à: {city.upper()}<br>Le: {datetime.now().strftime('%d/%m/%Y')}<br><b>Signature:</b></div><div style="border:1px dashed gray; width:45%; height:100px; padding:10px;"><b>Cachet:</b></div></div>
    </body></html>"""
    return HTMLResponse(content=html_content)

@app.get("/api/physics/thermic_signature/{client_id}")
async def get_thermic_signature(client_id: str):
    file_path = find_site_file(client_id)
    if not file_path: return JSONResponse({"error": "Introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    fin = cortex.enrich_site_financials(data)
    vol = fin.get('volume_mwh', 0)
    if vol == 0 and 'kpis' in data and 'volume_mwh' in data['kpis']: vol = float(data['kpis']['volume_mwh'])
    city = str(data.get('location', {}).get('city', 'Paris')).upper()
    dju_profile =[450, 400, 350, 200, 80, 10, 0, 0, 50, 200, 350, 420]
    if any(x in city for x in['LILLE', 'STRASBOURG', 'NANCY', 'METZ']): dju_profile =[x * 1.2 for x in dju_profile]
    elif any(x in city for x in['MARSEILLE', 'NICE', 'MONTPELLIER', 'TOULON']): dju_profile =[x * 0.7 for x in dju_profile]
    total_dju = sum(dju_profile)
    if total_dju == 0: total_dju = 1
    talon_pct = 0.15 if fin.get('meta', {}).get('is_gas', False) else 0.30
    talon_monthly = (vol * talon_pct) / 12; chauffage_annual = vol - (vol * talon_pct)
    points =[]
    for m in range(12): points.append({"x": round(dju_profile[m]), "y": round(((dju_profile[m]/total_dju)*chauffage_annual) + talon_monthly, 2), "month": m+1})
    x_mean = sum(p['x'] for p in points) / 12; y_mean = sum(p['y'] for p in points) / 12
    denominator = sum((p['x'] - x_mean)**2 for p in points)
    a = sum((p['x'] - x_mean) * (p['y'] - y_mean) for p in points) / denominator if denominator != 0 else 0
    b = y_mean - a * x_mean
    ss_tot = sum((p['y'] - y_mean)**2 for p in points)
    r2 = 1 - (sum((p['y'] - (a * p['x'] + b))**2 for p in points) / ss_tot) if ss_tot != 0 else 0
    return JSONResponse({"success": True, "points": points, "regression": {"a": round(a, 4), "b": round(b, 2), "r2": round(r2, 3)}, "diagnostics": {"talon_mensuel": round(talon_monthly, 2), "sensibilite": round(a * 1000, 2), "is_optimized": r2 > 0.85}})

@app.get("/api/tools/immo/{client_id}")
async def api_immo_analyze(client_id: str, user = Depends(get_current_user)):
    file_path = find_site_file(client_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    fin = cortex.enrich_site_financials(data)
    vol = fin.get('volume_mwh', 0)
    if vol == 0 and 'kpis' in data and 'volume_mwh' in data['kpis']: vol = float(data['kpis']['volume_mwh'])
    surface = float(data.get('location', {}).get('surface', 0))
    city = data.get('location', {}).get('city', 'Inconnue')
    naf = str(data.get('identity', {}).get('naf', '0000')).upper()
    if surface == 0 or vol == 0: return JSONResponse({"success": False, "error": "Volume ou Surface (m²) manquant."})
    intensity = (vol * 1000) / surface
    baseline_kwh_m2 = 200; sector_name = "Tertiaire Standard"
    if naf.startswith('47'): baseline_kwh_m2 = 450; sector_name = "Commerce"
    elif naf.startswith('84'): baseline_kwh_m2 = 150; sector_name = "Administration"
    elif naf.startswith('86'): baseline_kwh_m2 = 350; sector_name = "Santé"
    ratio = intensity / baseline_kwh_m2
    if ratio <= 0.5: dpe = "A"; decote_pct = 0.05 
    elif ratio <= 0.7: dpe = "B"; decote_pct = 0.02
    elif ratio <= 0.9: dpe = "C"; decote_pct = 0
    elif ratio <= 1.1: dpe = "D"; decote_pct = 0
    elif ratio <= 1.4: dpe = "E"; decote_pct = -0.05 
    elif ratio <= 1.8: dpe = "F"; decote_pct = -0.15 
    else: dpe = "G"; decote_pct = -0.20 
    prix_m2_moyen = 9500 if "PARIS" in city.upper() else (4500 if any(x in city.upper() for x in['LYON', 'BORDEAUX', 'NICE']) else 2500)
    valeur_theorique = surface * prix_m2_moyen
    impact_euros = valeur_theorique * decote_pct
    return JSONResponse({"success": True, "site": {"name": data.get('identity', {}).get('site_name', 'Site'), "city": city, "surface": surface, "naf": naf, "sector": sector_name}, "energy": {"volume_mwh": vol, "intensity_kwh_m2": round(intensity), "baseline_kwh_m2": baseline_kwh_m2}, "dpe": {"note": dpe, "is_passoire": dpe in['F', 'G']}, "finance": {"valeur_theorique": valeur_theorique, "impact_foncier": round(impact_euros), "decote_pct": round(decote_pct * 100)}})

# ==============================================================================
# INJECTION CORTEX 3 : LE SNIPER BRANCHÉ SUR L'OPEN DATA RTE (ZERO MOCK)
# ==============================================================================
@app.get("/api/tools/sniper/market")
async def api_sniper_market(user = Depends(get_current_user)):
    """Cortex Sniper : Interrogation en temps réel de l'API Open Data RTE."""
    path = os.path.join(DATA_DIR, "rte_settings.json")
    rte_token = None
    
    # 1. Vérification des Clés API RTE
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: keys = json.load(f)
            client_id = keys.get("client_id")
            client_secret = keys.get("client_secret")
            if client_id and client_secret and client_secret != "******":
                rte_token = get_rte_token(client_id, client_secret)
        except: pass
        
    # 2. Sécurité Tiers de Confiance : Pas de fausses data si pas d'API
    if not rte_token:
        return JSONResponse({
            "success": False, 
            "error": "Clés API RTE manquantes. Allez dans 'Settings > Satellites' pour configurer l'accès Open Data."
        })
        
    try:
        # 3. Interrogation réelle API RTE Wholesale Market v2 (Day-Ahead Prices France)
        end_date = datetime.utcnow() + timedelta(days=2)
        start_date = datetime.utcnow() - timedelta(days=15)
        
        start_str = start_date.strftime("%Y-%m-%dT00:00:00Z")
        end_str = end_date.strftime("%Y-%m-%dT00:00:00Z")
        
        url = f"https://digital.iservices.rte-france.com/open_api/wholesale_market/v2/france_day_ahead_prices?start_date={start_str}&end_date={end_str}"
        
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {rte_token}'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        points_elec =[]
        if 'france_day_ahead_prices' in data and len(data['france_day_ahead_prices']) > 0:
            values = data['france_day_ahead_prices'][0].get('values',[])
            
            # Agrégation journalière (Prix moyen Base Load CAL)
            daily_prices = {}
            for v in values:
                day = v['start_date'][:10]
                daily_prices.setdefault(day, []).append(v['price'])
                
            for day, prices in daily_prices.items():
                points_elec.append({"date": day, "price": round(sum(prices)/len(prices), 2)})
        
        # Tri chronologique sécurisé
        points_elec = sorted(points_elec, key=lambda x: x['date'])
        current_elec = points_elec[-1]['price'] if points_elec else 0
        
        # 4. Fallback PEG Gaz (RTE ne fait que l'Elec)
        points_gaz = [{"date": p['date'], "price": 35.0} for p in points_elec]
        
        return JSONResponse({
            "success": True,
            "market_elec_cal": points_elec,
            "market_gaz_peg": points_gaz,
            "current_prices": {"elec": current_elec, "gaz": 35.0},
            "status": "BEAR" if current_elec < 70 else "BULL",
            "alert_triggered": current_elec < 60
        })
        
    except Exception as e:
        return JSONResponse({
            "success": False, 
            "error": f"Erreur de connexion aux serveurs RTE: {str(e)}"
        })

@app.get("/api/tools/gridmap/capacity")
async def api_gridmap_capacity(user = Depends(get_current_user)):
    results =[]
    for p in glob.glob(os.path.join(DATA_DIR, "*.json")):
        if any(x in p for x in["master", "market", "m57", "carbon", "rte", "sentinel"]): continue
        try:
            with open(p, 'r', encoding='utf-8') as f: s = json.load(f)
            if "CLI_" in str(s.get('identity',{}).get('id')): continue
            pdl = s.get('contract', {}).get('pdl')
            if not pdl: continue
            power = float(s.get('contract', {}).get('power', 0))
            city = s.get('location', {}).get('city', 'Inconnue')
            capacity = 150 if power > 250 else (50 if power > 100 else 15)
            results.append({"pdl": pdl, "name": s.get('identity', {}).get('site_name', 'Site'), "city": city, "power_kva": power, "residual_capacity_kva": capacity, "can_host_fast_charge": capacity >= 50})
        except: continue
    return JSONResponse({"success": True, "nodes": results})

# --- API PRINCIPALES (SETTINGS & DATA) ---
def normalize_full_data(data):
    if 'contract' not in data: data['contract'] = {}
    if 'pricing' not in data: data['pricing'] = {}
    c = data['contract']; p = data['pricing']
    if 'power_details' not in c: c['power_details'] = {}
    sources =[data, c, data.get('technical', {}), p]
    power_map = { 'hph':['ps_hph', 'p_hph', 'PS_HPH', 'puissance_hph'], 'hch':['ps_hch', 'p_hch', 'PS_HCH', 'puissance_hch'], 'hpe':['ps_hpe', 'p_hpe', 'PS_HPE', 'puissance_hpe'], 'hce':['ps_hce', 'p_hce', 'PS_HCE', 'puissance_hce'] }
    for target, variants in power_map.items():
        for s in sources:
            if not s: continue
            for v in variants:
                if v in s and s[v]:
                    c['power_details'][target] = s[v]
                    c[f"ps_{target}"] = s[v] 
                    break

    price_map = { 'hph':['price_hph', 'prix_hph', 'P_HPH', 'tarif_hph'], 'hch':['price_hch', 'prix_hch', 'P_HCH', 'tarif_hch'], 'hpe':['price_hpe', 'prix_hpe', 'P_HPE', 'tarif_hpe'], 'hce':['price_hce', 'prix_hce', 'P_HCE', 'tarif_hce'] }
    for target, variants in price_map.items():
        for s in sources:
            if not s: continue
            for v in variants:
                if v in s and s[v]:
                    p[target] = s[v] 
                    break

    if 'identity' in data:
        i = data['identity']
        if 'siret' in data and data['siret']: i['siret'] = data['siret']
        if not i.get('id') and i.get('siret'): i['id'] = i['siret']
    data['contract'] = c
    data['pricing'] = p
    return data

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        data = normalize_full_data(data)
        raw_id = data.get("identity", {}).get("id") or f"CLI_{uuid.uuid4().hex[:8]}"
        data["identity"]["id"] = raw_id
        safe_id = get_safe_id(raw_id)
        file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f: existing_data = json.load(f)
            for section in['technical', 'location', 'identity', 'contract', 'pricing', 'kpis', 'financials', 'rgpd']:
                if section in data:
                    if section not in existing_data: existing_data[section] = {}
                    existing_data[section].update(data[section])
            final_data = existing_data
        else:
            final_data = data
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(final_data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "id": raw_id})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/settings/m57")
async def get_m57_settings():
    path = os.path.join(DATA_DIR, "m57_settings.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"bp_elec": 0.0, "bp_gaz": 0.0, "consumed_elec": 0.0, "consumed_gaz": 0.0, "bp_irve": 0.0, "consumed_irve": 0.0, "bp_enr": 0.0, "consumed_enr": 0.0}

@app.post("/api/settings/m57")
async def save_m57_settings(data: M57SettingsModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    try:
        path = os.path.join(DATA_DIR, "m57_settings.json")
        with open(path, 'w', encoding='utf-8') as f: json.dump(data.dict(), f, indent=4)
        return JSONResponse({"success": True})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/api/settings/carbon")
async def get_carbon_settings():
    path = os.path.join(DATA_DIR, "carbon_settings.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return {"baseline_year": 2010, "baseline_kwh_sqm": 0.0}

@app.post("/api/settings/carbon")
async def save_carbon_settings(data: CarbonSettingsModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    try:
        path = os.path.join(DATA_DIR, "carbon_settings.json")
        with open(path, 'w', encoding='utf-8') as f: json.dump(data.dict(), f, indent=4)
        return JSONResponse({"success": True})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/api/settings/rte")
async def get_rte_settings():
    path = os.path.join(DATA_DIR, "rte_settings.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: 
                data = json.load(f)
                return {"client_id": data.get("client_id", ""), "client_secret": "******" if data.get("client_secret") else ""}
        except: pass
    return {"client_id": "", "client_secret": ""}

@app.post("/api/settings/rte")
async def save_rte_settings(data: RTESettingsModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    try:
        path = os.path.join(DATA_DIR, "rte_settings.json")
        existing = {}
        if os.path.exists(path):
            with open(path, 'r') as f: existing = json.load(f)
        new_data = data.dict()
        if new_data["client_secret"] == "******": new_data["client_secret"] = existing.get("client_secret", "")
        with open(path, 'w', encoding='utf-8') as f: json.dump(new_data, f, indent=4)
        return JSONResponse({"success": True})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.post("/api/settings/update_site")
async def api_update_site(request: Request):
    try:
        payload = await request.json()
        payload = normalize_full_data(payload)
        site_id = payload.get('id')
        if not site_id: return JSONResponse({"error": "ID manquant"}, 400)
        file_path = find_site_file(site_id)
        if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        sections_to_update =['location', 'technical', 'identity', 'contract', 'pricing', 'financials', 'rgpd']
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
        if not sites: return JSONResponse({"success": False, "error": "Fichier illisible."})
        saved = 0
        for s in sites:
            try:
                raw_id = s.get('identity', {}).get('id') or f"GEN_{uuid.uuid4().hex[:8]}"
                s['identity']['id'] = raw_id
                safe_id = get_safe_id(raw_id)
                file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f: existing = json.load(f)
                    if 'contract' in s: existing['contract'].update(s['contract'])
                    if 'pricing' in s: existing['pricing'] = s['pricing']
                    if 'identity' in s: existing['identity'].update(s['identity'])
                    new_tech = s.get('technical', {})
                    old_tech = existing.get('technical', {})
                    for k, v in new_tech.items():
                        if v: old_tech[k] = v
                    existing['technical'] = old_tech
                    new_loc = s.get('location', {})
                    old_loc = existing.get('location', {})
                    for k, v in new_loc.items():
                        if v: old_loc[k] = v
                    existing['location'] = old_loc
                    final_s = existing
                else: final_s = s
                with open(file_path, 'w', encoding='utf-8') as f: json.dump(final_s, f, indent=4, ensure_ascii=False)
                saved += 1
            except Exception as e: pass
        return JSONResponse({"success": True, "imported": len(sites), "saved": saved})
    except ValueError as ve: return JSONResponse({"success": False, "error": str(ve)})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    raw_sites =[]
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for p in files:
        if "master" in p or "market" in p or "m57" in p or "carbon" in p or "rte" in p or "sentinel" in p: continue
        try:
            with open(p, 'r', encoding='utf-8') as f: data = json.load(f)
            if cortex:
                fin = cortex.enrich_site_financials(data)
                data['computed_financials'] = fin
            raw_sites.append(data)
        except: continue
    
    if cortex: analysis = cortex.analyze_portfolio(raw_sites)
    else: analysis = {"global": {}, "green_league": {}}

    fleet_list =[]
    all_cities, all_providers = set(), set()
    for s in raw_sites:
        if "CLI_" in str(s.get('identity',{}).get('id')): continue
        fin = s.get('computed_financials', {})
        contract = s.get('contract', {})
        city = fin.get('meta', {}).get('city', 'Inconnue')
        prov = contract.get('provider', 'Inconnu')
        if city and city != 'Inconnue': all_cities.add(city)
        if prov: all_providers.add(prov)
        
        raw_id = s.get('identity',{}).get('id')
        safe_id = get_safe_id(raw_id)
        pdl_display = contract.get('pdl')
        if not pdl_display or len(str(pdl_display)) < 5: pdl_display = contract.get('pce', '-')
        
        vol_engine = fin.get('volume_mwh', 0)
        vol_router = 0
        if 'kpis' in s and 'volume_mwh' in s['kpis']: vol_router = float(s['kpis']['volume_mwh'])
        final_vol = vol_engine
        if vol_engine == 0 and vol_router > 0: final_vol = vol_router

        final_budget = fin.get('budget_annual', 0)
        if vol_engine == 0 and vol_router > 0:
            pricing = s.get('pricing', {})
            avg_price = 0.20
            for k in['price_kwh', 'prix_kwh', 'price_hph', 'prix_hph']:
                if k in pricing and pricing[k]:
                    try: avg_price = float(pricing[k]); break
                    except: pass
            sub_cost = fin.get('budget_subscription', 0)
            energy_cost = (final_vol * 1000) * avg_price
            final_budget = sub_cost + energy_cost

        fleet_list.append({
            "id": safe_id, "name": fin.get('meta', {}).get('site_label', 'Inconnu'), "city": city, "zip": s.get('location', {}).get('zip_code', ''),
            "volume": final_vol, "energy": "gaz" if fin.get('meta', {}).get('is_gas') else "elec", "segment": contract.get('segment', '-'),
            "provider": prov, "budget": final_budget, "landing": fin.get('landing_forecast', 0), "alert": fin.get('kpis', {}).get('pmc_eur_mwh', 0) > 300,
            "ghost_savings": fin.get('kpis', {}).get('ghost_savings', 0), "power": contract.get('power', 0), "pdl": pdl_display, "surface": s.get('location', {}).get('surface', 0)
        })
    return JSONResponse(json_compliant({
        "fleet": fleet_list, "count": len(fleet_list), "green_league": analysis.get('green_league'), "global_kpis": analysis.get('global'),
        "filters_meta": { "cities": sorted(list(all_cities)), "providers": sorted(list(all_providers)), "segments":["C5", "C4", "C3", "C2", "C1", "T1", "T2", "T3"], "lots":["Lot 1", "Lot 2"] }
    }))

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str, response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    file_path = find_site_file(client_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    
    financials = cortex.enrich_site_financials(data)
    market_ref = get_market_ref()
    market_analysis = cortex.analyze_market_position(financials['kpis']['unit_price_kwh'], market_ref, is_gas = financials['meta']['is_gas'])
    
    if not market_analysis.get('ref_price'):
        is_gas = financials['meta']['is_gas']
        ref_price = market_ref['gaz']['peg_n1'] if is_gas else market_ref['elec']['cal_n1']
        label = "PEG N+1" if is_gas else "CAL N+1"
        market_analysis = { "status": "ANALYSE", "ref_price": ref_price, "details": { "market_base": ref_price, "market_label": label, "trend": "HAUSSIER" } }

    contract = data.get('contract', {})
    pricing = financials['pricing_details']
    display_segment = financials.get('display_overrides', {}).get('segment', contract.get('segment'))

    vol_display = financials['volume_mwh']
    kpis_raw = data.get('kpis', {})
    if vol_display == 0 and 'volume_mwh' in kpis_raw: vol_display = float(kpis_raw['volume_mwh'])

    budget_display = financials['budget_annual']
    volume_multiplier = 1000 if vol_display <= 100000 else 1
    if financials['volume_mwh'] == 0 and vol_display > 0:
        p_data = data.get('pricing', {}); u_price = 0.20
        for k in['price_kwh', 'prix_kwh', 'price_hph', 'prix_hph']:
            if k in p_data and p_data[k]: 
                try: u_price = float(p_data[k]); break
                except: pass
        budget_display = financials.get('budget_subscription', 0) + (vol_display * volume_multiplier * u_price)

    power_details = contract.get('power_details', {})
    if not contract.get('ps_hph'): contract['ps_hph'] = power_details.get('hph') or contract.get('p_hph') or contract.get('P_HPH') or "-"
    if not contract.get('ps_hch'): contract['ps_hch'] = power_details.get('hch') or contract.get('p_hch') or contract.get('P_HCH') or "-"
    if not contract.get('ps_hpe'): contract['ps_hpe'] = power_details.get('hpe') or contract.get('p_hpe') or contract.get('P_HPE') or "-"
    if not contract.get('ps_hce'): contract['ps_hce'] = power_details.get('hce') or contract.get('p_hce') or contract.get('P_HCE') or "-"

    if not financials['meta'].get('provider'): financials['meta']['provider'] = contract.get('provider') or "Inconnu"
    if not display_segment: display_segment = contract.get('segment') or "-"

    response_data = {
        "energy_type": "gaz" if financials['meta']['is_gas'] else "elec", "identity": data.get('identity', {}), "location": data.get('location', {}),
        "technical": data.get('technical', {}), "financials": data.get('financials', {}),
        "contract": {
            "pdl": contract.get('pdl'), "provider": financials['meta'].get('provider'), "segment": display_segment, "start_date": contract.get('start_date'),
            "end_date": contract.get('end_date'), "power": contract.get('power'), "p_max": contract.get('p_max'), "fta": contract.get('fta'),
            "grd": contract.get('grd'), "cja": contract.get('cja'), "profil": contract.get('profil'), "tarif_acheminement": contract.get('tarif_acheminement'),
            "power_details": power_details, "ps_hph": contract.get('ps_hph'), "ps_hch": contract.get('ps_hch'), "ps_hpe": contract.get('ps_hpe'),
            "ps_hce": contract.get('ps_hce'), "consumption_details": contract.get('consumption_details', {})
        },
        "pricing": pricing,
        "kpis": {
            "volume_mwh": vol_display, "budget": budget_display, "pmc": financials['kpis']['pmc_eur_mwh'], "ghost_savings": financials['kpis']['ghost_savings'],
            "talon_kw": kpis_raw.get('talon_kw', 0), "pmax_kw": kpis_raw.get('pmax_kw', 0), "cortex_advice": kpis_raw.get('cortex_advice', "Pas d'analyse disponible."),
            "is_alert": kpis_raw.get('is_alert', False)
        },
        "cortex_insight": { "message": "Analyse CORTEX terminée.", "conseil": "Prix optimisé." if market_analysis['status'] == 'OPTIMISÉ' else "Surveillez ce contrat." },
        "market_analysis": market_analysis, "electricity_price": financials['kpis']['unit_price_kwh']
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
    if vol == 0: fin = cortex.enrich_site_financials(data); vol = fin['volume_mwh']
    if vol == 0: vol = 100 
    typology = data.get('location', {}).get('typologie', '')
    if not typology:
        name = data.get('identity', {}).get('site_name', '').upper()
        if "ECOLE" in name: typology = "ECOLE"
        elif "ECLAIRAGE" in name: typology = "ECLAIRAGE"
        elif "MAIRIE" in name: typology = "ADMIN"
    energy = "gaz" if data.get('contract', {}).get('pce') else "elec"
    res = forecast.generate_3_year_projection(vol, typology, energy)
    res['volume_mwh'] = vol; res['volume_actuel'] = vol 
    return JSONResponse(json_compliant(res))

@app.post("/api/ops/market/update")
async def api_update_market(data: MarketUpdateModel, x_admin_token: str = Header(None)):
    try:
        new_payload = data.dict(); new_payload["updated_at"] = datetime.now().isoformat()
        with open(os.path.join(DATA_DIR, "market_ref.json"), "w") as f: json.dump(new_payload, f, indent=4)
        return JSONResponse({"success": True})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/physics/solar")
async def api_solar_sim(request: Request):
    try:
        payload = await request.json()
        return JSONResponse(physics.simulate_solar_roi(physics.get_coordinates_from_address(payload.get('address', ''))[0], physics.get_coordinates_from_address(payload.get('address', ''))[1], float(payload.get('surface_roof', 0)), float(payload.get('electricity_price', 0.20))))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/api/tools/template/{template_type}")
async def download_template(template_type: str):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    stream = io.BytesIO()
    try:
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if "import_elec" in template_type or "template_csv" == template_type:
                pd.DataFrame(columns=["ENTITE", "NOM_SITE", "ADRESSE_SITE", "CP", "VILLE", "SIRET_SITE", "REF_COPRO", "NAF", "CEE_ELIGIBLE", "GO_PERCENT", "COMPTEUR_PRODUCTION", "PDL", "SEGMENT", "FTA", "GRD", "TYPOLOGIE", "PUISSANCE_SOUSCRITE", "POINTE_MAX", "PS_HPH", "PS_HCH", "PS_HPE", "PS_HCE", "CONSO_HPH", "CONSO_HCH", "CONSO_HPE", "CONSO_HCE", "VOLUME_ANNUEL", "COMMENTAIRE", "DATE_DEBUT", "DATE_FIN", "FOURNISSEUR", "ABONNEMENT", "PRIX_HPH", "PRIX_HCH", "PRIX_HPE", "PRIX_HCE", "TAXES", "SURFACE_M2", "CODE_INSEE", "CHAUFFAGE", "ISOLATION", "REGULATION"]).to_excel(writer, index=False)
            elif "import_gaz" in template_type or "template_csv_gaz" == template_type:
                pd.DataFrame(columns=["ENTITE", "NOM_SITE", "ADRESSE_SITE", "CP", "VILLE", "SIRET_SITE", "NAF", "CEE_ELIGIBLE", "PCE", "CAR_MWH", "CJA_MWH_J", "SEGMENT_GAZ", "PROFIL", "TARIF_ACHEM", "GRD", "DATE_DEBUT", "DATE_FIN", "FOURNISSEUR", "ABONNEMENT", "PRIX_MOLECULE", "TERME_STOCK", "TAXES", "INSEE", "SURFACE_M2", "CHAUFFAGE", "ISOLATION", "REGULATION"]).to_excel(writer, index=False)
            elif "import_patrimoine" in template_type:
                pd.DataFrame(columns=["PDL", "NOM_SITE", "SURFACE_M2", "CHAUFFAGE", "ISOLATION", "REGULATION"]).to_excel(writer, index=False, sheet_name="DATA")
                pd.DataFrame({"CHAMP":["CHAUFFAGE", "ISOLATION", "REGULATION"], "VALEURS_AUTORISEES":["Gaz Condensation, Fioul, Élec Direct, PAC, Réseau Chaleur", "Non Isolé, Double Vitrage, ITE Complète", "Aucune, Thermostat Simple, GTB/GTC, Horloge"]}).to_excel(writer, index=False, sheet_name="MODE_EMPLOI")
            elif "bpu" in template_type:
                pd.DataFrame(columns=["PRIX_HPH", "ABONNEMENT"]).to_excel(writer, index=False)
            else:
                pd.DataFrame(columns=["A", "B"]).to_excel(writer, index=False)
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=Template_{template_type}.xlsx"})
    except:
        stream = io.StringIO(); pd.DataFrame().to_csv(stream)
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
        content = await file.read(); current_sites =[]
        for p in glob.glob(os.path.join(DATA_DIR, "*.json")):
            if any(x in p for x in["master", "m57", "carbon", "rte", "sentinel"]): continue
            try:
                with open(p, 'r', encoding='utf-8') as f: current_sites.append(json.load(f))
            except: continue
        return JSONResponse(json_compliant(cortex.simulate_budget_from_bpu(content, current_sites)))
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    return JSONResponse(json_compliant(cortex.analyze_load_curve(await file.read(), file.filename)))

@app.post("/api/ops/generate_tender")
async def generate_tender(request: Request):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    try:
        body = await request.json(); site_ids = body.get('site_ids',[]); selected_sites =[]
        for sid in site_ids:
            fp = find_site_file(sid)
            if fp:
                with open(fp, 'r', encoding='utf-8') as f: selected_sites.append(json.load(f))
        
        df_dqe = cortex.generate_dqe_structure(selected_sites)
        df_elec = df_dqe[df_dqe['Type'] == 'ELEC']; df_gaz = df_dqe[df_dqe['Type'] == 'GAZ']
        
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if not df_elec.empty: 
                df_elec.to_excel(writer, index=False, sheet_name="DATA_ELEC")
                df_bpu_elec = df_elec[["PDL", "Nom du site", "CP", "Ville", "Segment", "Vol. Annuel"]].copy()
                df_bpu_elec["OFFRE_NOM"] = ""; df_bpu_elec["PRIX_HPH_EUR_KWH"] = ""; df_bpu_elec["ABONNEMENT_EUR_AN"] = ""
                df_bpu_elec.to_excel(writer, index=False, sheet_name="REPONSE_ELEC")
            if not df_gaz.empty: 
                df_gaz.to_excel(writer, index=False, sheet_name="DATA_GAZ")
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=DQE_{datetime.now().strftime('%Y%m%d')}.xlsx"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/ops/ingest", response_class=HTMLResponse)
async def ops_ingest_page(request: Request, user = Depends(get_current_user)):
    if not user or user.get("role") not in["ADMIN", "OPS_TECH"]: return RedirectResponse(url="/login")
    try:
        if 'router' not in globals() and 'router' not in locals(): raise Exception("Le module Router n'est pas chargé.")
        return templates.TemplateResponse("ops_ingest.html", {"request": request, "api_status": router.get_api_status()})
    except Exception as e: return HTMLResponse(content=f"<h1>Erreur Système</h1><p>{str(e)}</p>", status_code=500)

@app.post("/api/ingest/upload")
async def ingest_files_mass(files: List[UploadFile] = File(...)):
    report =[]
    for file in files:
        try:
            report.append(router.analyze_file_stream(await file.read(), file.filename))
        except Exception as e: report.append({"filename": file.filename, "status": "ERROR", "message": str(e), "pdl": "ERR"})
    return JSONResponse(content={"report": report})

@app.post("/api/ops/market/simulate_strategy")
async def api_simulate_strategy(payload: StrategyRequest):
    file_path = find_site_file(payload.site_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    kpis = data.get('kpis', {})
    pmax = float(kpis.get('pmax_kw', 100)); talon = float(kpis.get('talon_kw', 20))
    load_curve =[talon + (pmax - talon) * 0.8 if 6 <= h <= 20 else talon for h in range(24)]
    return JSONResponse(json_compliant(market.valoriser_strategie(load_curve, payload.bloc_kw)))

@app.post("/api/ops/aggregate")
async def api_aggregate_sites(payload: AggregationRequest):
    try:
        csv_content = aggregator.aggregate_sites(payload.site_ids, payload.years)
        if not csv_content: return JSONResponse({"error": "Aucune donnée générée"}, 400)
        response = Response(content=csv_content, media_type="text/csv")
        response.headers["Content-Disposition"] = f"attachment; filename=SGE_AGGREGAT_{len(payload.site_ids)}SITES.csv"
        return response
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.post("/api/finance/upload")
async def api_finance_upload(file: UploadFile = File(...), site_id: str = Form(...)):
    try:
        content = await file.read()
        parsed = finance.parse_invoice(content, file.filename)
        if parsed.get("status") == "ERROR": return JSONResponse(parsed, status_code=400)
        file_path = find_site_file(site_id)
        site_data = {}
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f: site_data = json.load(f)
        return JSONResponse(json_compliant(finance.audit_invoice(parsed, site_data)))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

# ==========================================
# GESTION DES VUES / PAGES (ROUTING HTML)
# ==========================================
@app.get("/ops_nexus", response_class=HTMLResponse)
async def view_ops_nexus(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("ops_nexus.html", {"request": request})

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
                return templates.TemplateResponse("industry.html", {"request": request, "data": { "client_name": data.get('identity', {}).get('site_name', 'Client'), "site_type": "Industrie - Réel", "puissance_souscrite": data.get('contract', {}).get('power', 0), "talon_moyen": 0, "cos_phi": 0.95, "depassements": 0, "kpis": fin.get('kpis', {}) }})
    return templates.TemplateResponse("industry.html", {"request": request, "data": {"client_name": "USINE DÉMO", "site_type": "DÉMO", "puissance_souscrite": 0, "kpis": {}}})

@app.get("/syndic", response_class=HTMLResponse)
async def view_syndic(request: Request, id: Optional[str] = None, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    if id:
        file_path = find_site_file(id)
        if file_path:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                fin = cortex.enrich_site_financials(data)
                return templates.TemplateResponse("syndic.html", {"request": request, "data": { "client_name": data.get('identity', {}).get('site_name', 'Résidence'), "lots": 0, "chaufferie": "Chauffage Collectif", "dju_n": 2100, "dju_n_1": 2400, "conso_n": fin.get('volume_mwh', 0) * 1000, "conso_n_1": (fin.get('volume_mwh', 0) * 1000) * 1.1 }})
    return templates.TemplateResponse("syndic.html", {"request": request, "data": {"client_name": "RÉSIDENCE DÉMO", "dju_n": 2100, "dju_n_1": 2400, "conso_n": 450000}})

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

@app.get("/finance", response_class=HTMLResponse)
async def view_finance(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard_finance.html", {"request": request, "user": user})

@app.get("/api/finance/landing/{site_id}")
async def api_finance_landing(site_id: str):
    file_path = find_site_file(site_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    try:
        with open(file_path, 'r', encoding='utf-8') as f: site_data = json.load(f)
        return JSONResponse(json_compliant(finance.simulate_landing(site_data)))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/")
async def view_landing(request: Request): return templates.TemplateResponse("index.html", {"request": request})

@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/processing")
async def view_processing(request: Request): return templates.TemplateResponse("processing.html", {"request": request})

@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str, user = Depends(get_current_user)):
    if not user and profile not in["demo"]: return RedirectResponse(url="/login")
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
    return templates.TemplateResponse("settings_partner.html", {"request": request})

@app.get("/ops/market")
async def view_ops_market(request: Request): return templates.TemplateResponse("ops_market.html", {"request": request})

@app.get("/deal_desk", response_class=HTMLResponse)
async def view_deal_desk(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("deal_desk.html", {"request": request})

@app.get("/subventions", response_class=HTMLResponse)
async def view_subventions(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("subventions.html", {"request": request})

@app.get("/immo", response_class=HTMLResponse)
async def view_immo(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("immo.html", {"request": request})

@app.get("/sniper", response_class=HTMLResponse)
async def view_sniper(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("sniper.html", {"request": request})

@app.get("/gridmap", response_class=HTMLResponse)
async def view_gridmap(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    return templates.TemplateResponse("gridmap.html", {"request": request})

@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str, user = Depends(get_current_user)):
    PUBLIC_PAGES =["index.html", "onboarding.html", "processing.html", "login.html", "solutions.html", "cortex.html", "vitality.html", "connectivite.html", "audit_premium.html", "store.html", "ethique.html", "fournisseurs.html", "etudes-de-cas.html", "modele_economique.html"]
    if any(x in page_name for x in[".js", ".css", ".png", ".jpg"]): return JSONResponse({}, 404)
    target_file = page_name if page_name.endswith(".html") else f"{page_name}.html"
    if target_file not in PUBLIC_PAGES and not user: return RedirectResponse(url="/login")
    if os.path.exists(os.path.join(TEMPLATE_DIR, target_file)): return templates.TemplateResponse(target_file, {"request": request})
    if os.path.exists(os.path.join(TEMPLATE_DIR, "cor", target_file)): return templates.TemplateResponse(f"cor/{target_file}", {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in["static", "assets", "favicon"]): return JSONResponse({}, 404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
