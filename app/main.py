import os
import json
import glob
import uuid
import math
import io
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import pandas as pd
    PANDAS_READY = True
except ImportError:
    PANDAS_READY = False

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
        pass

app = FastAPI(title="ENERGISTRAT V3", version="STABLE-SAPPHIRE-V130")

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

def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return [json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

def get_safe_id(raw_id):
    """ Nettoie l'ID pour éviter les crashs d'URL et de fichiers """
    return str(raw_id).replace('/', '_').replace(' ', '').replace('+', '').replace(',', '').strip()

# --- API ---

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        cid = data.get("identity", {}).get("id") or f"CLI_{uuid.uuid4().hex[:8]}"
        if "identity" not in data: data["identity"] = {}
        data["identity"]["id"] = cid
        file_path = os.path.join(DATA_DIR, f"{get_safe_id(cid)}.json")
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "id": cid})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/update_site")
async def api_update_site(request: Request):
    try:
        payload = await request.json()
        site_id = payload.get('id')
        if not site_id: return JSONResponse({"error": "ID manquant"}, 400)
        
        file_path = os.path.join(DATA_DIR, f"{get_safe_id(site_id)}.json")
        if not os.path.exists(file_path): return JSONResponse({"error": "Site introuvable"}, 404)
        
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        
        # Merge intelligent pour l'Audit
        if 'location' in payload: data['location'] = {**data.get('location', {}), **payload['location']}
        if 'technical' in payload: data['technical'] = {**data.get('technical', {}), **payload['technical']}
        
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "message": "Sauvegardé"})
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
                file_path = os.path.join(DATA_DIR, f"{get_safe_id(cid)}.json")
                with open(file_path, 'w', encoding='utf-8') as f: json.dump(s, f, indent=4, ensure_ascii=False)
                saved += 1
            except: pass
        return JSONResponse({"success": True, "imported": len(sites), "saved": saved})
    except ValueError as ve: return JSONResponse({"success": False, "error": str(ve)})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    raw_sites = []
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for p in files:
        if "master" in p or "market" in p: continue
        # FILTRE ANTI-ZOMBIES (Fichiers avec noms corrompus)
        if "," in p or "+" in p: continue
        
        try:
            with open(p, 'r', encoding='utf-8') as f: data = json.load(f)
            fin = cortex.enrich_site_financials(data)
            data['computed_financials'] = fin
            raw_sites.append(data)
        except: continue
    
    analysis = cortex.analyze_portfolio(raw_sites)
    
    fleet_list = []
    all_cities, all_providers, all_segments = set(), set(), set()
    for s in raw_sites:
        if s.get('identity',{}).get('id') == "new_client": continue
        fin = s['computed_financials']
        contract = s.get('contract', {})
        city = fin['meta']['city']
        prov = contract.get('provider', 'Inconnu')
        seg = contract.get('segment', '-')
        
        if city: all_cities.add(city)
        if prov: all_providers.add(prov)
        if seg: all_segments.add(seg)
        
        # APLATISSEMENT POUR LE FRONTEND (FIXE LE DRILL-DOWN)
        fleet_list.append({
            "id": get_safe_id(s.get('identity',{}).get('id')), # ID SÉCURISÉ
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
    file_path = os.path.join(DATA_DIR, f"{get_safe_id(client_id)}.json")
    if not os.path.exists(file_path): return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    
    financials = cortex.enrich_site_financials(data)
    
    # APLATISSEMENT VITAL POUR AUDIT & SOLAR & DETAIL
    merged_data = {
        **data,
        **financials, # Injecte meta, details, kpis à la racine
        "budget": financials['budget_annual'],
        "volume_mwh": financials['volume_mwh'],
        "surface": data.get('location', {}).get('surface', 0), # Pour l'Audit
        "electricity_price": financials['kpis']['unit_price_kwh'] # Pour le Solaire
    }
    
    if "location" in data and "surface" in data["location"]:
        naf = data.get("identity", {}).get("naf", "")
        surf = data["location"]["surface"]
        vol = financials['volume_mwh']
        merged_data["benchmark"] = cortex.calculate_benchmark(naf, surf, vol)
    
    return JSONResponse(json_compliant(merged_data))

@app.post("/api/physics/solar")
async def api_solar_sim(request: Request):
    try:
        payload = await request.json()
        address = payload.get('address', '')
        surface = float(payload.get('surface_roof', 0))
        price_raw = float(payload.get('electricity_price', 0.20))
        price = price_raw / 1000.0 if price_raw > 2.0 else price_raw
        if price == 0: price = 0.20
        lat, lon = physics.get_coordinates_from_address(address)
        return JSONResponse(physics.simulate_solar_roi(lat, lon, surface, price))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/api/tools/template/{template_type}")
async def download_template(template_type: str):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    stream = io.BytesIO()
    try:
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if "import" in template_type:
                df = pd.DataFrame(columns=["PDL", "NOM_SITE", "ADRESSE", "CP", "VILLE", "VOLUME_ANNUEL", "PUISSANCE", "PRIX_HPH", "ABONNEMENT"])
                df.to_excel(writer, index=False)
            elif "bpu" in template_type:
                df = pd.DataFrame(columns=["PRIX_HPH", "ABONNEMENT"])
                df.to_excel(writer, index=False)
            else:
                df = pd.DataFrame(columns=["A", "B"])
                df.to_excel(writer, index=False)
        stream.seek(0)
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=template_{template_type}.xlsx"})
    except:
        stream = io.StringIO()
        pd.DataFrame().to_csv(stream)
        return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")

# ROUTEUR PASSE-PARTOUT POUR LES LIENS STATIQUES
@app.get("/app/assets/{filename}")
async def get_static_asset(filename: str):
    if "template" in filename: return await download_template("import")
    if "bpu" in filename: return await download_template("bpu")
    return JSONResponse({"error": "File not found"}, 404)

@app.get("/assets/{filename}")
async def get_static_asset_root(filename: str):
    if "template" in filename: return await download_template("import")
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
            if "," in p or "+" in p: continue # Anti-Zombie
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
            file_path = os.path.join(DATA_DIR, f"{get_safe_id(sid)}.json")
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f: selected_sites.append(json.load(f))
        df_dqe = cortex.generate_dqe_structure(selected_sites)
        df_elec = df_dqe[df_dqe['Type'] == 'ELEC']
        df_gaz = df_dqe[df_dqe['Type'] == 'GAZ']
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if not df_elec.empty: df_elec.to_excel(writer, index=False, sheet_name="ELEC")
            if not df_gaz.empty: df_gaz.to_excel(writer, index=False, sheet_name="GAZ")
            if df_elec.empty and df_gaz.empty: df_dqe.to_excel(writer, index=False, sheet_name="TOUT")
        stream.seek(0)
        timestamp = datetime.now().strftime("%Y%m%d")
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=DQE_{timestamp}.xlsx"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

# ROUTAGE HTML
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
