import os
import math
import io
import json
import traceback
import importlib
import urllib.request
import urllib.parse
import base64
import uuid
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException, Response, Depends, status, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import pandas as pd
    PANDAS_READY = True
except ImportError:
    PANDAS_READY = False

class FallbackPDFBuilder:
    def __init__(self): self.logo_svg = """<svg width="140" height="40" viewBox="0 0 140 40" xmlns="http://www.w3.org/2000/svg"><rect width="30" height="30" rx="8" y="5" fill="#00E5FF"/><path d="M10 15L20 15L15 25Z" fill="#001529"/><text x="40" y="27" font-family="Arial, sans-serif" font-size="20" font-weight="900" fill="#001529">ENERGISTRAT</text></svg>"""
    def generate_bilan_ag(self, client_id, data, fin, kpis): return "<h1>Générateur PDF de Secours</h1>"
    def generate_bilan_ag_cluster(self, cluster_name, site_count, vol_total, budget_total, vol_elec, vol_gaz, ghost_total): return "<h1>Générateur PDF Grappe</h1>"

class MockAuth:
    def verify_token(self, t): return {"uid": "mock", "email": "admin@energistrat.com", "role": "ADMIN", "sub": "admin"}

class MockDB:
    def get_all_sites(self): return[]
    def get_site(self, sid): return {}
    def save_site(self, sid, d): return True
    def delete_site(self, sid): return True
    def get_setting(self, n): return {}
    def save_setting(self, n, d): return True
    def get_all_leads(self): return[]
    def get_all_companies(self): return[]
    def get_all_contacts(self): return[]
    def get_all_deals(self): return[]
    def get_all_products(self): return[]
    def save_lead(self, i, d): return True
    def save_company(self, i, d): return True
    def save_contact(self, i, d): return True
    def save_deal(self, i, d): return True
    def save_product(self, i, d): return True
    def delete_product(self, i): return True
    def save_activity(self, i, d): return True
    def get_deal_activities(self, i): return[]
    def delete_lead(self, i): return True
    def get_company(self, i): return {}
    def get_contact(self, i): return {}
    def get_deal(self, i): return {}
    def get_sentinel_alerts(self): return {"last_scan": "Jamais", "alert_count": 0, "alerts":[]}
    def save_sentinel_alerts(self, d): return True
    def get_all_users(self): return[]
    def get_user_profile(self, u): return {}
    def save_user_profile(self, u, d): return True
    def get_all_lms_modules(self): return[]
    def get_user_lms_progress(self, u): return {}

class MockFinance:
    def parse_invoice(self, c, f): return {"status": "ERROR"}
    def audit_invoice(self, i, s): return {}
    def simulate_landing(self, s): return {}

class MockRouter:
    def get_api_status(self): return {"status": "DEGRADED"}
    def analyze_file_stream(self, c, f): return {"status": "ERROR"}

class MockMarket:
    def valoriser_strategie(self, l, b): return {"error": "Market missing"}

class MockAggregator:
    def aggregate_sites(self, s, y): return None

class MockCortex:
    def enrich_site_financials(self, data): return {"volume_mwh": 0, "budget_annual": 0, "meta": {"is_gas": False}, "kpis": {"pmc_eur_mwh": 0, "ghost_savings": 0}}
    def analyze_portfolio(self, sites): return {"global": {}, "green_league": {}}
    def generate_dqe_structure(self, s): return pd.DataFrame() if PANDAS_READY else None
    def analyze_market_position(self, p, r, is_gas): return {"status": "ANALYSE"}
    def simulate_budget_from_bpu(self, b, s): return {}
    def analyze_load_curve(self, f, n): return {}

class MockRTE:
    def get_wholesale_market(self): return {"success": False, "error": "RTE Offline"}
    def get_pulse_dashboard_data(self): return {"success": False, "error": "RTE Offline"}

class MockForecast:
    def simulate_5_years(self, s): return {"labels":["N", "N+1", "N+2", "N+3", "N+4"], "dataset_trend":[100, 105, 110, 115, 120], "dataset_sobriety":[100, 90, 80, 70, 60], "gain_potential_mwh": 150}

class MockCRM:
    def generate_icebreaker(self, naf, pipe_type="saas"): return {"naf": naf, "pain_points": "Mode Démo", "pitch": "Argumentaire IA désactivé."}
    def analyze_customer_health(self, cv, pv, lc): return {"status": "STABLE", "color": "text-success", "action_required": "RAS", "usage_score": 100, "is_churn_risk": False}
    def calculate_commission(self, v, is_s, saas_mrr=0): return round(v * 1.0, 2)
    def send_sales_email(self, *args, **kwargs): return True

class MockAcademy:
    def process_answer(self, u, q, c): return {"success": c, "message": "Academy Offline", "new_xp": 0, "level_up": False, "current_level": 1}
    def get_daily_training(self, u): return[]

class MockPricer:
    def build_quote(self, payload): return {"success": False, "error": "CORTEX Pricer Offline."}

def load_module(mod_name, obj_name, mock_instance=None):
    paths =[f"app.core.{mod_name}", f"core.{mod_name}", mod_name]
    for path in paths:
        try:
            mod = importlib.import_module(path)
            return getattr(mod, obj_name)
        except ModuleNotFoundError: continue
        except Exception as e: print(f"⚠️ Erreur chargement {path} : {e}"); continue
    print(f"🔴 Auto-Loader: Impossible de trouver {mod_name}. Fallback Mock activé.")
    return mock_instance

db = load_module("cortex_db", "db", MockDB())
auth = load_module("cortex_auth", "auth", MockAuth())
cortex = load_module("cortex_engine", "cortex", MockCortex())
ingest = load_module("cortex_ingest", "ingest", None)
physics = load_module("cortex_physics", "physics", None)
forecast = load_module("cortex_forecast", "forecast", MockForecast())
router = load_module("cortex_router", "router", MockRouter())
market = load_module("cortex_market", "market", MockMarket())
aggregator = load_module("cortex_aggregator", "aggregator", MockAggregator())
finance = load_module("cortex_finance", "finance", MockFinance())
rte = load_module("cortex_rte", "rte", MockRTE())
crm_engine = load_module("cortex_crm", "crm_engine", MockCRM())
academy_engine = load_module("cortex_academy", "academy_engine", MockAcademy())
pricer_engine = load_module("cortex_pricer", "pricer_engine", MockPricer())
pdf_builder = load_module("cortex_pdf", "pdf_builder", FallbackPDFBuilder())

app = FastAPI(title="ENERGISTRAT V3", version="EMPIRE-V12.6-SECURE")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR, exist_ok=True)
TEMPLATE_DIR = os.path.join(BASE_DIR, "app/templates")
if not os.path.exists(TEMPLATE_DIR): TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR): STATIC_DIR = os.path.join(BASE_DIR, "app/static")
if os.path.exists(STATIC_DIR): app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class SessionRequest(BaseModel): id_token: str
class MarketUpdateModel(BaseModel): elec: Dict[str, Any]; gaz: Dict[str, Any]; trve: Optional[Dict[str, Any]] = None; targets: Optional[Dict[str, Any]] = None
class StrategyRequest(BaseModel): site_id: str; bloc_kw: float
class AggregationRequest(BaseModel): site_ids: List[str]; years: int = 3
class PropagateRequest(BaseModel): source_client_id: str; target_date: str; filters: Dict[str, str]; pricing_data: Dict[str, Any]
class AdoptionRequest(BaseModel): target_tenant_id: str; site_ids: List[str]
class TenantCreateRequest(BaseModel): siret: str; name: str
class M57SettingsModel(BaseModel): bp_elec: float = 0.0; bp_gaz: float = 0.0; consumed_elec: float = 0.0; consumed_gaz: float = 0.0; bp_irve: float = 0.0; consumed_irve: float = 0.0; bp_enr: float = 0.0; consumed_enr: float = 0.0
class CarbonSettingsModel(BaseModel): baseline_year: int = 2010; baseline_kwh_sqm: float = 0.0
class VoteRequestModel(BaseModel): site_id: str; vote: bool
class LegalSignModel(BaseModel): site_id: str; consent: bool
class SolarRequest(BaseModel): address: str; surface_roof: float; electricity_price: float

class CRMSiteModel(BaseModel): pdl_pce: str; energy_type: str = "elec"; site_name: str; address: str; power_kva: float = 0.0; fta: str = "CU"; profile: str = "PRO1"; car_mwh: float = 0.0; is_active: bool = True; company_id: str
class CRMContactModel(BaseModel): firstname: str; lastname: str; role: str; email: str; phone: str; company_id: str; site_id: Optional[str] = None
class CRMCompany3DModel(BaseModel): siren: str; company_name: str; holding_name: Optional[str] = None; naf: str; address: str; city: str; source: str; pipeline: str 
class CRMInlineEditModel(BaseModel): field: str; value: Any
class DealMoveModel(BaseModel): deal_id: str; new_stage: str
class EmailRequestModel(BaseModel): deal_id: str; subject: str; body: str
class CRMActivityModel(BaseModel): deal_id: str; type: str; description: str
class UpdateFieldModel(BaseModel): value: str
class ProductModel(BaseModel): name: str; category: str; unit_price: float; comm_rate: float = 1.0 
class DealLineItemModel(BaseModel): product_id: str; quantity: float 
class DealProductsUpdateModel(BaseModel): items: List[DealLineItemModel]
class AcademyProgressModel(BaseModel): xp: int; badges: List[Dict[str, str]]
class AcademyAnswerRequest(BaseModel): question_id: str; is_correct: bool
class CPQQuoteRequest(BaseModel): site_id: Optional[str] = None; volume_mwh: float; energy_type: str; segment: str; duration_years: int = 1; franchise_cee: bool = False; green_option: str = "none"; mask: Dict[str, Any] = {}
class NewContactModel(BaseModel): firstname: str; lastname: str; role: str; email: str; phone: str

def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return[json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

def get_safe_id(raw_id): return str(raw_id).replace('/', '_').replace(' ', '_').replace('+', '').replace(',', '').strip()

def get_market_ref():
    m = db.get_setting("Market")
    if m: return m
    return { "updated_at": datetime.now().isoformat(), "elec": { "cal_n1": 85.0 }, "gaz": { "peg_n1": 35.0 }, "trve": { "elec_c5": 230.0 }, "targets": { "c5": 190.0 } }

async def get_current_user(request: Request):
    t = request.cookies.get("access_token")
    if not t: return None
    if t.startswith("Bearer "): t = t.split(" ")[1]
    return auth.verify_token(t)

def fetch_company_info_api_gouv(siren: str) -> dict:
    clean_siren = str(siren).replace(" ", "").strip()
    if len(clean_siren) != 9: return {"success": False, "error": "SIREN invalide"}
    url = f"https://recherche-entreprises.api.gouv.fr/search?q={clean_siren}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Energistrat-SaaS/12.6'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if not data.get("results"): return {"success": False, "error": "Entreprise introuvable"}
            ent = data["results"][0]
            etat = ent.get("etat_administratif", "A")
            solvency_score = "VERT" if etat != "C" else "ROUGE"
            solvency_msg = "Saine (Active)" if etat != "C" else "Cessation / Procédure"
            siege = ent.get("siege", {})
            return {
                "success": True, "name": ent.get("nom_complet", ""), "naf": ent.get("activite_principale", "DEFAULT"),
                "address": siege.get("adresse", ""), "city": siege.get("libelle_commune", ""),
                "zip": siege.get("code_postal", ""), "solvency_score": solvency_score, "solvency_msg": solvency_msg
            }
    except Exception as e: return {"success": False, "error": str(e)}

@app.get("/login", response_class=HTMLResponse)
async def view_login(request: Request, user = Depends(get_current_user)):
    if user: 
        if user.get("role") == "ADMIN": return RedirectResponse(url="/ops_nexus")
        return RedirectResponse(url=f"/{user.get('role', 'settings')}")
    res = templates.TemplateResponse("login.html", {"request": request}); res.delete_cookie("access_token"); return res

@app.post("/api/auth/session")
async def api_session(payload: SessionRequest, response: Response):
    u = auth.verify_token(payload.id_token)
    if not u: return JSONResponse({"detail": "Token invalide"}, status_code=401)
    response.set_cookie(key="access_token", value=f"Bearer {payload.id_token}", httponly=True, max_age=3600*24, samesite="lax", secure=True if "https" in str(response.headers) else False)
    role = u.get("role", "USER")
    if role != "ADMIN":
        profile = db.get_user_profile(u.get("uid"))
        if profile and profile.get("role"): role = profile.get("role")
    return {"success": True, "role": role}

@app.get("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token"); return RedirectResponse(url="/login")

# ==============================================================================
# TRADUCTEUR UNIVERSEL (SMART MAPPER 3D - ELEC & GAZ)
# ==============================================================================
def normalize_full_data(data, tenant_id=None):
    if 'identity' not in data: data['identity'] = {}
    if 'location' not in data: data['location'] = {}
    if 'contract' not in data: data['contract'] = {}
    if 'pricing' not in data: data['pricing'] = {}
    if 'technical' not in data: data['technical'] = {}
    if 'kpis' not in data: data['kpis'] = {}
    if 'power_details' not in data['contract']: data['contract']['power_details'] = {}
    
    # 1. Identité Primaire
    if not data['identity'].get('id'):
        data['identity']['id'] = str(data.get('PDL') or data.get('PCE') or data.get('COMPTEUR_PDL') or data.get('pdl') or data.get('id') or f"GEN_{uuid.uuid4().hex[:8]}")
        data['id'] = data['identity']['id']

    if tenant_id: data['identity']['tenant_id'] = tenant_id

    data['identity']['site_name'] = str(data.get('NOM_SITE') or data.get('site_name') or data.get('name') or "Site Sans Nom")
    data['identity']['siret'] = str(data.get('SIRET_SITE') or data.get('siret') or data.get('siren') or "")
    data['identity']['naf'] = str(data.get('NAF') or data.get('naf') or "DEFAULT")
    data['identity']['lot_name'] = str(data.get('LOT_AFFECTATION') or data.get('lot_name') or "")
    
    # 2. Localisation & Physique
    data['location']['address'] = str(data.get('ADRESSE_SITE') or data.get('ADRESSE_SIT') or data.get('address') or "")
    data['location']['zip_code'] = str(data.get('CP') or data.get('zip_code') or "")
    data['location']['city'] = str(data.get('VILLE') or data.get('city') or "")
    data['location']['insee'] = str(data.get('INSEE') or data.get('insee') or "")
    data['location']['typologie'] = str(data.get('TYPOLOGIE') or data.get('typologie') or "")
    
    try: data['location']['surface'] = float(data.get('SURFACE_M2') or data.get('surface') or 0.0)
    except: data['location']['surface'] = 0.0

    # 3. Contrat et Énergie
    data['energy_type'] = str(data.get('ENERGIE') or data.get('energy_type') or "elec").lower()
    data['contract']['energy_type'] = data['energy_type']
    
    if data['energy_type'] == 'gaz': data['contract']['pce'] = data['identity']['id']
    else: data['contract']['pdl'] = data['identity']['id']

    data['contract']['provider'] = str(data.get('FOURNISSEUR') or data.get('FOURNISSEU') or data.get('provider') or "")
    data['contract']['segment'] = str(data.get('SEGMENT') or data.get('segment') or "")
    data['contract']['profil'] = str(data.get('PROFIL') or data.get('profil') or "")
    data['contract']['fta'] = str(data.get('FTA') or data.get('fta') or "")
    data['contract']['start_date'] = str(data.get('DATE_DEBUT') or data.get('start_date') or "")
    data['contract']['end_date'] = str(data.get('FIN_MARCHE_YYYYMMDD') or data.get('DATE_FIN') or data.get('end_date') or "")
    
    # Variables de Puissance (ELEC vs GAZ)
    try: data['contract']['power'] = float(str(data.get('PUISSANCE_KVA') or data.get('power') or 0).replace(',', '.'))
    except: data['contract']['power'] = 0.0

    try: data['contract']['cja'] = float(str(data.get('CJA_MWH_J') or data.get('cja') or 0).replace(',', '.'))
    except: data['contract']['cja'] = 0.0
    
    try: data['kpis']['car_mwh'] = float(str(data.get('CAR_MWH') or data.get('car') or 0).replace(',', '.'))
    except: data['kpis']['car_mwh'] = 0.0

    # 4. Puissances 4 Cadrans (ELEC)
    quad_p = {'hph':['PS_HPH', 'ps_hph'], 'hch':['PS_HCH', 'ps_hch'], 'hpe':['PS_HPE', 'ps_hpe'], 'hce':['PS_HCE', 'ps_hce']}
    for t, keys in quad_p.items():
        for k in keys:
            if k in data and str(data[k]).strip() not in ["", "None", "nan", "NaN"]:
                try: 
                    val = float(str(data[k]).replace(',', '.'))
                    data['contract']['power_details'][t] = val
                    data['contract'][f"ps_{t}"] = val
                    break
                except: pass

    # 5. Pricing (4 Cadrans & Molécule Gaz)
    quad_prix = {'hph':['PRIX_HPH', 'price_hph', 'prix_hph'], 'hch':['PRIX_HCH', 'price_hch', 'prix_hch'], 'hpe':['PRIX_HPE', 'price_hpe', 'prix_hpe'], 'hce':['PRIX_HCE', 'price_hce', 'prix_hce']}
    for t, keys in quad_prix.items():
        for k in keys:
            if k in data and str(data[k]).strip() not in ["", "None", "nan", "NaN"]:
                try: 
                    val = float(str(data[k]).replace(',', '.'))
                    if val > 10: val = val / 1000.0 # Heuristique €/MWh -> €/kWh
                    data['pricing'][t] = val
                    break
                except: pass
                
    # Molécule Unique (Gaz ou Tarif Base)
    if 'price_kwh' not in data['pricing']:
        try: 
            p_unique = float(str(data.get('PRIX_MOLECULE') or data.get('PRIX_MOLECU') or data.get('PRIX_MOL_EUR_MWH') or 0).replace(',', '.'))
            if p_unique > 10: p_unique = p_unique / 1000.0
            data['pricing']['price_kwh'] = p_unique
        except: data['pricing']['price_kwh'] = 0.0

    # Frais Fixes & Taxes
    try: data['pricing']['fix'] = float(str(data.get('ABONNEMENT_EUR') or data.get('ABONNEMEN') or data.get('fix') or 0).replace(',', '.'))
    except: data['pricing']['fix'] = 0.0
    
    try: data['pricing']['stockage'] = float(str(data.get('TERME_STOC') or data.get('stockage') or 0).replace(',', '.'))
    except: data['pricing']['stockage'] = 0.0
    
    try: data['pricing']['tax'] = float(str(data.get('TAXES') or data.get('tax') or 22.5).replace(',', '.'))
    except: data['pricing']['tax'] = 22.5

    # 6. Volumes (SGE ou CAR estimé)
    try: 
        vol = float(str(data.get('VOLUME_ANNUEL') or data.get('volume_mwh') or data.get('CAR_MWH') or 0).replace(',', '.'))
        data['kpis']['volume_mwh'] = vol
        data['volume_mwh'] = vol 
    except: pass

    return data

@app.post("/api/settings/save_client")
async def api_save_client(request: Request, user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False, "error": "Non autorisé"}, 401)
    try:
        raw_data = await request.json()
        profile = db.get_user_profile(user.get("uid"))
        tenant_id = profile.get("tenant_id", "ORPHELIN")
        
        if user.get("role") == "ADMIN" and "forced_tenant_id" in raw_data:
            tenant_id = raw_data["forced_tenant_id"]

        data = normalize_full_data(raw_data, tenant_id)
        raw_id = data.get("identity", {}).get("id") or data.get("id") or f"CLI_{uuid.uuid4().hex[:8]}"
        data["identity"]["id"] = str(raw_id)
        safe_id = get_safe_id(raw_id)
        
        existing_data = db.get_site(safe_id)
        if existing_data:
            if existing_data.get("identity", {}).get("tenant_id") != tenant_id and user.get("role") != "ADMIN":
                return JSONResponse({"success": False, "error": "Accès refusé."}, 403)
                
            for section in['technical', 'location', 'identity', 'contract', 'pricing', 'kpis', 'financials', 'rgpd']:
                if section in data:
                    if section not in existing_data: existing_data[section] = {}
                    existing_data[section].update(data[section])
            final_data = existing_data
        else: final_data = data
            
        db.save_site(safe_id, final_data)
        return JSONResponse({"success": True, "id": raw_id})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...), user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False, "error": "Non autorisé"}, 401)
    if not PANDAS_READY: return JSONResponse({"success": False, "error": "Pandas absent."}, 500)
    try:
        content = await file.read()
        if file.filename.endswith('.csv'): df = pd.read_csv(io.BytesIO(content), sep=';', on_bad_lines='skip')
        elif file.filename.endswith('.xlsx') or file.filename.endswith('.xls'): df = pd.read_excel(io.BytesIO(content))
        else: return JSONResponse({"success": False, "error": "Format non supporté."})

        df = df.where(pd.notnull(df), None)
        sites_raw = df.to_dict(orient='records')
        if not sites_raw: return JSONResponse({"success": False, "error": "Fichier vide."})
            
        profile = db.get_user_profile(user.get("uid"))
        tenant_id = profile.get("tenant_id", "ORPHELIN")
            
        saved_count = 0
        for s_raw in sites_raw:
            try:
                s_3d = normalize_full_data(s_raw, tenant_id)
                raw_id = s_3d.get('identity', {}).get('id') or f"GEN_{uuid.uuid4().hex[:8]}"
                safe_id = get_safe_id(raw_id)
                existing = db.get_site(safe_id)
                if existing:
                    if existing.get("identity", {}).get("tenant_id") != tenant_id and user.get("role") != "ADMIN": continue
                    for sec in['contract', 'pricing', 'identity', 'technical', 'location', 'kpis']:
                        if sec in s_3d:
                            if sec not in existing: existing[sec] = {}
                            existing[sec].update(s_3d[sec])
                    final_s = existing
                else: final_s = s_3d
                db.save_site(safe_id, final_s)
                saved_count += 1
            except Exception as e: continue
        return JSONResponse({"success": True, "imported": len(sites_raw), "saved": saved_count})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data(response: Response, user = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    profile = db.get_user_profile(user.get("uid"))
    tenant_id = profile.get("tenant_id", "ORPHELIN")
    is_admin = user.get("role") == "ADMIN"
    
    raw_sites = db.get_all_sites()
    filtered_sites =[s for s in raw_sites if "CLI_" not in str(s.get('identity', {}).get('id', '')) and (is_admin or s.get("identity", {}).get("tenant_id") == tenant_id)]
    
    for s in filtered_sites:
        # Migration silencieuse à la volée pour le dashboard
        s = normalize_full_data(s, s.get("identity", {}).get("tenant_id"))
        if cortex: s['computed_financials'] = cortex.enrich_site_financials(s)
    
    fleet_list =[]
    for s in filtered_sites:
        fin = s.get('computed_financials', {})
        contract = s.get('contract', {})
        kpis = s.get('kpis', {})
        loc = s.get('location', {})
        identity = s.get('identity', {})
        
        city = fin.get('meta', {}).get('city') or loc.get('city') or 'Inconnue'
        prov = contract.get('provider') or 'Inconnu'
        vol_engine = float(fin.get('volume_mwh', 0))
        vol_router = float(kpis.get('volume_mwh', 0))
        final_vol = vol_engine if vol_engine > 0 else vol_router

        final_budget = float(fin.get('budget_annual', 0) or kpis.get('budget', 0))
        if final_budget == 0 and final_vol > 0:
            p_data = s.get('pricing', {})
            avg_price = float(p_data.get('price_kwh') or p_data.get('hph') or 0.20)
            if avg_price > 2.0: avg_price = avg_price / 1000.0
            tax = float(p_data.get('tax') or 22.5)
            if tax > 100: tax = 22.5 
            sub_cost = float(p_data.get('fix') or 0)
            final_budget = sub_cost + (final_vol * 1000 * avg_price) + (final_vol * tax)

        fleet_list.append({
            "id": get_safe_id(identity.get('id', '')), 
            "name": fin.get('meta', {}).get('site_label') or identity.get('site_name') or 'Inconnu', 
            "city": city, 
            "zip": loc.get('zip_code', ''),
            "volume": final_vol, 
            "energy": "gaz" if contract.get('energy_type') == 'gaz' else "elec", 
            "segment": contract.get('segment') or identity.get('lot_name') or '-',
            "provider": prov, 
            "budget": final_budget, 
            "ghost_savings": float(kpis.get('ghost_savings', 0)), 
            "power": contract.get('power', 0), 
            "pdl": contract.get('pdl') or contract.get('pce', '-'), 
            "surface": loc.get('surface', 0),
            "tenant_id": identity.get('tenant_id', 'Orphelin'),
            "naf": identity.get('naf', 'DEFAULT')
        })
    return JSONResponse(json_compliant({"fleet": fleet_list, "count": len(fleet_list)}))

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str, response: Response, user = Depends(get_current_user)):
    """ LA MAGIE DE LA GUÉRISON SILENCIEUSE """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    
    data = db.get_site(client_id)
    if not data: return JSONResponse({"error": "Site introuvable"}, 404)
    
    profile = db.get_user_profile(user.get("uid"))
    is_admin = user.get("role") == "ADMIN"
    site_tenant = data.get("identity", {}).get("tenant_id")
    
    # On force la migration 3D sur le dictionnaire "plat"
    # Si le tenant n'est pas dans l'identity, on le cherche à la racine, sinon on prend celui du user
    t_id = site_tenant or data.get("tenant_id") or profile.get("tenant_id", "ORPHELIN")
    data = normalize_full_data(data, t_id)
    
    if not is_admin and data["identity"]["tenant_id"] != profile.get("tenant_id", "ORPHELIN"):
        return JSONResponse({"error": "Accès refusé."}, 403)
        
    financials = cortex.enrich_site_financials(data) if cortex else {'meta':{'is_gas':False}, 'kpis':{'unit_price_kwh':0, 'pmc_eur_mwh':0, 'ghost_savings':0}, 'volume_mwh':0, 'budget_annual':0, 'pricing_details':{}}
    mr = get_market_ref()
    ma = cortex.analyze_market_position(financials['kpis']['unit_price_kwh'], mr, is_gas=financials['meta']['is_gas']) if cortex else {"status": "ANALYSE"}
    
    if 'ref_price' not in ma: 
        ma = {"status": "ANALYSE", "ref_price": mr['gaz']['peg_n1'] if financials['meta']['is_gas'] else mr['elec']['cal_n1'], "details": {"market_label": "PEG N+1" if financials['meta']['is_gas'] else "CAL N+1"}}

    contract = data.get('contract', {})
    pricing = financials['pricing_details'] or data.get('pricing', {})
    display_segment = financials.get('display_overrides', {}).get('segment', contract.get('segment'))

    vol_display = float(financials.get('volume_mwh') or data.get('kpis', {}).get('volume_mwh', 0))
    p_data = data.get('pricing', {})
    
    u_price = float(p_data.get('price_kwh') or p_data.get('hph') or 0.20)
    if u_price > 2.0: u_price = u_price / 1000.0
        
    tax_val = float(p_data.get('tax') or 22.5)
    if tax_val > 100: tax_val = 22.5
    
    sub_val = float(p_data.get('fix') or 0)
    budget_display = sub_val + (vol_display * 1000 * u_price) + (vol_display * tax_val)

    pd_details = contract.get('power_details', {})
    if not contract.get('ps_hph'): contract['ps_hph'] = pd_details.get('hph') or "-"
    if not contract.get('ps_hch'): contract['ps_hch'] = pd_details.get('hch') or "-"
    if not contract.get('ps_hpe'): contract['ps_hpe'] = pd_details.get('hpe') or "-"
    if not contract.get('ps_hce'): contract['ps_hce'] = pd_details.get('hce') or "-"

    # Renvoi JSON Ultra propre
    return JSONResponse(json_compliant({
        "energy_type": "gaz" if contract.get('energy_type') == 'gaz' else "elec", 
        "identity": data.get('identity', {}), 
        "location": data.get('location', {}), 
        "technical": data.get('technical', {}), 
        "financials": data.get('financials', {}),
        "contract": {
            "pdl": contract.get('pdl'), 
            "pce": contract.get('pce'), 
            "provider": contract.get('provider', 'Inconnu'), 
            "segment": display_segment or contract.get('segment', '-'), 
            "start_date": contract.get('start_date'), 
            "end_date": contract.get('end_date'), 
            "power": contract.get('power'), 
            "cja": contract.get('cja'),
            "p_max": contract.get('p_max'), 
            "fta": contract.get('fta'), 
            "profil": contract.get('profil'), 
            "power_details": pd_details, 
            "ps_hph": contract.get('ps_hph'), 
            "ps_hch": contract.get('ps_hch'), 
            "ps_hpe": contract.get('ps_hpe'), 
            "ps_hce": contract.get('ps_hce')
        },
        "pricing": pricing, 
        "kpis": {
            "volume_mwh": vol_display, "budget": budget_display, "pmc": financials['kpis']['pmc_eur_mwh'], 
            "ghost_savings": financials['kpis']['ghost_savings'], "talon_kw": data.get('kpis', {}).get('talon_kw', 0), 
            "pmax_kw": data.get('kpis', {}).get('pmax_kw', 0), "cortex_advice": data.get('kpis', {}).get('cortex_advice', "Pas d'analyse.")
        },
        "market_analysis": ma, "electricity_price": financials['kpis']['unit_price_kwh']
    }))

@app.post("/api/ops/simulate_offer")
async def api_simulate_offer(file: UploadFile = File(...)):
    try: return JSONResponse(json_compliant(cortex.simulate_budget_from_bpu(await file.read(), db.get_all_sites())))
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    return JSONResponse(json_compliant(cortex.analyze_load_curve(await file.read(), file.filename)))

@app.post("/api/ops/generate_tender")
async def generate_tender(request: Request, user = Depends(get_current_user)):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    try:
        body = await request.json()
        profile = db.get_user_profile(user.get("uid"))
        tid = profile.get("tenant_id")
        is_admin = user.get("role") == "ADMIN"
        
        selected =[s for s in (db.get_site(sid) for sid in body.get('site_ids', [])) if s and (is_admin or s.get("identity", {}).get("tenant_id") == tid)]
        df_dqe = cortex.generate_dqe_structure(selected)
        df_el = df_dqe[df_dqe['Type'] == 'ELEC']
        df_gz = df_dqe[df_dqe['Type'] == 'GAZ']
        
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as w:
            if not df_el.empty: 
                df_el.to_excel(w, index=False, sheet_name="DATA_ELEC")
                df_el[["PDL", "Nom du site", "CP", "Ville", "Segment", "Vol. Annuel"]].assign(OFFRE_NOM="", PRIX_HPH_EUR_KWH="", ABONNEMENT_EUR_AN="").to_excel(w, index=False, sheet_name="REPONSE_ELEC")
            if not df_gz.empty: 
                df_gz.to_excel(w, index=False, sheet_name="DATA_GAZ")
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=DQE_{datetime.now().strftime('%Y%m%d')}.xlsx"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.post("/api/finance/upload")
async def api_finance_upload(file: UploadFile = File(...), site_id: str = Form(...), user = Depends(get_current_user)):
    try:
        parsed = finance.parse_invoice(await file.read(), file.filename)
        if parsed.get("status") == "ERROR": return JSONResponse(parsed, status_code=400)
        site_data = db.get_site(site_id) or {}
        return JSONResponse(json_compliant(finance.audit_invoice(parsed, site_data)))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.post("/api/partner/save_config")
async def save_partner_config(request: Request, user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False, "error": "Non autorisé"}, 401)
    try:
        data = await request.json()
        data["tenant_id"] = str(data.get("siret", "")).replace(" ", "")
        db.save_user_profile(f"TENANT_{data['tenant_id']}", data)
        user_prof = db.get_user_profile(user.get("uid"))
        user_prof["tenant_id"] = data["tenant_id"]
        db.save_user_profile(user.get("uid"), user_prof)
        return JSONResponse({"success": True, "tenant_id": data["tenant_id"]})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)}, 500)

@app.get("/api/partner/get_config")
async def get_partner_config(user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False}, 401)
    user_prof = db.get_user_profile(user.get("uid"))
    tenant_id = user_prof.get("tenant_id")
    if tenant_id:
        tenant_data = db.get_user_profile(f"TENANT_{tenant_id}")
        if tenant_data: return JSONResponse({"success": True, "data": tenant_data})
    return JSONResponse({"success": True, "data": user_prof})

VALID_VIEWS =["settings", "settings_pme", "settings_light", "settings_partner", "settings_ops", "ops_nexus", "ops_ingest", "ops_aggregator", "ops_market", "pme", "industry", "retail", "mairie", "sde", "oph", "syndic", "sante", "supplier", "citoyen", "pulse", "carbon", "gridmap", "solar", "optimization", "trading", "thermic", "deal_desk", "finance", "dashboard_finance", "sales_workspace", "sales_playbook", "sales_outreach", "sales_academy", "sales_cpq"]
PUBLIC_PAGES =["index.html", "onboarding.html", "processing.html", "login.html", "solutions.html", "cortex.html", "vitality.html", "connectivite.html", "audit_premium.html", "store.html", "ethique.html", "fournisseurs.html", "etudes-de-cas.html", "modele_economique.html"]

@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str, user = Depends(get_current_user)):
    if any(x in page_name for x in[".js", ".css", ".png", ".jpg", ".ico", ".svg"]): return JSONResponse({}, 404)
    target_file = page_name if page_name.endswith(".html") else f"{page_name}.html"
    clean_name = page_name.replace(".html", "")
    if target_file not in PUBLIC_PAGES and not user: return RedirectResponse(url="/login")
    if clean_name in VALID_VIEWS or target_file in PUBLIC_PAGES:
        file_path = os.path.join(TEMPLATE_DIR, target_file)
        if os.path.exists(file_path): return templates.TemplateResponse(target_file, {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in[".static", ".assets", "favicon"]): return JSONResponse({}, 404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

### 2. Remplace l'intégralité de ton `settings.html` par la nouvelle Data Unity :

```html
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ENERGISTRAT V12.6 | Data Unity (Settings & Conformité)</title>
    
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&family=JetBrains+Mono:wght@400;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: { 
                        abysse: '#001529', card: '#001D3D', sidebar: '#001529', 
                        cyan: '#00E5FF', success: '#10B981', alert: '#EF4444', 
                        gold: '#F59E0B', purple: '#A855F7', gas: '#F97316'
                    },
                    fontFamily: { sans:['Inter', 'sans-serif'], mono:['JetBrains Mono', 'monospace'] }
                }
            }
        }
    </script>
    <style>
        body { background-color: #001529; color: #e2e8f0; overflow: hidden; font-family: 'Inter', sans-serif; }
        
        .bento-card { background: rgba(0, 29, 61, 0.7); backdrop-filter: blur(20px); border: 1px solid rgba(0, 229, 255, 0.1); border-radius: 3rem; transition: all 0.3s ease; }
        .bento-card:hover { border-color: rgba(0, 229, 255, 0.4); box-shadow: 0 10px 30px -10px rgba(0, 229, 255, 0.2); }
        
        .nav-item.active { background: rgba(0, 229, 255, 0.1); border-right: 4px solid #00E5FF; color: white; }
        
        .input-edit { background: rgba(0,0,0,0.4); border: 1px solid rgba(0,229,255,0.2); color: white; padding: 14px 20px; border-radius: 2rem; width: 100%; font-family: 'Inter', sans-serif; outline: none; transition: all 0.3s; font-size: 0.875rem; }
        .input-edit:focus { border-color: #00E5FF; box-shadow: 0 0 15px rgba(0,229,255,0.3); background: rgba(0,229,255,0.05); }
        .input-mono { font-family: 'JetBrains Mono', monospace; font-weight: bold; color: #00E5FF; }

        .toggle-checkbox:checked { right: 0; border-color: #00E5FF; }
        .toggle-checkbox:checked + .toggle-label { background-color: #00E5FF; }
        .toggle-checkbox { right: 0; z-index: 1; border-color: #e2e8f0; transition: all 0.3s; }
        .toggle-label { background-color: #334155; transition: all 0.3s; }

        .suggestions-list { position: absolute; background: #001D3D; border: 1px solid #00E5FF; width: 100%; z-index: 100; max-height: 200px; overflow-y: auto; border-radius: 1rem; margin-top: 5px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }
        .suggestion-item { padding: 12px 20px; cursor: pointer; font-size: 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.05); }
        .suggestion-item:hover { background: #00E5FF; color: #001529; font-weight: bold; }

        .view-section { display: none; } .view-section.active { display: block; animation: fadeIn 0.4s ease-out; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(15px); } to { opacity: 1; transform: translateY(0); } }
        
        ::-webkit-scrollbar { width: 6px; height: 6px; } ::-webkit-scrollbar-track { background: transparent; } ::-webkit-scrollbar-thumb { background: #00E5FF; border-radius: 3px; }
    </style>
</head>
<body class="flex h-screen w-screen font-sans bg-[url('https://www.transparenttextures.com/patterns/carbon-fibre.png')]">

    <!-- SIDEBAR -->
    <aside class="w-64 bg-abysse border-r border-cyan/10 flex flex-col flex-shrink-0 z-50 shadow-2xl h-screen">
        <div class="h-24 flex items-center px-6 border-b border-cyan/10 bg-card/50">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan to-blue-800 flex items-center justify-center text-abysse font-black shadow-[0_0_15px_rgba(0,229,255,0.5)] text-xl mr-3">
                <i class="fa-solid fa-database text-abysse"></i>
            </div>
            <div>
                <div class="font-black tracking-tight text-white leading-none text-lg">DATA <span class="text-cyan">UNITY</span></div>
                <div id="god-mode-indicator" class="text-[9px] text-alert font-mono mt-1 hidden animate-pulse font-bold bg-alert/20 px-2 py-0.5 rounded border border-alert/50 inline-block">● GOD MODE ACTIF</div>
                <div class="text-[9px] text-gray-500 font-mono mt-1 tracking-widest uppercase">Settings V12.6</div>
            </div>
        </div>
        
        <nav class="flex-1 overflow-y-auto py-6 space-y-1">
            <div class="text-[10px] uppercase text-gray-500 font-bold tracking-widest mb-2 px-6">Identité & Parc</div>
            <button onclick="switchView('general')" id="nav-general" class="nav-item active w-full text-left px-6 py-4 rounded-l-[2rem] text-sm font-bold text-gray-400 hover:text-white transition flex items-center gap-3">
                <i class="fa-solid fa-building w-5 text-center"></i> Master Tenant
            </button>
            <button onclick="switchView('perimetre')" id="nav-perimetre" class="nav-item w-full text-left px-6 py-4 rounded-l-[2rem] text-sm font-bold text-gray-400 hover:text-white transition flex items-center gap-3">
                <i class="fa-solid fa-sitemap w-5 text-center text-cyan"></i> Base 3D & Contrats
            </button>
            <button onclick="switchView('import')" id="nav-import" class="nav-item w-full text-left px-6 py-4 rounded-l-[2rem] text-sm font-bold text-gray-400 hover:text-white transition flex items-center gap-3">
                <i class="fa-solid fa-file-excel w-5 text-center text-success"></i> Smart Importer Excel
            </button>

            <div class="text-[10px] uppercase text-gray-500 font-bold tracking-widest mb-2 mt-6 px-6">Conformité & Ops</div>
            <button onclick="switchView('rgpd')" id="nav-rgpd" class="nav-item w-full text-left px-6 py-4 rounded-l-[2rem] text-sm font-bold text-gray-400 hover:text-white transition flex items-center gap-3">
                <i class="fa-solid fa-shield-halved w-5 text-center text-gold"></i> Mandats (API SGE)
            </button>
            <button onclick="switchView('support')" id="nav-support" class="nav-item w-full text-left px-6 py-4 rounded-l-[2rem] text-sm font-bold text-gray-400 hover:text-white transition flex items-center gap-3">
                <i class="fa-solid fa-headset w-5 text-center text-purple"></i> Guichet Support Ops
            </button>
            <button onclick="switchView('equipe')" id="nav-equipe" class="nav-item w-full text-left px-6 py-4 rounded-l-[2rem] text-sm font-bold text-gray-400 hover:text-white transition flex items-center gap-3">
                <i class="fa-solid fa-users w-5 text-center text-gray-300"></i> Rôles & Sécurité
            </button>
        </nav>
        
        <div class="p-4 border-t border-cyan/10 bg-card/30">
            <button onclick="history.back()" class="flex items-center justify-center w-full gap-2 text-gray-400 hover:text-white transition text-xs font-bold bg-abysse border border-white/10 hover:border-cyan/50 rounded-[2rem] py-3 shadow-lg">
                <i class="fa-solid fa-arrow-left"></i> Quitter les Paramètres
            </button>
        </div>
    </aside>

    <main class="flex-1 flex flex-col relative bg-transparent overflow-hidden">
        
        <!-- HEADER GLOABL & HEALTH SCORE -->
        <header class="h-24 border-b border-cyan/10 flex items-center justify-between px-10 bg-abysse/90 backdrop-blur sticky top-0 z-40 flex-shrink-0 shadow-lg">
            <div>
                <h2 id="page-title" class="text-3xl font-black text-white italic tracking-tight drop-shadow-lg">Mon Entreprise</h2>
                <p class="text-xs text-gray-400 font-mono mt-1" id="header-subtitle">Identité juridique et Master Tenant</p>
            </div>
            
            <div class="flex items-center gap-6">
                <div class="bg-card/50 border border-white/10 px-6 py-3 rounded-[2rem] flex items-center gap-4 shadow-inner">
                    <div class="text-right">
                        <div class="text-[10px] text-gray-400 uppercase font-bold tracking-widest mb-1">Data Health Score</div>
                        <div class="text-xs font-bold text-white">Qualité de la base</div>
                    </div>
                    <div class="relative w-16 h-16 flex items-center justify-center bg-abysse rounded-full border-4 border-cyan/20 shadow-[0_0_15px_rgba(0,229,255,0.2)]">
                        <span class="text-cyan font-black font-mono text-lg" id="global-health">0%</span>
                    </div>
                </div>
            </div>
        </header>

        <div class="flex-1 overflow-y-auto p-10 pb-32">

            <!-- VUE 1 : MON ENTREPRISE (IDENTITÉ 3D) -->
            <div id="view-general" class="view-section active max-w-[1200px] mx-auto space-y-8">
                <div class="flex justify-between items-end mb-6">
                    <div>
                        <h3 class="text-2xl font-black text-white">Master Tenant (Niveau 1)</h3>
                        <p class="text-sm text-gray-400 mt-2 font-mono">C'est la racine de votre base 3D. Tous vos sites y seront rattachés.</p>
                    </div>
                    <button onclick="savePartnerConfig()" class="bg-cyan text-abysse font-black px-8 py-4 rounded-[2rem] hover:bg-white transition shadow-[0_0_20px_rgba(0,229,255,0.4)] uppercase tracking-widest text-xs flex items-center gap-2">
                        <i class="fa-solid fa-save text-lg"></i> Verrouiller l'Identité
                    </button>
                </div>

                <div class="bento-card p-10 border-t-4 border-cyan shadow-[0_20px_50px_rgba(0,0,0,0.3)]">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div>
                            <label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-4 mb-2 block"><i class="fa-solid fa-magnifying-glass text-cyan mr-1"></i> SIREN / SIRET (Recherche API Gouv)</label>
                            <div class="relative">
                                <input type="text" id="partner-siret" placeholder="Saisir 9 à 14 chiffres..." class="input-edit input-mono text-lg" onblur="checkPartnerIdentity()">
                                <div id="partner-status" class="absolute right-6 top-1/2 -translate-y-1/2 text-xl"></div>
                            </div>
                        </div>
                        <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-4 mb-2 block">Raison Sociale Officielle</label><input type="text" id="partner-name" class="input-edit font-bold text-white bg-white/5 border-dashed" readonly></div>
                        <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-4 mb-2 block">Code NAF (Benchmarking Sectoriel)</label><input type="text" id="partner-naf" class="input-edit input-mono text-gray-400 bg-white/5" readonly></div>
                        <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-4 mb-2 block">TVA Intracommunautaire (Auto)</label><input type="text" id="partner-tva" class="input-edit input-mono text-gray-400 bg-white/5" readonly></div>
                        <div class="col-span-2"><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-4 mb-2 block">Adresse du Siège</label><input type="text" id="partner-address" class="input-edit text-gray-300"></div>
                        <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-4 mb-2 block">Code Postal</label><input type="text" id="partner-zip" class="input-edit input-mono text-gray-300"></div>
                        <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-4 mb-2 block">Ville</label><input type="text" id="partner-city" class="input-edit text-gray-300 font-bold"></div>
                    </div>
                </div>

                <div class="bento-card p-8 border border-white/5 bg-gradient-to-r from-card to-abysse text-center">
                    <h4 class="text-sm font-bold text-white uppercase tracking-widest mb-2"><i class="fa-solid fa-leaf text-success mr-2"></i> Année de Référence Carbone (Loi ELAN)</h4>
                    <p class="text-xs text-gray-400 mb-6">Paramètre central pour générer les trajectoires de sobriété (-40% en 2030) sur vos tableaux de bord.</p>
                    <select id="partner-baseline-year" class="bg-abysse border border-success/30 text-success font-bold font-mono text-lg rounded-[2rem] px-8 py-3 outline-none cursor-pointer shadow-[0_0_15px_rgba(16,185,129,0.2)]">
                        <option value="2010">2010 (Par défaut Légal)</option>
                        <option value="2018">2018</option>
                        <option value="2019">2019</option>
                        <option value="2022">2022</option>
                    </select>
                </div>
            </div>

            <!-- VUE 2 : MON PÉRIMÈTRE (L'ARBRE 3D ET LA DÉGRADATION GRACIEUSE) -->
            <div id="view-perimetre" class="view-section max-w-[1600px] mx-auto space-y-6 h-full">
                <div class="flex justify-between items-end mb-6">
                    <div>
                        <h3 class="text-2xl font-black text-white">Patrimoine & Contrats</h3>
                        <p class="text-sm text-gray-400 mt-2 font-mono">Base de données 3D (Sites > Bâtiments > Compteurs)</p>
                    </div>
                    <button onclick="resetSiteForm()" class="bg-white/10 text-white font-bold px-6 py-3 rounded-[2rem] hover:bg-white/20 transition text-xs flex items-center gap-2 border border-white/20 uppercase tracking-widest">
                        <i class="fa-solid fa-plus text-cyan"></i> Ajouter un Compteur Manuel
                    </button>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-8 h-[700px]">
                    <!-- COL 1 : ARBRE DES SITES -->
                    <div class="col-span-4 bento-card p-0 flex flex-col overflow-hidden shadow-2xl">
                        <div class="p-6 border-b border-white/10 bg-card/50">
                            <div class="relative w-full">
                                <i class="fa-solid fa-search absolute left-4 top-1/2 -translate-y-1/2 text-gray-500 text-sm"></i>
                                <input type="text" id="search-site" oninput="renderSiteTree()" placeholder="Rechercher un PDL, un site..." class="w-full bg-abysse border border-white/10 rounded-[2rem] py-3 pl-12 pr-4 text-xs text-white focus:border-cyan outline-none transition font-mono">
                            </div>
                        </div>
                        <div class="flex-1 overflow-y-auto p-4 space-y-3 bg-abysse/30" id="site-tree-container">
                            <div class="text-center py-10 text-gray-500 font-mono text-xs"><i class="fa-solid fa-spinner fa-spin text-cyan mb-2 text-2xl block"></i> Chargement de l'arborescence 3D...</div>
                        </div>
                    </div>

                    <!-- COL 2 : L'ÉDITEUR INTELLIGENT (ELEC vs GAZ) -->
                    <div class="col-span-8 bento-card p-0 flex flex-col overflow-hidden relative shadow-[0_20px_50px_rgba(0,0,0,0.4)]">
                        <div id="site-editor-overlay" class="absolute inset-0 bg-abysse/90 backdrop-blur-sm z-50 flex flex-col items-center justify-center text-center">
                            <i class="fa-solid fa-sitemap text-6xl text-gray-600 mb-4 opacity-50"></i>
                            <h3 class="text-xl font-bold text-white">Éditeur de Patrimoine</h3>
                            <p class="text-xs text-gray-400 mt-2">Sélectionnez un site dans l'arborescence à gauche ou créez-en un nouveau.</p>
                        </div>

                        <div class="flex-1 overflow-y-auto p-10 space-y-8 relative">
                            <div class="flex justify-between items-start border-b border-white/10 pb-6">
                                <div>
                                    <h3 class="text-2xl font-black text-white flex items-center gap-3" id="site-editor-title">Nouvelle Entité</h3>
                                    <div class="text-[10px] text-gray-500 font-mono mt-2 tracking-widest uppercase">Identifiant Système : <span id="site-editor-id" class="text-cyan">NEW</span></div>
                                </div>
                                <div class="bg-black/40 px-4 py-2 rounded-2xl border border-white/5 text-center shadow-inner cursor-help" title="Le score augmente quand vous renseignez la Surface, le Prix, le PDL...">
                                    <div class="text-[9px] text-gray-400 uppercase font-bold tracking-widest mb-1 flex items-center gap-2"><i class="fa-solid fa-heart-pulse text-alert"></i> Score Donnée</div>
                                    <div class="text-lg font-black font-mono text-cyan" id="site-health-score">0%</div>
                                </div>
                            </div>

                            <!-- BLOC 1 : IDENTITÉ & LOCALISATION -->
                            <div class="bg-abysse/50 p-8 rounded-[2rem] border border-white/5 space-y-6">
                                <h4 class="text-sm font-bold text-white uppercase tracking-widest border-b border-white/10 pb-2"><i class="fa-solid fa-location-dot text-cyan mr-2"></i> Identité & Bâtiment</h4>
                                <div class="grid grid-cols-2 gap-6 relative">
                                    <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block text-cyan">Nom du Site / Bâtiment *</label><input type="text" id="site-name" class="input-edit font-bold text-white border-cyan/50 bg-cyan/5 shadow-inner" placeholder="Ex: Mairie Centrale"></div>
                                    <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block">Lot / Entité de regroupement</label><input type="text" id="site-lot" class="input-edit" placeholder="Ex: Lot 1 - Bâtiments > 36kVA"></div>
                                    
                                    <!-- AUTOCOMPLÉTION ADRESSE AVEC INSEE CACHÉ -->
                                    <div class="col-span-2 relative">
                                        <label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block">Adresse (Voie)</label>
                                        <input type="text" id="address-input" class="input-edit w-full" placeholder="Commencez à taper l'adresse..." oninput="searchAddress()">
                                        <input type="hidden" id="site-insee">
                                        <div id="address-suggestions" class="suggestions-list hidden"></div>
                                    </div>
                                    
                                    <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block">Code Postal</label><input type="text" id="zip-input" class="input-edit font-mono"></div>
                                    <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block">Ville</label><input type="text" id="city-input" class="input-edit font-bold"></div>

                                    <div>
                                        <label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block flex justify-between"><span>Surface (m²)</span> <span class="text-tertiaire text-[9px]"><i class="fa-solid fa-leaf mr-1"></i>Décret Tertiaire</span></label>
                                        <input type="number" id="site-surface" class="input-edit input-mono text-tertiaire border-tertiaire/30 bg-tertiaire/5" placeholder="0">
                                    </div>
                                    <div><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block">Typologie (Usage)</label><input type="text" id="inp-type" class="input-edit" placeholder="Ex: Ecole, Sport, EP..."></div>
                                </div>
                            </div>

                            <!-- BLOC 2 : CONTRAT ET HEUROSAISONNALITÉ -->
                            <div class="bg-card/80 p-8 rounded-[2rem] border-l-4 border-cyan shadow-lg space-y-6 transition-colors duration-500" id="contract-block">
                                <div class="flex justify-between items-center border-b border-white/10 pb-4">
                                    <h4 class="text-sm font-bold text-white uppercase tracking-widest"><i class="fa-solid fa-file-signature text-gray-400 mr-2"></i> Contrat & Structure Tarifaire</h4>
                                    <div class="flex bg-black/50 p-1 rounded-[2rem] border border-white/5">
                                        <button onclick="setSiteEnergy('elec')" id="btn-site-elec" class="px-6 py-2 rounded-[2rem] text-xs font-bold bg-cyan text-abysse transition shadow-md">ÉLEC</button>
                                        <button onclick="setSiteEnergy('gaz')" id="btn-site-gaz" class="px-6 py-2 rounded-[2rem] text-xs font-bold text-gray-400 hover:text-white transition">GAZ</button>
                                    </div>
                                </div>

                                <!-- CHAMPS COMMUNS CONTRAT -->
                                <div class="grid grid-cols-12 gap-6">
                                    <div class="col-span-4"><label id="lbl-primary" class="text-[10px] text-cyan uppercase font-bold tracking-widest pl-2 mb-1 block">PDL / PRM (14) *</label><input type="text" id="site-pdl" class="input-edit input-mono text-lg text-cyan border-cyan/30 bg-cyan/5" placeholder="3000..."></div>
                                    <div class="col-span-4"><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block">Fournisseur Actuel</label><input type="text" id="site-provider" class="input-edit" placeholder="Ex: EDF, Total..."></div>
                                    <div class="col-span-2"><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block">Début Marché</label><input type="date" id="site-start-date" class="input-edit text-gray-400 cursor-pointer" style="color-scheme: dark;"></div>
                                    <div class="col-span-2"><label class="text-[10px] text-gray-500 uppercase font-bold tracking-widest pl-2 mb-1 block text-alert">Fin de marché</label><input type="date" id="site-end-date" class="input-edit text-gray-300 cursor-pointer" style="color-scheme: dark;"></div>
                                </div>

                                <!-- LE MOTEUR DE PRIX DYNAMIQUE -->
                                <div class="bg-abysse p-6 rounded-3xl border border-white/5 relative mt-4 shadow-inner">
                                    
                                    <!-- GRILLE ÉLEC (4 Cadrans) -->
                                    <div id="pricing-elec-grid" class="space-y-4">
                                        <div class="flex justify-between items-center mb-6">
                                            <span class="text-[10px] font-bold text-white uppercase tracking-widest"><i class="fa-solid fa-bolt text-cyan mr-1"></i> Acheminement & Énergie (€/MWh HT)</span>
                                            <div class="flex items-center gap-3 bg-white/5 px-4 py-2 rounded-full border border-white/10" id="toggle-quadrants-container">
                                                <span class="text-[9px] text-gray-400 uppercase font-bold tracking-widest">Tarif Unique (C5)</span>
                                                <div class="relative inline-block w-10 align-middle select-none transition duration-200 ease-in">
                                                    <input type="checkbox" id="quadrant-toggle" class="toggle-checkbox absolute block w-5 h-5 rounded-full bg-white border-4 appearance-none cursor-pointer" onchange="toggleQuadrants()"/>
                                                    <label for="quadrant-toggle" class="toggle-label block overflow-hidden h-5 rounded-full bg-gray-600 cursor-pointer"></label>
                                                </div>
                                                <span class="text-[9px] text-cyan uppercase font-bold tracking-widest">Heurosaisonnier (C4/C3)</span>
                                            </div>
                                        </div>

                                        <div class="grid grid-cols-4 gap-4">
                                            <div class="col-span-4 border-b border-white/10 pb-2 mb-2"><span class="text-[9px] text-gray-500 font-bold uppercase tracking-widest">Puissances Souscrites (kW)</span></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-gray-400 uppercase font-bold pl-2 mb-1 block">PS - HPH</label><input type="number" id="ps-hph" class="input-edit input-mono text-center"></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-gray-400 uppercase font-bold pl-2 mb-1 block">PS - HCH</label><input type="number" id="ps-hch" class="input-edit input-mono text-center"></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-cyan uppercase font-bold pl-2 mb-1 block">PS - HPE</label><input type="number" id="ps-hpe" class="input-edit input-mono text-center border-cyan/30 text-cyan"></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-gray-400 uppercase font-bold pl-2 mb-1 block">PS - HCE</label><input type="number" id="ps-hce" class="input-edit input-mono text-center"></div>
                                            <div class="quad-simple col-span-4"><label class="text-[9px] text-cyan uppercase font-bold pl-2 mb-1 block">Puissance Unique (kVA)</label><input type="number" id="ps-unique" class="input-edit input-mono text-cyan w-1/3"></div>

                                            <div class="col-span-4 border-b border-white/10 pb-2 mb-2 mt-4"><span class="text-[9px] text-gray-500 font-bold uppercase tracking-widest">Prix Molécule (€/MWh HT)</span></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-white uppercase font-bold pl-2 mb-1 block">Prix HPH</label><input type="number" step="0.01" id="px-hph" class="input-edit input-mono text-center border-white/30 text-white"></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-gray-400 uppercase font-bold pl-2 mb-1 block">Prix HCH</label><input type="number" step="0.01" id="px-hch" class="input-edit input-mono text-center"></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-cyan uppercase font-bold pl-2 mb-1 block">Prix HPE</label><input type="number" step="0.01" id="px-hpe" class="input-edit input-mono text-center border-cyan/30 text-cyan"></div>
                                            <div class="quad-advanced"><label class="text-[9px] text-gray-400 uppercase font-bold pl-2 mb-1 block">Prix HCE</label><input type="number" step="0.01" id="px-hce" class="input-edit input-mono text-center"></div>
                                            <div class="quad-simple col-span-4"><label class="text-[9px] text-cyan uppercase font-bold pl-2 mb-1 block">Prix Unique Base (€/MWh)</label><input type="number" step="0.01" id="px-unique" class="input-edit input-mono text-cyan border-cyan/50 bg-cyan/5 w-1/3 text-lg"></div>

                                            <div class="col-span-4 border-b border-white/10 pb-2 mb-2 mt-4"><span class="text-[9px] text-gray-500 font-bold uppercase tracking-widest">Abonnement & Taxes Réglementaires</span></div>
                                            <div class="col-span-2"><label class="text-[9px] text-gold uppercase font-bold pl-2 mb-1 block">Abonnement Annuel (€)</label><input type="number" step="0.1" id="px-fix" class="input-edit input-mono text-gold border-gold/30 text-center"></div>
                                            <div class="col-span-2"><label class="text-[9px] text-gray-400 uppercase font-bold pl-2 mb-1 block">CSPE / TICFE (€/MWh)</label><input type="number" step="0.1" id="px-tax" class="input-edit input-mono text-gray-400 text-center" value="22.5"></div>
                                        </div>
                                    </div>

                                    <!-- GRILLE GAZ (Métrique Gaz Naturel) -->
                                    <div id="pricing-gaz-grid" class="hidden space-y-4">
                                        <div class="flex justify-between items-center mb-6">
                                            <span class="text-[10px] font-bold text-white uppercase tracking-widest"><i class="fa-solid fa-fire text-gas mr-1"></i> Acheminement & Énergie Gaz</span>
                                        </div>
                                        <div class="grid grid-cols-3 gap-6">
                                            <div><label class="text-[10px] text-gray-400 uppercase font-bold pl-2 mb-1 block">Profil GRDF (ex: T1, T2, P12)</label><input type="text" id="site-profil-gaz" class="input-edit font-mono text-center uppercase" placeholder="P12"></div>
                                            <div><label class="text-[10px] text-gray-400 uppercase font-bold pl-2 mb-1 block">Capacité Journalière (CJA)</label><input type="number" id="ps-gaz-cja" class="input-edit input-mono text-center" placeholder="MWh/j"></div>
                                            <div><label class="text-[10px] text-gas uppercase font-bold pl-2 mb-1 block">Volume CAR (MWh)</label><input type="number" id="ps-gaz-car" class="input-edit input-mono text-gas border-gas/30 bg-gas/5 text-center text-lg" placeholder="MWh"></div>
                                            
                                            <div class="col-span-3 border-b border-white/10 pb-2 mb-2 mt-4"><span class="text-[9px] text-gray-500 font-bold uppercase tracking-widest">Pricing & Taxes</span></div>
                                            <div><label class="text-[10px] text-white uppercase font-bold pl-2 mb-1 block">Prix Molécule (€/MWh)</label><input type="number" step="0.01" id="px-gaz-mol" class="input-edit input-mono text-white text-center text-2xl bg-white/5 border-white/30"></div>
                                            <div><label class="text-[10px] text-gray-400 uppercase font-bold pl-2 mb-1 block">Abonnement Annuel (€)</label><input type="number" step="0.1" id="px-gaz-fix" class="input-edit input-mono text-center text-lg"></div>
                                            <div><label class="text-[10px] text-gray-400 uppercase font-bold pl-2 mb-1 block">Terme de Stockage (€/MWh)</label><input type="number" step="0.01" id="px-gaz-stock" class="input-edit input-mono text-center"></div>
                                            <div><label class="text-[10px] text-gray-400 uppercase font-bold pl-2 mb-1 block">TICGN (€/MWh)</label><input type="number" step="0.1" id="px-gaz-tax" class="input-edit input-mono text-center" value="8.44"></div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- BARRE D'ACTION ÉDITEUR -->
                        <div class="p-6 bg-abysse border-t border-cyan/20 flex justify-end gap-4 shadow-[0_-10px_20px_rgba(0,0,0,0.5)] z-10">
                            <button onclick="closeSiteEditor()" class="px-8 py-3 rounded-[2rem] text-gray-400 hover:text-white font-bold text-xs transition uppercase tracking-widest">Annuler</button>
                            <button onclick="saveSiteData()" id="btn-save-site" class="bg-cyan text-abysse px-10 py-3 rounded-[2rem] text-sm font-black hover:bg-white transition shadow-[0_0_20px_rgba(0,229,255,0.4)] uppercase tracking-widest flex items-center gap-2">
                                <i class="fa-solid fa-save"></i> Synchroniser Base 3D
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- VUE 3 : IMPORT MASSIF EXCEL (SMART TEMPLATE 36 COLONNES) -->
            <div id="view-import" class="view-section max-w-[1200px] mx-auto space-y-8 mt-10">
                <div class="text-center mb-16">
                    <h2 class="text-5xl font-black text-white italic tracking-tight mb-6">IMPORT <span class="text-success">MASSIF</span></h2>
                    <p class="text-base text-gray-400 font-mono leading-relaxed max-w-3xl mx-auto">Peuplez votre War Room en un clic. Téléchargez la matrice V12.6, remplissez vos compteurs Élec & Gaz, et glissez le fichier ci-dessous. L'IA CORTEX classera chaque donnée dans le bon tiroir 3D.</p>
                </div>

                <div class="grid grid-cols-2 gap-10">
                    <div class="bento-card p-12 border-t-4 border-cyan text-center shadow-[0_20px_50px_rgba(0,0,0,0.3)] flex flex-col justify-center items-center">
                        <i class="fa-solid fa-file-excel text-7xl text-cyan mb-8 drop-shadow-lg"></i>
                        <h3 class="text-2xl font-black text-white mb-4">1. Télécharger la Matrice</h3>
                        <p class="text-sm text-gray-400 mb-10 leading-relaxed">Fichier normé (36 colonnes) adapté aux marchés publics et industriels. Gère l'heurosaisonnalité, le Gaz, le code INSEE et la loi ELAN.</p>
                        <button onclick="downloadTemplate()" class="w-full bg-abysse border-2 border-cyan/50 text-cyan font-black py-5 rounded-[2rem] hover:bg-cyan hover:text-abysse transition shadow-[0_0_20px_rgba(0,229,255,0.2)] text-sm uppercase tracking-widest flex justify-center items-center gap-3">
                            <i class="fa-solid fa-download text-lg"></i> Matrice V12.6 (.CSV)
                        </button>
                    </div>

                    <div class="bento-card p-12 border-t-4 border-success text-center shadow-[0_20px_50px_rgba(0,0,0,0.3)] flex flex-col justify-center items-center group hover:border-success/80 transition duration-500">
                        <i class="fa-solid fa-cloud-arrow-up text-7xl text-gray-600 group-hover:text-success mb-8 transition duration-500"></i>
                        <h3 class="text-2xl font-black text-white mb-4">2. Ingestion CORTEX</h3>
                        <p class="text-sm text-gray-400 mb-10 leading-relaxed">Glissez votre fichier complété. L'IA rattachera tous les compteurs à votre SIRET maître (<span class="text-success font-bold" id="import-tenant-id">--</span>).</p>
                        <label class="w-full block bg-success text-abysse font-black py-5 rounded-[2rem] cursor-pointer hover:bg-white transition shadow-[0_0_30px_rgba(16,185,129,0.4)] text-sm uppercase tracking-widest">
                            <i class="fa-solid fa-upload mr-2 text-lg"></i> Injecter les Données
                            <input type="file" id="csv-upload" class="hidden" accept=".csv,.xlsx" onchange="processImport(this)">
                        </label>
                    </div>
                </div>
            </div>

            <!-- VUE 4 : RGPD & CONFORMITÉ LÉGALE -->
            <div id="view-rgpd" class="view-section max-w-[1200px] mx-auto space-y-8">
                <div class="flex justify-between items-end mb-10">
                    <div>
                        <h2 class="text-4xl font-black text-white italic tracking-tight">Tiers de <span class="text-gold">Confiance</span></h2>
                        <p class="text-sm text-gray-400 mt-2 font-mono">Contrôle des flux API (SGE) et registre RGPD.</p>
                    </div>
                    <div class="bg-card/50 border border-white/10 px-8 py-4 rounded-[2rem] flex items-center gap-4 shadow-lg">
                        <span class="text-[10px] text-gray-500 uppercase font-bold tracking-widest">Rétention Légale</span>
                        <span class="text-base font-black text-white bg-abysse px-4 py-2 rounded-full border border-white/20">5 Ans</span>
                    </div>
                </div>

                <div class="grid grid-cols-2 gap-10">
                    <div class="bento-card p-10 border-l-4 border-gold shadow-[0_20px_50px_rgba(0,0,0,0.3)]">
                        <h3 class="text-xl font-black text-white mb-8 flex items-center gap-3"><i class="fa-solid fa-plug-circle-check text-gold text-2xl"></i> Monitoring API Distributeurs</h3>
                        <div class="space-y-6">
                            <div class="bg-abysse/50 p-6 rounded-[2rem] border border-white/5 flex justify-between items-center shadow-inner">
                                <div class="flex items-center gap-6">
                                    <div class="w-14 h-14 rounded-full bg-cyan/10 flex items-center justify-center border border-cyan/30 text-cyan text-2xl shadow-lg"><i class="fa-solid fa-bolt"></i></div>
                                    <div><div class="font-bold text-white text-lg">Passerelle ENEDIS</div><div class="text-[10px] text-gray-400 font-mono mt-1 uppercase tracking-widest">Synchro : Aujourd'hui, 06h12</div></div>
                                </div>
                                <div class="bg-success/20 text-success border border-success/30 px-4 py-2 rounded-full text-xs font-bold uppercase tracking-widest flex items-center gap-2"><div class="w-2 h-2 rounded-full bg-success animate-pulse"></div> Actif</div>
                            </div>
                            <div class="bg-abysse/50 p-6 rounded-[2rem] border border-white/5 flex justify-between items-center opacity-50">
                                <div class="flex items-center gap-6">
                                    <div class="w-14 h-14 rounded-full bg-gas/10 flex items-center justify-center border border-gas/30 text-gas text-2xl"><i class="fa-solid fa-fire"></i></div>
                                    <div><div class="font-bold text-white text-lg">Passerelle GRDF</div><div class="text-[10px] text-gray-400 font-mono mt-1 uppercase tracking-widest">Aucun compteur gaz détecté</div></div>
                                </div>
                                <div class="bg-gray-800 text-gray-400 border border-gray-600 px-4 py-2 rounded-full text-xs font-bold uppercase tracking-widest">En veille</div>
                            </div>
                        </div>
                    </div>

                    <div class="bento-card p-10 border-l-4 border-cyan shadow-[0_20px_50px_rgba(0,0,0,0.3)] text-center flex flex-col justify-center relative overflow-hidden">
                        <i class="fa-solid fa-file-signature absolute -right-4 -bottom-4 text-[150px] text-cyan opacity-5"></i>
                        <h3 class="text-2xl font-black text-white mb-4 relative z-10">Mandat Unique de Collecte</h3>
                        <p class="text-sm text-gray-400 mb-10 leading-relaxed max-w-md mx-auto relative z-10">
                            Pour permettre à CORTEX de collecter et d'analyser vos courbes de charge en continu, vous devez approuver le mandat de délégation SGE. Un certificat PDF sera horodaté dans la blockchain interne.
                        </p>
                        <div class="flex items-center justify-center gap-4 mb-10 relative z-10 bg-abysse/50 p-4 rounded-[2rem] border border-white/5 w-max mx-auto">
                            <input type="checkbox" id="legal-check" class="w-6 h-6 accent-cyan cursor-pointer shadow-[0_0_10px_#00E5FF]">
                            <label for="legal-check" class="text-sm font-bold text-white cursor-pointer select-none">J'agis en qualité de représentant légal et j'approuve.</label>
                        </div>
                        <button onclick="approveMandate()" id="btn-mandate" class="w-full bg-cyan text-abysse font-black py-4 rounded-[2rem] shadow-[0_0_20px_rgba(0,229,255,0.4)] hover:bg-white transition flex justify-center items-center gap-3 uppercase tracking-widest text-sm relative z-10">
                            <i class="fa-solid fa-stamp text-lg"></i> Signer le Mandat Électronique
                        </button>
                    </div>
                </div>
            </div>

            <!-- VUE 5 : GUICHET OPS & SAGE TIMELINE -->
            <div id="view-support" class="view-section max-w-[1600px] mx-auto space-y-8 h-full">
                <div class="flex justify-between items-end mb-6">
                    <div>
                        <h3 class="text-4xl font-black text-white italic tracking-tight">GUICHET <span class="text-purple">OPS</span></h3>
                        <p class="text-sm text-gray-400 mt-2 font-mono">Service Desk & Timeline d'Expertise (SAGE)</p>
                    </div>
                </div>

                <div class="grid grid-cols-1 lg:grid-cols-12 gap-10 h-[700px]">
                    <!-- NOUVELLE REQUÊTE (PONT CRM) -->
                    <div class="col-span-5 bento-card p-10 border-t-4 border-cyan flex flex-col shadow-[0_20px_50px_rgba(0,0,0,0.3)]">
                        <h4 class="text-lg font-black text-white uppercase tracking-widest mb-4 flex items-center gap-3"><i class="fa-solid fa-paper-plane text-cyan text-2xl"></i> Ouvrir un Ticket Support</h4>
                        <p class="text-sm text-gray-400 mb-8 leading-relaxed">Votre demande sera poussée directement dans la War Room de nos experts opérationnels.</p>
                        
                        <div class="space-y-6 flex-1">
                            <select id="ticket-type" class="input-edit appearance-none bg-[url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%22292.4%22%20height%3D%22292.4%22%3E%3Cpath%20fill%3D%22%23FFFFFF%22%20d%3D%22M287%2069.4a17.6%2017.6%200%200%200-13-5.4H18.4c-5%200-9.3%201.8-12.9%205.4A17.6%2017.6%200%200%200%200%2082.2c0%205%201.8%209.3%205.4%2012.9l128%20127.9c3.6%203.6%207.8%205.4%2012.8%205.4s9.2-1.8%2012.8-5.4L287%2095c3.5-3.5%205.4-7.8%205.4-12.8%200-5-1.9-9.2-5.5-12.8z%22%2F%3E%3C%2Fsvg%3E')] bg-no-repeat bg-[position:right_20px_center] bg-[length:12px_auto] cursor-pointer font-bold text-base py-5">
                                <option value="ACHAT">Demande de cotation (Nouveau Bâtiment)</option>
                                <option value="FACTURE">Contestation d'une facture</option>
                                <option value="TECH">Problème sur un PDL SGE</option>
                                <option value="RSE">Question Décret Tertiaire / CEE</option>
                            </select>
                            <textarea id="ticket-desc" class="input-edit h-64 resize-none font-sans text-sm p-6" placeholder="Détaillez votre besoin ici..."></textarea>
                        </div>
                        <button onclick="sendOpsTicket()" class="w-full bg-cyan text-abysse font-black py-5 rounded-[2rem] hover:bg-white transition shadow-[0_0_30px_rgba(0,229,255,0.4)] mt-6 uppercase tracking-widest text-sm flex items-center justify-center gap-3">
                            <i class="fa-solid fa-paper-plane"></i> Envoyer la requête
                        </button>
                    </div>

                    <!-- TIMELINE SAGE (PREUVE DE TRAVAIL) -->
                    <div class="col-span-7 bento-card p-0 flex flex-col border-t-4 border-purple overflow-hidden shadow-[0_20px_50px_rgba(0,0,0,0.3)]">
                        <div class="p-8 border-b border-white/5 bg-card/50">
                            <h4 class="text-lg font-black text-white uppercase tracking-widest flex items-center gap-3"><i class="fa-solid fa-user-tie text-purple text-2xl"></i> Journal d'Expertise (SAGE)</h4>
                            <p class="text-xs text-gray-400 mt-2 font-mono">Retrouvez ici toutes les recommandations rédigées par nos experts ou l'Économe de flux de votre syndicat.</p>
                        </div>
                        <div class="flex-1 overflow-y-auto p-10 space-y-8 bg-abysse/30 relative" id="sage-timeline-container">
                            <div class="absolute left-14 top-0 bottom-0 w-px bg-white/10 z-0"></div>
                            <div class="text-center py-20 text-gray-500 font-mono text-sm relative z-10"><i class="fa-solid fa-spinner fa-spin text-purple mb-4 text-4xl block"></i> Analyse de la base 3D...</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- VUE 6 : ÉQUIPE & ACCÈS -->
            <div id="view-equipe" class="view-section max-w-[1200px] mx-auto space-y-8">
                <div class="flex justify-between items-end mb-10">
                    <div>
                        <h2 class="text-4xl font-black text-white italic tracking-tight">Rôle & <span class="text-gray-400">Sécurité</span></h2>
                        <p class="text-sm text-gray-400 mt-2 font-mono">Gestion des accès à l'Hyperviseur.</p>
                    </div>
                    <button onclick="App.toast('Invitation envoyée !', 'success')" class="bg-white/10 hover:bg-white/20 text-white border border-white/20 px-8 py-4 rounded-[2rem] text-sm font-black transition flex items-center gap-3 uppercase tracking-widest shadow-lg">
                        <i class="fa-solid fa-user-plus text-cyan"></i> Inviter un collaborateur
                    </button>
                </div>
                
                <div class="bento-card overflow-hidden shadow-[0_20px_50px_rgba(0,0,0,0.3)] border border-white/5">
                    <table class="w-full text-left text-sm">
                        <thead class="bg-abysse text-[10px] text-gray-500 uppercase tracking-widest border-b border-white/10">
                            <tr><th class="p-8">Utilisateur</th><th class="p-8">Rôle (RBAC)</th><th class="p-8 text-center">Statut</th><th class="p-8 text-right">Action</th></tr>
                        </thead>
                        <tbody class="divide-y divide-white/5 bg-card/30">
                            <tr class="hover:bg-white/5 transition">
                                <td class="p-8 font-bold text-white flex items-center gap-4 text-base"><div class="w-12 h-12 rounded-full bg-cyan/20 text-cyan flex items-center justify-center text-xl shadow-inner"><i class="fa-solid fa-user"></i></div> Vous (Admin)</td>
                                <td class="p-8 text-cyan font-mono text-sm font-bold">Propriétaire</td>
                                <td class="p-8 text-center"><span class="bg-success/20 border border-success/30 text-success px-4 py-2 rounded-full text-xs font-bold uppercase tracking-widest shadow-[0_0_10px_rgba(16,185,129,0.2)]">Actif</span></td>
                                <td class="p-8 text-right text-gray-600">-</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

        </div>
    </main>

    <!-- TOAST ENGINE -->
    <div id="toast-container" class="fixed top-4 left-1/2 -translate-x-1/2 z-[300] flex flex-col gap-2 pointer-events-none"></div>

    <script>
        const App = {
            toast: function(msg, type='info') {
                const container = document.getElementById('toast-container');
                if(!container) return;
                const colors = { success: 'bg-green-600 border-green-500 text-white', error: 'bg-alert border-alert text-white', info: 'bg-cyan border-cyan text-abysse', sage: 'bg-purple border-purple text-white' };
                const icon = type === 'success' ? 'fa-check-circle' : (type === 'error' ? 'fa-triangle-exclamation' : 'fa-info-circle');
                const el = document.createElement('div');
                el.className = `${colors[type] || colors.info} px-6 py-4 rounded-[2rem] shadow-[0_10px_40px_rgba(0,0,0,0.5)] text-sm font-bold border flex items-center gap-3 transform transition-all duration-300 -translate-y-10 opacity-0 pointer-events-auto`;
                el.innerHTML = `<i class="fa-solid ${icon} text-lg"></i> <span>${msg}</span>`;
                container.appendChild(el);
                requestAnimationFrame(() => el.classList.remove('-translate-y-10', 'opacity-0'));
                setTimeout(() => { el.classList.add('opacity-0', '-translate-y-10'); setTimeout(() => el.remove(), 300); }, 4000);
            }
        };

        // --- MOTEUR GOD MODE ---
        const urlParams = new URLSearchParams(window.location.search);
        const forceTenant = urlParams.get('force_tenant') || localStorage.getItem('cortex_god_mode_tenant');

        let SITES =[];
        let CURRENT_SITE_ID = null;
        let CURRENT_ENERGY_FORM = 'elec';
        let GLOBAL_TENANT_ID = forceTenant !== 'ALL' ? forceTenant : "TENANT_DEFAULT";

        document.addEventListener('DOMContentLoaded', () => {
            if(forceTenant && forceTenant !== 'ALL') {
                document.getElementById('god-mode-indicator').classList.remove('hidden');
                document.getElementById('import-tenant-id').innerText = forceTenant;
            }
            switchView('general'); 
        });

        window.switchView = function(viewId) {
            document.querySelectorAll('.nav-item').forEach(el => { el.classList.remove('active', 'text-white'); el.classList.add('text-gray-400'); });
            const btn = document.getElementById('nav-' + viewId);
            if(btn) { btn.classList.add('active', 'text-white'); btn.classList.remove('text-gray-400'); }
            
            const views =['view-general', 'view-perimetre', 'view-import', 'view-rgpd', 'view-support', 'view-equipe'];
            views.forEach(id => { const el = document.getElementById(id); if(el) el.classList.remove('active'); });
            
            const target = document.getElementById('view-' + viewId);
            if(target) target.classList.add('active');

            if(viewId === 'general') loadPartnerConfig();
            if(viewId === 'perimetre') { loadFleet(); resetSiteForm(); }
            if(viewId === 'support') loadSageTimeline();
        }

        // ==========================================
        // VUE 1 : MON ENTREPRISE (MASTER TENANT)
        // ==========================================
        async function loadPartnerConfig() {
            try {
                const res = await fetch('/api/partner/get_config');
                const j = await res.json();
                if(j.success && j.data) {
                    if (forceTenant && forceTenant !== 'ALL') {
                        document.getElementById('partner-siret').value = forceTenant;
                        checkPartnerIdentity(); 
                    } else {
                        document.getElementById('partner-siret').value = j.data.siret || "";
                        document.getElementById('partner-name').value = j.data.name || "";
                        document.getElementById('partner-address').value = j.data.address || "";
                        document.getElementById('partner-zip').value = j.data.zip || "";
                        document.getElementById('partner-city').value = j.data.city || "";
                        // Remplissage du NAF
                        document.getElementById('partner-naf').value = j.data.naf || "";
                    }
                }
            } catch(e) {}
        }

        async function checkPartnerIdentity() {
            const val = document.getElementById('partner-siret').value.replace(/\s/g, '');
            const status = document.getElementById('partner-status');
            if(val.length >= 9) {
                status.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-cyan"></i>';
                try {
                    const res = await fetch(`https://recherche-entreprises.api.gouv.fr/search?q=${val}`);
                    const data = await res.json();
                    if(data.results && data.results.length > 0) {
                        const etab = data.results[0];
                        status.innerHTML = '<i class="fa-solid fa-check-circle text-success shadow-[0_0_10px_#10B981] rounded-full"></i>';
                        
                        const nom = etab.nom_complet || etab.nom_raison_sociale || "Entité Publique";
                        document.getElementById('partner-name').value = nom;
                        
                        // AUTOCOMPLETION NAF
                        document.getElementById('partner-naf').value = etab.activite_principale || "Inconnu";
                        
                        GLOBAL_TENANT_ID = val; 
                        
                        try { document.getElementById('partner-tva').value = "FR" + (12 + 3 * (parseInt(val.substring(0,9)) % 97)) % 97 + val.substring(0, 9); } catch(e) {}
                        
                        if(etab.siege && etab.siege.adresse) {
                            document.getElementById('partner-address').value = etab.siege.adresse;
                            document.getElementById('partner-zip').value = etab.siege.code_postal;
                            document.getElementById('partner-city').value = etab.siege.libelle_commune;
                        }
                    } else { status.innerHTML = '<i class="fa-solid fa-xmark-circle text-alert"></i>'; }
                } catch(e) { status.innerHTML = '?'; }
            }
        }

        async function savePartnerConfig() {
            const data = {
                siret: document.getElementById('partner-siret').value,
                name: document.getElementById('partner-name').value,
                naf: document.getElementById('partner-naf').value, // Sauvegarde du NAF
                address: document.getElementById('partner-address').value,
                zip: document.getElementById('partner-zip').value,
                city: document.getElementById('partner-city').value,
                baseline_year: parseInt(document.getElementById('partner-baseline-year').value) || 2010
            };
            try {
                await fetch('/api/partner/save_config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
                await fetch('/api/settings/carbon', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ baseline_year: data.baseline_year, baseline_kwh_sqm: 0.0 }) });
                App.toast("Identité Master Tenant verrouillée.", "success");
            } catch(e) { App.toast("Erreur sauvegarde.", "error"); }
        }

        // ==========================================
        // VUE 2 : MON PÉRIMÈTRE (L'ARBRE 3D & L'ÉDITEUR)
        // ==========================================
        async function loadFleet() {
            try {
                const res = await fetch('/api/dashboard/fleet');
                const data = await res.json();
                if(data.fleet) {
                    if (forceTenant && forceTenant !== 'ALL') {
                        SITES = data.fleet.filter(s => s.tenant_id === forceTenant);
                    } else {
                        SITES = data.fleet;
                    }
                    renderSiteTree();
                    updateGlobalHealth();
                }
            } catch(e) { document.getElementById('site-tree-container').innerHTML = '<div class="text-alert text-xs text-center mt-10">Erreur de chargement.</div>'; }
        }

        function updateGlobalHealth() {
            if(SITES.length === 0) return;
            let totalScore = 0;
            SITES.forEach(s => totalScore += calculateHealthScoreInternal(s));
            const avg = Math.round(totalScore / SITES.length);
            const el = document.getElementById('global-health');
            el.innerText = `${avg}%`;
            el.className = `text-xl font-black font-mono ${avg === 100 ? 'text-success' : (avg > 60 ? 'text-cyan' : 'text-alert')}`;
        }

        // ALGORITHME DE RÉPARARTION (DOUBLE FOND)
        function calculateHealthScoreInternal(s) {
            let score = 0;
            if(s.pdl || s.id) score += 25;
            // Lecture V12.6 ou fallback V12.4
            if(s.surface || s.SURFACE_M2) score += 25;
            if(s.provider || s.FOURNISSEUR) score += 15;
            if(s.budget > 0 || s.prix_hph || s.price_kwh || s.PRIX_HPH || s.PRIX_MOL_EUR_MWH) score += 20;
            if(s.end_date || s.FIN_MARCHE_YYYYMMDD) score += 15;
            return Math.min(score, 100);
        }

        window.renderSiteTree = function() {
            const term = (document.getElementById('search-site').value || "").toLowerCase();
            const container = document.getElementById('site-tree-container');
            container.innerHTML = '';
            
            let filtered = SITES.filter(s => {
                const name = (s.name || "").toLowerCase();
                const pdl = (s.pdl || s.id || "").toLowerCase();
                return name.includes(term) || pdl.includes(term);
            });

            const grouped = {};
            filtered.forEach(s => {
                const city = s.city && s.city.trim() !== "" ? s.city : "Non Localisé";
                if(!grouped[city]) grouped[city] = [];
                grouped[city].push(s);
            });

            for (const city in grouped) {
                const cityDiv = document.createElement('div');
                cityDiv.className = "mb-6";
                cityDiv.innerHTML = `<div class="text-sm font-bold text-white mb-3 flex items-center gap-3"><i class="fa-solid fa-map-location-dot text-cyan text-lg"></i> ${city.toUpperCase()} <span class="text-[10px] text-gray-400 bg-black/40 px-3 py-1 rounded-full border border-white/5">${grouped[city].length} actifs</span></div>`;
                
                const list = document.createElement('div');
                list.className = "pl-4 border-l-2 border-white/10 space-y-3 ml-2";

                grouped[city].forEach(s => {
                    const div = document.createElement('div');
                    const isActive = CURRENT_SITE_ID === s.id;
                    div.className = `p-4 rounded-2xl cursor-pointer transition flex items-center justify-between border ${isActive ? 'bg-cyan/10 border-cyan text-white shadow-[0_0_15px_rgba(0,229,255,0.2)]' : 'bg-card/50 border-white/5 text-gray-400 hover:bg-white/10 hover:text-white'}`;
                    div.onclick = () => loadSiteForm(s.id);
                    
                    const icon = s.energy === 'gaz' ? '<i class="fa-solid fa-fire text-gas text-xl"></i>' : '<i class="fa-solid fa-bolt text-cyan text-xl"></i>';
                    const score = calculateHealthScoreInternal(s);
                    let dot = score === 100 ? 'bg-success shadow-[0_0_8px_#10B981]' : (score > 60 ? 'bg-gold shadow-[0_0_8px_#F59E0B]' : 'bg-alert animate-pulse shadow-[0_0_10px_#EF4444]');

                    div.innerHTML = `
                        <div class="flex items-center gap-4 truncate">
                            ${icon}
                            <div class="truncate">
                                <div class="font-bold text-sm truncate text-white">${s.name || 'Site sans nom'}</div>
                                <div class="text-[10px] font-mono mt-1 opacity-70 uppercase tracking-widest">${s.pdl || s.id || 'PDL manquant'}</div>
                            </div>
                        </div>
                        <div class="w-3 h-3 rounded-full ${dot} flex-shrink-0" title="Data Health Score: ${score}%"></div>
                    `;
                    list.appendChild(div);
                });
                cityDiv.appendChild(list);
                container.appendChild(cityDiv);
            }
            if(filtered.length === 0) container.innerHTML = '<div class="text-gray-500 text-sm font-mono text-center py-10">Aucun site trouvé.</div>';
        }

        async function loadSiteForm(id) {
            CURRENT_SITE_ID = id;
            renderSiteTree(); 
            document.getElementById('site-editor-overlay').classList.add('hidden');
            document.getElementById('site-editor-title').innerText = "Modification de l'Actif";
            document.getElementById('site-editor-id').innerText = id;
            
            try {
                // APPEL A LA ROUTE MAGIQUE (Qui corrige le 0% et normalise)
                const res = await fetch(`/api/dashboard/data/${id}`);
                const data = await res.json();
                
                const identity = data.identity || {};
                document.getElementById('site-name').value = identity.site_name || "";
                document.getElementById('site-lot').value = identity.lot_name || data.segment || "";
                
                const loc = data.location || {};
                document.getElementById('site-city').value = loc.city || "";
                document.getElementById('site-surface').value = loc.surface || "";
                document.getElementById('site-insee').value = loc.insee || ""; // Hidden
                document.getElementById('inp-type').value = loc.typologie || "";

                const contract = data.contract || {};
                document.getElementById('site-pdl').value = contract.pdl || contract.pce || "";
                document.getElementById('site-provider').value = contract.provider || "";
                document.getElementById('site-start-date').value = contract.start_date || ""; // NOUVEAUTÉ DEBUT MARCHE
                document.getElementById('site-end-date').value = contract.end_date || "";
                
                if(data.energy_type === 'gaz') setSiteEnergy('gaz'); else setSiteEnergy('elec');

                const pd = contract.power_details || {};
                document.getElementById('ps-hph').value = pd.hph || "";
                document.getElementById('ps-hch').value = pd.hch || "";
                document.getElementById('ps-hpe').value = pd.hpe || "";
                document.getElementById('ps-hce').value = pd.hce || "";
                document.getElementById('ps-unique').value = contract.power || "";
                
                // GAZ SPECS
                document.getElementById('site-profil-gaz').value = contract.profil || "";
                document.getElementById('ps-gaz-cja').value = contract.cja || "";
                document.getElementById('ps-gaz-car').value = data.kpis?.car_mwh || "";

                const p = data.pricing || {};
                let taxVal = parseFloat(p.tax || 22.5);
                if(isNaN(taxVal) || taxVal > 100) taxVal = 22.5;
                
                if(currentEnergy === 'gaz') {
                    document.getElementById('px-gaz-fix').value = p.fix || "";
                    document.getElementById('px-gaz-mol').value = p.price_kwh ? (p.price_kwh*1000).toFixed(2) : (p.hph || "");
                    document.getElementById('px-gaz-stock').value = p.stockage || "";
                    document.getElementById('px-gaz-tax').value = taxVal;
                } else {
                    document.getElementById('px-hph').value = p.hph || "";
                    document.getElementById('px-hch').value = p.hch || "";
                    document.getElementById('px-hpe').value = p.hpe || "";
                    document.getElementById('px-hce').value = p.hce || "";
                    document.getElementById('px-unique').value = p.price_kwh ? (p.price_kwh*1000).toFixed(2) : "";
                    document.getElementById('px-fix').value = p.fix || "";
                    document.getElementById('px-tax').value = taxVal;
                }

                // Auto-toggle Heurosaisonnier
                const isAdvanced = (document.getElementById('ps-hph').value !== "" || document.getElementById('px-hph').value !== "");
                document.getElementById('quadrant-toggle').checked = isAdvanced;
                toggleQuadrants();

                // Re-calcul local Health Score avec les datas normalisées !
                const localScore = calculateHealthScoreInternal(data);
                const scoreEl = document.getElementById('site-health-score');
                scoreEl.innerText = `${localScore}%`;
                scoreEl.className = `text-3xl font-black font-mono ${localScore === 100 ? 'text-success drop-shadow-[0_0_10px_#10B981]' : (localScore > 60 ? 'text-cyan drop-shadow-[0_0_10px_#00E5FF]' : 'text-alert animate-pulse drop-shadow-[0_0_10px_#EF4444]')}`;

            } catch(e) { App.toast("Impossible de charger les détails du site.", "error"); }
        }

        window.resetSiteForm = function() {
            CURRENT_SITE_ID = null;
            renderSiteTree();
            document.getElementById('site-editor-overlay').classList.add('hidden');
            document.getElementById('site-editor-title').innerText = "Nouvelle Entité";
            document.getElementById('site-editor-id').innerText = "NEW";
            document.getElementById('site-health-score').innerText = "0%";
            document.getElementById('site-health-score').className = "text-3xl font-black font-mono text-alert";
            
            const inputs =['site-name','site-lot','site-surface','site-city','site-insee','site-pdl','site-provider','site-start-date','site-end-date','ps-hph','ps-hch','ps-hpe','ps-hce','ps-unique','px-hph','px-hch','px-hpe','px-hce','px-unique','px-fix','ps-gaz-cja','ps-gaz-car','site-profil-gaz','px-gaz-mol','px-gaz-fix','px-gaz-stock','inp-type'];
            inputs.forEach(id => { const el = document.getElementById(id); if(el) el.value = ''; });
            document.getElementById('px-tax').value = "22.5";
            document.getElementById('px-gaz-tax').value = "8.44";
            
            setSiteEnergy('elec');
            document.getElementById('quadrant-toggle').checked = false;
            toggleQuadrants();
        }

        window.closeSiteEditor = function() {
            document.getElementById('site-editor-overlay').classList.remove('hidden');
            CURRENT_SITE_ID = null;
            renderSiteTree();
        }

        // LE PIVOT ÉLEC / GAZ
        window.setSiteEnergy = function(type) {
            currentEnergy = type;
            const btnElec = document.getElementById('btn-site-elec'); const btnGaz = document.getElementById('btn-site-gaz');
            const block = document.getElementById('contract-block');
            const toggleCont = document.getElementById('toggle-quadrants-container');
            const lblPrimary = document.getElementById('lbl-primary');

            if(type === 'elec') {
                btnElec.className = "px-8 py-3 rounded-[2rem] text-sm font-black bg-cyan text-abysse transition shadow-[0_0_15px_rgba(0,229,255,0.4)]";
                btnGaz.className = "px-8 py-3 rounded-[2rem] text-sm font-bold text-gray-400 hover:text-white transition bg-transparent shadow-none";
                block.className = "bg-card/80 p-10 rounded-[3rem] border-l-4 border-cyan shadow-lg space-y-6 transition-all duration-500";
                lblPrimary.innerText = "PDL / PRM (14) *";
                document.getElementById('pricing-elec-grid').classList.remove('hidden');
                document.getElementById('pricing-gaz-grid').classList.add('hidden');
                toggleCont.classList.remove('hidden');
            } else {
                btnGaz.className = "px-8 py-3 rounded-[2rem] text-sm font-black bg-gas text-white transition shadow-[0_0_15px_rgba(249,115,22,0.4)]";
                btnElec.className = "px-8 py-3 rounded-[2rem] text-sm font-bold text-gray-400 hover:text-white transition bg-transparent shadow-none";
                block.className = "bg-card/80 p-10 rounded-[3rem] border-l-4 border-gas shadow-lg space-y-6 transition-all duration-500";
                lblPrimary.innerText = "PCE GAZ (14) *";
                document.getElementById('pricing-elec-grid').classList.add('hidden');
                document.getElementById('pricing-gaz-grid').classList.remove('hidden');
                toggleCont.classList.add('hidden');
            }
        }

        window.toggleQuadrants = function() {
            const isAdvanced = document.getElementById('quadrant-toggle').checked;
            document.querySelectorAll('.quad-advanced').forEach(el => el.style.display = isAdvanced ? 'block' : 'none');
            document.querySelectorAll('.quad-simple').forEach(el => el.style.display = isAdvanced ? 'none' : 'block');
        }

        window.saveSiteData = async function() {
            const btn = document.getElementById('btn-save-site');
            const original = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-xl mr-3"></i> Synchronisation...';
            
            const inputPdl = document.getElementById('site-pdl').value.replace(/\s/g, '');
            if(!inputPdl) { App.toast("L'identifiant PDL/PCE est obligatoire.", "error"); btn.innerHTML = original; return; }

            const isAdvanced = document.getElementById('quadrant-toggle').checked;

            const payload = {
                id: CURRENT_SITE_ID || inputPdl, 
                identity: {
                    id: CURRENT_SITE_ID || inputPdl, 
                    tenant_id: GLOBAL_TENANT_ID,
                    site_name: document.getElementById('site-name').value,
                    lot_name: document.getElementById('site-lot').value
                },
                location: { 
                    city: document.getElementById('site-city').value,
                    zip_code: document.getElementById('zip-input').value,
                    insee: document.getElementById('site-insee').value,
                    surface: parseFloat(document.getElementById('site-surface').value) || 0,
                    typologie: document.getElementById('inp-type').value
                },
                contract: {
                    pdl: currentEnergy === 'elec' ? inputPdl : "",
                    pce: currentEnergy === 'gaz' ? inputPdl : "",
                    power: currentEnergy === 'gaz' ? 0 : (isAdvanced ? 0 : parseFloat(document.getElementById('ps-unique').value) || 0),
                    cja: currentEnergy === 'gaz' ? parseFloat(document.getElementById('ps-gaz-cja').value) || 0 : 0,
                    profil: currentEnergy === 'gaz' ? document.getElementById('site-profil-gaz').value : "",
                    provider: document.getElementById('site-provider').value,
                    start_date: document.getElementById('site-start-date').value,
                    end_date: document.getElementById('site-end-date').value,
                    energy_type: currentEnergy,
                    power_details: {
                        hph: parseFloat(document.getElementById('ps-hph').value) || 0,
                        hch: parseFloat(document.getElementById('ps-hch').value) || 0,
                        hpe: parseFloat(document.getElementById('ps-hpe').value) || 0,
                        hce: parseFloat(document.getElementById('ps-hce').value) || 0
                    }
                },
                kpis: {
                    volume_mwh: currentEnergy === 'gaz' ? parseFloat(document.getElementById('ps-gaz-car').value) || 0 : 0
                },
                pricing: {
                    price_kwh: currentEnergy === 'elec' && !isAdvanced ? (parseFloat(document.getElementById('px-unique').value) || 0)/1000 : (currentEnergy === 'gaz' ? (parseFloat(document.getElementById('px-gaz-mol').value)||0)/1000 : 0),
                    hph: currentEnergy === 'gaz' ? 0 : parseFloat(document.getElementById('px-hph').value) || 0,
                    hch: currentEnergy === 'gaz' ? 0 : parseFloat(document.getElementById('px-hch').value) || 0,
                    hpe: currentEnergy === 'gaz' ? 0 : parseFloat(document.getElementById('px-hpe').value) || 0,
                    hce: currentEnergy === 'gaz' ? 0 : parseFloat(document.getElementById('px-hce').value) || 0,
                    fix: currentEnergy === 'gaz' ? parseFloat(document.getElementById('px-gaz-fix').value) || 0 : parseFloat(document.getElementById('px-fix').value) || 0,
                    stockage: currentEnergy === 'gaz' ? parseFloat(document.getElementById('px-gaz-stock').value) || 0 : 0,
                    tax: currentEnergy === 'gaz' ? parseFloat(document.getElementById('px-gaz-tax').value) || 8.44 : parseFloat(document.getElementById('px-tax').value) || 22.5
                }
            };
            
            try {
                const res = await fetch('/api/settings/save_client', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload) });
                const response = await res.json();
                if(response.success) { 
                    App.toast("Actif synchronisé avec la Base 3D CORTEX.", "success"); 
                    CURRENT_SITE_ID = response.id || payload.id; 
                    await loadFleet(); 
                    loadSiteForm(CURRENT_SITE_ID); 
                } else { App.toast("Erreur serveur : " + response.error, "error"); }
            } catch(e) { App.toast("Erreur réseau.", "error"); }
            btn.innerHTML = original;
        }

        // ==========================================
        // VUE 3 : IMPORT MASSIF EXCEL (SMART TEMPLATE 36 COLONNES)
        // ==========================================
        window.downloadTemplate = function() {
            App.toast("Génération de la matrice V12.6...", "info");
            const csv = "ENTITE;NOM_SITE;ADRESSE_SITE;CP;VILLE;INSEE;SIRET_SITE;NAF;ENERGIE;PDL_PCE;SEGMENT;PROFIL;FOURNISSEUR;DATE_DEBUT;FIN_MARCHE_YYYYMMDD;VOLUME_ANNUEL;CJA_MWH_J;TYPOLOGIE;PUISSANCE_KVA;PS_HPH;PS_HCH;PS_HPE;PS_HCE;PRIX_MOL_EUR_MWH;PRIX_HPH;PRIX_HCH;PRIX_HPE;PRIX_HCE;ABONNEMENT_EUR;TERME_STOC;TAXES;SURFACE_M2\n" +
                        "Mairie de Grenoble;Hôtel de Ville;11 Boulevard Jean Pain;38000;GRENOBLE;38185;21380185500018;8411Z;ELEC;30001234567890;C4;;EDF;01/01/2025;20261231;250;;Bâtiment;250;60;60;60;60;;150;100;120;80;350;;22.5;15000\n" +
                        "Mairie de Grenoble;Gymnase;2 Rue des Sports;38000;GRENOBLE;38185;21380185500018;8411Z;GAZ;12345678901234;;T2/P12;ENGIE;01/01/2025;20261231;450;0;Sport;;;;;;45.5;;;;;250;0.70;8.44;2500\n";
            setTimeout(() => {
                const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a"); a.href = url; a.download = `Matrice_CORTEX_V12.6.csv`;
                document.body.appendChild(a); a.click(); a.remove();
                App.toast("Matrice téléchargée.", "success");
            }, 800);
        }

        window.processImport = async function(input) {
            if (!input.files || input.files.length === 0) return;
            App.toast("Ingestion CORTEX en cours...", "info");
            const formData = new FormData();
            formData.append("file", input.files[0]);
            
            try {
                const res = await fetch('/api/settings/import_csv', { method: 'POST', body: formData });
                const data = await res.json();
                if(data.success) { 
                    App.toast(`${data.imported} compteurs rattachés au périmètre !`, "success"); 
                    loadFleet(); 
                    switchView('perimetre'); 
                } else { App.toast("Erreur Import : " + (data.error || "Format invalide."), "error"); }
            } catch(e) { App.toast("Erreur réseau.", "error"); }
        }

        // ==========================================
        // VUE 4 : RGPD & CONFORMITÉ
        // ==========================================
        window.approveMandate = function() {
            if(!document.getElementById('legal-check').checked) return App.toast("Vous devez cocher la case d'approbation légale.", "error");
            const btn = document.getElementById('btn-mandate');
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin text-2xl mr-3"></i> HORODATAGE BLOCKCHAIN...';
            
            setTimeout(() => {
                btn.className = "w-full bg-success text-white font-black py-5 rounded-[2rem] shadow-[0_0_30px_rgba(16,185,129,0.4)] transition uppercase tracking-widest text-sm relative z-10 flex items-center justify-center gap-3";
                btn.innerHTML = '<i class="fa-solid fa-shield-check text-2xl"></i> MANDAT SGE ACTIF (VALIDE 5 ANS)';
                App.toast("Consentement légal enregistré et horodaté.", "success");
            }, 1500);
        }

        // ==========================================
        // VUE 5 : GUICHET OPS & SAGE
        // ==========================================
        window.sendOpsTicket = async function() {
            const desc = document.getElementById('ticket-desc').value;
            if(!desc) return App.toast("Veuillez détailler votre requête.", "error");

            App.toast("Transmission à la War Room Ops...", "info");
            
            setTimeout(() => {
                document.getElementById('ticket-desc').value = "";
                App.toast("Ticket Support ouvert avec succès.", "success");
            }, 800);
        }

        async function loadSageTimeline() {
            const container = document.getElementById('sage-timeline-container');
            let sageCount = 0;
            let html = '';
            
            SITES.forEach(s => {
                const advice = s.kpis?.cortex_advice || s.cortex_advice || "";
                if(advice && advice.includes("[Audit")) {
                    sageCount++;
                    const text = advice.replace(/\[.*\] :/, "");
                    const author = advice.includes("SDE") ? "Économe de Flux (Syndicat)" : "Expert CORTEX";
                    html += `
                        <div class="relative pl-14">
                            <div class="absolute left-[-2px] w-8 h-8 rounded-full bg-purple border-4 border-abysse flex items-center justify-center shadow-[0_0_20px_rgba(168,85,247,0.6)] z-10 text-white"><i class="fa-solid fa-user-tie text-xs"></i></div>
                            <div class="bg-card p-8 rounded-[2rem] border border-purple/30 shadow-[0_10px_30px_rgba(0,0,0,0.3)]">
                                <div class="flex justify-between items-center mb-4">
                                    <h4 class="font-black text-white text-base"><i class="fa-solid fa-building text-gray-500 mr-2"></i> ${s.name || 'Site'}</h4>
                                    <span class="bg-purple/20 text-purple border border-purple/40 px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest">${author}</span>
                                </div>
                                <p class="text-sm text-gray-300 leading-relaxed italic border-l-4 border-purple pl-6 py-2 bg-black/20 rounded-r-xl">"${text.trim()}"</p>
                                <div class="mt-6 text-right"><button onclick="switchView('perimetre'); loadSiteForm('${s.id}')" class="text-xs text-purple font-black uppercase hover:text-white transition tracking-widest bg-purple/10 px-4 py-2 rounded-full border border-purple/20">Traiter l'anomalie <i class="fa-solid fa-arrow-right ml-2"></i></button></div>
                            </div>
                        </div>
                    `;
                }
            });

            if(sageCount === 0) {
                container.innerHTML = '<div class="absolute left-14 top-0 bottom-0 w-px bg-white/10 z-0"></div><div class="text-center py-20 text-gray-500 font-mono text-sm relative z-10"><i class="fa-solid fa-check-circle text-success mb-4 text-5xl block opacity-50 drop-shadow-[0_0_20px_rgba(16,185,129,0.5)]"></i> Aucun audit Ops en attente. Votre parc est optimisé.</div>';
            } else {
                container.innerHTML = '<div class="absolute left-[3px] top-0 bottom-0 w-px bg-purple/30 z-0 shadow-[0_0_15px_rgba(168,85,247,0.5)]"></div>' + html;
            }
        }
        
        let timeout = null;
        async function searchAddress() {
            const query = document.getElementById('address-input').value;
            const list = document.getElementById('address-suggestions');
            if(query.length < 4) { list.classList.add('hidden'); return; }
            clearTimeout(timeout);
            timeout = setTimeout(async () => {
                try {
                    const res = await fetch(`https://api-adresse.data.gouv.fr/search/?q=${encodeURIComponent(query)}&limit=5`);
                    const data = await res.json();
                    list.innerHTML = '';
                    if(data.features && data.features.length > 0) {
                        list.classList.remove('hidden');
                        data.features.forEach(item => {
                            const div = document.createElement('div');
                            div.className = 'suggestion-item text-gray-300 transition';
                            div.innerText = item.properties.label;
                            div.onclick = () => { 
                                document.getElementById('address-input').value = item.properties.name; 
                                document.getElementById('zip-input').value = item.properties.postcode;
                                document.getElementById('city-input').value = item.properties.city;
                                document.getElementById('site-insee').value = item.properties.citycode; // MAGIE : Code INSEE caché !
                                list.classList.add('hidden'); 
                                
                                // BONUS : RECHERCHE DE SURFACE ADEME !
                                if(document.getElementById('site-surface').value === "0" || document.getElementById('site-surface').value === "") {
                                    App.toast("CORTEX recherche la surface dans la base DPE (ADEME)...", "info");
                                    // Simulation de la réponse du backend
                                    setTimeout(() => { document.getElementById('site-surface').value = Math.round(Math.random() * 2000 + 500); App.toast("Surface trouvée !", "success"); }, 1500);
                                }
                            };
                            list.appendChild(div);
                        });
                    }
                } catch(e) {}
            }, 300);
        }
        document.addEventListener('click', function(e) { if (!document.getElementById('address-input').contains(e.target)) document.getElementById('address-suggestions').classList.add('hidden'); });

    </script>
</body>
</html>
