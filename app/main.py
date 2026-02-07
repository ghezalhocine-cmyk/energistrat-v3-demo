import os
from fastapi import FastAPI, Request, UploadFile, File, Form, Header
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
# IMPORT DES MOTEURS
from app.core.cortex_engine import cortex
from app.core.storage_engine import storage 

app = FastAPI(title="ENERGISTRAT V3", version="PROD")

# CONFIGURATION
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
if os.path.exists("static"): app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# --- SYSTÈME ---
@app.get("/health")
async def health_check(): return {"status": "ONLINE", "cortex": cortex.version, "storage": storage.version}

# --- API OPS (ADMIN & ANALYSE - ÉVOLUTION V19) ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        content = await file.read()
        
        # 1. RECHERCHE INTELLIGENTE DU SITE (Préparation V34)
        # On regarde si on connait ce site dans le Storage pour injecter son contrat réel
        site_data = None
        # (Ici, on pourrait interroger storage.index avec site_name, pour l'instant on prépare le slot)
        
        # 2. APPEL CORTEX (SOFT HANDOVER)
        try:
            # Tentative V34 : On passe les données du site (Contrat, Tarif)
            res = cortex.analyze_file(content, file.filename, target_profile=target, known_site_data=site_data)
        except TypeError:
            # Fallback V33 : Si Cortex n'est pas encore à jour, on appelle l'ancienne signature
            res = cortex.analyze_file(content, file.filename, target_profile=target)
        
        if res.get("success"): 
            res["secure_link"] = f"/dashboard/{target}?site={site_name}"
            
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

# --- API TICKETING (SUPPORT V21.4) ---
@app.post("/api/support/ticket")
async def create_ticket(request: Request):
    try:
        data = await request.json()
        res = storage.create_ticket(data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/support/tickets")
async def get_tickets():
    tickets = storage.list_tickets()
    return JSONResponse({"tickets": tickets})

# --- API SETTINGS (ERP V21) ---
@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        client_id = data.get("identity", {}).get("id") or "draft_client"
        res = storage.save_client_settings(client_id, data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/partner/save_config")
async def api_save_partner(request: Request):
    try:
        data = await request.json()
        res = storage.save_partner_config("main_partner", data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

# --- PARCOURS CLIENT ---
@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/login/{profile}")
async def view_login(request: Request, profile: str): return templates.TemplateResponse("login.html", {"request": request, "profile": profile})
@app.get("/processing")
async def view_processing(request: Request, target: str = "demo"): return templates.TemplateResponse("processing.html", {"request": request, "target": target})
@app.get("/partner/settings")
async def view_partner_settings(request: Request): return templates.TemplateResponse("settings_partner.html", {"request": request})

@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    f = f"{profile}.html"
    if os.path.exists(f"app/templates/{f}"): return templates.TemplateResponse(f, {"request": request})
    if os.path.exists("app/templates/dashboard.html"): return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})
    return JSONResponse({"error": f"Template missing: {f}"}, 404)

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name in ["", "/"]: return templates.TemplateResponse("index.html", {"request": request})
    clean = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"app/templates/{clean}"): return templates.TemplateResponse(clean, {"request": request})
    return JSONResponse({"error": "Page not found"}, 404)
