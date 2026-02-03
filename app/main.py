# app/main.py V12.0 - PRODUCTION (FULL CONNECTIVITY)
import os
import secrets
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# IMPORT DES MOTEURS (Validés par le Safe Boot)
from app.core.storage_engine import storage
from app.core.cortex_engine import cortex

app = FastAPI(title="ENERGISTRAT V3", version="PROD")

# 1. MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. STATIC & TEMPLATES
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# 3. SYSTEM HEALTH
@app.get("/health")
async def health_check():
    return {
        "status": "ONLINE",
        "version": "V3.0-PROD",
        "cortex": cortex.version,
        "storage": "WRITABLE" if os.access("/app/data", os.W_OK) else "READ_ONLY"
    }

# 4. API : ANALYSE SGE (CSV/EXCEL)
@app.post("/api/ops/analyze")
async def api_analyze(
    file: UploadFile = File(...), 
    target: str = Form("demo"), 
    site_name: str = Form("Site_Principal"), 
    x_admin_token: str = Header(None)
):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)

    try:
        content = await file.read()
        token = secrets.token_urlsafe(6)
        
        # Appel Cortex V26
        analysis_result = cortex.analyze_file(content, file.filename, target_profile=target)
        
        if not analysis_result.get("success"):
            return JSONResponse(analysis_result)

        # Lien dashboard
        analysis_result["token"] = token
        analysis_result["secure_link"] = f"/dashboard/{target}?site={site_name}"
        
        return JSONResponse(analysis_result)

    except Exception as e:
        print(f"[API ERROR] {e}")
        return JSONResponse({"success": False, "error": str(e)})

# 5. API : AUDIT PDF (Connecté au V26)
@app.post("/api/ops/audit")
async def api_audit(
    invoice: UploadFile = File(...),
    contract: UploadFile = File(None),
    x_admin_token: str = Header(None)
):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    
    try:
        inv_content = await invoice.read()
        ctr_content = await contract.read() if contract else None
        
        # Appel Cortex
        result = cortex.analyze_invoice_real(inv_content, ctr_content)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"score": 0, "checks": [], "error": str(e)})

# 6. API : CHAT & CHAOS
@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    return JSONResponse({"response": cortex.ask_agent(message)})

@app.post("/api/ops/chaos")
async def api_chaos(x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    return JSONResponse(cortex.run_chaos_monkey())

@app.get("/api/ops/aggregate/{client}")
async def api_aggregate(client: str, x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    return JSONResponse({"success": False, "error": "Module Agrégation en cours"})

# 7. ROUTAGE FRONT
@app.get("/dashboard/{profile}")
async def client_dashboard(request: Request, profile: str):
    clean_name = profile.replace(".html", "")
    filename = f"{clean_name}.html"
    if os.path.exists(f"app/templates/{filename}"):
        return templates.TemplateResponse(filename, {"request": request})
    if os.path.exists("app/templates/dashboard.html"):
        return templates.TemplateResponse("dashboard.html", {"request": request})
    return HTMLResponse("Dashboard introuvable", 404)

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name == "" or path_name == "/":
        # On renvoie vers Ops par défaut pour la démo
        return templates.TemplateResponse("ops.html", {"request": request})
        
    clean_name = path_name if path_name.endswith(".html") else f"{path_name}.html"
    
    if os.path.exists(f"app/templates/{clean_name}"):
        return templates.TemplateResponse(clean_name, {"request": request})
        
    return JSONResponse({"error": "Page not found"}, 404)
