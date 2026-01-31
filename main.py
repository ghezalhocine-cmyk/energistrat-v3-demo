# main.py V8.0 - CORTEX CONNECTOR (HYBRID ENGINE ACTIVE)
import os
import json
import secrets
import logging
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- IMPORT DU MOTEUR DE STOCKAGE ---
from storage_engine import db

# --- 1. CONFIGURATION ---
ADMIN_PIN = "BOSS_V5"
DATA_DIR = "data_store"

# Création des dossiers critiques
os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

# --- IMPORT DU CERVEAU V8 (CORTEX) ---
try:
    from cortex_engine import cortex
    CORTEX_AVAILABLE = True
except ImportError:
    cortex = None
    CORTEX_AVAILABLE = False
    print("⚠️ CRITICAL : CORTEX ENGINE NOT FOUND")

app = FastAPI(title="ENERGISTRAT V8.0", version="CORTEX CONNECTED")

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montage des fichiers statiques
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates" if os.path.exists("templates") else ".")

# --- 2. API OPS : ANALYSE VIA CORTEX (REMPLACEMENT DU MOTEUR INTERNE) ---
@app.post("/api/ops/analyze")
async def api_analyze(
    file: UploadFile = File(...), 
    target: str = Form("demo"), 
    site_name: str = Form("Site_Principal"), 
    x_admin_token: str = Header(None)
):
    # Vérification Sécurité
    if x_admin_token != ADMIN_PIN: return JSONResponse({"success": False, "error": "PIN Incorrect"}, 401)
    
    # Vérification Moteur
    if not CORTEX_AVAILABLE:
        return JSONResponse({"success": False, "error": "Moteur Cortex Offline. Vérifiez le déploiement."}, 500)

    try:
        content = await file.read()
        token = secrets.token_urlsafe(6)
        
        # --- APPEL AU CERVEAU V8 (HYBRIDE) ---
        # Cortex gère tout : Ingestion Pandas, Maths, Narration
        analysis_result = await cortex.analyze_file(content, file.filename, target_profile=target)
        
        if not analysis_result.get("success"):
            return JSONResponse(analysis_result) # Renvoie l'erreur de Cortex si échec

        # Enrichissement Meta pour le stockage
        analysis_result["meta"] = {
            "client_group": target,
            "site": site_name,
            "original_filename": file.filename,
            "token": token,
            "ingestion_date": datetime.now().isoformat(),
            "engine_version": "V8.0"
        }

        # --- SAUVEGARDE VIA STORAGE ENGINE ---
        saved_path, entry_log = db.save_analysis(target, site_name, analysis_result)
        phys_filename = os.path.basename(saved_path)

        return JSONResponse({
            "success": True,
            "filename": phys_filename,
            "token": token,
            "secure_link": f"/dashboard/{target}?file={phys_filename}&token={token}",
            "kpi": analysis_result['kpi'],
            "chart": analysis_result['chart'],
            "ai_insight": analysis_result.get('ai_insight'),
            "storage_log": f"Stocké dans {target}/{site_name}"
        })

    except Exception as e:
        return JSONResponse({"success": False, "error": f"Erreur Pipeline: {str(e)}"})

# --- 3. API OUTILS & STRUCTURE ---

@app.get("/api/ops/structure")
async def get_structure(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({}, 401)
    return JSONResponse(db.get_client_structure())

@app.get("/api/ops/aggregate/{client}")
async def aggregate_client(client: str, x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"error": "Unauthorized"}, 401)
    return JSONResponse(db.aggregate_client_data(client))

@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    found_path = None
    for root, dirs, files in os.walk("data_store"):
        if filename in files:
            found_path = os.path.join(root, filename)
            break
    if not found_path or token not in filename: raise HTTPException(403)
    return FileResponse(found_path, media_type='application/json')

@app.post("/api/ops/audit")
async def audit_ep(invoice: UploadFile = File(...), contract: UploadFile = File(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({}, 401)
    # L'audit passe aussi par Cortex maintenant
    return JSONResponse(cortex.analyze_invoice_real(await invoice.read(), await contract.read()) if CORTEX_AVAILABLE else {})

@app.post("/api/ops/chaos")
async def chaos_ep(x_admin_token: str = Header(None)):
    return JSONResponse({"results": cortex.run_chaos_monkey() if CORTEX_AVAILABLE else []})

@app.post("/api/ops/chat")
async def chat_ep(message: str = Form(...), x_admin_token: str = Header(None)):
    return JSONResponse({"response": cortex.ask_agent(message) if CORTEX_AVAILABLE else "Cortex Offline"})

# --- 4. NAVIGATION ---

@app.get("/ops")
@app.get("/ops.html")
async def r_ops(request: Request):
    if os.path.exists("ops.html"): return FileResponse("ops.html")
    if os.path.exists("templates/ops.html"): return templates.TemplateResponse("ops.html", {"request": request})
    return HTMLResponse("<h1>Ops Not Found</h1>", 404)

@app.get("/")
@app.get("/index.html")
async def r_idx(request: Request):
    if os.path.exists("templates/index.html"): return templates.TemplateResponse("index.html", {"request": request})
    if os.path.exists("index.html"): return FileResponse("index.html")
    return await r_ops(request)

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if os.path.isfile(path_name): return FileResponse(path_name)
    target = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"templates/{target}"): return templates.TemplateResponse(target, {"request": request})
    return HTMLResponse("404", 404)

