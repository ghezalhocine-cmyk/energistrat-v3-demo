import os
import re
import json
import glob
import io
import csv
import traceback
import uuid
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
    # Fallback pour exécution locale
    from cortex_ingest import ingest
    from cortex_engine import cortex
    from cortex_physics import physics
    from storage_engine import storage

app = FastAPI(title="ENERGISTRAT V3", version="PROD-TRINITY-V56.DIAMOND")

# CONFIGURATION DU CHEMIN DE DONNÉES (CRITIQUE POUR LA MÉMOIRE)
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

# FICHIERS STATIQUES & TEMPLATES
if os.path.exists("static"): 
    app.mount("/static", StaticFiles(directory="static"), name="static")
template_dir = "app/templates" if os.path.exists("app/templates") else "templates"
templates = Jinja2Templates(directory=template_dir)

# --- HEALTH CHECK ---
@app.get("/health")
async def health_check(): 
    # Compte les fichiers en mémoire pour vérifier si l'import a marché
    site_count = len(glob.glob(f"{DATA_DIR}/*.json"))
    return {
        "status": "ONLINE", 
        "architecture": "TRINITY V56",
        "memory_status": f"{site_count} sites en base de données",
        "data_dir": DATA_DIR,
        "engines": {
            "ingest": ingest.version,
            "cortex": cortex.version, 
            "physics": physics.version
        }
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
    tax: Optional[str] = "0.00"

class PropagationRequest(BaseModel):
    source_client_id: str
    target_date: str
    filters: PropagationFilters
    pricing_data: PricingData

class TenderRequest(BaseModel):
    site_ids: List[str]

class MarketUpdateModel(BaseModel):
    elec: Dict[str, Any]
    gaz: Dict[str, Any]
    trve: Optional[Dict[str, Any]] = None
    targets: Optional[Dict[str, Any]] = None

class SolarSimRequest(BaseModel):
    address: str
    surface_roof: float
    electricity_price: float

# =========================================================
# API : SETTINGS & IMPORT (LA RÉPARATION EST ICI)
# =========================================================
@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    """
    IMPORT MASSIF : Reçoit Excel/CSV -> Ingest -> Sauvegarde JSON Unitaire
    C'est cette route qui peuple le Dashboard.
    """
    try:
        content = await file.read()
        
        # 1. INGESTION (Extraction propre via V56)
        sites = ingest.parse_mass_import_unified(content)
        
        if not sites: 
            return JSONResponse({"success": False, "error": "Aucun site détecté. Vérifiez le format du fichier."})
        
        saved_count = 0
        errors = []

        # 2. PERSISTANCE (Écriture Disque Dur)
        for s in sites:
            try:
                # Récupération ID propre ou génération
                cid = s.get('identity', {}).get('id')
                if not cid:
                    cid = f"GEN_{uuid.uuid4().hex[:8]}"
                    s['identity']['id'] = cid
                
                # Nettoyage ID pour nom de fichier (pas de slash, pas d'espace)
                safe_id = str(cid).replace('/', '_').replace('\\', '_').replace(' ', '')
                
                # Écriture directe du fichier JSON (Bypasse les wrappers complexes pour la sécurité)
                file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(s, f, indent=4, ensure_ascii=False)
                
                saved_count += 1
            except Exception as write_err:
                print(f"Erreur écriture site {cid}: {write_err}")
                errors.append(str(write_err))
            
        return JSONResponse({
            "success": True, 
            "imported": len(sites), 
            "saved": saved_count,
            "message": f"{saved_count} sites injectés dans la mémoire."
        })
        
    except Exception as e: 
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        cid = data.get("identity", {}).get("id")
        if not cid: return JSONResponse({"success": False, "error": "ID manquant"})
        
        safe_id = str(cid).replace('/', '_').replace(' ', '')
        file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        return JSONResponse({"success": True})
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

# =========================================================
# API : DASHBOARD & FLEET (LECTURE DES DONNÉES)
# =========================================================
@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    """
    Lit tous les JSON générés par l'import et construit le Dashboard.
    """
    raw_sites = []
    # Scan de tous les JSON dans DATA_DIR
    files = glob.glob(f"{DATA_DIR}/*.json")
    
    for p in files:
        # Ignore les fichiers de config globale
        if "master_index" in p or "market_ref" in p or "market_history" in p: 
            continue
            
        try:
            with open(p, 'r', encoding='utf-8') as f: 
                data = json.load(f)
            
            # Vérif minimale
            if not data or 'identity' not in data: 
                continue
            
            # Enrichissement Financier Live (Cortex Engine V56)
            # Transforme les données brutes en KPIs (Budget, Conso, etc.)
            financials = cortex.enrich_site_financials(data)
            
            # Injection des KPIs calculés dans l'objet pour le tri
            data['computed_financials'] = financials
            
            raw_sites.append(data)
        except Exception as e:
            print(f"Erreur lecture fichier {p}: {e}")
            continue
    
    # Si vide, renvoie structure vide propre
    if not raw_sites:
        return JSONResponse({
            "fleet": [], "count": 0, "global_kpis": {"total_budget": 0}, "message": "Aucune donnée"
        })

    # Analyse de Portefeuille (Green League)
    # L'Engine V56 fait tout le travail de tri et d'agrégation
    analysis_result = cortex.analyze_portfolio(raw_sites)
    
    # Transformation pour le format attendu par le Frontend (DataTable)
    fleet_list = []
    
    # Métadonnées pour filtres
    all_cities = set()
    all_providers = set()
    all_segments = set()

    for s in raw_sites:
        fin = s['computed_financials']
        ident = s.get('identity', {})
        contract = s.get('contract', {})
        
        # Données normalisées par Cortex Engine
        site_name = fin['meta']['site_label']
        city = fin['meta']['city']
        energy_type = fin['meta']['energy_type']
        
        provider = contract.get('provider', 'Inconnu')
        segment = contract.get('segment', '-')

        if city: all_cities.add(city)
        if provider: all_providers.add(provider)
        if segment: all_segments.add(segment)

        fleet_list.append({
            "id": ident.get('id'),
            "name": site_name, # Affiche le vrai nom !
            "city": city,
            "zip": s.get('location', {}).get('zip_code', ''),
            "volume": fin['volume_mwh'],
            "energy": "gaz" if "Gaz" in energy_type else "elec",
            "segment": segment,
            "provider": provider,
            "power": contract.get('power', 0),
            "budget": fin['budget_annual'],
            "ratio": fin['kpis']['pmc_eur_mwh'], # Prix moyen complet
            "status": "Estimé" if fin['kpis']['is_estimated_price'] else "Réel"
        })

    return JSONResponse({
        "fleet": fleet_list, 
        "count": len(fleet_list),
        "green_league": analysis_result.get('green_league'),
        "global_kpis": analysis_result.get('global'),
        "filters_meta": { 
            "cities": sorted(list(all_cities)),
            "providers": sorted(list(all_providers)),
            "segments": sorted(list(all_segments))
        }
    })

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    """ Récupère le détail d'un site spécifique """
    # Nettoyage ID
    safe_id = str(client_id).replace('/', '_').replace(' ', '')
    path = os.path.join(DATA_DIR, f"{safe_id}.json")
    
    if not os.path.exists(path): 
        return JSONResponse({"error": "Site introuvable"}, status_code=404)
    
    with open(path, 'r', encoding='utf-8') as f: 
        data = json.load(f)
    
    # Recalcul Live
    fin = cortex.enrich_site_financials(data)
    data['financials'] = fin
    
    # Ajout Analyse Marché (Mocké via constantes Engine)
    data["market_analysis"] = {
        "status": "NEUTRE",
        "conseil": "Prix cohérent avec le marché actuel."
    }
    
    return JSONResponse(data)

# =========================================================
# API : MARKET WATCH & PHYSICS
# =========================================================
@app.get("/api/market/current")
async def api_get_market(): 
    # Données marché statiques pour la démo
    return JSONResponse({
        "updated_at": datetime.now().isoformat(),
        "elec": { "cal_n1": 82.50, "trend": "BAISSIER" },
        "gaz": { "peg_n1": 39.40, "trend": "STABLE" }
    })

@app.get("/api/physics/industry/global")
async def api_industry_global():
    # Agrégation rapide pour la page Industry
    files = glob.glob(f"{DATA_DIR}/*.json")
    total_elec = 0
    total_gaz = 0
    
    for p in files:
        if "master" in p: continue
        try:
            with open(p,'r') as f: d = json.load(f)
            fin = cortex.enrich_site_financials(d)
            if "Gaz" in fin['meta']['energy_type']: total_gaz += fin['volume_mwh']
            else: total_elec += fin['volume_mwh']
        except: continue
        
    return JSONResponse({
        "kpi": {"total_elec_mwh": round(total_elec, 1), "total_gaz_mwh": round(total_gaz, 1)},
        "carbon": physics.calculate_carbon_footprint(total_elec*1000, total_gaz*1000)
    })

# =========================================================
# API : OPS TOOLS
# =========================================================
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    content = await file.read()
    # Appel Engine -> Physics pour analyse courbe
    res = cortex.analyze_load_curve(content, file.filename)
    return JSONResponse(res)

@app.post("/api/ops/generate_tender")
async def generate_tender(payload: TenderRequest):
    # Génération Excel DQE
    if not EXCEL_ENGINE_READY: return JSONResponse({"error": "No Excel Engine"}, 500)
    
    sites_data = []
    for sid in payload.site_ids:
        safe_id = str(sid).replace('/', '_')
        p = os.path.join(DATA_DIR, f"{safe_id}.json")
        if os.path.exists(p):
            with open(p,'r') as f: sites_data.append(json.load(f))
            
    # Utilisation de Pandas pour générer l'Excel
    df = cortex.generate_dqe_structure(sites_data)
    
    stream = io.BytesIO()
    with pd.ExcelWriter(stream) as writer:
        df.to_excel(writer, index=False)
    stream.seek(0)
    
    return StreamingResponse(
        stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=DQE_Export.xlsx"}
    )

# =========================================================
# ROUTAGE HTML (FRONTEND)
# =========================================================
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    # Routage simple vers les templates HTML
    if path_name in ["", "/", "nexus"]: return templates.TemplateResponse("nexus.html", {"request": request})
    
    clean_name = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if "dashboard" in path_name: clean_name = "dashboard.html"
    
    # Vérification existence template
    possible_paths = [f"app/templates/{clean_name}", f"templates/{clean_name}"]
    for p in possible_paths:
        if os.path.exists(p):
            return templates.TemplateResponse(clean_name, {"request": request})
            
    return JSONResponse({"error": "Page introuvable"}, 404)

# LANCEMENT LOCAL
if __name__ == "__main__":
    import uvicorn
    print(f"🚀 ENERGISTRAT V3 STARTING... DATA_DIR={DATA_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=8080)
