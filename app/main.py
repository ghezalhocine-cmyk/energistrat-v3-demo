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

# ==============================================================================
# LE MOTEUR PDF DE SECOURS (ANTI-CRASH)
# ==============================================================================
class FallbackPDFBuilder:
    def __init__(self):
        self.logo_svg = """<svg width="140" height="40" viewBox="0 0 140 40" xmlns="http://www.w3.org/2000/svg"><rect width="30" height="30" rx="8" y="5" fill="#00E5FF"/><path d="M10 15L20 15L15 25Z" fill="#001529"/><text x="40" y="27" font-family="Arial, sans-serif" font-size="20" font-weight="900" fill="#001529">ENERGISTRAT</text></svg>"""
    
    def generate_bilan_ag(self, client_id, data, fin, kpis): 
        return "<h1>Générateur PDF de Secours</h1>"
    
    def generate_bilan_ag_cluster(self, cluster_name, site_count, vol_total, budget_total, vol_elec, vol_gaz, ghost_total): 
        return "<h1>Générateur PDF Grappe</h1>"

# ==============================================================================
# FALLBACK MOCKS (SÉCURITÉ CLOUD RUN)
# ==============================================================================
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
    def get_all_companies(self): return []
    def get_all_contacts(self): return[]
    def get_all_deals(self): return []
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

# ==============================================================================
# AUTO-LOADER CORTEX ROBUSTE (ISOLEMENT ANTI-DOMINO)
# ==============================================================================
def load_module(mod_name, obj_name, mock_instance=None):
    paths =[f"app.core.{mod_name}", f"core.{mod_name}", mod_name]
    for path in paths:
        try:
            mod = importlib.import_module(path)
            return getattr(mod, obj_name)
        except ModuleNotFoundError:
            continue
        except Exception as e:
            print(f"⚠️ Erreur chargement {path} : {e}")
            continue
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

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"],
)

# === SETUP DIRECTORIES ===
BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR): 
    os.makedirs(DATA_DIR, exist_ok=True)
    
TEMPLATE_DIR = os.path.join(BASE_DIR, "app/templates")
if not os.path.exists(TEMPLATE_DIR): 
    TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
    
templates = Jinja2Templates(directory=TEMPLATE_DIR)

STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR): 
    STATIC_DIR = os.path.join(BASE_DIR, "app/static")
if os.path.exists(STATIC_DIR): 
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ==============================================================================
# PYDANTIC MODELS (DATA UNITY 3D)
# ==============================================================================
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

# === UTILS ===
def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return [json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

def get_safe_id(raw_id): 
    return str(raw_id).replace('/', '_').replace(' ', '_').replace('+', '').replace(',', '').strip()

def get_market_ref():
    m = db.get_setting("Market")
    if m: return m
    return { "updated_at": datetime.now().isoformat(), "elec": { "cal_n1": 85.0 }, "gaz": { "peg_n1": 35.0 }, "trve": { "elec_c5": 230.0 }, "targets": { "c5": 190.0 } }

async def get_current_user(request: Request):
    t = request.cookies.get("access_token")
    if not t: return None
    if t.startswith("Bearer "): t = t.split(" ")[1]
    return auth.verify_token(t)

# ==============================================================================
# OUTILS (API GOUVERNEMENT & ADEME)
# ==============================================================================
def fetch_company_info_api_gouv(siren: str) -> dict:
    """Interroge l'API Recherche Entreprises de l'État (Gratuit & Zéro Mock)"""
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

def fetch_surface_ademe(address: str, zip_code: str = "") -> float:
    """API ADEME (DPE Tertiaire) pour déduire la surface automatiquement sans clé API."""
    if not address: return 0.0
    try:
        query = urllib.parse.quote(f"{address} {zip_code}".strip())
        url = f"https://data.ademe.fr/data-fair/api/v1/datasets/dpe-v2-tertiaire-2/lines?q={query}&size=1&select=surface_utile"
        req = urllib.request.Request(url, headers={'User-Agent': 'Energistrat-SaaS/12.6'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            if data.get("results") and len(data["results"]) > 0:
                return float(data["results"][0].get("surface_utile", 0.0))
    except Exception: pass
    return 0.0

# ==========================================
# AUTHENTIFICATION & ROUTAGE INTELLIGENT
# ==========================================
@app.get("/login", response_class=HTMLResponse)
async def view_login(request: Request, user = Depends(get_current_user)):
    if user: 
        if user.get("role") == "ADMIN": return RedirectResponse(url="/ops_nexus")
        return RedirectResponse(url=f"/{user.get('role', 'settings')}")
    res = templates.TemplateResponse("login.html", {"request": request})
    res.delete_cookie("access_token")
    return res

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
    response.delete_cookie("access_token")
    return RedirectResponse(url="/login")
    # ==============================================================================
# ENERGISTRAT V12.6 - MAIN.PY (PARTIE 2/2)
# ==============================================================================

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
        data['identity']['id'] = str(data.get('COMPTEUR_PDL') or data.get('PDL') or data.get('pdl') or data.get('PCE') or data.get('pce') or data.get('id') or f"GEN_{uuid.uuid4().hex[:8]}")
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
    
    try: data['location']['surface'] = float(str(data.get('SURFACE_M2') or data.get('surface') or 0.0).replace(',', '.'))
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

    try: data['kpis']['pmax_kw'] = float(str(data.get('PUISSANCE_POINTE_MAX') or data.get('pmax_kw') or 0).replace(',', '.'))
    except: pass

    return data

# ==========================================
# API CRM V12.6 (MODÈLE 3D, SOLVABILITÉ & INLINE EDIT)
# ==========================================

@app.post("/api/crm/lead")
async def api_create_crm_lead_and_convert(payload: CRMCompany3DModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
        
    owner_id = user.get("uid")
    now = datetime.now().isoformat()

    gouv_data = fetch_company_info_api_gouv(payload.siren)
    
    solvency_score = "INCONNU"
    solvency_msg = "Non vérifié"
    final_name = payload.company_name
    final_address = payload.address
    final_city = payload.city
    final_naf = payload.naf
    
    if gouv_data.get("success"):
        solvency_score = gouv_data["solvency_score"]
        solvency_msg = gouv_data["solvency_msg"]
        final_name = gouv_data["name"] or final_name
        final_address = gouv_data["address"] or final_address
        final_city = gouv_data["city"] or final_city
        final_naf = gouv_data["naf"] or final_naf

    company_id = f"COMP_{payload.siren.replace(' ', '') if payload.siren else uuid.uuid4().hex[:8]}"
    company_data = {
        "siren": payload.siren, "name": final_name, "holding_name": payload.holding_name or final_name,
        "naf": final_naf, "address": final_address, "city": final_city, "website": "", "logo": "", 
        "solvency_score": solvency_score, "solvency_msg": solvency_msg, "created_at": now, "owner_id": owner_id, "source": payload.source
    }
    db.save_company(company_id, company_data)

    deal_id = f"DEAL_{uuid.uuid4().hex[:12]}"
    deal_data = {
        "company_id": company_id, "name": f"{final_name} - {payload.pipeline.upper()}", "pipeline": payload.pipeline, 
        "stage": "LEAD", "volume_est": 0.0, "commission_est": 0.0, "products":[], "documents":[],
        "created_at": now, "owner_id": owner_id
    }
    db.save_deal(deal_id, deal_data)

    db.save_activity(f"ACT_{uuid.uuid4().hex[:12]}", {
        "deal_id": deal_id, "type": "SYSTEM", "title": "Création Entité 3D", 
        "description": f"Pipeline: {payload.pipeline} | Solvabilité: {solvency_score}", "timestamp": now, "owner_id": owner_id
    })
    
    return JSONResponse({"success": True, "deal_id": deal_id, "company_id": company_id, "solvency": solvency_score})

@app.post("/api/crm/edit/{entity_type}/{entity_id}")
async def api_inline_edit(entity_type: str, entity_id: str, payload: CRMInlineEditModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
        
    data = None
    if entity_type == "company": data = db.get_company(entity_id); save_func = db.save_company
    elif entity_type == "contact": data = db.get_contact(entity_id); save_func = db.save_contact
    elif entity_type == "site": data = db.get_site(entity_id); save_func = db.save_site
        
    if not data: return JSONResponse({"success": False, "error": "Entité introuvable."})
        
    data[payload.field] = payload.value
    data[f"{payload.field}_manual_override"] = True 
    save_func(entity_id, data)
    return JSONResponse({"success": True, "message": "Mise à jour synchronisée."})

@app.post("/api/crm/company/{company_id}/contact")
async def api_add_contact_3d(company_id: str, payload: CRMContactModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
        
    contact_id = f"CONT_{uuid.uuid4().hex[:12]}"
    contact_data = {
        "company_id": company_id, "site_id": payload.site_id, "firstname": payload.firstname, "lastname": payload.lastname,
        "role": payload.role, "email": payload.email, "phone": payload.phone, "linkedin": "", 
        "created_at": datetime.now().isoformat(), "owner_id": user.get("uid")
    }
    db.save_contact(contact_id, contact_data)
    return JSONResponse({"success": True, "contact_id": contact_id})

@app.post("/api/crm/company/{company_id}/site")
async def api_add_site_3d(company_id: str, payload: CRMSiteModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
        
    site_id = f"SITE_{payload.pdl_pce.replace(' ', '')}"
    site_data = {
        "identity": {"id": site_id, "tenant_id": company_id, "site_name": payload.site_name},
        "location": {"address": payload.address},
        "contract": {"pdl": payload.pdl_pce if payload.energy_type == "elec" else "", "pce": payload.pdl_pce if payload.energy_type == "gaz" else "", "power": payload.power_kva, "fta": payload.fta, "profil": payload.profile},
        "kpis": {"volume_mwh": payload.car_mwh},
        "meta": {"is_gas": payload.energy_type == "gaz", "is_active": payload.is_active}
    }
    db.save_site(site_id, site_data)
    return JSONResponse({"success": True, "site_id": site_id})

@app.get("/api/crm/pipeline/{pipe_type}")
async def api_get_crm_pipeline(pipe_type: str, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Accès réservé"}, 401)
    
    all_deals = db.get_all_deals()
    all_comps = {c.get("id"): c for c in db.get_all_companies()}
    all_conts = {c.get("id"): c for c in db.get_all_contacts()}
    real_sites = db.get_all_sites()

    try:
        old_leads = db.get_all_leads()
        for old in old_leads:
            old_pipe = str(old.get("pipeline") or "saas").lower()
            if old_pipe == pipe_type.lower():
                all_deals.append({
                    "id": old.get("id"), "legacy": True, "name": old.get("company_name", "Ancien Lead"), 
                    "stage": old.get("stage", "LEAD"), "volume_est": float(old.get("volume_est") or 0.0), 
                    "commission_est": float(old.get("commission_est") or 0.0), "pipeline": old_pipe, 
                    "products": old.get("products",[]), "documents": old.get("documents",[]), "_old_data": old
                })
    except: pass

    formatted_deals =[]
    
    for deal in all_deals:
        deal_pipe = str(deal.get("pipeline") or "saas").lower()
        if deal_pipe != pipe_type.lower(): continue
            
        if not deal.get("legacy"):
            comp = all_comps.get(deal.get("company_id"), {})
            deal_contacts =[c for c in all_conts.values() if c.get("company_id") == comp.get("id")]
            company_sites =[s for s in real_sites if s.get("identity", {}).get("tenant_id") == comp.get("id")]
            total_vol = sum([float(s.get("kpis", {}).get("volume_mwh", 0)) for s in company_sites])
            
            saas_alerts =[]
            for s in company_sites:
                if s.get("kpis", {}).get("is_alert"): saas_alerts.append(f"⚠️ Dépassement détecté sur {s.get('identity', {}).get('site_name', 'Site')}")

            vol = float(deal.get("volume_est") or total_vol)
            naf = comp.get("naf", "DEFAULT")
            intel = crm_engine.generate_icebreaker(naf, pipe_type) 
            comms = float(deal.get("commission_est") or crm_engine.calculate_commission(vol, pipe_type, saas_mrr=299))
            
            formatted_deals.append({
                "id": deal.get("id"), "company_id": comp.get("id"), "holding_name": comp.get("holding_name") or comp.get("name", "Inconnu"),
                "name": deal.get("name", "Inconnu"), "city": comp.get("city", ""),
                "solvency_score": comp.get("solvency_score", "INCONNU"), "solvency_msg": comp.get("solvency_msg", "Non vérifié"),
                "naf": naf, "volume": vol, "stage": deal.get("stage", "LEAD"), "all_contacts": deal_contacts, "sites_count": len(company_sites),
                "saas_alerts": saas_alerts, "intelligence": intel, "commission_est": comms, "products": deal.get("products",[]), "documents": deal.get("documents",[])
            })
        else:
            old = deal.get("_old_data", {})
            vol = float(deal.get("volume_est", 0.0))
            naf = old.get("naf", "DEFAULT")
            comms = float(deal.get("commission_est") or crm_engine.calculate_commission(vol, pipe_type, saas_mrr=299))
            fake_contact = {
                "id": old.get("id"), "firstname": str(old.get("contact_firstname", "")).strip(),
                "lastname": str(old.get("contact_lastname", "")).strip(), "role": old.get("contact_role", "Contact"), 
                "phone": old.get("contact_phone", ""), "email": old.get("contact_email", ""), "linkedin": old.get("linkedin", "")
            }
            formatted_deals.append({
                "id": old.get("id"), "company_id": old.get("id"), "holding_name": old.get("company_name", "Ancien Client"),
                "name": deal.get("name", "Ancien Deal"), "city": old.get("city", ""),
                "solvency_score": "INCONNU", "solvency_msg": "Legacy (Créé avant API)",
                "naf": naf, "volume": vol, "stage": old.get("stage", "LEAD"), "all_contacts":[fake_contact], "sites_count": 0, "saas_alerts":[],
                "intelligence": crm_engine.generate_icebreaker(naf, pipe_type), "commission_est": comms, "products": deal.get("products",[]), "documents": deal.get("documents",[])
            })

    return JSONResponse(json_compliant({"success": True, "pipeline": formatted_deals}))

@app.post("/api/crm/contact/{contact_id}/linkedin")
async def update_contact_linkedin(contact_id: str, payload: UpdateFieldModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    contact = db.get_contact(contact_id)
    if contact:
        contact["linkedin"] = payload.value; db.save_contact(contact_id, contact); return JSONResponse({"success": True})
    legacy = db.get_setting(contact_id)
    if legacy: legacy["linkedin"] = payload.value; db.save_setting(contact_id, legacy); return JSONResponse({"success": True}) 
    return JSONResponse({"success": False, "error": "Introuvable"})

@app.post("/api/crm/company/{company_id}/website")
async def update_company_website(company_id: str, payload: UpdateFieldModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    company = db.get_company(company_id)
    if company:
        company["website"] = payload.value; db.save_company(company_id, company); return JSONResponse({"success": True})
    legacy = db.get_setting(company_id)
    if legacy:
        legacy["website"] = payload.value; db.save_setting(company_id, legacy); return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Introuvable"})

@app.post("/api/crm/deal/move")
async def api_move_crm_deal(payload: DealMoveModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Accès refusé"}, 401)
    deal_data = db.get_deal(payload.deal_id)
    if deal_data:
        deal_data["stage"] = payload.new_stage
        db.save_deal(payload.deal_id, deal_data)
        db.save_activity(f"ACT_{uuid.uuid4().hex[:12]}", {"deal_id": payload.deal_id, "type": "STAGE_CHANGE", "title": f"Passage à l'étape {payload.new_stage}", "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Deal introuvable"})

@app.post("/api/crm/email/send")
async def api_send_crm_email(payload: EmailRequestModel, background_tasks: BackgroundTasks, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    deal_data = db.get_deal(payload.deal_id)
    to_email = "test@energistrat.com"
    if deal_data and deal_data.get("primary_contact_id"):
        cont = db.get_contact(deal_data["primary_contact_id"])
        if cont: to_email = cont.get("email", to_email)
    background_tasks.add_task(crm_engine.send_sales_email, to_email=to_email, subject=payload.subject, html_content=payload.body, lead_id=payload.deal_id)
    db.save_activity(f"ACT_{uuid.uuid4().hex[:12]}", {"deal_id": payload.deal_id, "type": "EMAIL", "title": f"Email: {payload.subject}", "description": payload.body, "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
    return JSONResponse({"success": True, "message": "Email placé en file d'attente."})

@app.get("/api/crm/track/open/{deal_id}")
async def api_track_email_open(deal_id: str):
    db.save_activity(f"ACT_{uuid.uuid4().hex[:12]}", {"deal_id": deal_id, "type": "TRACKING", "title": "Le client a ouvert un email", "timestamp": datetime.now().isoformat(), "owner_id": "SYSTEM"})
    pixel = base64.b64decode("R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")
    return Response(content=pixel, media_type="image/gif")

@app.post("/api/crm/activity")
async def api_create_crm_activity(payload: CRMActivityModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    db.save_activity(f"ACT_{uuid.uuid4().hex[:12]}", {"deal_id": payload.deal_id, "type": payload.type, "title": payload.type, "description": payload.description, "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
    return JSONResponse({"success": True})

@app.get("/api/crm/deal/{deal_id}/activities")
async def api_get_crm_activities(deal_id: str, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Accès réservé"}, 401)
    return JSONResponse({"success": True, "activities": db.get_deal_activities(deal_id)})

@app.get("/api/crm/products")
async def api_get_products(user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Accès réservé"}, 401)
    return JSONResponse({"success": True, "products": db.get_all_products()})

@app.post("/api/crm/products")
async def api_save_product(payload: ProductModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    prod_id = f"PROD_{uuid.uuid4().hex[:8]}"
    db.save_product(prod_id, payload.dict())
    return JSONResponse({"success": True, "product_id": prod_id})

@app.delete("/api/crm/products/{prod_id}")
async def api_delete_product(prod_id: str, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    db.delete_product(prod_id)
    return JSONResponse({"success": True})

@app.post("/api/crm/deal/{deal_id}/products")
async def api_update_deal_products(deal_id: str, payload: DealProductsUpdateModel, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    deal = db.get_deal(deal_id)
    is_legacy = False
    if not deal:
        deal = db.get_setting(deal_id)
        is_legacy = True
        if not deal: return JSONResponse({"error": "Deal introuvable."}, 404)

    all_prods = {p["id"]: p for p in db.get_all_products()}
    total_vol = 0.0
    total_comm = 0.0
    detailed_lines =[]

    for item in payload.items:
        prod = all_prods.get(item.product_id)
        if not prod: continue
        cat = prod.get("category", "SERVICE")
        price = float(prod.get("unit_price", 0.0))
        qty = float(item.quantity)
        rate = float(prod.get("comm_rate", 1.0))
        line_comm = price * qty * rate 
        if cat == "COURTAGE": total_vol += qty
        total_comm += line_comm
        detailed_lines.append({"product_id": prod["id"], "name": prod["name"], "category": cat, "quantity": qty, "unit_price": price, "line_comm": line_comm})

    deal["products"] = detailed_lines
    deal["volume_est"] = total_vol
    deal["commission_est"] = total_comm
    if is_legacy: db.save_setting(deal_id, deal)
    else: db.save_deal(deal_id, deal)
    db.save_activity(f"ACT_{uuid.uuid4().hex[:12]}", {"deal_id": deal_id, "type": "SYSTEM", "title": "Devis (CPQ) mis à jour", "description": f"Nouvelle commission : {total_comm:,.2f} €", "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
    return JSONResponse({"success": True})

@app.post("/api/crm/deal/{deal_id}/upload")
async def api_upload_deal_file(deal_id: str, file: UploadFile = File(...), user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    deal = db.get_deal(deal_id)
    is_legacy = False
    if not deal:
        deal = db.get_setting(deal_id)
        is_legacy = True
        if not deal: return JSONResponse({"error": "Deal introuvable"}, 404)
    
    file_meta = {"id": f"DOC_{uuid.uuid4().hex[:8]}", "name": file.filename, "size": f"{round(len(await file.read()) / 1024)} KB", "uploaded_at": datetime.now().isoformat()}
    if "documents" not in deal: deal["documents"] =[]
    deal["documents"].append(file_meta)
    if is_legacy: db.save_setting(deal_id, deal)
    else: db.save_deal(deal_id, deal)
    
    db.save_activity(f"ACT_{uuid.uuid4().hex[:12]}", {"deal_id": deal_id, "type": "DOCUMENT", "title": "Document ajouté", "description": file.filename, "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
    return JSONResponse({"success": True, "document": file_meta})

# ==========================================
# API CORTEX ACADEMY, PRICER & OUTILS OPS
# ==========================================

@app.get("/api/v1/academy/modules")
async def api_get_academy_modules(user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    return JSONResponse({"success": True, "modules": db.get_all_lms_modules()})

@app.get("/api/v1/academy/progress")
async def api_get_lms_progress(user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    return JSONResponse({"success": True, "progress": db.get_user_lms_progress(user.get("uid"))})

@app.get("/api/v1/academy/arena")
async def api_get_arena_training(user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    return JSONResponse({"success": True, "questions": academy_engine.get_daily_training(user.get("uid"))})

@app.post("/api/v1/academy/answer")
async def api_post_academy_answer(payload: AcademyAnswerRequest, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    return JSONResponse(academy_engine.process_answer(user.get("uid"), payload.question_id, payload.is_correct))

@app.post("/api/v1/cpq/quote")
async def api_generate_cpq_quote(payload: CPQQuoteRequest, user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    if not pricer_engine: return JSONResponse({"success": False, "error": "Moteur Pricer hors ligne."})
    return JSONResponse(pricer_engine.build_quote(payload.dict()))

@app.post("/api/v1/cpq/ingest_dqe")
async def api_ingest_dqe(file: UploadFile = File(...), user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    if not PANDAS_READY: return JSONResponse({"error": "Pandas introuvable sur le serveur."}, 500)
    try:
        content = await file.read()
        df = pd.read_excel(io.BytesIO(content))
        pdl_col = next((c for c in df.columns if any(k in str(c).lower() for k in["pdl", "pce", "point de", "référence"])), None)
        vol_col = next((c for c in df.columns if any(k in str(c).lower() for k in["volume", "conso", "kwh", "mwh", "quantité"])), None)
        type_col = next((c for c in df.columns if any(k in str(c).lower() for k in["type", "usage", "ep", "bat", "catégorie"])), None)
        
        if not pdl_col or not vol_col: return JSONResponse({"success": False, "error": "Impossible d'identifier les colonnes PDL et Volume dans ce fichier."})
            
        lots = {"EP (Éclairage Public)": 0, "BAT (Bâtiments)": 0, "Non Classifié": 0}
        sites_count = 0
        for idx, row in df.iterrows():
            vol = row[vol_col]
            try: vol_val = float(vol)
            except: continue
            
            usage = str(row[type_col]).upper() if type_col else ""
            if "EP" in usage or "ECLAIRAGE" in usage: lots["EP (Éclairage Public)"] += vol_val
            elif "BAT" in usage or "MAIRIE" in usage or "ECOLE" in usage: lots["BAT (Bâtiments)"] += vol_val
            else: lots["Non Classifié"] += vol_val
            sites_count += 1
            
        total_mwh = sum(lots.values())
        if total_mwh > 50000: lots = {k: v/1000 for k, v in lots.items()}
            
        return JSONResponse({"success": True, "filename": file.filename, "sites_detected": sites_count, "total_volume_mwh": round(sum(lots.values()), 2), "suggested_lots": {k: round(v, 2) for k, v in lots.items() if v > 0}})
    except Exception as e: return JSONResponse({"success": False, "error": f"Erreur Smart-Mapping : {str(e)}"})

@app.post("/api/v1/cpq/ingest_curves")
async def api_ingest_curves(files: List[UploadFile] = File(...), user = Depends(get_current_user)):
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    if not PANDAS_READY: return JSONResponse({"error": "Pandas introuvable."}, 500)
    
    total_volume_mwh = 0
    max_power_kw = 0
    processed_count = 0
    for file in files:
        try:
            content = await file.read()
            df = pd.read_csv(io.BytesIO(content), sep=';', on_bad_lines='skip', nrows=5000)
            val_col = next((c for c in df.columns if "valeur" in str(c).lower() or "conso" in str(c).lower()), None)
            if val_col:
                vol = (pd.to_numeric(df[val_col], errors='coerce').sum() / 6) / 1000
                pmax = pd.to_numeric(df[val_col], errors='coerce').max()
                if vol > 0:
                    total_volume_mwh += vol
                    max_power_kw = max(max_power_kw, pmax)
                    processed_count += 1
        except: continue
    return JSONResponse({"success": True, "files_processed": processed_count, "aggregated_volume_mwh": round(total_volume_mwh, 2), "aggregated_peak_kw": round(max_power_kw, 2)})

@app.get("/api/ops/sentinel/alerts")
async def api_get_sentinel_alerts(): return db.get_sentinel_alerts()

@app.post("/api/ops/sentinel/run")
async def api_run_sentinel_scan(user = Depends(get_current_user)): return JSONResponse({"success": True, "message": "Scan SGE déclenché."})

@app.get("/api/tools/sniper/market")
async def api_sniper_market(user = Depends(get_current_user)):
    if not rte: return JSONResponse({"success": False, "error": "Module RTE hors ligne"})
    return JSONResponse(rte.get_wholesale_market())

@app.get("/api/rte/live")
async def get_rte_live_data(user = Depends(get_current_user)):
    if not rte: return JSONResponse({"success": False, "error": "Module RTE hors ligne"})
    return JSONResponse(rte.get_pulse_dashboard_data())

@app.post("/api/dealdesk/analyze")
async def api_dealdesk_analyze(request: Request):
    b = await request.json()
    q = str(b.get('query', '')).strip().lower()
    if not q: return JSONResponse({"success": False, "error": "Requête vide."})
    
    sd = next((s for s in db.get_all_sites() if q in str(s.get('contract', {}).get('pdl', '')).strip() or q in str(s.get('identity', {}).get('site_name', '')).strip().lower()), None)
    if not sd: return JSONResponse({"success": False, "error": "Introuvable."})
    
    try: vol = cortex.enrich_site_financials(sd).get('volume_mwh', 0)
    except: vol = 0
        
    p = float(sd.get('contract', {}).get('power', 0))
    is_micro = vol < 36 and p <= 36
    return JSONResponse({"success": True, "site": { "name": sd.get('identity',{}).get('site_name', 'Inconnu'), "pdl": sd.get('contract',{}).get('pdl', 'N/A'), "volume": round(vol, 2), "power": p }, "segment": "B2B_HEAVY" if vol > 5000 else ("C4_MID" if p > 36 or vol > 250 else "C5_MASS"), "legal": {"is_micro": is_micro}})

@app.get("/api/ops/orphans")
async def api_get_orphans(keyword: str = "", user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    orphans =[]
    kw = keyword.lower().strip()
    for s in db.get_all_sites():
        identity = s.get('identity', {})
        tenant_id = identity.get('tenant_id')
        name = str(identity.get('site_name', '')).lower()
        if not tenant_id or tenant_id == "ORPHELIN" or tenant_id == "" or (kw and kw in name):
            orphans.append({"id": get_safe_id(identity.get('id', '')), "name": identity.get('site_name', 'Inconnu'), "pdl": str(s.get('contract', {}).get('pdl', '')), "city": s.get('location', {}).get('city', ''), "current_tenant": tenant_id or "Aucun"})
    return JSONResponse({"success": True, "orphans": orphans})

@app.post("/api/ops/adopt")
async def api_adopt_sites(payload: AdoptionRequest, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    updated_count = 0
    for site_id in payload.site_ids:
        data = db.get_site(site_id)
        if data:
            if 'identity' not in data: data['identity'] = {}
            data['identity']['tenant_id'] = payload.target_tenant_id
            if db.save_site(site_id, data): updated_count += 1
    return JSONResponse({"success": True, "updated_count": updated_count})

@app.get("/api/ops/tenants")
async def api_get_tenants(user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    return JSONResponse({"success": True, "tenants": db.get_all_users()})

@app.post("/api/ops/create_tenant")
async def api_create_tenant(payload: TenantCreateRequest, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    try:
        tenant_id = str(payload.siret).replace(" ", "")
        data = { "tenant_id": tenant_id, "siret": tenant_id, "name": payload.name, "created_by": "ADMIN" }
        db.save_user_profile(f"TENANT_{tenant_id}", data)
        return JSONResponse({"success": True, "tenant": data})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)}, 500)

# ==========================================
# API : DATA UNITY & IMPORT MASSIF (ZERO MOCK / 36 COLONNES)
# ==========================================

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
        raw_id = data.get("identity", {}).get("id") or data.get("id") or data.get("siret") or f"CLI_{uuid.uuid4().hex[:8]}"
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

# ==========================================
# API : RSE (LOI ELAN / CSRD) ET BUDGETS M57 (SDE/MAIRIE)
# ==========================================
@app.get("/api/settings/m57")
async def api_get_m57(user = Depends(get_current_user)):
    tenant_id = db.get_user_profile(user.get("uid")).get("tenant_id", "DEFAULT") if user else "DEFAULT"
    data = db.get_setting(f"M57_{tenant_id}")
    return JSONResponse(data if data else {"bp_elec": 0, "bp_gaz": 0, "consumed_elec": 0, "consumed_gaz": 0})

@app.post("/api/settings/m57")
async def api_save_m57(payload: M57SettingsModel, user = Depends(get_current_user)):
    tenant_id = db.get_user_profile(user.get("uid")).get("tenant_id", "DEFAULT") if user else "DEFAULT"
    db.save_setting(f"M57_{tenant_id}", payload.dict())
    return JSONResponse({"success": True})

@app.get("/api/settings/carbon")
async def api_get_carbon(user = Depends(get_current_user)):
    tenant_id = db.get_user_profile(user.get("uid")).get("tenant_id", "DEFAULT") if user else "DEFAULT"
    data = db.get_setting(f"CARBON_{tenant_id}")
    return JSONResponse(data if data else {"baseline_year": 2010, "baseline_kwh_sqm": 0.0})

@app.post("/api/settings/carbon")
async def api_save_carbon(payload: CarbonSettingsModel, user = Depends(get_current_user)):
    tenant_id = db.get_user_profile(user.get("uid")).get("tenant_id", "DEFAULT") if user else "DEFAULT"
    db.save_setting(f"CARBON_{tenant_id}", payload.dict())
    return JSONResponse({"success": True})

# ==========================================
# API : DASHBOARD & FLEET (LE COEUR DU SYSTÈME 3D)
# ==========================================
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
            "city": city, "zip": loc.get('zip_code', ''), "volume": final_vol, 
            "energy": "gaz" if contract.get('energy_type') == 'gaz' else "elec", 
            "segment": contract.get('segment') or identity.get('lot_name') or '-',
            "provider": prov, "budget": final_budget, "ghost_savings": float(kpis.get('ghost_savings', 0)), 
            "power": contract.get('power', 0), "pdl": contract.get('pdl') or contract.get('pce', '-'), 
            "surface": loc.get('surface', 0), "tenant_id": identity.get('tenant_id', 'Orphelin'), "naf": identity.get('naf', 'DEFAULT')
        })
    return JSONResponse(json_compliant({"fleet": fleet_list, "count": len(fleet_list)}))

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str, response: Response, user = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    
    data = db.get_site(client_id)
    if not data: return JSONResponse({"error": "Site introuvable"}, 404)
    
    profile = db.get_user_profile(user.get("uid"))
    is_admin = user.get("role") == "ADMIN"
    
    t_id = data.get("identity", {}).get("tenant_id") or data.get("tenant_id") or profile.get("tenant_id", "ORPHELIN")
    data = normalize_full_data(data, t_id)
    
    if not is_admin and data["identity"]["tenant_id"] != profile.get("tenant_id", "ORPHELIN"):
        return JSONResponse({"error": "Accès refusé."}, 403)
        
    financials = cortex.enrich_site_financials(data) if cortex else {'meta':{'is_gas':False}, 'kpis':{'unit_price_kwh':0, 'pmc_eur_mwh':0, 'ghost_savings':0}, 'volume_mwh':0, 'budget_annual':0, 'pricing_details':{}}
    mr = get_market_ref()
    ma = cortex.analyze_market_position(financials['kpis']['unit_price_kwh'], mr, is_gas=financials['meta']['is_gas']) if cortex else {"status": "ANALYSE"}
    if 'ref_price' not in ma: ma = {"status": "ANALYSE", "ref_price": mr['gaz']['peg_n1'] if financials['meta']['is_gas'] else mr['elec']['cal_n1'], "details": {"market_label": "PEG N+1" if financials['meta']['is_gas'] else "CAL N+1"}}

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

    return JSONResponse(json_compliant({
        "energy_type": "gaz" if contract.get('energy_type') == 'gaz' else "elec", 
        "identity": data.get('identity', {}), "location": data.get('location', {}), 
        "technical": data.get('technical', {}), "financials": data.get('financials', {}),
        "contract": {
            "pdl": contract.get('pdl'), "pce": contract.get('pce'), "provider": contract.get('provider', 'Inconnu'), 
            "segment": display_segment or contract.get('segment', '-'), "start_date": contract.get('start_date'), 
            "end_date": contract.get('end_date'), "power": contract.get('power'), "cja": contract.get('cja'),
            "p_max": contract.get('p_max'), "fta": contract.get('fta'), "profil": contract.get('profil'), 
            "power_details": pd_details, "ps_hph": contract.get('ps_hph'), "ps_hch": contract.get('ps_hch'), 
            "ps_hpe": contract.get('ps_hpe'), "ps_hce": contract.get('ps_hce')
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
            if not df_gz.empty: df_gz.to_excel(w, index=False, sheet_name="DATA_GAZ")
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
