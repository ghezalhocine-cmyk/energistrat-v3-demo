import os
import json
import glob
import uuid
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

# =========================================================
# 1. CHARGEMENT DES ORGANES VITAUX (TRI-CORTEX)
# =========================================================
try:
    # On tente l'import Docker/Prod
    from app.core.cortex_ingest import ingest
    from app.core.cortex_engine import cortex
    from app.core.cortex_physics import physics
except ImportError:
    # Fallback Local (si exécuté hors conteneur)
    try:
        from cortex_ingest import ingest
        from cortex_engine import cortex
        from cortex_physics import physics
    except ImportError as e:
        print(f"🚨 ERREUR CRITIQUE: Modules Cortex manquants. {e}")
        # On ne crash pas, mais l'app sera en mode dégradé

# =========================================================
# 2. CONFIGURATION DU SERVEUR
# =========================================================
app = FastAPI(title="ENERGISTRAT V3", version="STABLE-UX-V60")

# Sécurité & Accès
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gestion des Chemins (Data & Templates)
BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

# Templates HTML (Détection intelligente)
TEMPLATE_DIR = os.path.join(BASE_DIR, "app/templates")
if not os.path.exists(TEMPLATE_DIR):
    TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")

templates = Jinja2Templates(directory=TEMPLATE_DIR)

# Fichiers Statiques (CSS/JS/Images)
STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR):
    STATIC_DIR = os.path.join(BASE_DIR, "app/static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# =========================================================
# 3. API : IMPORT & MÉMOIRE (LE CŒUR DU SYSTÈME)
# =========================================================

@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    """
    Reçoit le fichier Excel/CSV -> Ingest -> Sauvegarde JSON.
    C'est ici que la mémoire se crée.
    """
    try:
        content = await file.read()
        
        # 1. INGESTION (Extraction propre via V56)
        sites = ingest.parse_mass_import_unified(content)
        
        if not sites: 
            return JSONResponse({"success": False, "error": "Fichier vide ou format non reconnu."})
        
        saved_count = 0
        
        # 2. PERSISTANCE (Écriture Disque Dur)
        for s in sites:
            try:
                # Création d'un ID unique si absent
                cid = s.get('identity', {}).get('id')
                if not cid:
                    cid = f"GEN_{uuid.uuid4().hex[:8]}"
                    s['identity']['id'] = cid
                
                # Nettoyage ID pour nom de fichier
                safe_id = str(cid).replace('/', '_').replace('\\', '_').replace(' ', '')
                file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
                
                # Sauvegarde
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(s, f, indent=4, ensure_ascii=False)
                
                saved_count += 1
            except Exception as e:
                print(f"Erreur sauvegarde site {cid}: {e}")
            
        return JSONResponse({
            "success": True, 
            "imported": len(sites), 
            "saved": saved_count,
            "message": f"{saved_count} sites intégrés avec succès."
        })
        
    except Exception as e: 
        traceback.print_exc()
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    """
    Lit les JSONs et renvoie les données pour les bentos.
    """
    raw_sites = []
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    
    for p in files:
        if "master" in p or "market" in p: continue
        try:
            with open(p, 'r', encoding='utf-8') as f: 
                data = json.load(f)
            
            # Enrichissement Live (Calculs Engine)
            fin = cortex.enrich_site_financials(data)
            data['computed_financials'] = fin
            raw_sites.append(data)
        except: continue
    
    # Analyse Portefeuille (Green League)
    analysis = cortex.analyze_portfolio(raw_sites)
    
    # Formatage pour le Frontend
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
        "filters_meta": { 
            "cities": sorted(list(all_cities)),
            "providers": sorted(list(all_providers)),
            "segments": sorted(list(all_segments))
        }
    })

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    safe_id = str(client_id).replace('/', '_').replace(' ', '')
    path = os.path.join(DATA_DIR, f"{safe_id}.json")
    
    if not os.path.exists(path): 
        return JSONResponse({"error": "Site introuvable"}, status_code=404)
    
    with open(path, 'r', encoding='utf-8') as f: 
        data = json.load(f)
    
    # Recalcul Live
    data['financials'] = cortex.enrich_site_financials(data)
    return JSONResponse(data)

# =========================================================
# 4. ROUTAGE UX STRICT (VOTRE PARCOURS VALIDÉ)
# =========================================================

# A. LANDING PAGE (Index)
@app.get("/")
async def view_landing(request: Request):
    """ Point d'entrée : Landing Page """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/index.html")
async def view_landing_explicit(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# B. ONBOARDING (Upload)
@app.get("/onboarding")
async def view_onboarding(request: Request):
    """ Étape 1 : Upload Fichier """
    return templates.TemplateResponse("onboarding.html", {"request": request})

@app.get("/onboarding.html")
async def view_onboarding_explicit(request: Request):
    return templates.TemplateResponse("onboarding.html", {"request": request})

# C. PROCESSING (Attente IA)
@app.get("/processing")
async def view_processing(request: Request):
    """ Étape 2 : Animation de calcul """
    return templates.TemplateResponse("processing.html", {"request": request})

@app.get("/processing.html")
async def view_processing_explicit(request: Request):
    return templates.TemplateResponse("processing.html", {"request": request})

# D. PROFILS MÉTIERS (Dashboards Spécifiques)

@app.get("/dashboard/retail")
async def view_retail(request: Request):
    """ Profil : Citoyen / Petit Pro """
    return templates.TemplateResponse("retail.html", {"request": request, "profile": "retail"})

@app.get("/dashboard/mairie")
async def view_mairie(request: Request):
    """ Profil : Collectivité / Public """
    return templates.TemplateResponse("mairie.html", {"request": request, "profile": "mairie"})

@app.get("/dashboard/industry")
async def view_industry(request: Request):
    """ Profil : Industrie / Grand Compte """
    return templates.TemplateResponse("industry.html", {"request": request, "profile": "industry"})

@app.get("/dashboard/syndic")
async def view_syndic(request: Request):
    """ Profil : OPH / Syndic """
    return templates.TemplateResponse("syndic.html", {"request": request, "profile": "syndic"})

@app.get("/dashboard/b2b")
async def view_b2b(request: Request):
    """ Profil : PME / Tertiaire """
    return templates.TemplateResponse("b2b.html", {"request": request, "profile": "b2b"})

# E. PAGES SATELLITES (Outils)
@app.get("/audit")
async def view_audit(request: Request): return templates.TemplateResponse("audit.html", {"request": request})
@app.get("/optimization")
async def view_opti(request: Request): return templates.TemplateResponse("optimization.html", {"request": request})
@app.get("/carbon")
async def view_carbon(request: Request): return templates.TemplateResponse("carbon.html", {"request": request})
@app.get("/settings")
async def view_settings(request: Request): return templates.TemplateResponse("settings.html", {"request": request})

# F. HEALTH CHECK
@app.get("/health")
async def health_check():
    sites = len(glob.glob(os.path.join(DATA_DIR, "*.json")))
    return {"status": "OPERATIONAL", "ux_flow": "STRICT", "sites_loaded": sites}

# G. CATCH-ALL (Redirection douce)
@app.get("/{full_path:path}")
async def catch_all(request: Request, full_path: str):
    # Évite les erreurs 404 sur les assets
    if "static" in full_path or "assets" in full_path or "favicon" in full_path:
        return JSONResponse({"error": "File not found"}, status_code=404)
    # Redirige tout le reste vers la Landing
    return templates.TemplateResponse("index.html", {"request": request})

# =========================================================
# LANCEMENT
# =========================================================
if __name__ == "__main__":
    import uvicorn
    print(f"🚀 ENERGISTRAT V3 UX-READY. DATA_DIR={DATA_DIR}")
    uvicorn.run(app, host="0.0.0.0", port=8080)
