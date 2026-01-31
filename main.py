from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import os
import json
import re

# Tentative d'import du moteur Cortex
try:
    from cortex_engine import cortex
except ImportError:
    cortex = None

app = FastAPI(title="ENERGISTRAT V3", version="3.17 RETAIL READY")

# ==============================================================================
# 1. SETUP DOSSIERS & CONFIG
# ==============================================================================
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")
if not os.path.exists("data_store"): os.makedirs("data_store")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# 2. ROUTES API (BACKEND INTELLIGENCE)
# ==============================================================================

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    """
    Ingestion SGE : Lit le fichier, l'analyse via Cortex (avec contexte métier), et sauvegarde le JSON.
    """
    if not cortex: return JSONResponse({"success": False, "error": "Moteur Cortex HS"})
    
    try:
        content = await file.read()
        
        # Appel au moteur Cortex avec le profil cible (target) pour adapter l'IA et les calculs (ex: Retail)
        result = await cortex.analyze_file(content, file.filename, target_profile=target)
        
        if result.get("success"):
            # PERSISTANCE : Ecriture sur disque pour que les Dashboard Clients puissent lire
            file_path = f"data_store/{target}.json"
            with open(file_path, "w") as f:
                json.dump(result, f)
            print(f"✅ [PERSISTANCE] Données écrites pour {target} : {file_path}")
            
        return JSONResponse(result)
    except Exception as e:
        print(f"❌ Erreur Analyze: {str(e)}")
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/data/{profil}")
async def get_client_data(profil: str):
    """
    Pont de Données : Le Dashboard Client (Front) appelle cette route pour récupérer ses données.
    """
    file_path = f"data_store/{profil}.json"
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            data = json.load(f)
        return JSONResponse({"found": True, "data": data})
    else:
        return JSONResponse({"found": False, "message": "Aucune donnée réelle disponible."})

@app.post("/api/ops/audit")
async def api_audit(invoice: UploadFile = File(...), contract: UploadFile = File(...)):
    """
    AUDIT LAB : Comparaison Facture vs Contrat (PDF/OCR Réel)
    """
    if not cortex: return JSONResponse({"score": 0, "checks": [], "status": "ENGINE_OFF"})
    
    try:
        # Lecture binaire des fichiers PDF
        inv_bytes = await invoice.read()
        ctr_bytes = await contract.read()
        
        # Appel du moteur d'analyse PDF expert
        result = cortex.analyze_invoice_real(inv_bytes, ctr_bytes)
        
        # Ajout du statut global pour l'UI
        result["status"] = "SUCCESS" if result["score"] >= 80 else "ANOMALIE"
        
        return JSONResponse(result)
    except Exception as e:
        print(f"❌ Erreur Audit: {str(e)}")
        return JSONResponse({
            "score": 0, 
            "status": "ERROR", 
            "checks": [{"point": "Erreur Technique", "a": str(e), "b": "-", "status": "CRASH", "error": True}]
        })

@app.post("/api/ops/chaos")
async def api_chaos():
    """
    Lance le Chaos Monkey pour tester la robustesse (CPU, RAM, Disque, IA)
    """
    if not cortex: return JSONResponse({"results": []})
    return JSONResponse({"results": cortex.run_chaos_monkey()})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...)):
    """
    Chatbot Ops (Cortex Dev) - Interroge l'IA ou le moteur de règles
    """
    if not cortex: return JSONResponse({"response": "Cortex Offline."})
    return JSONResponse({"response": cortex.ask_agent(message)})

# ==============================================================================
# 3. ROUTES FRONTEND (HTML)
# ==============================================================================

def render_404(request):
    if os.path.isfile("templates/404.html"):
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    return HTMLResponse("<h1>404 - Page Not Found</h1>", status_code=404)

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

# Route générique pour les pages statiques (settings, etc.)
@app.get("/{page_name}.html", response_class=HTMLResponse)
async def show_static_page(request: Request, page_name: str):
    file_path = f"{page_name}.html"
    if os.path.isfile(f"templates/{file_path}"):
        return templates.TemplateResponse(file_path, {"request": request})
    return render_404(request)

# Route dynamique pour les profils clients (industry, mairie, sde, etc.)
@app.get("/dashboard/{profil}", response_class=HTMLResponse)
async def read_dashboard(request: Request, profil: str):
    clean_profil = profil.replace(".html", "")
    file_path = f"{clean_profil}.html"
    if os.path.isfile(f"templates/{file_path}"):
        return templates.TemplateResponse(file_path, {"request": request})
    return render_404(request)
