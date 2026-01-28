from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

app = FastAPI(title="ENERGISTRAT V3", version="3.8 Final")

# 1. SETUP DES DOSSIERS (Sécurité anti-crash)
if not os.path.exists("static"):
    os.makedirs("static")
if not os.path.exists("templates"):
    os.makedirs("templates")

# Montage des fichiers statiques (CSS, JS, Images)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Moteur de template
templates = Jinja2Templates(directory="templates")

# --- FONCTION UTILITAIRE POUR LA PAGE 404 ---
def render_404(request):
    """ Affiche la belle page 404.html si elle existe, sinon une erreur brute """
    if os.path.isfile("templates/404.html"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse("<h1>404 - Not Found</h1>", status_code=404)


# ==============================================================================
# ROUTES DU SITE
# ==============================================================================

# --- LANDING PAGE ---
@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def landing(request: Request):
    if not os.path.isfile("templates/index.html"): return render_404(request)
    return templates.TemplateResponse("index.html", {"request": request})

# --- TUNNEL D'ACQUISITION ---
@app.get("/onboarding", response_class=HTMLResponse)
@app.get("/onboarding.html", response_class=HTMLResponse)
async def onboarding(request: Request):
    if not os.path.isfile("templates/onboarding.html"): return render_404(request)
    return templates.TemplateResponse("onboarding.html", {"request": request})

@app.get("/processing", response_class=HTMLResponse)
@app.get("/processing.html", response_class=HTMLResponse)
async def processing(request: Request):
    if not os.path.isfile("templates/processing.html"): return render_404(request)
    return templates.TemplateResponse("processing.html", {"request": request})

# --- NEXUS (MENU PRINCIPAL) ---
@app.get("/nexus", response_class=HTMLResponse)
@app.get("/dashboard.html", response_class=HTMLResponse)
async def nexus(request: Request):
    if not os.path.isfile("templates/dashboard.html"): return render_404(request)
    return templates.TemplateResponse("dashboard.html", {"request": request})

# --- ADMIN OPS ---
@app.get("/ops", response_class=HTMLResponse)
@app.get("/ops.html", response_class=HTMLResponse)
async def ops_dashboard(request: Request):
    if not os.path.isfile("templates/ops.html"): return render_404(request)
    return templates.TemplateResponse("ops.html", {"request": request})

# --- ROUTE MAGIQUE POUR LES PAGES VITRINES ---
# Sert automatiquement : store.html, cortex.html, vitality.html, etc.
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def show_static_page(request: Request, page_name: str):
    file_path = f"{page_name}.html"
    full_path = os.path.join("templates", file_path)
    
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    
    return render_404(request)

# --- ROUTE DASHBOARDS MÉTIERS ---
# Sert : /dashboard/industry, /dashboard/mairie, etc.
@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    # Nettoyage au cas où l'utilisateur tape .html
    clean_profil = profil.replace(".html", "")
    file_path = f"{clean_profil}.html"
    full_path = os.path.join("templates", file_path)
    
    # 1. Si le fichier existe, on l'affiche
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    
    # 2. Sinon, Erreur 404 personnalisée
    return render_404(request)

# Pour lancer : uvicorn main:app --reload
