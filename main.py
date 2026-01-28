from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import os

# Import du moteur V4
try:
    from cortex_engine import cortex
except ImportError:
    cortex = None

app = FastAPI(title="ENERGISTRAT V3", version="3.10 Ops-Ready")

if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- ROUTES API OPS (LE BACKEND RÉEL) ---

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...)):
    """Analyse réelle d'un fichier de courbe de charge"""
    if not cortex: return JSONResponse({"success": False, "error": "Moteur HS"})
    content = await file.read()
    result = await cortex.analyze_file(content, file.filename)
    return JSONResponse(result)

@app.post("/api/ops/chaos")
async def api_chaos():
    """Lance le Chaos Monkey sur le serveur"""
    if not cortex: return JSONResponse({"results": []})
    results = cortex.run_chaos_monkey()
    return JSONResponse({"results": results})

@app.post("/api/ops/audit")
async def api_audit(filename: str = Form(...)):
    """Simule un audit métier sur un fichier"""
    result = cortex.simulate_audit(filename)
    return JSONResponse(result)

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...)):
    """Chat avec l'agent Ops"""
    response = cortex.ask_agent(message)
    return JSONResponse({"response": response})

# --- ROUTES FRONTEND (EXISTANTES) ---
# ... (Garde tes routes existantes ici : /, /onboarding, /nexus, etc.) ...
# Je remets juste les essentielles pour le contexte, ne les efface pas si elles y sont

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def landing(request: Request):
    if not os.path.isfile("templates/index.html"): return HTMLResponse("Err index", 404)
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/onboarding", response_class=HTMLResponse)
@app.get("/onboarding.html", response_class=HTMLResponse)
async def onboarding(request: Request):
    return templates.TemplateResponse("onboarding.html", {"request": request})

@app.get("/processing", response_class=HTMLResponse)
@app.get("/processing.html", response_class=HTMLResponse)
async def processing(request: Request):
    return templates.TemplateResponse("processing.html", {"request": request})

@app.get("/nexus", response_class=HTMLResponse)
@app.get("/dashboard.html", response_class=HTMLResponse)
async def nexus(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.get("/ops", response_class=HTMLResponse)
@app.get("/ops.html", response_class=HTMLResponse)
async def ops_dashboard(request: Request):
    return templates.TemplateResponse("ops.html", {"request": request})

@app.get("/{page_name}.html", response_class=HTMLResponse)
async def show_static_page(request: Request, page_name: str):
    file_path = f"{page_name}.html"
    if os.path.isfile(f"templates/{file_path}"):
        return templates.TemplateResponse(file_path, {"request": request})
    return HTMLResponse("404", 404)

@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    clean = profil.replace(".html", "")
    if os.path.isfile(f"templates/{clean}.html"):
        return templates.TemplateResponse(f"{clean}.html", {"request": request})
    if os.path.isfile("templates/404.html"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse("404", 404)
