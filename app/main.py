import os
import re
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

@app.get("/health")
async def health_check(): return {"status": "ONLINE", "cortex": cortex.version, "storage": storage.version}

# --- API OPS (ADMIN & ANALYSE - SMART SCAN V19.2) ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        content = await file.read()
        
        # 1. SCAN DU PDL (AMÉLIORÉ : NOM DE FICHIER D'ABORD)
        detected_pdl = None
        
        # A. On cherche D'ABORD dans le nom du fichier (Ex: ..._30000930316907.csv)
        # C'est la ligne critique qui manquait
        filename_match = re.search(r'(\d{14})', file.filename)
        if filename_match:
            detected_pdl = filename_match.group(1)
            print(f"[SCAN] PDL trouvé dans le nom de fichier : {detected_pdl}")
        
        # B. Sinon, on cherche dans le contenu (Entête)
        if not detected_pdl:
            try:
                content_str = content.decode('latin-1', errors='ignore')[:1000]
                content_match = re.search(r'\b(\d{14})\b', content_str)
                if content_match: detected_pdl = content_match.group(1)
            except: pass

        # 2. RECONCILIATION
        site_data = None
        if detected_pdl:
            site_data = storage.find_site_by_pdl(detected_pdl)
            if site_data:
                print(f"[RECONCILIATION] SUCCÈS : {site_data.get('client_name')} lié au PDL {detected_pdl}")
            else:
                print(f"[RECONCILIATION] ÉCHEC : Le PDL {detected_pdl} est inconnu dans Settings.")

        # 3. APPEL CORTEX
        res = cortex.analyze_file(content, file.filename, target_profile=target, known_site_data=site_data)
        
        if res.get("success"): 
            res["secure_link"] = f"/dashboard/{target}?site={site_name}"
            # Flag pour le frontend
            if site_data: res["reconciled"] = True
            
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

# --- API TICKETING ---
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

# --- API SETTINGS ---
@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        # On utilise le SIRET/RNC comme ID
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
