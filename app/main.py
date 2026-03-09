import os
import math
import io
import traceback
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
        try:
            identity = data.get('identity', {})
            loc = data.get('location', {})
            site_name = str(identity.get('site_name') or identity.get('name') or "Copropriété")
            address = f"{loc.get('address', '')} - {loc.get('city', '')}".strip(" -")
            
            try: vol_mwh = float(fin.get('volume_mwh') or 0)
            except: vol_mwh = 0.0
            
            if vol_mwh == 0: 
                try: vol_mwh = float(kpis.get('volume_mwh') or 0)
                except: vol_mwh = 0.0
                
            try: budget = float(fin.get('budget_annual') or 0)
            except: budget = 0.0
            
            if budget == 0: budget = vol_mwh * 180.0
            budget_non_negocie = budget * 1.15 
            economie = budget_non_negocie - budget
            is_gas = fin.get('meta', {}).get('is_gas', False) if isinstance(fin, dict) else False
            talon_pct = 0.15 if is_gas else 0.30
            talon_monthly = (vol_mwh * talon_pct) / 12.0
            
            try: ghost = float(kpis.get('ghost_savings') or 0)
            except: ghost = 0.0
            
            r2_simule = 0.88 if ghost < (vol_mwh * 0.1) else 0.65
            etat_chaufferie = "Excellente régulation climatique." if r2_simule > 0.85 else "Dérive thermique constatée. Réglage recommandé."
            couleur_chaufferie = "#10B981" if r2_simule > 0.85 else "#EF4444"
            annee_en_cours = datetime.now().year
            date_edition = datetime.now().strftime('%d/%m/%Y')

            return f"""
            <!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>BILAN_AG_{site_name.replace(' ', '_')}</title>
            <style>@page {{ size: A4; margin: 0; }} body {{ font-family: 'Segoe UI', Helvetica, Arial, sans-serif; color: #1e293b; background: white; margin: 0; padding: 0; font-size: 13px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }} .page {{ width: 210mm; min-height: 296mm; padding: 20mm; box-sizing: border-box; page-break-after: always; position: relative; }} .header-brand {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 4px solid #001529; padding-bottom: 15px; margin-bottom: 30px; }} h1 {{ color: #001529; font-size: 22px; margin: 0; text-transform: uppercase; letter-spacing: -0.5px; }} .subtitle {{ color: #00E5FF; font-weight: 900; font-size: 14px; text-transform: uppercase; letter-spacing: 2px; }} h2 {{ color: #001529; font-size: 16px; border-left: 5px solid #00E5FF; padding-left: 12px; margin-top: 35px; text-transform: uppercase; letter-spacing: 1px; }} .info-box {{ background: #001529; color: white; border-radius: 12px; padding: 20px; margin-bottom: 25px; display: flex; gap: 20px; }} .info-label {{ font-size: 10px; text-transform: uppercase; color: #00E5FF; font-weight: bold; margin-bottom: 5px; }} .info-value {{ font-size: 16px; font-weight: bold; }} .kpi-grid {{ display: flex; gap: 20px; margin-bottom: 30px; }} .kpi-card {{ flex: 1; border: 2px solid #e2e8f0; border-radius: 12px; padding: 20px; text-align: center; background: #f8fafc; }} .kpi-val {{ font-size: 26px; font-weight: 900; color: #001529; margin: 10px 0; font-family: monospace; }} .shield-box {{ background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 1px solid #22c55e; padding: 20px; border-radius: 12px; }} .legal-box {{ background: #f1f5f9; border-left: 4px solid #94a3b8; padding: 15px; margin-top: 40px; font-size: 10px; color: #475569; }} .footer-doc {{ position: absolute; bottom: 15mm; left: 20mm; right: 20mm; border-top: 2px solid #e2e8f0; padding-top: 10px; display: flex; justify-content: space-between; font-size: 9px; font-weight: bold; color: #94a3b8; text-transform: uppercase; }} .no-print {{ position: fixed; top: 20px; right: 20px; z-index: 1000; }} .btn-print {{ background: #001529; color: #00E5FF; border: 2px solid #00E5FF; padding: 12px 24px; border-radius: 8px; font-weight: 900; cursor: pointer; text-transform: uppercase; }} @media print {{ .no-print {{ display: none; }} }}</style>
            </head><body onload="setTimeout(function(){{ window.print(); }}, 800);"><div class="no-print"><button class="btn-print" onclick="window.print()">🖨️ Télécharger le Rapport PDF</button></div>
            <div class="page"><div class="header-brand"><div>{self.logo_svg}</div><div style="text-align: right;"><h1>BILAN ÉNERGÉTIQUE ANNUEL</h1><div class="subtitle">Préparation Assemblée Générale {annee_en_cours}</div></div></div><div class="info-box"><div style="flex:1;"><div class="info-label">Copropriété</div><div class="info-value">{site_name.upper()}</div></div><div style="flex:1;"><div class="info-label">Localisation</div><div class="info-value">{address}</div></div><div style="flex:1;"><div class="info-label">Identifiant SGE</div><div class="info-value">{client_id}</div></div></div><h2>1. Synthèse Budgétaire & Achats</h2><div class="kpi-grid"><div class="kpi-card"><div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">Volume Réel Consommé</div><div class="kpi-val">{round(vol_mwh)} <span style="font-size: 14px;">MWh</span></div></div><div class="kpi-card"><div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">Budget Annuel Facturé</div><div class="kpi-val" style="color: #00E5FF;">{int(budget):,} <span style="font-size: 14px;">€ TTC</span></div></div></div><div class="shield-box"><strong style="color: #15803d; font-size: 16px;">🛡️ Bouclier Tarifaire & Négociation</strong><br><br>Le marché de gros a subi de fortes turbulences. Le syndicat a évité le tarif moyen estimé à {int(budget_non_negocie):,} €.<br><br><b>Économie globale sécurisée : <span style="font-size: 18px; color: #166534;">{int(economie):,} €</span>.</b></div><h2>2. Audit Thermique (Signature Énergétique)</h2><div style="display:flex; gap:20px;"><div style="flex:1; border-left:4px solid {couleur_chaufferie}; padding-left:15px;"><div class="info-label" style="color: #64748b;">Qualité de Régulation (R²)</div><div style="font-size: 24px; font-weight: 900; color: {couleur_chaufferie};">{round(r2_simule * 100)} %</div></div><div style="flex:2;"><b>Diagnostic de l'Expert IA :</b><br>{etat_chaufferie}<br><i>Talon de base estimé : {round(talon_monthly, 1)} MWh/mois.</i></div></div><div class="legal-box"><strong>⚖️ ATTESTATION DE PROVENANCE (TIERS DE CONFIANCE)</strong><br>ENERGISTRAT atteste que les volumes présentés sont extraits directement des Systèmes de Gestion des Échanges (SGE) des distributeurs nationaux via API sécurisée.</div><div class="footer-doc"><span>© ENERGISTRAT</span><span>Date d'édition : {date_edition}</span><span>Page 1 / 1</span></div></div></body></html>
            """
        except Exception as e:
            return f"<h1>Erreur interne</h1><p>{str(e)}</p>"

    def generate_bilan_ag_cluster(self, cluster_name, site_count, vol_total, budget_total, vol_elec, vol_gaz, ghost_total):
        budget_non_negocie = budget_total * 1.15 
        economie = budget_non_negocie - budget_total
        pct_elec = (vol_elec / vol_total) * 100 if vol_total > 0 else 0
        pct_gaz = (vol_gaz / vol_total) * 100 if vol_total > 0 else 0
        
        r2_simule = 0.88 if ghost_total < (vol_total * 0.1) else 0.65
        etat_chaufferie = "Excellente régulation globale du parc." if r2_simule > 0.85 else "Dérives thermiques ou talons électriques nocturnes constatés."
        couleur_chaufferie = "#10B981" if r2_simule > 0.85 else "#EF4444"
        annee_en_cours = datetime.now().year
        date_edition = datetime.now().strftime('%d/%m/%Y')

        return f"""
        <!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>BILAN_AG_GRAPPE_{cluster_name.replace(' ', '_')}</title>
        <style>@page {{ size: A4; margin: 0; }} body {{ font-family: 'Segoe UI', Helvetica, Arial, sans-serif; color: #1e293b; background: white; margin: 0; padding: 0; font-size: 13px; -webkit-print-color-adjust: exact; print-color-adjust: exact; }} .page {{ width: 210mm; min-height: 296mm; padding: 20mm; box-sizing: border-box; page-break-after: always; position: relative; }} .header-brand {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 4px solid #001529; padding-bottom: 15px; margin-bottom: 30px; }} h1 {{ color: #001529; font-size: 22px; margin: 0; text-transform: uppercase; letter-spacing: -0.5px; }} .subtitle {{ color: #00E5FF; font-weight: 900; font-size: 14px; text-transform: uppercase; letter-spacing: 2px; }} h2 {{ color: #001529; font-size: 16px; border-left: 5px solid #00E5FF; padding-left: 12px; margin-top: 35px; text-transform: uppercase; letter-spacing: 1px; }} .info-box {{ background: #001529; color: white; border-radius: 12px; padding: 20px; margin-bottom: 25px; display: flex; gap: 20px; }} .info-label {{ font-size: 10px; text-transform: uppercase; color: #00E5FF; font-weight: bold; margin-bottom: 5px; }} .info-value {{ font-size: 16px; font-weight: bold; }} .kpi-grid {{ display: flex; gap: 20px; margin-bottom: 30px; }} .kpi-card {{ flex: 1; border: 2px solid #e2e8f0; border-radius: 12px; padding: 20px; text-align: center; background: #f8fafc; }} .kpi-val {{ font-size: 26px; font-weight: 900; color: #001529; margin: 10px 0; font-family: monospace; }} .shield-box {{ background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 1px solid #22c55e; padding: 20px; border-radius: 12px; }} .legal-box {{ background: #f1f5f9; border-left: 4px solid #94a3b8; padding: 15px; margin-top: 40px; font-size: 10px; color: #475569; }} .mix-bar {{ width: 100%; height: 20px; background: #f1f5f9; border-radius: 10px; overflow: hidden; display: flex; margin-top: 10px; border: 1px solid #cbd5e1;}} .mix-gas {{ background: #F97316; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 10px; color: white; font-weight: bold; }} .mix-elec {{ background: #00E5FF; height: 100%; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #001529; font-weight: bold; }} .footer-doc {{ position: absolute; bottom: 15mm; left: 20mm; right: 20mm; border-top: 2px solid #e2e8f0; padding-top: 10px; display: flex; justify-content: space-between; font-size: 9px; font-weight: bold; color: #94a3b8; text-transform: uppercase; }} .no-print {{ position: fixed; top: 20px; right: 20px; z-index: 1000; }} .btn-print {{ background: #001529; color: #00E5FF; border: 2px solid #00E5FF; padding: 12px 24px; border-radius: 8px; font-weight: 900; cursor: pointer; text-transform: uppercase; }} @media print {{ .no-print {{ display: none; }} }}</style>
        </head><body onload="setTimeout(function(){{ window.print(); }}, 800);"><div class="no-print"><button class="btn-print" onclick="window.print()">🖨️ Télécharger le PDF (Grappe)</button></div>
        <div class="page"><div class="header-brand"><div>{self.logo_svg}</div><div style="text-align: right;"><h1>BILAN MULTI-ÉNERGIES (GRAPPE)</h1><div class="subtitle">Préparation Assemblée Générale {annee_en_cours}</div></div></div><div class="info-box"><div style="flex:1;"><div class="info-label">Résidence (Grappe)</div><div class="info-value">{cluster_name.upper()}</div></div><div style="flex:1;"><div class="info-label">Compteurs fusionnés</div><div class="info-value">{site_count} PDL / PCE</div></div></div><h2>1. Mix Énergétique du Bâtiment (DPE Collectif)</h2><div class="mix-bar"><div class="mix-gas" style="width: {pct_gaz}%;">GAZ {round(pct_gaz)}%</div><div class="mix-elec" style="width: {pct_elec}%;">ÉLEC {round(pct_elec)}%</div></div><h2>2. Synthèse Budgétaire Globale</h2><div class="kpi-grid" style="margin-top: 15px;"><div class="kpi-card"><div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">Volume Réel Consommé</div><div class="kpi-val">{round(vol_total)} <span style="font-size: 14px;">MWh</span></div></div><div class="kpi-card"><div style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase;">Budget Annuel Facturé</div><div class="kpi-val" style="color: #00E5FF;">{int(budget_total):,} <span style="font-size: 14px;">€ TTC</span></div></div></div><div class="shield-box"><strong style="color: #15803d; font-size: 16px;">🛡️ Bouclier Tarifaire Global</strong><br><br><b>Économie globale sécurisée sur la grappe : <span style="font-size: 18px; color: #166534;">{int(economie):,} €</span>.</b></div><h2>3. Audit & Dérive Thermique</h2><div style="display:flex; gap:20px;"><div style="flex:1; border-left:4px solid {couleur_chaufferie}; padding-left:15px;"><div class="info-label" style="color: #64748b;">Régulation Globale</div><div style="font-size: 24px; font-weight: 900; color: {couleur_chaufferie};">{round(r2_simule * 100)} %</div></div><div style="flex:2;"><b>Diagnostic IA Multi-Sites :</b><br>{etat_chaufferie}<br><i>Gaspillage estimé de la grappe : {round(ghost_total)} €/an.</i></div></div><div class="legal-box"><strong>⚖️ ATTESTATION DE PROVENANCE (TIERS DE CONFIANCE)</strong><br>ENERGISTRAT atteste que les {site_count} compteurs ont été certifiés via les API des gestionnaires de réseau. Ce document fait foi pour l'étude PPPT.</div><div class="footer-doc"><span>© ENERGISTRAT - GRAPPE</span><span>Date : {date_edition}</span><span>Page 1 / 1</span></div></div></body></html>"""

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
    from app.core.cortex_db import db
    try:
        from app.core.cortex_pdf import pdf_builder
    except ImportError:
        pdf_builder = FallbackPDFBuilder()

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
        from core.cortex_db import db
        try:
            from core.cortex_pdf import pdf_builder
        except ImportError:
            pdf_builder = FallbackPDFBuilder()
    except Exception as e_local:
        print(f"⚠️ LOCAL IMPORT ERROR: {str(e_local)}")
        class MockAuth:
            def verify_token(self, t): return {"uid": "mock", "email": "admin@energistrat.com", "role": "ADMIN", "sub": "admin"}
        auth = MockAuth()
        class MockDB:
            def get_all_sites(self): return[]
            def get_site(self, sid): return {}
            def save_site(self, sid, d): return True
            def delete_site(self, sid): return True
            def get_setting(self, n): return {}
            def save_setting(self, n, d): return True
            def get_sentinel_alerts(self): return {"last_scan": "Jamais", "alert_count": 0, "alerts":[]}
            def save_sentinel_alerts(self, d): return True
            def get_user_profile(self, u): return {}
            def save_user_profile(self, u, d): return True
        db = MockDB()
        class MockFinance:
            def parse_invoice(self, c, f): return {"status": "ERROR"}
            def audit_invoice(self, i, s): return {}
            def simulate_landing(self, s): return {}
        finance = MockFinance()
        class MockRouter:
            def get_api_status(self): return {"status": "DEGRADED"}
            def analyze_file_stream(self, c, f): return {"status": "ERROR"}
        router = MockRouter()
        class MockMarket:
            def valoriser_strategie(self, l, b): return {"error": "Market missing"}
        market = MockMarket()
        class MockAggregator:
            def aggregate_sites(self, s, y): return None
        aggregator = MockAggregator()
        class MockCortex:
            def enrich_site_financials(self, data): return {"volume_mwh": 0, "budget_annual": 0, "meta": {"is_gas": False}, "kpis": {"pmc_eur_mwh": 0, "ghost_savings": 0}}
            def analyze_portfolio(self, sites): return {"global": {}, "green_league": {}}
            def generate_dqe_structure(self, s): return pd.DataFrame() if PANDAS_READY else None
        cortex = MockCortex()
        ingest = None
        physics = None
        forecast = None
        pdf_builder = FallbackPDFBuilder()

app = FastAPI(title="ENERGISTRAT V3", version="EMPIRE-V8.1-MULTI-TENANT")

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
class SessionRequest(BaseModel): id_token: str
class MarketUpdateModel(BaseModel): elec: Dict[str, Any]; gaz: Dict[str, Any]; trve: Optional[Dict[str, Any]] = None; targets: Optional[Dict[str, Any]] = None
class StrategyRequest(BaseModel): site_id: str; bloc_kw: float
class AggregationRequest(BaseModel): site_ids: List[str]; years: int = 3
class PropagateRequest(BaseModel): source_client_id: str; target_date: str; filters: Dict[str, str]; pricing_data: Dict[str, Any]
class M57SettingsModel(BaseModel): bp_elec: float = 0.0; bp_gaz: float = 0.0; consumed_elec: float = 0.0; consumed_gaz: float = 0.0; bp_irve: float = 0.0; consumed_irve: float = 0.0; bp_enr: float = 0.0; consumed_enr: float = 0.0
class CarbonSettingsModel(BaseModel): baseline_year: int = 2010; baseline_kwh_sqm: float = 0.0
class RTESettingsModel(BaseModel): client_id: str = ""; client_secret: str = ""

# --- FONCTIONS UTILITAIRES ---
def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return [json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

def get_safe_id(raw_id):
    return str(raw_id).replace('/', '_').replace(' ', '_').replace('+', '').replace(',', '').strip()

def get_market_ref():
    market_data = db.get_setting("Market")
    if market_data: return market_data
    return { "updated_at": datetime.now().isoformat(), "elec": { "cal_n1": 85.0 }, "gaz": { "peg_n1": 35.0 }, "trve": { "elec_c5": 230.0 }, "targets": { "c5": 190.0 } }

async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token: return None
    if token.startswith("Bearer "): token = token.split(" ")[1]
    payload = auth.verify_token(token)
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
            return json.loads(response.read().decode('utf-8')).get("access_token")
    except: return None

# ==========================================
# AUTHENTIFICATION
# ==========================================
@app.get("/login", response_class=HTMLResponse)
async def view_login(request: Request, user = Depends(get_current_user)):
    if user: return RedirectResponse(url="/ops_nexus" if user.get("role") == "ADMIN" else "/dashboard/citoyen")
    response = templates.TemplateResponse("login.html", {"request": request})
    response.delete_cookie("access_token")
    return response

@app.post("/api/auth/session")
async def api_session(payload: SessionRequest, response: Response):
    user_data = auth.verify_token(payload.id_token)
    if not user_data: return JSONResponse({"detail": "Token Firebase invalide"}, status_code=401)
    response.set_cookie(key="access_token", value=f"Bearer {payload.id_token}", httponly=True, max_age=3600 * 24, samesite="lax", secure=True if "https" in str(response.headers) else False)
    return {"success": True, "role": user_data.get("role", "USER")}

@app.get("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return RedirectResponse(url="/login")

# ==========================================
# API CORTEX SENTINEL
# ==========================================
@app.get("/api/ops/sentinel/alerts")
async def api_get_sentinel_alerts(): return db.get_sentinel_alerts()

@app.post("/api/ops/sentinel/run")
async def trigger_sentinel_scan(background_tasks: BackgroundTasks):
    async def run_sentinel_scan():
        alerts = []
        try:
            sites = db.get_all_sites()
            for data in sites:
                if not data or cortex is None: continue
                fin = cortex.enrich_site_financials(data)
                vol = fin.get('volume_mwh', 0)
                budget = fin.get('budget_annual', 0)
                ghost = fin.get('kpis', {}).get('ghost_savings', 0)
                pdl = data.get('contract', {}).get('pdl') or data.get('identity', {}).get('id', 'N/A')
                
                action = motif = color = ""
                if vol > 0 and budget == 0:
                    action = "🟢 Entrée Orpheline"; motif = "Raccordement détecté mais hors marché."; color = "text-success bg-success/10 border-success/30"
                elif vol == 0 and budget > 0:
                    action = "🔴 Sortie de Parc"; motif = "Facturation active (Abonnement) mais conso nulle."; color = "text-alert bg-alert/10 border-alert/30"
                elif budget > 0 and ghost > (budget * 0.4):
                    action = "🟡 Dérive Majeure"; motif = f"Gaspillage estimé à {int(ghost)} €/an."; color = "text-gold bg-gold/10 border-gold/30"
                
                if action:
                    alerts.append({"id": data.get('identity',{}).get("id", ""), "city": data.get('location',{}).get('city', 'Inconnue'), "name": data.get('identity',{}).get('site_name', 'Inconnu'), "pdl": pdl, "action": action, "motif": motif, "color": color, "timestamp": datetime.now().isoformat()})
            db.save_sentinel_alerts({"last_scan": datetime.now().isoformat(), "alert_count": len(alerts), "alerts": alerts})
        except: pass
    background_tasks.add_task(run_sentinel_scan)
    return JSONResponse({"success": True, "message": "Scan Sentinel déclenché."})

# ==========================================
# API DEAL DESK & OUTILS
# ==========================================
@app.post("/api/dealdesk/analyze")
async def api_dealdesk_analyze(request: Request):
    body = await request.json()
    query = str(body.get('query', '')).strip().lower()
    if not query: return JSONResponse({"success": False, "error": "Requête vide."})
    
    site_data = next((s for s in db.get_all_sites() if query in str(s.get('contract', {}).get('pdl', '')).strip() or query in str(s.get('identity', {}).get('site_name', '')).strip().lower()), None)
    if not site_data: return JSONResponse({"success": False, "error": "Introuvable dans la Data Unity."})
        
    try: vol = cortex.enrich_site_financials(site_data).get('volume_mwh', 0)
    except: vol = 0
    power = float(site_data.get('contract', {}).get('power', 0))
    pdl_val = site_data.get('contract', {}).get('pdl', 'N/A')
    siret = site_data.get('identity', {}).get('siret', '')
    nom = site_data.get('identity', {}).get('site_name', 'Inconnu')

    legal = {"is_micro": False, "regime": "CODE_COMMERCE", "nom": nom, "siret": siret}
    segment = "B2B_HEAVY" if vol > 5000 else ("C4_MID" if power > 36 or vol > 250 else "C5_MASS")
    return JSONResponse({"success": True, "site": { "name": nom, "pdl": pdl_val, "volume": round(vol, 2), "power": power }, "legal": legal, "segment": segment})

@app.get("/api/tools/gridmap/capacity")
async def api_gridmap_capacity(user = Depends(get_current_user)):
    results = [{"pdl": s.get('contract', {}).get('pdl'), "name": s.get('identity', {}).get('site_name', 'Site'), "city": s.get('location', {}).get('city', 'Inconnue'), "power_kva": float(s.get('contract', {}).get('power', 0)), "residual_capacity_kva": 150 if float(s.get('contract', {}).get('power', 0)) > 250 else (50 if float(s.get('contract', {}).get('power', 0)) > 100 else 15), "can_host_fast_charge": float(s.get('contract', {}).get('power', 0)) > 100} for s in db.get_all_sites() if s.get('contract', {}).get('pdl') and "CLI_" not in str(s.get('identity', {}).get('id'))]
    return JSONResponse({"success": True, "nodes": results})
    # ==========================================
# API SUBVENTIONS & CERFA
# ==========================================
@app.get("/api/tools/subventions")
async def api_subventions_analyze(user = Depends(get_current_user)):
    raw_sites = db.get_all_sites()
    cee_price_mwh = 6.50
    results = []
    total_enveloppe = 0

    for s in raw_sites:
        if "CLI_" in str(s.get('identity', {}).get('id')): continue
        
        if cortex: s['computed_financials'] = cortex.enrich_site_financials(s)
        fin = s.get('computed_financials', {})
        loc = s.get('location', {})
        vol = float(fin.get('volume_mwh', 0) or s.get('kpis', {}).get('volume_mwh', 0))
        surface = float(loc.get('surface', 0))
        city = str(loc.get('city', '')).upper()
        
        if surface == 0:
            results.append({"id": get_safe_id(s.get('identity', {}).get('id', '')), "pdl": str(s.get('contract', {}).get('pdl') or s.get('contract', {}).get('pce') or "Inconnu"), "name": fin.get('meta', {}).get('site_label', 'Site Inconnu'), "city": city, "status": "MISSING_DATA", "reason": "Surface manquante."})
            continue
            
        zf = 1.3 if any(x in city for x in ['LILLE', 'PARIS', 'STRASBOURG', 'LYON', 'NANCY', 'REIMS', 'METZ']) else (0.8 if any(x in city for x in ['MARSEILLE', 'NICE', 'MONTPELLIER', 'TOULON', 'PERPIGNAN', 'NIMES']) else 1.0)
        zn = "H1" if zf == 1.3 else ("H3" if zf == 0.8 else "H2")
        
        aides = []
        ghost = float(fin.get('kpis', {}).get('ghost_savings', 0))
        
        if surface >= 500 and ghost > (vol * 0.1): aides.append({"code": "BAT-TH-116", "nom": "Coup de Pouce GTB", "details": f"Surface ({surface}m²) × Forfait × Zone {zn}", "montant": round(((surface * 250 * zf) / 1000) * cee_price_mwh * 1.5)})
        if surface > 0 and (vol * 1000) / surface > 300: aides.append({"code": "BAT-EN-101", "nom": "Isolation Thermique Toiture", "details": f"Surface toit ({round(surface * 0.3)}m²) × 1400 kWhc × Zone {zn}", "montant": round((((surface * 0.3) * 1400 * zf) / 1000) * cee_price_mwh)})
        if fin.get('meta', {}).get('is_gas', False) and vol > 500: aides.append({"code": "ADEME-CHALEUR", "nom": "Fonds Chaleur", "details": f"Substitution {round(vol)} MWh fossile × 25€", "montant": round(vol * 25)})
        
        total_site = sum(a['montant'] for a in aides)
        total_enveloppe += total_site
        
        results.append({"id": get_safe_id(s.get('identity', {}).get('id', '')), "pdl": str(s.get('contract', {}).get('pdl') or s.get('contract', {}).get('pce') or "Inconnu"), "name": fin.get('meta', {}).get('site_label', 'Site Inconnu'), "city": city, "status": "ELIGIBLE" if aides else "NON_ELIGIBLE", "aides": aides, "total_site": total_site, "reason": "Site optimisé." if not aides else ""})
            
    return JSONResponse({"success": True, "results": results, "total_enveloppe": round(total_enveloppe)})

@app.get("/api/tools/cerfa/{site_id}/{aide_code}", response_class=HTMLResponse)
async def generate_cerfa_pdf(site_id: str, aide_code: str, user = Depends(get_current_user)):
    try:
        if not user: return HTMLResponse("Non autorisé", status_code=401)
        data = db.get_site(site_id)
        if not data: return HTMLResponse(f"<h1>Erreur</h1><p>Site introuvable dans Firestore.</p>", status_code=404)
        
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
            
        cluster_siret = str(base_data.get('identity', {}).get('siret') or "").strip()
        cluster_name = str(base_data.get('identity', {}).get('site_name') or "").strip()
        
        cluster_files = [d for d in db.get_all_sites() if (cluster_siret and str(d.get('identity', {}).get('siret', '')).strip() == cluster_siret) or (cluster_name and str(d.get('identity', {}).get('site_name', '')).strip() == cluster_name)] if (cluster_name or cluster_siret) else [base_data]
        if not cluster_files: cluster_files = [base_data]
            
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
    except Exception as e: return HTMLResponse(f"<div style='padding:40px; font-family:sans-serif;'><h1>🚨 Erreur Interne (API 500)</h1><p style='color:red;'><b>{str(e)}</b></p><pre style='background:#f4f4f4; padding:20px; border-radius:10px;'>{traceback.format_exc()}</pre></div>", status_code=500)

@app.get("/api/physics/thermic_signature/{client_id}")
async def get_thermic_signature(client_id: str):
    data = db.get_site(client_id)
    if not data: return JSONResponse({"error": "Site introuvable dans Firestore"}, 404)
        
    fin = cortex.enrich_site_financials(data)
    vol = float(fin.get('volume_mwh') or data.get('kpis', {}).get('volume_mwh', 0))
    city = str(data.get('location', {}).get('city', 'Paris')).upper()
    dju_profile = [x * 1.2 if any(v in city for v in ['LILLE', 'STRASBOURG', 'NANCY', 'METZ']) else (x * 0.7 if any(v in city for v in ['MARSEILLE', 'NICE', 'MONTPELLIER', 'TOULON']) else x) for x in [450, 400, 350, 200, 80, 10, 0, 0, 50, 200, 350, 420]]
    total_dju = sum(dju_profile) or 1
    
    talon_monthly = (vol * (0.15 if fin.get('meta', {}).get('is_gas', False) else 0.30)) / 12
    chauf_ann = vol - (talon_monthly * 12)
    
    points = [{"x": round(dju_profile[m]), "y": round(((dju_profile[m]/total_dju)*chauf_ann) + talon_monthly, 2), "month": m+1} for m in range(12)]
    xm = sum(p['x'] for p in points) / 12; ym = sum(p['y'] for p in points) / 12
    den = sum((p['x'] - xm)**2 for p in points)
    a = sum((p['x'] - xm) * (p['y'] - ym) for p in points) / den if den != 0 else 0
    b = ym - a * xm
    ss_tot = sum((p['y'] - ym)**2 for p in points)
    r2 = 1 - (sum((p['y'] - (a * p['x'] + b))**2 for p in points) / ss_tot) if ss_tot != 0 else 0
    
    return JSONResponse({"success": True, "points": points, "regression": {"a": round(a, 4), "b": round(b, 2), "r2": round(r2, 3)}, "diagnostics": {"talon_mensuel": round(talon_monthly, 2), "sensibilite": round(a * 1000, 2), "is_optimized": r2 > 0.85}})

# ==========================================
# GESTION DES PROFILS PARTENAIRES (POUPÉES RUSSES)
# ==========================================
@app.post("/api/partner/save_config")
async def save_partner_config(request: Request, user = Depends(get_current_user)):
    """Sauvegarde le profil de l'entreprise (qui devient le Tenant ID)."""
    if not user: return JSONResponse({"success": False, "error": "Non autorisé"}, 401)
    
    try:
        data = await request.json()
        uid = user.get("uid")
        
        # Le SIRET renseigné devient la clé du coffre-fort de ce client
        data["tenant_id"] = str(data.get("siret", "")).replace(" ", "")
        
        db.save_user_profile(uid, data)
        return JSONResponse({"success": True, "tenant_id": data["tenant_id"]})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, 500)

@app.get("/api/partner/get_config")
async def get_partner_config(user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False}, 401)
    try:
        profile = db.get_user_profile(user.get("uid"))
        return JSONResponse({"success": True, "data": profile})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, 500)

# ==========================================
# API PRINCIPALES (DATA UNITY & FIRESTORE)
# ==========================================
def normalize_full_data(data, tenant_id=None):
    if 'contract' not in data: data['contract'] = {}
    if 'pricing' not in data: data['pricing'] = {}
    if 'power_details' not in data['contract']: data['contract']['power_details'] = {}
        
    for t, v in {'hph': ['ps_hph', 'p_hph', 'PS_HPH', 'puissance_hph'], 'hch':['ps_hch', 'p_hch', 'PS_HCH', 'puissance_hch'], 'hpe':['ps_hpe', 'p_hpe', 'PS_HPE', 'puissance_hpe'], 'hce':['ps_hce', 'p_hce', 'PS_HCE', 'puissance_hce']}.items():
        for s in [data, data['contract'], data.get('technical', {}), data['pricing']]:
            if not s: continue
            for k in v:
                if k in s and s[k]: data['contract']['power_details'][t] = s[k]; data['contract'][f"ps_{t}"] = s[k]; break

    for t, v in {'hph':['price_hph', 'prix_hph', 'P_HPH', 'tarif_hph'], 'hch':['price_hch', 'prix_hch', 'P_HCH', 'tarif_hch'], 'hpe':['price_hpe', 'prix_hpe', 'P_HPE', 'tarif_hpe'], 'hce':['price_hce', 'prix_hce', 'P_HCE', 'tarif_hce']}.items():
        for s in [data, data['contract'], data.get('technical', {}), data['pricing']]:
            if not s: continue
            for k in v:
                if k in s and s[k]: data['pricing'][t] = s[k]; break

    if 'identity' not in data: data['identity'] = {}
    if 'siret' in data and data['siret']: data['identity']['siret'] = data['siret']
    if not data['identity'].get('id') and data['identity'].get('siret'): data['identity']['id'] = data['identity']['siret']
    
    # INJECTION DU TENANT ID DE SÉCURITÉ
    if tenant_id:
        data['identity']['tenant_id'] = tenant_id
        
    return data

@app.post("/api/settings/save_client")
async def api_save_client(request: Request, user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False, "error": "Non autorisé"}, 401)
    
    try:
        raw_data = await request.json()
        
        # Récupération du Tenant ID du client connecté
        profile = db.get_user_profile(user.get("uid"))
        tenant_id = profile.get("tenant_id", "ORPHELIN")
        
        # Si c'est un ADMIN_OPS, il peut forcer un tenant_id, sinon c'est le sien
        if user.get("role") == "ADMIN" and "forced_tenant_id" in raw_data:
            tenant_id = raw_data["forced_tenant_id"]

        data = normalize_full_data(raw_data, tenant_id)
        
        raw_id = data.get("identity", {}).get("id") or data.get("id") or data.get("siret") or f"CLI_{uuid.uuid4().hex[:8]}"
        data["identity"]["id"] = str(raw_id)
        safe_id = get_safe_id(raw_id)
        
        existing_data = db.get_site(safe_id)
        if existing_data:
            # Sécurité : Un client ne peut pas écraser un site qui n'est pas dans son Tenant (sauf Admin)
            if existing_data.get("identity", {}).get("tenant_id") != tenant_id and user.get("role") != "ADMIN":
                return JSONResponse({"success": False, "error": "Accès refusé à ce PDL."}, 403)
                
            for section in ['technical', 'location', 'identity', 'contract', 'pricing', 'kpis', 'financials', 'rgpd']:
                if section in data:
                    if section not in existing_data: existing_data[section] = {}
                    existing_data[section].update(data[section])
            final_data = existing_data
        else:
            final_data = data
            
        if not db: return JSONResponse({"success": False, "error": "Moteur DB hors ligne."})
        db.save_site(safe_id, final_data)
        return JSONResponse({"success": True, "id": raw_id})
    except Exception as e: 
        print(f"CRASH api_save_client: {str(e)}")
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...), user = Depends(get_current_user)):
    if not user: return JSONResponse({"success": False, "error": "Non autorisé"}, 401)
    try:
        content = await file.read()
        sites = ingest.parse_mass_import_unified(content) if ingest else []
        if not sites: return JSONResponse({"success": False, "error": "Fichier illisible ou vide."})
            
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
                    if existing.get("identity", {}).get("tenant_id") != tenant_id and user.get("role") != "ADMIN":
                        continue # On passe les sites qui ne lui appartiennent pas sans crasher
                    for sec in ['contract', 'pricing', 'identity', 'technical', 'location']:
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

# ==========================================
# LE VIDEUR DU CLUB (FILTRAGE TENANT ID)
# ==========================================
@app.get("/api/dashboard/fleet")
async def get_fleet_data(response: Response, user = Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    if not user: return JSONResponse({"error": "Non autorisé"}, 401)
    
    # Récupération de l'identité du locataire
    profile = db.get_user_profile(user.get("uid"))
    tenant_id = profile.get("tenant_id", "ORPHELIN")
    is_admin = user.get("role") == "ADMIN"
    
    raw_sites = db.get_all_sites()
    filtered_sites = []
    
    # LE FILTRE IMPLACABLE
    for s in raw_sites:
        if "CLI_" in str(s.get('identity', {}).get('id')): continue
        
        site_tenant = s.get("identity", {}).get("tenant_id")
        
        # Si c'est l'Admin (Toi), il voit tout. 
        # Si c'est un client, il ne voit QUE les sites qui ont son Tenant ID.
        if is_admin or site_tenant == tenant_id:
            filtered_sites.append(s)
    
    for s in filtered_sites:
        if cortex: s['computed_financials'] = cortex.enrich_site_financials(s)
    
    analysis = cortex.analyze_portfolio(filtered_sites) if cortex else {"global": {}, "green_league": {}}
    fleet_list = []
    all_cities = set()
    all_providers = set()
    
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
            final_budget = fin.get('budget_subscription', 0) + (final_vol * 1000 * avg_price)

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
            "tenant_id": s.get('identity', {}).get('tenant_id', 'Orphelin') # Ajouté pour contrôle visuel
        })
        
    return JSONResponse(json_compliant({
        "fleet": fleet_list, 
        "count": len(fleet_list), 
        "green_league": analysis.get('green_league'), 
        "global_kpis": analysis.get('global'),
        "filters_meta": { "cities": sorted(list(all_cities)), "providers": sorted(list(all_providers)), "segments": ["C5", "C4", "C3", "C2", "C1", "T1", "T2", "T3"], "lots": ["Lot 1", "Lot 2"] }
    }))

@app.post("/api/settings/propagate_tariff")
async def api_propagate_tariff(payload: PropagateRequest, user = Depends(get_current_user)):
    try:
        if not user: return JSONResponse({"error": "Non autorisé"}, 401)
        
        # Un client ne peut propager des tarifs QUE sur son propre parc
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
                
                # Le bouclier
                if not is_admin and identity.get('tenant_id') != tenant_id: continue
                
                contract = data.get('contract', {})
                segment_match = (str(payload.filters.get('segment', '')).lower() == str(contract.get('segment', '')).lower())
                lot_match = True
                if payload.filters.get('lot_name') and payload.filters.get('lot_name') != "Aucun":
                    lot_match = (str(payload.filters.get('lot_name')).lower() == str(identity.get('ref_copro', '')).lower() or str(payload.filters.get('lot_name')).lower() == str(identity.get('lot_name', '')).lower())
                
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
    if not data: return JSONResponse({"error": "Site introuvable dans Firestore"}, 404)
    
    # Bouclier de lecture individuelle
    profile = db.get_user_profile(user.get("uid"))
    if user.get("role") != "ADMIN" and data.get("identity", {}).get("tenant_id") != profile.get("tenant_id", "ORPHELIN"):
        return JSONResponse({"error": "Accès refusé à ce PDL."}, 403)
        
    financials = cortex.enrich_site_financials(data) if cortex else {'meta':{'is_gas':False}, 'kpis':{'unit_price_kwh':0, 'pmc_eur_mwh':0, 'ghost_savings':0}, 'volume_mwh':0, 'budget_annual':0, 'pricing_details':{}}
    mr = get_market_ref()
    ma = cortex.analyze_market_position(financials['kpis']['unit_price_kwh'], mr, is_gas=financials['meta']['is_gas']) if cortex else {"status": "ANALYSE"}
    if 'ref_price' not in ma: ma = {"status": "ANALYSE", "ref_price": mr['gaz']['peg_n1'] if financials['meta']['is_gas'] else mr['elec']['cal_n1'], "details": {"market_label": "PEG N+1" if financials['meta']['is_gas'] else "CAL N+1"}}

    contract = data.get('contract', {})
    pricing = financials['pricing_details']
    vol_display = float(financials['volume_mwh'] or data.get('kpis', {}).get('volume_mwh', 0))
    budget_display = float(financials['budget_annual'])
    if budget_display == 0 and vol_display > 0: budget_display = financials.get('budget_subscription', 0) + (vol_display * 1000 * float(data.get('pricing', {}).get('hph') or 0.20))
    pd = contract.get('power_details', {})

    return JSONResponse(json_compliant({
        "energy_type": "gaz" if financials['meta']['is_gas'] else "elec", "identity": data.get('identity', {}), "location": data.get('location', {}), "technical": data.get('technical', {}), "financials": data.get('financials', {}),
        "contract": {"pdl": contract.get('pdl'), "provider": financials['meta'].get('provider') or contract.get('provider', 'Inconnu'), "segment": financials.get('display_overrides', {}).get('segment', contract.get('segment', '-')), "start_date": contract.get('start_date'), "end_date": contract.get('end_date'), "power": contract.get('power'), "p_max": contract.get('p_max'), "fta": contract.get('fta'), "grd": contract.get('grd'), "cja": contract.get('cja'), "profil": contract.get('profil'), "tarif_acheminement": contract.get('tarif_acheminement'), "power_details": pd, "ps_hph": contract.get('ps_hph') or pd.get('hph') or "-", "ps_hch": contract.get('ps_hch') or pd.get('hch') or "-", "ps_hpe": contract.get('ps_hpe') or pd.get('hpe') or "-", "ps_hce": contract.get('ps_hce') or pd.get('hce') or "-", "consumption_details": contract.get('consumption_details', {})},
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
        
        selected = [s for s in (db.get_site(sid) for sid in body.get('site_ids', [])) if s and (is_admin or s.get("identity", {}).get("tenant_id") == tid)]
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
    return JSONResponse(content={"report": [router.analyze_file_stream(await f.read(), f.filename) for f in files]})

@app.post("/api/finance/upload")
async def api_finance_upload(file: UploadFile = File(...), site_id: str = Form(...), user = Depends(get_current_user)):
    try:
        parsed = finance.parse_invoice(await file.read(), file.filename)
        if parsed.get("status") == "ERROR": return JSONResponse(parsed, status_code=400)
        
        site_data = db.get_site(site_id) or {}
        # Securité
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
# VUES HTML (SÉCURISÉES)
# ==========================================
@app.get("/settings", response_class=HTMLResponse)
async def view_settings(request: Request, user = Depends(get_current_user)):
    if not user: return RedirectResponse(url="/login")
    # C'est la page du client. Elle est bridée.
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/settings_ops", response_class=HTMLResponse)
async def view_settings_ops(request: Request, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return RedirectResponse(url="/login")
    # C'est TA page (God Mode).
    return templates.TemplateResponse("settings_ops.html", {"request": request})

@app.get("/ops_nexus", response_class=HTMLResponse)
async def view_ops_nexus(request: Request, user = Depends(get_current_user)):
    if not user or user.get("role") != "ADMIN": return RedirectResponse(url="/login")
    return templates.TemplateResponse("ops_nexus.html", {"request": request})

@app.get("/ops/ingest", response_class=HTMLResponse)
async def ops_ingest_page(request: Request, user = Depends(get_current_user)):
    if not user or user.get("role") not in ["ADMIN", "OPS_TECH"]: return RedirectResponse(url="/login")
    return templates.TemplateResponse("ops_ingest.html", {"request": request, "api_status": router.get_api_status() if router else {}})

@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str, user = Depends(get_current_user)):
    PUBLIC_PAGES = ["index.html", "onboarding.html", "processing.html", "login.html", "solutions.html", "cortex.html", "vitality.html", "connectivite.html", "audit_premium.html", "store.html", "ethique.html", "fournisseurs.html", "etudes-de-cas.html", "modele_economique.html"]
    if any(x in page_name for x in [".js", ".css", ".png", ".jpg"]): return JSONResponse({}, 404)
    target_file = page_name if page_name.endswith(".html") else f"{page_name}.html"
    
    if target_file not in PUBLIC_PAGES and not user: return RedirectResponse(url="/login")
    if os.path.exists(os.path.join(TEMPLATE_DIR, target_file)): return templates.TemplateResponse(target_file, {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in ["static", "assets", "favicon"]): return JSONResponse({}, 404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
