from fastapi import FastAPI, Request, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import os

# Import du moteur IA (Assure-toi que cortex_engine.py est bien créé)
try:
    from cortex_engine import cortex
except ImportError:
    cortex = None
    print("⚠️ ALERTE : cortex_engine.py manquant. L'analyse ne fonctionnera pas.")

app = FastAPI(title="ENERGISTRAT V3", version="3.9 Data-Ready")

# 1. SETUP DOSSIERS
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# ROUTEUR API (BACKEND DATA)
# ==============================================================================

@app.post("/api/analyze")
async def analyze_energy_data(file: UploadFile = File(...)):
    """
    Reçoit un fichier Excel/CSV (Courbe de charge 10min),
    L'analyse via CORTEX,
    Renvoie les KPI et les points du graphique simplifiés.
    """
    if not cortex:
        return JSONResponse({"success": False, "error": "Moteur CORTEX non chargé."})
    
    content = await file.read()
    result = await cortex.analyze_file(content, file.filename)
    return JSONResponse(result)


# ==============================================================================
# ROUTEUR PAGES (FRONTEND)
# ==============================================================================

# --- LANDING PAGE ---
@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def landing(request: Request):
    if not os.path.isfile("templates/index.html"):
        return HTMLResponse("<h1>Erreur: index.html manquant</h1>", status_code=404)
    return templates.TemplateResponse("index.html", {"request": request})

# --- TUNNEL D'ACQUISITION ---
@app.get("/onboarding", response_class=HTMLResponse)
@app.get("/onboarding.html", response_class=HTMLResponse)
async def onboarding(request: Request):
    return templates.TemplateResponse("onboarding.html", {"request": request})

@app.get("/processing", response_class=HTMLResponse)
@app.get("/processing.html", response_class=HTMLResponse)
async def processing(request: Request):
    return templates.TemplateResponse("processing.html", {"request": request})

# --- NEXUS ---
@app.get("/nexus", response_class=HTMLResponse)
@app.get("/dashboard.html", response_class=HTMLResponse)
async def nexus(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

# --- ADMIN OPS ---
@app.get("/ops", response_class=HTMLResponse)
@app.get("/ops.html", response_class=HTMLResponse)
async def ops_dashboard(request: Request):
    return templates.TemplateResponse("ops.html", {"request": request})

# --- ROUTE MAGIQUE VITRINES ---
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def show_static_page(request: Request, page_name: str):
    file_path = f"{page_name}.html"
    full_path = os.path.join("templates", file_path)
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    return HTMLResponse(f"<h1>404 - Page '{page_name}' introuvable</h1>", status_code=404)

# --- ROUTE DASHBOARDS MÉTIERS ---
@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    clean_profil = profil.replace(".html", "")
    file_path = f"{clean_profil}.html"
    full_path = os.path.join("templates", file_path)
    
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    
    if os.path.isfile("templates/404.html"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
        
    return HTMLResponse("<h1>404 - Dashboard Introuvable</h1>", status_code=404)
