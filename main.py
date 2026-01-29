from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import os
import json

try:
    from cortex_engine import cortex
except ImportError:
    cortex = None

app = FastAPI(title="ENERGISTRAT V3", version="3.14 PERSISTENCE")

# 1. SETUP DOSSIERS
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")
# Création d'un dossier pour stocker les données clients temporaires
if not os.path.exists("data_store"): os.makedirs("data_store")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# ROUTES API
# ==============================================================================

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    if not cortex: return JSONResponse({"success": False, "error": "Moteur HS"})
    
    try:
        content = await file.read()
        result = await cortex.analyze_file(content, file.filename)
        
        if result.get("success"):
            # SAUVEGARDE SUR DISQUE (JSON)
            # On écrit dans un fichier physique pour que toutes les instances le voient
            file_path = f"data_store/{target}.json"
            with open(file_path, "w") as f:
                json.dump(result, f)
            print(f"✅ Données écrites sur disque : {file_path}")
            
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/data/{profil}")
async def get_client_data(profil: str):
    """
    Lit le fichier JSON sur le disque
    """
    file_path = f"data_store/{profil}.json"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            data = json.load(f)
        return JSONResponse({"found": True, "data": data})
    else:
        return JSONResponse({"found": False, "message": "Aucune donnée"})

# ... (Le reste des routes Chaos, Audit, Chat et Frontend reste inchangé) ...
# Copie-colle le reste des routes (api_chaos, api_audit, render_404, etc.) ici
# Je te remets le bloc standard pour être sûr :

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
