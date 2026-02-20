import os
import json
import glob
import uuid
import math
import io
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime

# FRAMEWORK FASTAPI
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# BLOC IMPORT ROBUSTE
try:
    import pandas as pd
    PANDAS_READY = True
except ImportError:
    PANDAS_READY = False

# =========================================================
# 1. CHARGEMENT
# =========================================================
try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_engine import cortex
    from app.core.cortex_physics import physics
except ImportError:
    try:
        from cortex_ingest import ingest
        from cortex_engine import cortex
        from cortex_physics import physics
    except ImportError:
        print("🚨 ERREUR CRITIQUE: Modules Cortex manquants.")

app = FastAPI(title="ENERGISTRAT V3", version="STABLE-DIAMOND-V85")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GESTION DES DOSSIERS
BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR, exist_ok=True)

TEMPLATE_DIR = os.path.join(BASE_DIR, "app/templates")
if not os.path.exists(TEMPLATE_DIR): TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATE_DIR)

STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR): STATIC_DIR = os.path.join(BASE_DIR, "app/static")
if os.path.exists(STATIC_DIR): app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Dossier pour les Templates Excel (Téléchargement)
ASSETS_DIR = os.path.join(BASE_DIR, "app/assets")
if not os.path.exists(ASSETS_DIR): os.makedirs(ASSETS_DIR, exist_ok=True)

# =========================================================
# 2. UTILS
# =========================================================
def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return [json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

# =========================================================
# 3. API : CRUD & PERSISTANCE
# =========================================================

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        cid = data.get("identity", {}).get("id") or f"CLI_{uuid.uuid4().hex[:8]}"
        if "identity" not in data: data["identity"] = {}
        data["identity"]["id"] = cid
        safe_id = str(cid).replace('/', '_').replace('\\', '_').replace(' ', '')
        file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "id": cid})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

# --- FIX AUDIT : ROUTE POUR SAUVEGARDER LA SURFACE ---
@app.post("/api/settings/update_site")
async def api_update_site(request: Request):
    """ Met à jour un site (ex: ajout de surface) et sauvegarde sur disque """
    try:
        payload = await request.json()
        site_id = payload.get('id')
        if not site_id: return JSONResponse({"error": "ID manquant"}, 400)
        
        safe_id = str(site_id).replace('/', '_').replace(' ', '')
        file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
        
        if not os.path.exists(file_path): return JSONResponse({"error": "Site introuvable"}, 404)
        
        # Lecture Existant
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Mise à jour des champs (Merge intelligent)
        if 'location' in payload:
            data['location'] = {**data.get('location', {}), **payload['location']}
        if 'technical' in payload:
            data['technical'] = {**data.get('technical', {}), **payload['technical']}
            
        # Sauvegarde
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        return JSONResponse({"success": True, "message": "Données sauvegardées"})
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
                cid = s.get('identity', {}).get('id') or f"GEN_{uuid.uuid4().hex[:8]}"
                s['identity']['id'] = cid
                safe_id = str(cid).replace('/', '_').replace('\\', '_').replace(' ', '')
                file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(s, f, indent=4, ensure_ascii=False)
                saved += 1
            except: pass
        return JSONResponse({"success": True, "imported": len(sites), "saved": saved})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    raw_sites = []
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for p in files:
        if "master" in p or "market" in p: continue
        try:
            with open(p, 'r', encoding='utf-8') as f: 
                data = json.load(f)
            fin = cortex.enrich_site_financials(data)
            data['computed_financials'] = fin
            raw_sites.append(data)
        except: continue
    
    analysis = cortex.analyze_portfolio(raw_sites)
    
    fleet_list = []
    all_cities, all_providers, all_segments = set(), set(), set()
    for s in raw_sites:
        fin = s['computed_financials']
        contract = s.get('contract', {})
        city = fin['meta']['city']
        prov = contract.get('provider', 'Inconnu')
        seg = contract.get('segment', '-')
        if city: all_cities.add(city)
        if prov: all_providers.add(prov)
        if seg: all_segments.add(seg)
        fleet_list.append({
            "id": s.get('identity',{}).get('id'),
            "name": fin['meta']['site_label'],
            "city": city,
            "volume": fin['volume_mwh'],
            "energy": "gaz" if "Gaz" in fin['meta']['energy_type'] else "elec",
            "segment": seg,
            "provider": prov,
            "budget": fin['budget_annual'],
            "ratio": fin['kpis']['pmc_eur_mwh'],
            "landing": fin['landing_forecast']
        })
    response = {
        "fleet": fleet_list, "count": len(fleet_list),
        "green_league": analysis.get('green_league'),
        "global_kpis": analysis.get('global'),
        "filters_meta": { "cities": sorted(list(all_cities)), "providers": sorted(list(all_providers)), "segments": sorted(list(all_segments)) }
    }
    return JSONResponse(json_compliant(response))

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    safe_id = str(client_id).replace('/', '_').replace(' ', '')
    path = os.path.join(DATA_DIR, f"{safe_id}.json")
    if not os.path.exists(path): return JSONResponse({"error": "Site introuvable"}, 404)
    with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
    
    # Enrichissement
    data['financials'] = cortex.enrich_site_financials(data)
    
    # Benchmark (Audit)
    if "location" in data and "surface" in data["location"]:
        naf = data.get("identity", {}).get("naf", "")
        surf = data["location"]["surface"]
        vol = data['financials']['volume_mwh']
        data["benchmark"] = cortex.calculate_benchmark(naf, surf, vol)
    
    return JSONResponse(json_compliant(data))

# =========================================================
# 4. API : OUTILS EXPERTS (SOLAR, EXPORT, COMPARATEUR)
# =========================================================

# --- FIX SOLAR : ROUTE RESTAURÉE ---
@app.post("/api/physics/solar")
async def api_solar_sim(request: Request):
    """ Proxy vers PVGIS via Physics """
    try:
        payload = await request.json()
        address = payload.get('address', '')
        surface = float(payload.get('surface_roof', 0))
        price = float(payload.get('electricity_price', 0.20))
        
        # Géocoding via Physics
        lat, lon = physics.get_coordinates_from_address(address)
        # Simulation
        return JSONResponse(physics.simulate_solar_roi(lat, lon, surface, price))
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

# --- FIX TEMPLATES : ROUTE RESTAURÉE ---
@app.get("/api/tools/template/{template_type}")
async def download_template(template_type: str):
    """ Génère un template Excel à la volée si inexistant """
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    
    filename = f"template_{template_type}.xlsx"
    
    # Création à la volée d'un template propre
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        if template_type == "import":
            df = pd.DataFrame(columns=["PDL", "NOM_SITE", "ADRESSE", "CP", "VILLE", "VOLUME_ANNUEL", "PUISSANCE", "PRIX_HPH", "ABONNEMENT"])
            df.to_excel(writer, index=False)
        else:
            df = pd.DataFrame(columns=["A", "B"])
            df.to_excel(writer, index=False)
    stream.seek(0)
    
    return StreamingResponse(
        stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

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
    """ Génération Excel DQE Conforme au Masque """
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    try:
        body = await request.json()
        site_ids = body.get('site_ids', [])
        selected_sites = []
        for sid in site_ids:
            safe_id = str(sid).replace('/', '_').replace(' ', '')
            path = os.path.join(DATA_DIR, f"{safe_id}.json")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f: selected_sites.append(json.load(f))
        
        # Appel Engine V85 (Nouveau générateur DQE)
        df_dqe = cortex.generate_dqe_structure(selected_sites)
        
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            df_dqe.to_excel(writer, index=False, sheet_name="DQE_Sites")
        stream.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        return StreamingResponse(
            stream, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            headers={"Content-Disposition": f"attachment; filename=DQE_{timestamp}.xlsx"}
        )
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

# =========================================================
# 5. ROUTAGE HTML
# =========================================================
@app.get("/")
async def view_landing(request: Request): return templates.TemplateResponse("index.html", {"request": request})
@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/processing")
async def view_processing(request: Request): return templates.TemplateResponse("processing.html", {"request": request})
@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    t = f"{profile}.html"
    if os.path.exists(os.path.join(TEMPLATE_DIR, t)): return templates.TemplateResponse(t, {"request": request, "profile": profile})
    return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})
@app.get("/settings")
async def view_settings(request: Request): return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/partner/settings")
async def view_partner_settings(request: Request):
    if "supplier" in request.headers.get("referer", ""): return templates.TemplateResponse("settings_partner.html", {"request": request})
    return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str):
    if any(x in page_name for x in [".js", ".css", ".png", ".jpg"]): return JSONResponse({}, 404)
    c = page_name if page_name.endswith(".html") else f"{page_name}.html"
    if os.path.exists(os.path.join(TEMPLATE_DIR, c)): return templates.TemplateResponse(c, {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})
@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in ["static", "assets", "favicon"]): return JSONResponse({}, 404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
