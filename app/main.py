# app/main.py V11.0 - SAFE BOOT (DIAGNOSTIC MODE)
import os
import sys
import secrets
import traceback
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# --- 1. INITIALISATION SÉCURISÉE ---
app = FastAPI(title="ENERGISTRAT V3", version="SAFE_BOOT")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. CHARGEMENT DES COMPOSANTS (AVEC PROTECTION) ---
GLOBAL_STATUS = {"status": "STARTING", "errors": []}

# A. Moteur de Stockage
try:
    from app.core.storage_engine import storage
    GLOBAL_STATUS["storage"] = "OK"
except Exception as e:
    GLOBAL_STATUS["storage"] = f"ERROR: {str(e)}"
    print(f"CRITICAL STORAGE ERROR: {e}")

# B. Moteur Cortex
cortex = None
try:
    from app.core.cortex_engine import cortex
    GLOBAL_STATUS["cortex"] = "OK"
except Exception as e:
    GLOBAL_STATUS["cortex"] = f"ERROR: {str(e)}"
    # On capture la trace complète pour le log
    traceback.print_exc()

# C. Templates & Static
templates = None
try:
    if os.path.exists("static"):
        app.mount("/static", StaticFiles(directory="static"), name="static")
    
    # Vérification dossier templates
    if os.path.exists("app/templates"):
        templates = Jinja2Templates(directory="app/templates")
        GLOBAL_STATUS["templates"] = "OK"
    else:
        GLOBAL_STATUS["templates"] = "MISSING DIR app/templates"
except Exception as e:
    GLOBAL_STATUS["templates"] = f"ERROR: {str(e)}"

# --- 3. ROUTES DE DIAGNOSTIC ---

@app.get("/")
async def root(request: Request):
    # Si tout va bien, on affiche l'index ou Ops
    if templates and GLOBAL_STATUS["cortex"] == "OK":
        if os.path.exists("app/templates/ops.html"):
            return templates.TemplateResponse("ops.html", {"request": request})
    
    # Sinon, page de secours
    return JSONResponse(GLOBAL_STATUS)

@app.get("/health")
async def health_check():
    # Cette route nous dira EXACTEMENT pourquoi ça plantait
    return {
        "system": "SAFE_MODE",
        "components": GLOBAL_STATUS,
        "python_path": sys.path,
        "cwd": os.getcwd(),
        "files_in_app": os.listdir("app") if os.path.exists("app") else "MISSING"
    }

# --- 4. ROUTES MÉTIER (PROTÉGÉES) ---

@app.post("/api/ops/analyze")
async def api_analyze(
    file: UploadFile = File(...), 
    target: str = Form("demo"), 
    site_name: str = Form("Site_Principal"), 
    x_admin_token: str = Header(None)
):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    
    # Si Cortex a planté au démarrage
    if not cortex:
        return JSONResponse({"success": False, "error": f"Cortex Offline: {GLOBAL_STATUS['cortex']}"})

    try:
        content = await file.read()
        token = secrets.token_urlsafe(6)
        
        analysis_result = cortex.analyze_file(content, file.filename, target_profile=target)
        
        if not analysis_result.get("success"):
            return JSONResponse(analysis_result)

        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "token": token,
            "secure_link": f"/dashboard/{target}?file={file.filename}",
            "kpi": analysis_result.get('kpi', {}),
            "chart": analysis_result.get('chart', {}),
            "ai_insight": analysis_result.get('ai_insight', "")
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

# Routes Placeholder pour éviter 404 si l'interface appelle
@app.post("/api/ops/audit")
async def api_audit(): return JSONResponse({"score": 0, "checks": []})

@app.post("/api/ops/chat")
async def api_chat(): return JSONResponse({"response": "Mode Safe: Chat indisponible"})

@app.post("/api/ops/chaos")
async def api_chaos(): return JSONResponse({"results": []})

# Catch-all pour les templates
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if templates:
        clean_name = path_name if path_name.endswith(".html") else f"{path_name}.html"
        if os.path.exists(f"app/templates/{clean_name}"):
            return templates.TemplateResponse(clean_name, {"request": request})
    return JSONResponse({"error": "Page not found or Templates offline"}, 404)
