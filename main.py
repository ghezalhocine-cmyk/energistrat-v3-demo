from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import os

app = FastAPI(title="ENERGISTRAT V3", version="3.8 Final")

# 1. SETUP
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# FONCTION UTILITAIRE POUR LA 404
def render_404(request):
    if os.path.isfile("templates/404.html"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse("<h1>404 - Not Found</h1>", status_code=404)

# 2. ROUTES
@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def landing(request: Request):
    if not os.path.isfile("templates/index.html"): return render_404(request)
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

# ROUTE VITRINES
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def show_static_page(request: Request, page_name: str):
    file_path = f"{page_name}.html"
    full_path = os.path.join("templates", file_path)
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    return render_404(request)

# ROUTE DASHBOARDS
@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    clean_profil = profil.replace(".html", "")
    file_path = f"{clean_profil}.html"
    full_path = os.path.join("templates", file_path)
    
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    
    return render_404(request)
