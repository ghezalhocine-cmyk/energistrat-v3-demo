from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import os

# Import du moteur IA
try:
    from cortex_engine import cortex
except ImportError:
    cortex = None
    print("ERREUR CRITIQUE : cortex_engine.py est introuvable ou plante.")

app = FastAPI(title="ENERGISTRAT V3", version="3.11 FINAL")

# 1. SETUP DOSSIERS
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# 1. ROUTES API (BACKEND INTELLIGENT) - C'est ce qui te manquait !
# ==============================================================================

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...)):
    """Reçoit le CSV et lance CORTEX"""
    if not cortex: return JSONResponse({"success": False, "error": "Moteur CORTEX non chargé (vérifiez les logs serveur)."})
    
    try:
        content = await file.read()
        result = await cortex.analyze_file(content, file.filename)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": f"Crash API : {str(e)}"})

@app.post("/api/ops/chaos")
async def api_chaos():
    if not cortex: return JSONResponse({"results": []})
    results = cortex.run_chaos_monkey()
    return JSONResponse({"results": results})

@app.post("/api/ops/audit")
async def api_audit(filename: str = Form(...)):
    if not cortex: return JSONResponse({"compliant": False, "anomalies": ["Moteur HS"]})
    result = cortex.simulate_audit(filename)
    return JSONResponse(result)

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...)):
    if not cortex: return JSONResponse({"response": "Cerveau déconnecté."})
    response = cortex.ask_agent(message)
    return JSONResponse({"response": response})


# ==============================================================================
# 2. ROUTES FRONTEND (NAVIGATION)
# ==============================================================================

# --- FONCTION 404 ---
def render_404(request):
    if os.path.isfile("templates/404.html"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse("<h1>404 - Page Introuvable</h1>", status_code=404)

# --- PAGES PRINCIPALES ---
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

# --- ROUTE MAGIQUE VITRINES ---
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def show_static_page(request: Request, page_name: str):
    file_path = f"{page_name}.html"
    full_path = os.path.join("templates", file_path)
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    return render_404(request)

# --- ROUTE DASHBOARDS MÉTIERS ---
@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    clean_profil = profil.replace(".html", "")
    file_path = f"{clean_profil}.html"
    full_path = os.path.join("templates", file_path)
    
    if os.path.isfile(full_path):
        return templates.TemplateResponse(file_path, {"request": request})
    
    return render_404(request)

# Pour lancer : uvicorn main:app --reload
