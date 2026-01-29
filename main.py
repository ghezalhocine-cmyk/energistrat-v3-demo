from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import os

try:
    from cortex_engine import cortex
except ImportError:
    cortex = None

app = FastAPI(title="ENERGISTRAT V3", version="3.12 Multi-Tenant")

if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- 💾 BASE DE DONNÉES EN MÉMOIRE (SIMULATION DB) ---
# C'est ici que l'on stocke les données de chaque client temporairement
# Structure : { "industry": { ...data... }, "mairie": { ...data... } }
DATA_STORE = {}

# ==============================================================================
# ROUTES API
# ==============================================================================

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    """
    1. Analyse le fichier
    2. Sauvegarde le résultat dans le casier du client ciblé (target)
    """
    if not cortex: return JSONResponse({"success": False, "error": "Moteur HS"})
    
    try:
        content = await file.read()
        result = await cortex.analyze_file(content, file.filename)
        
        if result.get("success"):
            # SAUVEGARDE DANS LA MÉMOIRE DU SERVEUR
            DATA_STORE[target] = result
            print(f"✅ Données sauvegardées pour le profil : {target}")
            
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/data/{profil}")
async def get_client_data(profil: str):
    """
    Le Dashboard Client appelle cette route pour récupérer SA donnée.
    """
    data = DATA_STORE.get(profil)
    if data:
        return JSONResponse({"found": True, "data": data})
    else:
        return JSONResponse({"found": False, "message": "Aucune donnée réelle pour ce client."})

# ... (Le reste des routes Chaos, Audit, Chat et Frontend reste inchangé) ...
# (Copie-colle le reste de ton ancien main.py ici pour les routes /ops, /dashboard, etc.)
# Je remets les routes essentielles pour que tu puisses copier-coller tout le bloc si besoin :

@app.post("/api/ops/chaos")
async def api_chaos():
    if not cortex: return JSONResponse({"results": []})
    return JSONResponse({"results": cortex.run_chaos_monkey()})

@app.post("/api/ops/audit")
async def api_audit(filename: str = Form(...)):
    return JSONResponse(cortex.simulate_audit(filename))

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...)):
    return JSONResponse({"response": cortex.ask_agent(message)})

def render_404(request):
    if os.path.isfile("templates/404.html"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse("<h1>404</h1>", status_code=404)

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def landing(request: Request):
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
    return render_404(request)

@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    clean_profil = profil.replace(".html", "")
    file_path = f"{clean_profil}.html"
    if os.path.isfile(f"templates/{file_path}"):
        return templates.TemplateResponse(file_path, {"request": request})
    return render_404(request)
