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
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# BLOC IMPORT ROBUSTE (PANDAS EST REQUIS POUR L'EXPORT EXCEL)
try:
    import pandas as pd
    PANDAS_READY = True
except ImportError:
    PANDAS_READY = False
    print("⚠️ WARNING: Pandas manquant. L'export Excel sera désactivé.")

# =========================================================
# 1. CHARGEMENT DES ORGANES VITAUX (TRI-CORTEX)
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
app = FastAPI(title="ENERGISTRAT V3", version="STABLE-PLATINUM-V80")

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

# =========================================================
# 3. UTILITAIRE DE SÉCURITÉ (ANTI-NAN)
# =========================================================
def json_compliant(data):
    """
    Nettoie récursivement les données avant envoi au Frontend.
    Remplace NaN, Infinity par 0.0 pour éviter le crash du JSON.
    """
    if isinstance(data, dict):
        return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

# =========================================================
# 4. API : GESTION DES DONNÉES (CRUD)
# =========================================================

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    """ Création de compte (Onboarding) """
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
    """ Import Massif Excel/CSV """
    try:
        content = await file.read()
        sites = ingest.parse_mass_import_unified(content)
        
        if not sites: 
            return JSONResponse({"success": False, "error": "Fichier vide ou illisible."})
        
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
    """ Données pour les Tableaux de Bord (Retail, Mairie, etc.) """
    raw_sites = []
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    
    for p in files:
        if "master" in p or "market" in p: continue
        try:
            with open(p, 'r', encoding='utf-8') as f: 
                data = json.load(f)
            # Enrichissement Live via Cortex Engine
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
            "landing": fin['landing_forecast'] # La valeur sécurisée anti-NaN
        })

    response_data = {
        "fleet": fleet_list, 
        "count": len(fleet_list),
        "green_league": analysis.get('green_league'),
        "global_kpis": analysis.get('global'),
        "filters_meta": { 
            "cities": sorted(list(all_cities)),
            "providers": sorted(list(all_providers)),
            "segments": sorted(list(all_segments))
        }
    }
    # Passage au filtre Anti-NaN avant envoi
    return JSONResponse(json_compliant(response_data))

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    """ Drill-down : Détail d'un site """
    safe_id = str(client_id).replace('/', '_').replace(' ', '')
    path = os.path.join(DATA_DIR, f"{safe_id}.json")
    
    if not os.path.exists(path): 
        return JSONResponse({"error": "Site introuvable"}, status_code=404)
    
    with open(path, 'r', encoding='utf-8') as f: 
        data = json.load(f)
    
    data['financials'] = cortex.enrich_site_financials(data)
    
    # Appel Physics pour Benchmark (Audit)
    if "location" in data and "surface" in data["location"]:
        naf = data.get("identity", {}).get("naf", "")
        surf = data["location"]["surface"]
        vol = data['financials']['volume_mwh']
        data["benchmark"] = cortex.calculate_benchmark(naf, surf, vol)
    
    return JSONResponse(json_compliant(data))

# =========================================================
# 5. API : OUTILS EXPERTS (COMPARATEUR & EXPORT)
# =========================================================

@app.post("/api/ops/simulate_offer")
async def api_simulate_offer(file: UploadFile = File(...)):
    """ Comparateur BPU """
    try:
        content = await file.read()
        # Charger les sites actuels
        current_sites = []
        files = glob.glob(os.path.join(DATA_DIR, "*.json"))
        for p in files:
            if "master" in p: continue
            try:
                with open(p, 'r', encoding='utf-8') as f: current_sites.append(json.load(f))
            except: continue
        
        # Appel Engine
        res = cortex.simulate_budget_from_bpu(content, current_sites)
        return JSONResponse(json_compliant(res))
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    """ Analyse Courbe de Charge (Solar/Audit) """
    content = await file.read()
    res = cortex.analyze_load_curve(content, file.filename)
    return JSONResponse(json_compliant(res))

@app.post("/api/ops/generate_tender")
async def generate_tender(request: Request):
    """ 
    Génération Excel DQE (RESTAURÉE) 
    Lit les IDs envoyés en JSON et renvoie un fichier .xlsx
    """
    if not PANDAS_READY:
        return JSONResponse({"error": "Pandas non installé sur le serveur."}, status_code=500)
        
    try:
        body = await request.json()
        site_ids = body.get('site_ids', [])
        
        selected_sites = []
        for sid in site_ids:
            safe_id = str(sid).replace('/', '_').replace(' ', '')
            path = os.path.join(DATA_DIR, f"{safe_id}.json")
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    selected_sites.append(json.load(f))
        
        # Appel Engine pour structurer le DQE
        df_dqe = cortex.generate_dqe_structure(selected_sites)
        
        # Création du fichier en mémoire
        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            df_dqe.to_excel(writer, index=False, sheet_name="DQE_Sites")
        stream.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"DQE_Energistrat_{len(selected_sites)}sites_{timestamp}.xlsx"
        
        return StreamingResponse(
            stream, 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# =========================================================
# 6. ROUTAGE HTML & UX (NAVIGATION)
# =========================================================

# A. PARCOURS UTILISATEUR
@app.get("/")
async def view_landing(request: Request): return templates.TemplateResponse("index.html", {"request": request})
@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/processing")
async def view_processing(request: Request): return templates.TemplateResponse("processing.html", {"request": request})

# B. DASHBOARDS MÉTIERS
@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    # Cherche template spécifique (ex: retail.html) sinon fallback dashboard.html
    t = f"{profile}.html"
    if os.path.exists(os.path.join(TEMPLATE_DIR, t)): 
        return templates.TemplateResponse(t, {"request": request, "profile": profile})
    return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})

# C. SETTINGS INTELLIGENTS
@app.get("/settings")
async def view_settings(request: Request):
    """ Route standard """
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/partner/settings")
async def view_partner_settings(request: Request):
    """ Route Smart : Détecte si on vient du Supplier """
    referer = request.headers.get("referer", "")
    if "supplier" in referer or "fournisseur" in referer:
        return templates.TemplateResponse("settings_partner.html", {"request": request})
    return templates.TemplateResponse("settings.html", {"request": request})

# D. SATELLITES & CATCH-ALL DYNAMIQUE
@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str):
    # Sécurité Assets
    if any(x in page_name for x in [".js", ".css", ".png", ".jpg", ".svg", ".ico"]):
        return JSONResponse({"error": "Asset not found"}, status_code=404)
    
    # Nettoyage nom
    clean_name = page_name if page_name.endswith(".html") else f"{page_name}.html"
    
    # Vérification fichier
    if os.path.exists(os.path.join(TEMPLATE_DIR, clean_name)):
        return templates.TemplateResponse(clean_name, {"request": request})
    
    # Redirection silencieuse vers Index si page inconnue
    return templates.TemplateResponse("index.html", {"request": request})

# E. CATCH-ALL PROFOND (Sécurité ultime)
@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in ["static", "assets", "favicon"]):
        return JSONResponse({"error": "File not found"}, status_code=404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
