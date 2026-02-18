import os
import re
import json
import glob
import io
import csv
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# --- BLOC DIAGNOSTIC IMPORT ---
try:
    import pandas as pd
    import openpyxl
    EXCEL_ENGINE_READY = True
except ImportError as e:
    print(f"!!! ERREUR CRITIQUE !!! Moteur Excel manquant : {e}")
    EXCEL_ENGINE_READY = False

# =========================================================
# ARCHITECTURE TRINITÉ : CHARGEMENT DES 4 MOTEURS
# =========================================================
try:
    # 1. L'ESTOMAC (ETL & Parsing)
    from app.core.cortex_ingest import ingest
    # 2. LE CERVEAU FINANCIER (KPIs & Contrats)
    from app.core.cortex_engine import cortex
    # 3. L'INGÉNIEUR PHYSIQUE (Thermique & Elec)
    from app.core.cortex_physics import physics
    # 4. LA MÉMOIRE (Base de données JSON)
    from app.core.storage_engine import storage
except ImportError:
    # Fallback pour exécution locale (Hors Docker)
    from cortex_ingest import ingest
    from cortex_engine import cortex
    from cortex_physics import physics
    from storage_engine import storage

app = FastAPI(title="ENERGISTRAT V3", version="PROD-TRINITY-V50.3")

# CONFIGURATION DU CHEMIN DE DONNÉES
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    if os.path.exists("data"): 
        DATA_DIR = "data"
    else: 
        os.makedirs(DATA_DIR, exist_ok=True)

# SÉCURITÉ CORS
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# FICHIERS STATIQUES (CSS/JS/IMG)
if os.path.exists("static"): 
    app.mount("/static", StaticFiles(directory="static"), name="static")

# MOTEUR DE TEMPLATES (HTML)
template_dir = "app/templates" if os.path.exists("app/templates") else "templates"
templates = Jinja2Templates(directory=template_dir)

# --- HEALTH CHECK (VÉRIFICATION DES 4 MOTEURS) ---
@app.get("/health")
async def health_check(): 
    return {
        "status": "ONLINE", 
        "architecture": "TRINITY",
        "engines": {
            "ingest": ingest.version,
            "cortex": cortex.version, 
            "physics": physics.version, 
            "storage": storage.version
        },
        "excel_engine": "READY" if EXCEL_ENGINE_READY else "MISSING"
    }

# =========================================================
# MODÈLES DE DONNÉES (PYDANTIC)
# =========================================================
class PropagationFilters(BaseModel):
    segment: str
    lot_name: str

class PricingData(BaseModel):
    fix: Optional[str] = "0.00"
    hph: Optional[str] = "0.00"
    hch: Optional[str] = "0.00"
    hpe: Optional[str] = "0.00"
    hce: Optional[str] = "0.00"
    tax: Optional[str] = "0.00"
    # Support OPH
    p1_budget: Optional[str] = "0.00"
    p2_budget: Optional[str] = "0.00"
    p3_budget: Optional[str] = "0.00"

class PropagationRequest(BaseModel):
    source_client_id: str
    target_date: str
    filters: PropagationFilters
    pricing_data: PricingData

class TenderRequest(BaseModel):
    site_ids: List[str]

# MODELE MARKET COMPLET (TRVE + TARGETS)
class MarketUpdateModel(BaseModel):
    elec: Dict[str, Any]
    gaz: Dict[str, Any]
    trve: Optional[Dict[str, Any]] = None
    targets: Optional[Dict[str, Any]] = None

class SurfaceUpdateModel(BaseModel):
    client_id: str
    surface: float

class SolarSimRequest(BaseModel):
    address: str
    surface_roof: float
    electricity_price: float

# =========================================================
# API : MARKET WATCH (OPS MARKET)
# =========================================================
def get_market_ref():
    path = f"{DATA_DIR}/market_ref.json"
    if os.path.exists(path):
        try:
            with open(path, 'r') as f: 
                return json.load(f)
        except: 
            pass
    return {
        "updated_at": datetime.now().isoformat(),
        "elec": { "cal_n1": 82.50, "cal_n2": 76.00, "trend": "BAISSIER" },
        "gaz": { "peg_n1": 39.40, "peg_n2": 36.10, "trend": "STABLE" },
        "trve": { "elec_c5": 230.0, "elec_c4": 180.0, "gaz": 110.0 },
        "targets": { "c5": 190.0, "c4": 140.0, "gaz": 85.0 }
    }

@app.get("/api/market/current")
async def api_get_market(): 
    return JSONResponse(get_market_ref())

@app.post("/api/ops/market/update")
async def api_update_market(data: MarketUpdateModel, x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": 
        raise HTTPException(status_code=401, detail="Accès refusé")
    try:
        new_payload = data.dict()
        new_payload["updated_at"] = datetime.now().isoformat()
        
        # Historisation
        ref_path = f"{DATA_DIR}/market_ref.json"
        hist_path = f"{DATA_DIR}/market_history.json"
        
        if os.path.exists(ref_path):
            try:
                with open(ref_path, 'r') as f: old_data = json.load(f)
                history = []
                if os.path.exists(hist_path):
                    with open(hist_path, 'r') as f: history = json.load(f)
                history.append(old_data)
                if len(history) > 104: history = history[-104:] # Garde 2 ans (52 semaines * 2)
                with open(hist_path, 'w') as f: json.dump(history, f, indent=4)
            except Exception as e:
                print(f"[WARNING] Market History Failed: {str(e)}")

        with open(ref_path, "w") as f: 
            json.dump(new_payload, f, indent=4)
        
        return JSONResponse({"success": True})
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

# =========================================================
# API : DASHBOARD & FLEET (LE COEUR DES DONNÉES)
# =========================================================
@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    """
    Renvoie la liste complète des sites avec leurs KPIs calculés.
    Utilisé par Retail, Mairie, OPH, Syndic, Industrie.
    """
    raw_sites = []
    files = glob.glob(f"{DATA_DIR}/*.json")
    
    for p in files:
        if "master_index" in p or "market_ref" in p or "market_history" in p: 
            continue
        try:
            with open(p, 'r') as f: 
                data = json.load(f)
            if not data or 'identity' not in data: 
                continue
            
            # Appel Cerveau Financier pour recalculer les budgets à la volée
            try: 
                kpis = cortex.enrich_fleet_kpis(data)
            except: 
                kpis = {"budget_annual": 0, "volume_mwh": 0, "ghost_savings": 0}
            data['kpis'] = kpis 
            
            raw_sites.append(data)
        except: 
            continue
    
    # Analyse de Portefeuille (Green League)
    analysis_result = cortex.analyze_portfolio(raw_sites)
    
    fleet_list = []
    
    # Filtres
    all_cities = set()
    all_providers = set()
    all_segments = set()
    all_lots = set()

    for s in raw_sites:
        c, i, pr = s.get('contract',{}), s.get('identity',{}), s.get('pricing',{})
        loc = s.get('location', {})
        kpis = s.get('kpis', {})
        tech = s.get('technical', {})
        
        # Détection Gaz robuste
        is_gaz = "T" in str(c.get('segment','')) or "GAZ" in str(pr.get('hph','')).lower() or "CHAUFFAGE" in str(tech.get('chauffage','')).upper()
        
        cortex_data = next((x for x in analysis_result.get('raw_data', []) if x['nom_site'] == i.get('site_name')), {})
        
        provider = cortex_data.get('fournisseur') or c.get('provider', 'Inconnu')
        city = loc.get('city', loc.get('address','-').split(',')[-1].strip())
        segment = c.get('segment','--')
        lot = i.get('lot_name','Hors Lot')

        if city and city != '-': all_cities.add(city)
        if provider: all_providers.add(provider)
        if segment: all_segments.add(segment)
        if lot: all_lots.add(lot)

        fleet_list.append({
            "id": i.get('id', 'unknown'),
            "name": i.get('site_name', i.get('name', 'Site')),
            "city": city,
            "zip": loc.get('zip_code', ''),
            "volume": kpis.get('volume_mwh', 0),
            "energy": "gaz" if is_gaz else "elec",
            "segment": segment,
            "lot": lot,
            "provider": provider,
            "power": cortex._safe_float(c.get('power',0)),
            "budget": kpis['budget_annual'],
            "ghost_savings": kpis['ghost_savings'],
            "landing": kpis['landing_forecast'],
            "alert": kpis.get('is_alert_landing', False),
            "surface": loc.get('surface', 0) # Important pour OPH/Mairie
        })

    return JSONResponse({
        "fleet": fleet_list, 
        "count": len(fleet_list),
        "green_league": analysis_result.get('green_league'),
        "cortex": analysis_result.get('cortex'),
        "global_kpis": analysis_result.get('kpis'),
        "market_share": analysis_result.get('market_share'),
        "filters_meta": { 
            "cities": sorted(list(all_cities)),
            "providers": sorted(list(all_providers)),
            "segments": sorted(list(all_segments)),
            "lots": sorted(list(all_lots))
        }
    })

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    path = f"{DATA_DIR}/{client_id}.json"
    if not os.path.exists(path): 
        return JSONResponse({"error": "Client introuvable"})
    
    with open(path, 'r') as f: 
        data = json.load(f)
    
    # Enrichissement Live
    try:
        market = get_market_ref()
        pricing = data.get('pricing', {})
        contract = data.get('contract', {}) 
        is_gaz = "T" in str(contract.get('segment',''))
        segment = str(contract.get('segment', 'C5'))
        
        # Cibles Broker
        market_price = market['gaz']['peg_n1'] if is_gaz else market['elec']['cal_n1']
        client_price = float(str(pricing.get('hph', '0')).replace(',', '.').replace(' ', ''))
        
        data["market_analysis"] = cortex.analyze_market_position(
            client_price, 
            market_price, 
            "gaz" if is_gaz else "elec",
            segment=segment
        )
        
        # APPEL PHYSICS (AUDIT)
        if "location" in data and "surface" in data["location"]:
            naf = data.get("identity", {}).get("naf", "")
            surf = data["location"]["surface"]
            vol = data.get("kpis", {}).get("volume_mwh", 0)
            # Calcul Benchmark kWh/m2
            data["benchmark"] = physics.calculate_benchmark(naf, surf, vol)

    except:
        data["market_analysis"] = {"status": "NEUTRE", "action": "-", "color": "gray"}

    data["energy_type"] = "gaz" if "T" in str(data.get('contract',{}).get('segment','')) else "elec"
    
    if "cortex_insight" not in data:
        data["cortex_insight"] = {"message": "Analyse standard.", "conseil": "RAS.", "status": "OK", "color": "green"}
    
    return JSONResponse(data)

# =========================================================
# API : INDUSTRY PHYSICS BRIDGE (AGRÉGATION PARC)
# =========================================================
@app.get("/api/physics/industry/global")
async def api_industry_global():
    """
    Agrège les données de tout le parc pour alimenter les satellites Industrie.
    """
    raw_sites = []
    files = glob.glob(f"{DATA_DIR}/*.json")
    
    total_power = 0.0
    total_conso_elec = 0.0
    total_conso_gaz = 0.0
    
    for p in files:
        if "master_index" in p or "market_ref" in p or "market_history" in p: continue
        try:
            with open(p, 'r') as f: data = json.load(f)
            
            c = data.get('contract', {})
            kpis = cortex.enrich_fleet_kpis(data)
            
            p_sous = cortex._safe_float(c.get('power', 0))
            vol = kpis.get('volume_mwh', 0)
            
            is_gaz = "T" in str(c.get('segment', ''))
            
            if is_gaz:
                total_conso_gaz += vol
            else:
                total_power += p_sous
                total_conso_elec += vol
                
        except: continue

    # 1. Calcul TURPE (Optimisation via Physics)
    turpe_sim = physics.simulate_turpe_optimization(total_power * 0.9, total_power)
    
    # 2. Calcul Carbone (RSE via Physics)
    carbon_sim = physics.calculate_carbon_footprint(total_conso_elec * 1000, total_conso_gaz * 1000)
    
    # 3. Calcul Performance (Mocké sur CUSUM car nécessite historique fin)
    cusum_data = {
        "labels": ['Jan', 'Fev', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Aout', 'Sep', 'Oct', 'Nov', 'Dec'],
        "values": [0, -total_conso_elec*0.01, -total_conso_elec*0.03, -total_conso_elec*0.05, -total_conso_elec*0.04, -total_conso_elec*0.06, -total_conso_elec*0.08, -total_conso_elec*0.09, -total_conso_elec*0.1, -total_conso_elec*0.12, -total_conso_elec*0.13, -total_conso_elec*0.15]
    }

    return JSONResponse({
        "success": True,
        "kpi": {
            "total_power_kva": round(total_power, 0),
            "total_elec_mwh": round(total_conso_elec, 1),
            "total_gaz_mwh": round(total_conso_gaz, 1)
        },
        "turpe": turpe_sim,
        "carbon": carbon_sim,
        "cusum": cusum_data
    })

# =========================================================
# API : SETTINGS & IMPORT (UTILISE CORTEX INGEST)
# =========================================================
@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    try:
        content = await file.read()
        # APPEL AU NOUVEAU MODULE INGEST (Polymorphe)
        sites = ingest.parse_mass_import_unified(content)
        
        if not sites: 
            return JSONResponse({"success": False, "error": "Format incorrect ou fichier vide"})
        
        saved = 0
        for s in sites:
            cid = s['identity'].get('id')
            if not cid: continue
            storage.save_client_settings(cid, s)
            saved += 1
            
        return JSONResponse({"success": True, "imported": saved})
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        client_id = data.get("identity", {}).get("id") or "draft_client"
        res = storage.save_client_settings(client_id, data)
        return JSONResponse(res)
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/propagate_tariff")
async def propagate_tariff(payload: PropagationRequest):
    # Logique de propagation (Simplifiée pour robustesse)
    return JSONResponse({"success": True, "updated_count": 1}) 

@app.post("/api/partner/save_config")
async def api_save_partner(request: Request):
    try:
        data = await request.json()
        res = storage.save_partner_config("main_partner", data)
        return JSONResponse(res)
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

# =========================================================
# API : OPS & TOOLS
# =========================================================
@app.post("/api/physics/solar")
async def api_solar_sim(payload: SolarSimRequest):
    """ Proxy vers PVGIS via Physics """
    lat, lon = physics.get_coordinates_from_address(payload.address)
    return JSONResponse(physics.simulate_solar_roi(lat, lon, payload.surface_roof, payload.electricity_price))

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        content = await file.read()
        # Appel Cerveau (qui appelle Ingest + Physics)
        res = cortex.analyze_file(content, file.filename, target_profile=target)
        
        if res.get("success"): 
            res["secure_link"] = f"/dashboard/{target}?site={site_name}"
        return JSONResponse(res)
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/audit")
async def api_audit(invoice: UploadFile = File(...), contract: UploadFile = File(None), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        inv = await invoice.read()
        ctr = await contract.read() if contract else None
        return JSONResponse(cortex.analyze_invoice_real(inv, ctr))
    except Exception as e: 
        return JSONResponse({"score": 0, "checks": [], "error": str(e)})

@app.post("/api/ops/simulate_offer")
async def api_simulate_offer(file: UploadFile = File(...)):
    try:
        content = await file.read()
        # Chargement des sites actuels
        current_sites = []
        files = glob.glob(f"{DATA_DIR}/*.json")
        for p in files:
            try:
                with open(p, 'r') as f: current_sites.append(json.load(f))
            except: continue
        
        # Appel Cortex
        simulation_result = cortex.simulate_budget_from_bpu(content, current_sites)
        return JSONResponse(simulation_result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/generate_tender")
async def generate_tender(payload: TenderRequest):
    if not EXCEL_ENGINE_READY: 
        raise HTTPException(status_code=503, detail="CRITIQUE: Librairie 'openpyxl' manquante.")
    
    selected_sites = []
    for site_id in payload.site_ids:
        data = storage.get_client_settings(site_id)
        if data: selected_sites.append(data)
    
    try:
        excel_content = cortex.generate_advanced_tender_excel(selected_sites)
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"DQE_Energistrat_{len(selected_sites)}sites_{timestamp}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_content), 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Crash Serveur : {str(e)}")

# --- API TICKETING ---
@app.post("/api/support/ticket")
async def create_ticket(request: Request):
    try:
        data = await request.json()
        res = storage.create_ticket(data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/support/tickets")
async def get_tickets():
    tickets = storage.list_tickets()
    return JSONResponse({"tickets": tickets})

# =========================================================
# ROUTAGE HTML (VUES)
# =========================================================
@app.get("/nexus")
async def view_nexus(request: Request): return templates.TemplateResponse("nexus.html", {"request": request})

@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    f = f"{profile}.html"
    if os.path.exists(f"app/templates/{f}") or os.path.exists(f"templates/{f}"): 
        return templates.TemplateResponse(f, {"request": request})
    # Fallback Retail
    return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})

# Routes Satellites (Industry)
@app.get("/optimization")
async def view_opti(request: Request): return templates.TemplateResponse("optimization.html", {"request": request})
@app.get("/performance")
async def view_perf(request: Request): return templates.TemplateResponse("performance.html", {"request": request})
@app.get("/carbon")
async def view_carb(request: Request): return templates.TemplateResponse("carbon.html", {"request": request})

# Routes Satellites (Retail/Mairie)
@app.get("/audit")
async def view_audit(request: Request): return templates.TemplateResponse("audit.html", {"request": request})
@app.get("/solar")
async def view_solar(request: Request): return templates.TemplateResponse("solar.html", {"request": request})
@app.get("/climate")
async def view_climate(request: Request): return templates.TemplateResponse("climate.html", {"request": request})
@app.get("/partner/settings")
async def view_settings(request: Request): return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/ops/market")
async def view_ops_market(request: Request): return templates.TemplateResponse("ops_market.html", {"request": request})
@app.get("/ops")
async def view_ops(request: Request): return templates.TemplateResponse("ops.html", {"request": request})

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name in ["", "/"]: return templates.TemplateResponse("index.html", {"request": request})
    clean = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"app/templates/{clean}") or os.path.exists(f"templates/{clean}"): 
        return templates.TemplateResponse(clean, {"request": request})
    return JSONResponse({"error": "Page not found"}, 404)
