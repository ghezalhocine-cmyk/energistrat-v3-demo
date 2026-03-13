import os
import math
import io
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
    def generate_bilan_ag(self, client_id, data, fin, kpis): return "<h1>Générateur PDF de Secours</h1>"
    def generate_bilan_ag_cluster(self, cluster_name, site_count, vol_total, budget_total, vol_elec, vol_gaz, ghost_total): return "<h1>Générateur PDF Grappe</h1>"

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
    def get_all_companies(self): return[]
    def get_all_contacts(self): return[]
    def get_all_deals(self): return[]
    def save_lead(self, i, d): return True
    def save_company(self, i, d): return True
    def save_contact(self, i, d): return True
    def save_deal(self, i, d): return True
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
    def generate_icebreaker(self, naf, pipe_type="saas"): return {"naf": naf, "pain_points": "Mode Démo", "pitch": "Argumentaire non disponible."}
    def analyze_customer_health(self, cv, pv, lc): return {"status": "STABLE", "color": "text-success", "action_required": "RAS", "usage_score": 100, "is_churn_risk": False}
    def calculate_commission(self, v, is_s, saas_mrr=0): return round(v * 1.0, 2)
    def send_sales_email(self, *args, **kwargs): return True

# ==============================================================================
# AUTO-LOADER CORTEX ROBUSTE
# ==============================================================================
def load_module(mod_name, obj_name, mock_instance=None):
    paths =[f"app.core.{mod_name}", f"core.{mod_name}", mod_name]
    for path in paths:
        try:
            mod = importlib.import_module(path)
            return getattr(mod, obj_name)
        except ModuleNotFoundError: continue
        except Exception as e:
            print(f"⚠️ Erreur {path} : {e}")
            continue
    print(f"🔴 Auto-Loader: Impossible de trouver {mod_name}. Mock activé.")
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
pdf_builder = load_module("cortex_pdf", "pdf_builder", FallbackPDFBuilder())

app = FastAPI(title="ENERGISTRAT V3", version="EMPIRE-V12-CRM-PHASE3")

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

# === PYDANTIC MODELS ===
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

def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return[json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

def get_safe_id(raw_id): return str(raw_id).replace('/', '_').replace(' ', '_').replace('+', '').replace(',', '').strip()

def get_market_ref():
    m = db.get_setting("Market")
    return m if m else { "updated_at": datetime.now().isoformat(), "elec": { "cal_n1": 85.0 }, "gaz": { "peg_n1": 35.0 }, "trve": { "elec_c5": 230.0 }, "targets": { "c5": 190.0 } }

async def get_current_user(request: Request):
    t = request.cookies.get("access_token")
    if not t: return None
    if t.startswith("Bearer "): t = t.split(" ")[1]
    return auth.verify_token(t)

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

# ==========================================
# MOTEUR CRM V12 (HUBSPOT KILLER - PHASE 3.1)
# ==========================================

class CRMLeadModel(BaseModel):
    siret: str
    company_name: str
    naf: str
    city: str
    contact_firstname: str
    contact_lastname: str
    contact_role: str
    contact_email: str
    contact_phone: str
    source: str
    pipeline: str 

class DealMoveModel(BaseModel):
    deal_id: str
    new_stage: str

class EmailRequestModel(BaseModel):
    deal_id: str
    subject: str
    body: str

class CRMActivityModel(BaseModel):
    deal_id: str
    type: str
    description: str

class UpdateFieldModel(BaseModel):
    value: str

@app.post("/api/crm/lead")
async def api_create_crm_lead_and_convert(payload: CRMLeadModel, user = Depends(get_current_user)):
    """Convertit DIRECTEMENT le Lead en Company, Contact et Deal"""
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    
    owner_id = user.get("uid")
    now = datetime.now().isoformat()

    domain = ""
    logo_url = ""
    try:
        if "@" in payload.contact_email:
            parts = payload.contact_email.split("@")
            domain = parts[1].lower()
            if domain not in["gmail.com", "yahoo.fr", "hotmail.fr", "orange.fr", "wanadoo.fr"]:
                logo_url = f"https://logo.clearbit.com/{domain}"
    except: pass

    company_id = f"COMP_{payload.siret or uuid.uuid4().hex[:8]}"
    company_data = {
        "siret": payload.siret, "name": payload.company_name, "naf": payload.naf,
        "city": payload.city, "website": domain, "logo": logo_url, "created_at": now, "owner_id": owner_id
    }
    db.save_company(company_id, company_data)

    contact_id = f"CONT_{uuid.uuid4().hex[:12]}"
    contact_data = {
        "company_id": company_id, "firstname": payload.contact_firstname, "lastname": payload.contact_lastname,
        "role": payload.contact_role, "email": payload.contact_email, "phone": payload.contact_phone,
        "linkedin": "", "created_at": now, "owner_id": owner_id
    }
    db.save_contact(contact_id, contact_data)

    deal_id = f"DEAL_{uuid.uuid4().hex[:12]}"
    deal_data = {
        "company_id": company_id, "primary_contact_id": contact_id, "name": f"{payload.company_name} - {payload.pipeline.upper()}",
        "pipeline": payload.pipeline, "stage": "LEAD", "volume_est": 0.0, "products":[], "created_at": now, "owner_id": owner_id
    }
    db.save_deal(deal_id, deal_data)

    act_id = f"ACT_{uuid.uuid4().hex[:12]}"
    db.save_activity(act_id, {"deal_id": deal_id, "type": "SYSTEM", "title": "Création du compte", "description": f"Import initial.", "timestamp": now, "owner_id": owner_id})

    return JSONResponse({"success": True, "deal_id": deal_id})

@app.get("/api/crm/pipeline/{pipe_type}")
async def api_get_crm_pipeline(pipe_type: str, user = Depends(get_current_user)):
    """Assemble les Deals V12 et passe le type de pipeline à l'IA."""
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Accès réservé"}, 401)
    
    all_deals = db.get_all_deals()
    all_comps = {c.get("id"): c for c in db.get_all_companies()}
    all_conts = {c.get("id"): c for c in db.get_all_contacts()}

    try:
        old_leads = db.get_all_leads()
        for old in old_leads:
            if str(old.get("pipeline", "")).lower() == pipe_type.lower():
                all_deals.append({"id": old.get("id"), "legacy": True, "name": old.get("company_name", "Ancien Lead"), "stage": old.get("stage", "LEAD"), "volume_est": float(old.get("volume_est") or 0.0), "pipeline": old.get("pipeline"), "_old_data": old})
    except: pass

    formatted_deals =[]
    for deal in all_deals:
        if str(deal.get("pipeline", "")).lower() != pipe_type.lower(): continue
            
        if not deal.get("legacy"):
            comp = all_comps.get(deal.get("company_id"), {})
            cont = all_conts.get(deal.get("primary_contact_id"), {})
            
            vol = float(deal.get("volume_est", 0.0))
            naf = comp.get("naf", "DEFAULT")
            
            intel = crm_engine.generate_icebreaker(naf, pipe_type) # IA Dynamique
            health = crm_engine.analyze_customer_health(vol, vol,[])
            comms = crm_engine.calculate_commission(vol, pipe_type, saas_mrr=299)

            formatted_deals.append({
                "id": deal.get("id"), "company_id": comp.get("id"), "contact_id": cont.get("id"),
                "name": comp.get("name", deal.get("name")), "city": comp.get("city", ""),
                "website": comp.get("website", ""), "logo": comp.get("logo", ""), "naf": naf,
                "volume": vol, "stage": deal.get("stage", "LEAD"),
                "contact": {"name": f"{cont.get('firstname', '')} {cont.get('lastname', '')}".strip() or "Contact", "role": cont.get("role", "Décideur"), "phone": cont.get("phone", ""), "email": cont.get("email", ""), "linkedin": cont.get("linkedin", "")},
                "intelligence": intel, "health": health, "commission_est": comms, "last_contact": "Aujourd'hui"
            })
        else:
            old = deal.get("_old_data", {})
            vol = float(old.get("volume_est") or 0.0)
            naf = old.get("naf", "DEFAULT")
            intel = crm_engine.generate_icebreaker(naf, pipe_type) # IA Dynamique
            formatted_deals.append({
                "id": old.get("id"), "company_id": old.get("id"), "contact_id": old.get("id"),
                "name": old.get("company_name", "Inconnu"), "city": old.get("city", ""),
                "website": "", "logo": "", "naf": naf, "volume": vol, "stage": old.get("stage", "LEAD"),
                "contact": {"name": f"{old.get('contact_firstname', '')} {old.get('contact_lastname', '')}".strip(), "role": old.get("contact_role", "Contact"), "phone": old.get("contact_phone", ""), "email": old.get("contact_email", ""), "linkedin": ""},
                "intelligence": intel, "health": crm_engine.analyze_customer_health(vol, vol,[]), "commission_est": crm_engine.calculate_commission(vol, pipe_type, saas_mrr=299), "last_contact": old.get("last_contact", "Jamais")
            })

    return JSONResponse(json_compliant({"success": True, "pipeline": formatted_deals}))

@app.post("/api/crm/contact/{contact_id}/linkedin")
async def update_contact_linkedin(contact_id: str, payload: UpdateFieldModel, user = Depends(get_current_user)):
    """Met à jour l'URL LinkedIn d'un contact"""
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    
    contact = db.get_contact(contact_id)
    if contact:
        contact["linkedin"] = payload.value
        db.save_contact(contact_id, contact)
        return JSONResponse({"success": True})
        
    legacy = db.get_setting(contact_id)
    if legacy: return JSONResponse({"success": True}) 
    
    return JSONResponse({"success": False, "error": "Contact introuvable"})

@app.post("/api/crm/company/{company_id}/website")
async def update_company_website(company_id: str, payload: UpdateFieldModel, user = Depends(get_current_user)):
    """Met à jour l'URL du site web d'une société"""
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    
    company = db.get_company(company_id)
    if company:
        company["website"] = payload.value
        db.save_company(company_id, company)
        return JSONResponse({"success": True})
    return JSONResponse({"success": False, "error": "Société introuvable"})

@app.post("/api/crm/deal/move")
async def api_move_crm_deal(payload: DealMoveModel, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Accès refusé"}, 401)
    deal_data = db.get_deal(payload.deal_id)
    if deal_data:
        deal_data["stage"] = payload.new_stage
        db.save_deal(payload.deal_id, deal_data)
        act_id = f"ACT_{uuid.uuid4().hex[:12]}"
        db.save_activity(act_id, {"deal_id": payload.deal_id, "type": "STAGE_CHANGE", "title": f"Passage à l'étape {payload.new_stage}", "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
    else:
        lead_data = db.get_setting(payload.deal_id)
        if lead_data:
            lead_data["stage"] = payload.new_stage
            db.save_setting(payload.deal_id, lead_data)
    return JSONResponse({"success": True})

@app.post("/api/crm/email/send")
async def api_send_crm_email(payload: EmailRequestModel, background_tasks: BackgroundTasks, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    deal_data = db.get_deal(payload.deal_id)
    to_email = "test@energistrat.com"
    if deal_data and deal_data.get("primary_contact_id"):
        cont = db.get_contact(deal_data["primary_contact_id"])
        if cont: to_email = cont.get("email", to_email)
    background_tasks.add_task(crm_engine.send_sales_email, to_email=to_email, subject=payload.subject, html_content=payload.body, lead_id=payload.deal_id)
    act_id = f"ACT_{uuid.uuid4().hex[:12]}"
    db.save_activity(act_id, {"deal_id": payload.deal_id, "type": "EMAIL", "title": f"Email: {payload.subject}", "description": payload.body, "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
    return JSONResponse({"success": True, "message": "Email placé en file d'attente."})

@app.get("/api/crm/track/open/{deal_id}")
async def api_track_email_open(deal_id: str):
    act_id = f"ACT_{uuid.uuid4().hex[:12]}"
    db.save_activity(act_id, {"deal_id": deal_id, "type": "TRACKING", "title": "Le client a ouvert un email", "timestamp": datetime.now().isoformat(), "owner_id": "SYSTEM"})
    pixel = base64.b64decode("R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")
    return Response(content=pixel, media_type="image/gif")

@app.post("/api/crm/activity")
async def api_create_crm_activity(payload: CRMActivityModel, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Non autorisé"}, 401)
    act_id = f"ACT_{uuid.uuid4().hex[:12]}"
    db.save_activity(act_id, {"deal_id": payload.deal_id, "type": payload.type, "title": "Note manuelle" if payload.type == "NOTE" else payload.type, "description": payload.description, "timestamp": datetime.now().isoformat(), "owner_id": user.get("uid")})
    return JSONResponse({"success": True})

@app.get("/api/crm/deal/{deal_id}/activities")
async def api_get_crm_activities(deal_id: str, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return JSONResponse({"error": "Accès réservé"}, 401)
    activities = db.get_deal_activities(deal_id)
    return JSONResponse({"success": True, "activities": activities})

# ==========================================
# API CORTEX SENTINEL & RTE
# ==========================================
@app.get("/api/ops/sentinel/alerts")
async def api_get_sentinel_alerts(): 
    return db.get_sentinel_alerts()

@app.post("/api/ops/sentinel/run")
async def api_run_sentinel_scan(user = Depends(get_current_user)):
    return JSONResponse({"success": True, "message": "Scan SGE déclenché."})

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

# ==========================================
# L'OUTIL D'ADOPTION DE MASSE
# ==========================================
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
            orphans.append({ "id": get_safe_id(identity.get('id', '')), "name": identity.get('site_name', 'Inconnu'), "pdl": str(s.get('contract', {}).get('pdl', '')), "city": s.get('location', {}).get('city', ''), "current_tenant": tenant_id or "Aucun" })
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
# API MÉTIERS : M57, FORECAST, VOTES & LOM
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

@app.get("/api/forecast/simulate/{client_id}")
async def api_forecast_simulate(client_id: str, user = Depends(get_current_user)):
    site_data = db.get_site(client_id)
    if not site_data: return JSONResponse({"error": "Site introuvable"}, status_code=404)
    if forecast:
        try: return JSONResponse(json_compliant(forecast.simulate_5_years(site_data)))
        except: pass
    vol = float(site_data.get('kpis', {}).get('volume_mwh', 100))
    if vol == 0: vol = 100
    return JSONResponse({
        "labels":["N", "N+1", "N+2", "N+3", "N+4"],
        "dataset_trend":[vol, vol*1.02, vol*1.04, vol*1.06, vol*1.08],
        "dataset_sobriety":[vol, vol*0.9, vol*0.82, vol*0.75, vol*0.68],
        "gain_potential_mwh": round(vol * 1.5)
    })

@app.post("/api/vote")
async def api_register_vote(payload: VoteRequestModel, user = Depends(get_current_user)):
    db.save_setting(f"VOTE_{payload.site_id}_{uuid.uuid4().hex[:6]}", {"vote": payload.vote, "timestamp": datetime.now().isoformat()})
    return JSONResponse({"success": True})

@app.post("/api/legal/sign")
async def api_legal_sign(payload: LegalSignModel, user = Depends(get_current_user)):
    db.save_setting(f"LOM_{payload.site_id}_{uuid.uuid4().hex[:6]}", {"consent": payload.consent, "timestamp": datetime.now().isoformat()})
    return JSONResponse({"success": True})

@app.post("/api/physics/solar")
async def api_physics_solar(payload: SolarRequest, user = Depends(get_current_user)):
    if not physics: return JSONResponse({"success": False, "error": "Moteur Physique hors ligne"})
    try:
        lat, lon = physics.get_coordinates_from_address(payload.address)
        result = physics.simulate_solar_roi(lat, lon, payload.surface_roof, payload.electricity_price)
        if "error" in result: return JSONResponse({"success": False, "error": result["error"]})
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

# ==========================================
# API SUBVENTIONS & CERFA
# ==========================================
@app.get("/api/tools/subventions")
async def api_subventions_analyze(user = Depends(get_current_user)):
    profile = db.get_user_profile(user.get("uid")) if user else {}
    tid = profile.get("tenant_id", "ORPHELIN")
    is_admin = user and user.get("role") == "ADMIN"
    
    raw_sites = db.get_all_sites()
    results =[]
    total_enveloppe = 0

    for s in raw_sites:
        if "CLI_" in str(s.get('identity', {}).get('id')): continue
        if not is_admin and s.get("identity", {}).get("tenant_id") != tid: continue
        
        if cortex: s['computed_financials'] = cortex.enrich_site_financials(s)
        fin = s.get('computed_financials', {})
        loc = s.get('location', {})
        vol = float(fin.get('volume_mwh', 0) or s.get('kpis', {}).get('volume_mwh', 0))
        surface = float(loc.get('surface', 0))
        city = str(loc.get('city', '')).upper()
        
        if surface == 0:
            results.append({"id": get_safe_id(s.get('identity', {}).get('id', '')), "pdl": str(s.get('contract', {}).get('pdl') or s.get('contract', {}).get('pce') or "Inconnu"), "name": fin.get('meta', {}).get('site_label', 'Site Inconnu'), "city": city, "status": "MISSING_DATA", "reason": "Surface manquante."})
            continue
            
        zf = 1.3 if any(x in city for x in['LILLE', 'PARIS', 'STRASBOURG', 'LYON', 'NANCY', 'REIMS', 'METZ']) else (0.8 if any(x in city for x in['MARSEILLE', 'NICE', 'MONTPELLIER', 'TOULON', 'PERPIGNAN', 'NIMES']) else 1.0)
        zn = "H1" if zf == 1.3 else ("H3" if zf == 0.8 else "H2")
        
        aides =[]
        ghost = float(fin.get('kpis', {}).get('ghost_savings', 0))
        
        if surface >= 500 and ghost > (vol * 0.1): aides.append({"code": "BAT-TH-116", "nom": "Coup de Pouce GTB", "details": f"Surface ({surface}m²) × Forfait × Zone {zn}", "montant": round(((surface * 250 * zf) / 1000) * 6.50 * 1.5)})
        if surface > 0 and (vol * 1000) / surface > 300: aides.append({"code": "BAT-EN-101", "nom": "Isolation Thermique Toiture", "details": f"Surface toit ({round(surface * 0.3)}m²) × 1400 kWhc × Zone {zn}", "montant": round((((surface * 0.3) * 1400 * zf) / 1000) * 6.50)})
        if fin.get('meta', {}).get('is_gas', False) and vol > 500: aides.append({"code": "ADEME-CHALEUR", "nom": "Fonds Chaleur", "details": f"Substitution {round(vol)} MWh fossile × 25€", "montant": round(vol * 25)})
        
        t_site = sum(a['montant'] for a in aides)
        total_enveloppe += t_site
        results.append({"id": get_safe_id(s.get('identity', {}).get('id', '')), "pdl": str(s.get('contract', {}).get('pdl') or s.get('contract', {}).get('pce') or "Inconnu"), "name": fin.get('meta', {}).get('site_label', 'Site Inconnu'), "city": city, "status": "ELIGIBLE" if aides else "NON_ELIGIBLE", "aides": aides, "total_site": t_site, "reason": "Site optimisé." if not aides else ""})
    return JSONResponse({"success": True, "results": results, "total_enveloppe": round(total_enveloppe)})

@app.get("/api/tools/cerfa/{site_id}/{aide_code}", response_class=HTMLResponse)
async def generate_cerfa_pdf(site_id: str, aide_code: str, user = Depends(get_current_user)):
    try:
        if not user: return HTMLResponse("Non autorisé", status_code=401)
        data = db.get_site(site_id)
        if not data: return HTMLResponse(f"<h1>Erreur</h1><p>Site introuvable.</p>", status_code=404)
        
        i = data.get('identity', {}); l = data.get('location', {}); c = data.get('contract', {})
        titre = "MISE EN PLACE D'UN SYSTÈME DE GESTION TECHNIQUE DU BÂTIMENT (GTB)" if "116" in aide_code else ("ISOLATION DE COMBLES OU DE TOITURES" if "101" in aide_code else "OPÉRATION STANDARDISÉE")
        fiche = "BAT-TH-116" if "116" in aide_code else ("BAT-EN-101" if "101" in aide_code else aide_code)
        
        return HTMLResponse(content=f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>CERFA_{fiche}_{str(c.get('pdl') or c.get('pce') or 'N/A')}</title><style>@page {{ size: A4; margin: 15mm; }} body {{ font-family: Helvetica, Arial, sans-serif; font-size: 12px; }} h2 {{ background: #e0e0e0; padding: 5px; border: 1px solid black; }} .form-row {{ display: flex; border: 1px solid black; border-top: none; }} .form-label {{ width: 40%; padding: 8px; border-right: 1px solid black; font-weight: bold; background: #f9f9f9; }} .form-value {{ width: 60%; padding: 8px; font-family: monospace; }}</style></head><body onload="setTimeout(function(){{ window.print(); }}, 500);"><div style="display:flex; justify-content:space-between; border-bottom:2px solid black; padding-bottom:10px; margin-bottom:20px;"><div style="border:1px solid black; padding:10px; text-align:center; font-weight:bold; font-size:10px;">Liberté<br>Égalité<br>Fraternité<br><br>RÉPUBLIQUE FRANÇAISE</div><div style="text-align:center; flex:1;"><h1>ATTESTATION SUR L'HONNEUR</h1><p>Opérations d'économies d'énergie (CEE)</p></div><div style="border:1px solid black; padding:10px; text-align:center; font-weight:bold;">CERFA<br>N° 15404*01</div></div><h2>A - BÉNÉFICIAIRE</h2><div class="form-row" style="border-top:1px solid black;"><div class="form-label">Raison Sociale</div><div class="form-value">{str(i.get('site_name') or i.get('name') or 'N/A').upper()}</div></div><div class="form-row"><div class="form-label">N° SIRET</div><div class="form-value">{str(i.get('siret') or 'N/A')}</div></div><h2>B - LIEU DES TRAVAUX</h2><div class="form-row" style="border-top:1px solid black;"><div class="form-label">Adresse</div><div class="form-value">{str(l.get('address') or 'N/A')} - {str(l.get('city') or 'N/A').upper()}</div></div><div class="form-row"><div class="form-label">PDL / PCE</div><div class="form-value">{str(c.get('pdl') or c.get('pce') or 'N/A')}</div></div><div class="form-row"><div class="form-label">Surface</div><div class="form-value">{str(l.get('surface') or 'N/A')} m²</div></div><h2>C - OPÉRATION</h2><div class="form-row" style="border-top:1px solid black;"><div class="form-label">Fiche CEE</div><div class="form-value">{fiche}</div></div><div class="form-row"><div class="form-label">Nature</div><div class="form-value">{titre}</div></div><div style="margin-top:30px; border:1px solid black; padding:15px;"><b>Je soussigné(e) atteste sur l'honneur l'exactitude des informations. ENERGISTRAT est mandaté.</b></div><div style="margin-top:20px; display:flex; justify-content:space-between;"><div style="border:1px dashed gray; width:45%; height:100px; padding:10px;">Fait à: {str(l.get('city') or 'N/A').upper()}<br>Le: {datetime.now().strftime('%d/%m/%Y')}<br><b>Signature:</b></div><div style="border:1px dashed gray; width:45%; height:100px; padding:10px;"><b>Cachet:</b></div></div></body></html>""")
    except Exception as e: return HTMLResponse(f"<h1>Erreur Serveur</h1><p>{str(e)}</p><pre>{traceback.format_exc()}</pre>", status_code=500)

@app.get("/api/tools/bilan_ag/{client_id}", response_class=HTMLResponse)
async def api_generate_bilan_ag(client_id: str, user = Depends(get_current_user)):
    try:
        if not user: return HTMLResponse("Non autorisé", status_code=401)
        base_data = db.get_site(client_id)
        if not base_data: return HTMLResponse(f"<h1>Erreur 404</h1><p>Copropriété introuvable.</p>", status_code=404)
        
        profile = db.get_user_profile(user.get("uid"))
        if user.get("role") != "ADMIN" and base_data.get("identity", {}).get("tenant_id") != profile.get("tenant_id"):
            return HTMLResponse(f"<h1>Erreur 403</h1><p>Accès refusé.</p>", status_code=403)
            
        cluster_siret = str(base_data.get('identity', {}).get('siret') or "").strip()
        cluster_name = str(base_data.get('identity', {}).get('site_name') or "").strip()
        
        cluster_files =[]
        if cluster_name or cluster_siret:
            for d in db.get_all_sites():
                if (cluster_siret and str(d.get('identity', {}).get('siret', '')).strip() == cluster_siret) or (cluster_name and str(d.get('identity', {}).get('site_name', '')).strip() == cluster_name):
                    cluster_files.append(d)
        else:
            cluster_files = [base_data]
            
        if not cluster_files: cluster_files =[base_data]
            
        if len(cluster_files) > 1:
            v_tot = b_tot = v_el = v_gz = g_tot = 0
            for s in cluster_files:
                fin = cortex.enrich_site_financials(s) if cortex else {}
                vol = float(fin.get('volume_mwh') or s.get('kpis', {}).get('volume_mwh') or 0)
                b_tot += float(fin.get('budget_annual') or (vol * 180.0))
                v_tot += vol; g_tot += float(fin.get('kpis', {}).get('ghost_savings') or s.get('kpis', {}).get('ghost_savings') or 0)
                if fin.get('meta', {}).get('is_gas', False): v_gz += vol 
                else: v_el += vol
            return HTMLResponse(content=pdf_builder.generate_bilan_ag_cluster(cluster_name or f"Grappe_{client_id}", len(cluster_files), v_tot, b_tot, v_el, v_gz, g_tot))
        else:
            return HTMLResponse(content=pdf_builder.generate_bilan_ag(client_id, base_data, cortex.enrich_site_financials(base_data) if cortex else {}, base_data.get('kpis', {})))
    except Exception as e: return HTMLResponse(f"<h1>🚨 Erreur Interne (API 500)</h1><p>{str(e)}</p>", status_code=500)

@app.get("/api/physics/thermic_signature/{client_id}")
async def get_thermic_signature(client_id: str):
    data = db.get_site(client_id)
    if not data: return JSONResponse({"error": "Site introuvable"}, 404)
        
    fin = cortex.enrich_site_financials(data)
    vol = float(fin.get('volume_mwh') or data.get('kpis', {}).get('volume_mwh', 0))
    city = str(data.get('location', {}).get('city', 'Paris')).upper()
    dju_profile =[x * 1.2 if any(v in city for v in['LILLE', 'STRASBOURG', 'NANCY', 'METZ']) else (x * 0.7 if any(v in city for v in['MARSEILLE', 'NICE', 'MONTPELLIER', 'TOULON']) else x) for x in[450, 400, 350, 200, 80, 10, 0, 0, 50, 200, 350, 420]]
    total_dju = sum(dju_profile) or 1
    talon_monthly = (vol * (0.15 if fin.get('meta', {}).get('is_gas', False) else 0.30)) / 12
    chauf_ann = vol - (talon_monthly * 12)
    
    points =[{"x": round(dju_profile[m]), "y": round(((dju_profile[m]/total_dju)*chauf_ann) + talon_monthly, 2), "month": m+1} for m in range(12)]
    xm = sum(p['x'] for p in points) / 12; ym = sum(p['y'] for p in points) / 12
    den = sum((p['x'] - xm)**2 for p in points)
    a = sum((p['x'] - xm) * (p['y'] - ym) for p in points) / den if den != 0 else 0
    b = ym - a * xm
    ss_tot = sum((p['y'] - ym)**2 for p in points)
    r2 = 1 - (sum((p['y'] - (a * p['x'] + b))**2 for p in points) / ss_tot) if ss_tot != 0 else 0
    
    return JSONResponse({"success": True, "points": points, "regression": {"a": round(a, 4), "b": round(b, 2), "r2": round(r2, 3)}, "diagnostics": {"talon_mensuel": round(talon_monthly, 2), "sensibilite": round(a * 1000, 2), "is_optimized": r2 > 0.85}})

# ==========================================
# GESTION DES PROFILS PARTENAIRES
# ==========================================
@app.post("/api/partner/save_config")
async def save_partner_config(request: Request, user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False, "error": "Non autorisé"}, 401)
    try:
        data = await request.json()
        data["tenant_id"] = str(data.get("siret", "")).replace(" ", "")
        db.save_user_profile(user.get("uid"), data)
        return JSONResponse({"success": True, "tenant_id": data["tenant_id"]})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)}, 500)

@app.get("/api/partner/get_config")
async def get_partner_config(user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False}, 401)
    return JSONResponse({"success": True, "data": db.get_user_profile(user.get("uid"))})

# ==========================================
# API PRINCIPALES (DATA UNITY)
# ==========================================
def normalize_full_data(data, tenant_id=None):
    if 'contract' not in data: data['contract'] = {}
    if 'pricing' not in data: data['pricing'] = {}
    if 'power_details' not in data['contract']: data['contract']['power_details'] = {}
    if 'identity' not in data: data['identity'] = {}
    if 'organization_matrix' not in data['identity']: data['identity']['organization_matrix'] = {"entity_fille": "", "legal_status": "", "cost_center": ""}
        
    for t, v in {'hph':['ps_hph', 'p_hph', 'PS_HPH', 'puissance_hph'], 'hch':['ps_hch', 'p_hch', 'PS_HCH', 'puissance_hch'], 'hpe':['ps_hpe', 'p_hpe', 'PS_HPE', 'puissance_hpe'], 'hce':['ps_hce', 'p_hce', 'PS_HCE', 'puissance_hce']}.items():
        for s in [data, data['contract'], data.get('technical', {}), data['pricing']]:
            if not s: continue
            for k in v:
                if k in s and s[k]: data['contract']['power_details'][t] = s[k]; data['contract'][f"ps_{t}"] = s[k]; break

    for t, v in {'hph':['price_hph', 'prix_hph', 'P_HPH', 'tarif_hph'], 'hch':['price_hch', 'prix_hch', 'P_HCH', 'tarif_hch'], 'hpe':['price_hpe', 'prix_hpe', 'P_HPE', 'tarif_hpe'], 'hce':['price_hce', 'prix_hce', 'P_HCE', 'tarif_hce']}.items():
        for s in[data, data['contract'], data.get('technical', {}), data['pricing']]:
            if not s: continue
            for k in v:
                if k in s and s[k]: data['pricing'][t] = s[k]; break

    if 'siret' in data and data['siret']: data['identity']['siret'] = data['siret']
    if not data['identity'].get('id') and data['identity'].get('siret'): data['identity']['id'] = data['identity']['siret']
    
    if tenant_id: data['identity']['tenant_id'] = tenant_id
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
    try:
        content = await file.read()
        sites = ingest.parse_mass_import_unified(content) if ingest else[]
        if not sites: return JSONResponse({"success": False, "error": "Fichier vide."})
            
        profile = db.get_user_profile(user.get("uid"))
        tenant_id = profile.get("tenant_id", "ORPHELIN")
            
        saved = 0
        for s in sites:
            try:
                s = normalize_full_data(s, tenant_id)
                raw_id = s.get('identity', {}).get('id') or f"GEN_{uuid.uuid4().hex[:8]}"
                safe_id = get_safe_id(raw_id)
                
                existing = db.get_site(safe_id)
                if existing:
                    if existing.get("identity", {}).get("tenant_id") != tenant_id and user.get("role") != "ADMIN": continue
                    for sec in['contract', 'pricing', 'identity', 'technical', 'location']:
                        if sec in s:
                            if sec not in existing: existing[sec] = {}
                            existing[sec].update(s[sec])
                    final_s = existing
                else: final_s = s
                    
                db.save_site(safe_id, final_s)
                saved += 1
            except: pass
        return JSONResponse({"success": True, "imported": len(sites), "saved": saved})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data(response: Response, user = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    
    profile = db.get_user_profile(user.get("uid"))
    tenant_id = profile.get("tenant_id", "ORPHELIN")
    is_admin = user.get("role") == "ADMIN"
    
    raw_sites = db.get_all_sites()
    filtered_sites =[s for s in raw_sites if "CLI_" not in str(s.get('identity', {}).get('id')) and (is_admin or s.get("identity", {}).get("tenant_id") == tenant_id)]
    
    for s in filtered_sites:
        if cortex: s['computed_financials'] = cortex.enrich_site_financials(s)
    
    analysis = cortex.analyze_portfolio(filtered_sites) if cortex else {"global": {}, "green_league": {}}
    fleet_list =[]
    all_cities = set(); all_providers = set()
    
    for s in filtered_sites:
        fin = s.get('computed_financials', {})
        contract = s.get('contract', {})
        city = fin.get('meta', {}).get('city', 'Inconnue')
        prov = contract.get('provider', 'Inconnu')
        
        if city and city != 'Inconnue': all_cities.add(city)
        if prov: all_providers.add(prov)
        
        vol_engine = fin.get('volume_mwh', 0)
        vol_router = float(s.get('kpis', {}).get('volume_mwh', 0))
        final_vol = vol_engine if vol_engine > 0 else vol_router

        final_budget = fin.get('budget_annual', 0)
        if final_budget == 0 and final_vol > 0:
            avg_price = float(s.get('pricing', {}).get('price_kwh') or s.get('pricing', {}).get('prix_kwh') or s.get('pricing', {}).get('hph') or 0.20)
            if avg_price > 2.0: avg_price = avg_price / 1000.0
            
            tax = float(s.get('pricing', {}).get('tax') or s.get('pricing', {}).get('taxes') or 22.5)
            if tax > 100: tax = 22.5 
            
            sub_cost = float(s.get('pricing', {}).get('fix') or s.get('pricing', {}).get('abonnement') or 0)
            final_budget = sub_cost + (final_vol * 1000 * avg_price) + (final_vol * tax)

        fleet_list.append({
            "id": get_safe_id(s.get('identity', {}).get('id')), 
            "name": fin.get('meta', {}).get('site_label', 'Inconnu'), 
            "city": city, 
            "zip": s.get('location', {}).get('zip_code', ''),
            "volume": final_vol, 
            "energy": "gaz" if fin.get('meta', {}).get('is_gas') else "elec", 
            "segment": contract.get('segment', '-'),
            "provider": prov, 
            "budget": final_budget, 
            "landing": fin.get('landing_forecast', 0), 
            "alert": fin.get('kpis', {}).get('pmc_eur_mwh', 0) > 300,
            "ghost_savings": fin.get('kpis', {}).get('ghost_savings', 0), 
            "power": contract.get('power', 0), 
            "pdl": contract.get('pdl') or contract.get('pce', '-'), 
            "surface": s.get('location', {}).get('surface', 0),
            "tenant_id": s.get('identity', {}).get('tenant_id', 'Orphelin'),
            "naf": s.get('identity', {}).get('naf', 'DEFAULT')
        })
        
    return JSONResponse(json_compliant({"fleet": fleet_list, "count": len(fleet_list), "green_league": analysis.get('green_league'), "global_kpis": analysis.get('global'), "filters_meta": { "cities": sorted(list(all_cities)), "providers": sorted(list(all_providers)), "segments":["C5", "C4", "C3", "C2", "C1", "T1", "T2", "T3"], "lots":["Lot 1", "Lot 2"] }}))

@app.post("/api/settings/propagate_tariff")
async def api_propagate_tariff(payload: PropagateRequest, user = Depends(get_current_user)):
    try:
        if not user: return JSONResponse({"error": "Non autorisé"}, 401)
        
        profile = db.get_user_profile(user.get("uid"))
        tenant_id = profile.get("tenant_id", "ORPHELIN")
        is_admin = user.get("role") == "ADMIN"
        
        sites = db.get_all_sites()
        updated_count = 0
        
        for data in sites:
            try:
                identity = data.get('identity', {})
                site_id = identity.get('id')
                if not site_id: continue
                if not is_admin and identity.get('tenant_id') != tenant_id: continue
                
                contract = data.get('contract', {})
                segment_match = (str(payload.filters.get('segment', '')).lower() == str(contract.get('segment', '')).lower())
                lot_match = True
                if payload.filters.get('lot_name') and payload.filters.get('lot_name') != "Aucun":
                    lot_name = str(payload.filters.get('lot_name')).lower()
                    lot_match = (lot_name == str(identity.get('ref_copro', '')).lower() or lot_name == str(identity.get('lot_name', '')).lower() or lot_name == str(identity.get('organization_matrix', {}).get('entity_fille', '')).lower())
                
                if segment_match and lot_match:
                    if 'pricing' not in data: data['pricing'] = {}
                    for k, v in payload.pricing_data.items():
                        if v and str(v) != "0": data['pricing'][k] = float(v)
                    contract['start_date'] = payload.target_date
                    data['contract'] = contract
                    db.save_site(site_id, data)
                    updated_count += 1
            except: continue
        return JSONResponse({"success": True, "updated_count": updated_count})
    except Exception as e: return JSONResponse({"success": False, "detail": str(e)})

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str, response: Response, user = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    
    data = db.get_site(client_id)
    if not data: return JSONResponse({"error": "Site introuvable"}, 404)
    
    profile = db.get_user_profile(user.get("uid"))
    if user.get("role") != "ADMIN" and data.get("identity", {}).get("tenant_id") != profile.get("tenant_id", "ORPHELIN"):
        return JSONResponse({"error": "Accès refusé."}, 403)
        
    financials = cortex.enrich_site_financials(data) if cortex else {'meta':{'is_gas':False}, 'kpis':{'unit_price_kwh':0, 'pmc_eur_mwh':0, 'ghost_savings':0}, 'volume_mwh':0, 'budget_annual':0, 'pricing_details':{}}
    mr = get_market_ref()
    ma = cortex.analyze_market_position(financials['kpis']['unit_price_kwh'], mr, is_gas=financials['meta']['is_gas']) if cortex else {"status": "ANALYSE"}
    if 'ref_price' not in ma: ma = {"status": "ANALYSE", "ref_price": mr['gaz']['peg_n1'] if financials['meta']['is_gas'] else mr['elec']['cal_n1'], "details": {"market_label": "PEG N+1" if financials['meta']['is_gas'] else "CAL N+1"}}

    contract = data.get('contract', {})
    pricing = financials['pricing_details']
    display_segment = financials.get('display_overrides', {}).get('segment', contract.get('segment'))

    vol_display = float(financials['volume_mwh'] or data.get('kpis', {}).get('volume_mwh', 0))
    p_data = data.get('pricing', {})
    
    u_price = float(p_data.get('price_kwh') or p_data.get('prix_kwh') or p_data.get('hph') or 0.20)
    if u_price > 2.0: u_price = u_price / 1000.0
    tax_val = float(p_data.get('tax') or p_data.get('taxes') or 22.5)
    if tax_val > 100: tax_val = 22.5
    sub_val = float(p_data.get('fix') or p_data.get('abonnement') or 0)
    budget_display = sub_val + (vol_display * 1000 * u_price) + (vol_display * tax_val)

    pd = contract.get('power_details', {})
    if not contract.get('ps_hph'): contract['ps_hph'] = pd.get('hph') or contract.get('p_hph') or contract.get('P_HPH') or "-"
    if not contract.get('ps_hch'): contract['ps_hch'] = pd.get('hch') or contract.get('p_hch') or contract.get('P_HCH') or "-"
    if not contract.get('ps_hpe'): contract['ps_hpe'] = pd.get('hpe') or contract.get('p_hpe') or contract.get('P_HPE') or "-"
    if not contract.get('ps_hce'): contract['ps_hce'] = pd.get('hce') or contract.get('p_hce') or contract.get('P_HCE') or "-"

    return JSONResponse(json_compliant({
        "energy_type": "gaz" if financials['meta']['is_gas'] else "elec", "identity": data.get('identity', {}), "location": data.get('location', {}), "technical": data.get('technical', {}), "financials": data.get('financials', {}),
        "contract": {"pdl": contract.get('pdl'), "provider": financials['meta'].get('provider') or contract.get('provider', 'Inconnu'), "segment": display_segment or contract.get('segment', '-'), "start_date": contract.get('start_date'), "end_date": contract.get('end_date'), "power": contract.get('power'), "p_max": contract.get('p_max'), "fta": contract.get('fta'), "grd": contract.get('grd'), "cja": contract.get('cja'), "profil": contract.get('profil'), "tarif_acheminement": contract.get('tarif_acheminement'), "power_details": pd, "ps_hph": contract.get('ps_hph'), "ps_hch": contract.get('ps_hch'), "ps_hpe": contract.get('ps_hpe'), "ps_hce": contract.get('ps_hce'), "consumption_details": contract.get('consumption_details', {})},
        "pricing": pricing, "kpis": {"volume_mwh": vol_display, "budget": budget_display, "pmc": financials['kpis']['pmc_eur_mwh'], "ghost_savings": financials['kpis']['ghost_savings'], "talon_kw": data.get('kpis', {}).get('talon_kw', 0), "pmax_kw": data.get('kpis', {}).get('pmax_kw', 0), "cortex_advice": data.get('kpis', {}).get('cortex_advice', "Pas d'analyse."), "is_alert": data.get('kpis', {}).get('is_alert', False)},
        "cortex_insight": {"message": "Analyse CORTEX terminée.", "conseil": "Prix optimisé." if ma['status'] == 'OPTIMISÉ' else "Surveillez ce contrat."}, "market_analysis": ma, "electricity_price": financials['kpis']['unit_price_kwh']
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
        df_el = df_dqe[df_dqe['Type'] == 'ELEC']; df_gz = df_dqe[df_dqe['Type'] == 'GAZ']
        
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as w:
            if not df_el.empty: df_el.to_excel(w, index=False, sheet_name="DATA_ELEC"); df_el[["PDL", "Nom du site", "CP", "Ville", "Segment", "Vol. Annuel"]].assign(OFFRE_NOM="", PRIX_HPH_EUR_KWH="", ABONNEMENT_EUR_AN="").to_excel(w, index=False, sheet_name="REPONSE_ELEC")
            if not df_gz.empty: df_gz.to_excel(w, index=False, sheet_name="DATA_GAZ")
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=DQE_{datetime.now().strftime('%Y%m%d')}.xlsx"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.post("/api/ingest/upload")
async def ingest_files_mass(files: List[UploadFile] = File(...)):
    return JSONResponse(content={"report":[router.analyze_file_stream(await f.read(), f.filename) for f in files]})

@app.post("/api/finance/upload")
async def api_finance_upload(file: UploadFile = File(...), site_id: str = Form(...), user = Depends(get_current_user)):
    try:
        parsed = finance.parse_invoice(await file.read(), file.filename)
        if parsed.get("status") == "ERROR": return JSONResponse(parsed, status_code=400)
        
        site_data = db.get_site(site_id) or {}
        if user.get("role") != "ADMIN" and site_data.get("identity", {}).get("tenant_id") != db.get_user_profile(user.get("uid")).get("tenant_id"):
            return JSONResponse({"error": "Accès refusé"}, 403)
            
        return JSONResponse(json_compliant(finance.audit_invoice(parsed, site_data)))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/api/finance/landing/{site_id}")
async def api_finance_landing(site_id: str, user = Depends(get_current_user)):
    site_data = db.get_site(site_id)
    if not site_data: return JSONResponse({"error": "Site introuvable"}, 404)
    if user.get("role") != "ADMIN" and site_data.get("identity", {}).get("tenant_id") != db.get_user_profile(user.get("uid")).get("tenant_id"):
        return JSONResponse({"error": "Accès refusé"}, 403)
    try: return JSONResponse(json_compliant(finance.simulate_landing(site_data)))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

# ==========================================
# VUES HTML & ROUTAGE (ANTI-404 V12)
# ==========================================

VALID_VIEWS =[
    "settings", "settings_pme", "settings_light", "settings_partner", "settings_ops",
    "ops_nexus", "ops_ingest", "ops_aggregator", "ops_market",
    "pme", "industry", "retail", "mairie", "sde", "oph", "syndic", "sante", "supplier", "citoyen",
    "pulse", "carbon", "gridmap", "solar", "optimization", "trading", "thermic", "deal_desk", "finance", "dashboard_finance",
    "sales_workspace"
]

PUBLIC_PAGES =[
    "index.html", "onboarding.html", "processing.html", "login.html", "solutions.html", 
    "cortex.html", "vitality.html", "connectivite.html", "audit_premium.html", 
    "store.html", "ethique.html", "fournisseurs.html", "etudes-de-cas.html", "modele_economique.html"
]

@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str, user = Depends(get_current_user)):
    if any(x in page_name for x in[".js", ".css", ".png", ".jpg", ".ico", ".svg"]): 
        return JSONResponse({}, 404)
        
    target_file = page_name if page_name.endswith(".html") else f"{page_name}.html"
    clean_name = page_name.replace(".html", "")

    if target_file not in PUBLIC_PAGES and not user: 
        return RedirectResponse(url="/login")

    if clean_name in VALID_VIEWS or target_file in PUBLIC_PAGES:
        file_path = os.path.join(TEMPLATE_DIR, target_file)
        if os.path.exists(file_path): 
            return templates.TemplateResponse(target_file, {"request": request})
            
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in["static", "assets", "favicon"]): return JSONResponse({}, 404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
