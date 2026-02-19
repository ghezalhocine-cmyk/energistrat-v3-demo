import os
import json
import glob
import uuid
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime

# FRAMEWORK FASTAPI
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# =========================================================
# 1. CHARGEMENT DES ORGANES VITAUX
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

# =========================================================
# 2. CONFIGURATION DU SERVEUR
# =========================================================
app = FastAPI(title="ENERGISTRAT V3", version="STABLE-SMART-SETTINGS-V71")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# =========================================================
# 3. API : FONCTIONS VITALES (Back-End)
# =========================================================

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    """ Création de compte """
    try:
        data = await request.json()
        cid = data.get("identity", {}).get("id")
        if not cid:
            cid = f"CLI_{uuid.uuid4().hex[:8]}"
            if "identity" not in data: data["identity"] = {}
            data["identity"]["id"] = cid
        safe_id = str(cid).replace('/', '_').replace('\\', '_').replace(' ', '')
        file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "id": cid})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    """ Import Massif """
    try:
        content = await file.read()
        sites = ingest.parse_mass_import_unified(content)
        if not sites: return JSONResponse({"success": False, "error": "Fichier vide."})
        saved_count = 0
        for s in sites:
            try:
                cid = s.get('identity', {}).get('id') or f"GEN_{uuid.uuid4().hex[:8]}"
                s['identity']['id'] = cid
                safe_id = str(cid).replace('/', '_').replace('\\', '_').replace(' ', '')
                file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(s, f, indent=4, ensure_ascii=False)
                saved_count += 1
            except: pass
        return JSONResponse({"success": True, "imported": len(sites), "saved": saved_count})
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    """ Données Dashboard """
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
            "ratio": fin['kpis']['pmc_eur_mwh']
        })
    return JSONResponse({
        "fleet": fleet_list, 
        "count": len(fleet_list),
        "green_league": analysis.get('green_league'),
        "global_kpis": analysis.get('global'),
        "filters_meta": { "cities": sorted(list(all_cities)), "providers": sorted(list(all_providers)), "segments": sorted(list(all_segments)) }
    })

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    safe_id = str(client_id).replace('/', '_').replace(' ', '')
    path = os.path.join(DATA_DIR, f"{safe_id}.json")
    if not os.path.exists(path): return JSONResponse({"error": "Site introuvable"}, 404)
    with open(path, 'r', encoding='utf-8') as f: data = json.load(f)
    data['financials'] = cortex.enrich_site_financials(data)
    return JSONResponse(data)

# =========================================================
# 4. ROUTAGE INTELLIGENT (SMART ROUTING)
# =========================================================

# A. FLUX PRINCIPAL
@app.get("/")
async def view_landing(request: Request): return templates.TemplateResponse("index.html", {"request": request})
@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/processing")
async def view_processing(request: Request): return templates.TemplateResponse("processing.html", {"request": request})

# B. DASHBOARDS (Profils)
@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    template_name = f"{profile}.html"
    path = os.path.join(TEMPLATE_DIR, template_name)
    if os.path.exists(path):
        return templates.TemplateResponse(template_name, {"request": request, "profile": profile})
    return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})

# C. GESTION DES SETTINGS (LE FIX EST ICI)
# ---------------------------------------------------------
@app.get("/settings")
async def view_settings(request: Request):
    """ Route standard pour Settings """
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/partner/settings")
async def view_partner_settings_smart(request: Request):
    """
    Route 'Intelligente' :
    - Si l'utilisateur vient du Dashboard SUPPLIER -> Affiche Settings Partenaire.
    - Sinon (Retail, Mairie, etc.) -> Redirige vers Settings Standard.
    """
    referer = request.headers.get("referer", "")
    
    # Si le referer contient 'supplier' ou 'fournisseur', c'est un partenaire
    if "supplier" in referer or "fournisseur" in referer:
        return templates.TemplateResponse("settings_partner.html", {"request": request})
    
    # Pour TOUS les autres (Retail, Mairie, Citoyen...), on force le standard
    return templates.TemplateResponse("settings.html", {"request": request})

# D. AUTRES PAGES SATELLITES
@app.get("/ops/market")
async def view_ops_market(request: Request): return templates.TemplateResponse("ops_market.html", {"request": request})

# E. ROUTEUR DYNAMIQUE (Pour tout le reste)
@app.get("/{page_name}")
async def serve_dynamic_pages(request: Request, page_name: str):
    if any(ext in page_name for ext in [".js", ".css", ".png", ".jpg", ".svg", ".ico"]):
        return JSONResponse({"error": "Asset not found"}, status_code=404)

    clean_name = page_name if page_name.endswith(".html") else f"{page_name}.html"
    file_path = os.path.join(TEMPLATE_DIR, clean_name)
    
    if os.path.exists(file_path):
        return templates.TemplateResponse(clean_name, {"request": request})
    
    # Fallback Index
    return templates.TemplateResponse("index.html", {"request": request})

# F. CATCH-ALL DEEP
@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in ["static", "assets", "favicon"]):
        return JSONResponse({"error": "File not found"}, status_code=404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
