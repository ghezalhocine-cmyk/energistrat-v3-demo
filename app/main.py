# app/main.py V13.0 - ROUTAGE STANDARD (SITE VITRINE + APP)
import os
import secrets
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# MOTEURS
from app.core.storage_engine import storage
from app.core.cortex_engine import cortex

app = FastAPI(title="ENERGISTRAT V3", version="PROD_ROUTING")

# 1. CONFIGURATION
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. FICHIERS STATIQUES (CSS/JS/IMG)
# Vital pour que le site ne soit pas "moche" ou "figé"
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="app/templates")

# 3. ROUTES SYSTÈME
@app.get("/health")
async def health_check():
    return {"status": "ONLINE", "version": "V3.0", "cortex": cortex.version}

# ============================================================
# 4. API MÉTIER (OPS & CORTEX)
# ============================================================

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
        # Appel Cortex
        analysis_result = cortex.analyze_file(content, file.filename, target_profile=target)
        if not analysis_result.get("success"): return JSONResponse(analysis_result)

        analysis_result["token"] = token
        analysis_result["secure_link"] = f"/dashboard/{target}?site={site_name}"
        return JSONResponse(analysis_result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/audit")
async def api_audit(invoice: UploadFile = File(...), contract: UploadFile = File(None), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        inv = await invoice.read()
        ctr = await contract.read() if contract else None
        return JSONResponse(cortex.analyze_invoice_real(inv, ctr))
    except Exception as e: return JSONResponse({"score": 0, "checks": [], "error": str(e)})

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
    return JSONResponse({"success": False, "error": "Module Agrégation en cours"})

# ============================================================
# 5. ROUTAGE NAVIGATION (VITRINE & APP)
# ============================================================

# A. LA RACINE (ACCUEIL)
@app.get("/")
async def root(request: Request):
    # On sert index.html (la vitrine) par défaut
    if os.path.exists("app/templates/index.html"):
        return templates.TemplateResponse("index.html", {"request": request})
    return "ENERGISTRAT V3 ONLINE - Index manquante"

# B. TABLEAUX DE BORD CLIENTS
@app.get("/dashboard/{profile}")
async def client_dashboard(request: Request, profile: str):
    clean_name = profile.replace(".html", "")
    filename = f"{clean_name}.html"
    if os.path.exists(f"app/templates/{filename}"):
        return templates.TemplateResponse(filename, {"request": request})
    if os.path.exists("app/templates/dashboard.html"):
        return templates.TemplateResponse("dashboard.html", {"request": request})
    return HTMLResponse("Dashboard introuvable", 404)

# C. ROUTAGE GÉNÉRIQUE (Pour /pme, /syndic, /ops...)
@app.get("/{path_name}")
async def catch_pages(request: Request, path_name: str):
    # Nettoyage du nom (ex: "ops" -> "ops.html")
    clean_name = path_name if path_name.endswith(".html") else f"{path_name}.html"
    
    # Sécurité : on empêche de remonter dans les dossiers
    if ".." in clean_name or "/" in clean_name:
        return HTMLResponse("Chemin invalide", 403)

    if os.path.exists(f"app/templates/{clean_name}"):
        return templates.TemplateResponse(clean_name, {"request": request})
    
    return JSONResponse({"error": f"Page '{clean_name}' introuvable"}, 404)
