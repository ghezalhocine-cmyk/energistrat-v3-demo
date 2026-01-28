from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

app = FastAPI(title="ENERGISTRAT V3", version="3.7 Universal")

# 1. SETUP DOSSIERS
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# ROUTEUR UNIVERSEL (Gère tout le site automatiquement)
# ==============================================================================

# --- LANDING PAGE (Racine) ---
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

# --- ADMIN OPS ---
@app.get("/ops", response_class=HTMLResponse)
@app.get("/ops.html", response_class=HTMLResponse)
async def ops_dashboard(request: Request):
    return templates.TemplateResponse("ops.html", {"request": request})

# --- ROUTE MAGIQUE POUR LES PAGES VITRINES ---
# Cette route sert automatiquement :
# - store.html
# - connectivite.html
# - etudes-de-cas.html
# - ethique.html
# - fournisseurs.html
# - audit_premium.html
# - cortex.html
# - vitality.html
# - modele_economique.html
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def show_static_page(request: Request, page_name: str):
    file_path = f"{page_name}.html"
    full_path = os.path.join("templates", file_path)
    
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    
    return HTMLResponse(f"<h1>404 - Page '{page_name}.html' introuvable</h1>", status_code=404)

# --- ROUTE DASHBOARDS MÉTIERS ---
@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    """
    Gère les dashboards (industry, mairie, citoyen...)
    """
    clean_profil = profil.replace(".html", "")
    file_path = f"{clean_profil}.html"
    full_path = os.path.join("templates", file_path)
    
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    
    # Fallback vers le Nexus (Menu) si le dashboard spécifique n'existe pas
    if os.path.isfile("templates/dashboard.html"):
        return templates.TemplateResponse("dashboard.html", {"request": request})
        
    return HTMLResponse("<h1>404 - Dashboard Introuvable</h1>", status_code=404)

# Pour lancer : uvicorn main:app --reload