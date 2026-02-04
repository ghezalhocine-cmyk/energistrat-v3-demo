import os
from fastapi import FastAPI, Request, UploadFile, File, Form, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from app.core.cortex_engine import cortex

app = FastAPI(title="ENERGISTRAT V3", version="PROD")

# CONFIGURATION
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
if os.path.exists("static"): app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- SYSTÈME ---
@app.get("/health")
async def health_check(): return {"status": "ONLINE", "cortex": cortex.version}

# --- API OPS ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        content = await file.read()
        res = cortex.analyze_file(content, file.filename, target_profile=target)
        if res.get("success"): res["secure_link"] = f"/dashboard/{target}?site={site_name}"
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

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

# --- PARCOURS CLIENT (ONBOARDING -> LOGIN -> DASHBOARD) ---

@app.get("/onboarding")
async def view_onboarding(request: Request):
    # Correspond à votre Capture 2
    return templates.TemplateResponse("onboarding.html", {"request": request})

@app.get("/login/{profile}")
async def view_login(request: Request, profile: str):
    # Correspond à votre Capture 3 (Login spécifique)
    return templates.TemplateResponse("login.html", {"request": request, "profile": profile})

@app.get("/processing")
async def view_processing(request: Request, target: str = "demo"):
    # Correspond à votre Capture 4
    return templates.TemplateResponse("processing.html", {"request": request, "target": target})

@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    """
    Routeur Intelligent V2 :
    Redirige vers le fichier spécifique (ex: retail.html) s'il existe.
    """
    specific_file = f"{profile}.html"
    
    if os.path.exists(f"app/templates/{specific_file}"):
        return templates.TemplateResponse(specific_file, {"request": request})
    
    # Fallback si le fichier spécifique n'existe pas encore
    if os.path.exists("app/templates/dashboard.html"):
        return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})
        
    return JSONResponse({"error": f"Template introuvable: {specific_file}"}, 404)

# --- CATCH-ALL (Sécurité) ---
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name == "" or path_name == "/": 
        return templates.TemplateResponse("index.html", {"request": request})
    
    clean_name = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"app/templates/{clean_name}"): 
        return templates.TemplateResponse(clean_name, {"request": request})
    
    return JSONResponse({"error": "Page not found"}, 404)
