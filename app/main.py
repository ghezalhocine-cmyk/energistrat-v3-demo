# app/main.py V10.0 - ARCHITECTURE V3 (ENTERPRISE BRIDGE)
import os
import secrets
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# Import des moteurs modulaires (Le secret de la V3)
from app.core.storage_engine import storage
from app.core.cortex_engine import cortex

app = FastAPI(title="ENERGISTRAT V3.0", version="ENTERPRISE")

# 1. SÉCURITÉ & MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. MONTAGE DES FICHIERS
# Les fichiers statiques (CSS/JS) sont à la racine du conteneur
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
elif os.path.exists("statique"): # Support legacy
    app.mount("/static", StaticFiles(directory="statique"), name="static")

templates = Jinja2Templates(directory="app/templates")

# 3. ROUTES SYSTÈME (Santé Cloud Run)
@app.get("/health")
async def health_check():
    return {
        "status": "ONLINE",
        "version": "V3.0",
        "storage_ok": os.access("/app/data", os.W_OK),
        "cortex_version": cortex.version
    }

# 4. API OPS : ANALYSE FICHIER (CSV/SGE)
@app.post("/api/ops/analyze")
async def api_analyze(
    file: UploadFile = File(...), 
    target: str = Form("demo"), 
    site_name: str = Form("Site_Principal"), 
    x_admin_token: str = Header(None)
):
    # Sécurité (PIN codé en dur pour l'instant)
    if x_admin_token != "BOSS_V5": 
        return JSONResponse({"success": False, "error": "PIN Incorrect"}, 401)

    try:
        content = await file.read()
        token = secrets.token_urlsafe(6)
        
        # Appel au Cerveau (Cortex Engine V26)
        analysis_result = cortex.analyze_file(content, file.filename, target_profile=target)
        
        if not analysis_result.get("success"):
            return JSONResponse(analysis_result)

        # Sauvegarde simulée et réponse
        return JSONResponse({
            "success": True,
            "filename": file.filename,
            "token": token,
            "secure_link": f"/dashboard/{target}?file={file.filename}&token={token}",
            "kpi": analysis_result.get('kpi', {}),
            "chart": analysis_result.get('chart', {}),
            "ai_insight": analysis_result.get('ai_insight', "Analyse V3 en cours...")
        })

    except Exception as e:
        print(f"[ERROR] Pipeline Failed: {e}")
        return JSONResponse({"success": False, "error": str(e)})

# --- NOUVELLES ROUTES (POUR OPS V15) ---

@app.post("/api/ops/audit")
async def api_audit(
    invoice: UploadFile = File(...),
    contract: UploadFile = File(None),
    x_admin_token: str = Header(None)
):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    
    # Lecture des fichiers en mémoire
    inv_content = await invoice.read()
    ctr_content = await contract.read() if contract else None
    
    # Appel Cortex Audit
    return JSONResponse(cortex.analyze_invoice_real(inv_content, ctr_content))

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    # Appel Cortex IA
    return JSONResponse({"response": cortex.ask_agent(message)})

@app.post("/api/ops/chaos")
async def api_chaos(x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    # Appel Cortex Tests
    return JSONResponse(cortex.run_chaos_monkey())

@app.get("/api/ops/aggregate/{client}")
async def api_aggregate(client: str, x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    # Placeholder pour éviter l'erreur 404 côté JS
    return JSONResponse({"success": False, "error": "Module Agrégation en cours de construction"})

# ---------------------------------------

# 5. ROUTAGE INTELLIGENT (DASHBOARDS)
@app.get("/dashboard/{profile}")
async def client_dashboard(request: Request, profile: str):
    """Charge dynamiquement le template HTML demandé."""
    clean_name = profile.replace(".html", "")
    filename = f"{clean_name}.html"
    
    # Vérifie dans app/templates
    if os.path.exists(f"app/templates/{filename}"):
        return templates.TemplateResponse(filename, {"request": request})
    
    # Fallback générique
    if os.path.exists("app/templates/dashboard.html"):
        return templates.TemplateResponse("dashboard.html", {"request": request, "profile": clean_name})
        
    return HTMLResponse(f"<h1>Dashboard '{clean_name}' introuvable</h1>", 404)

# 6. ROUTE CATCH-ALL (Pour index, ops, etc.)
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name == "" or path_name == "/":
        return templates.TemplateResponse("index.html", {"request": request})
        
    clean_name = path_name if path_name.endswith(".html") else f"{path_name}.html"
    
    if os.path.exists(f"app/templates/{clean_name}"):
        return templates.TemplateResponse(clean_name, {"request": request})
        
    return JSONResponse({"error": "Page not found"}, 404)404)
