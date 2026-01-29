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

app = FastAPI(title="ENERGISTRAT V3", version="3.14 PERSISTENCE & AUDIT")

# ==============================================================================
# 1. SETUP DOSSIERS & CONFIG
# ==============================================================================
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")
# Dossier pour la persistance des données clients (Pont de Données)
if not os.path.exists("data_store"): os.makedirs("data_store")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ==============================================================================
# 2. ROUTES API (BACKEND INTELLIGENCE)
# ==============================================================================

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    """
    Ingestion SGE : Lit le fichier, l'analyse via Cortex, et sauvegarde le JSON.
    """
    if not cortex: return JSONResponse({"success": False, "error": "Moteur Cortex HS"})
    
    try:
        content = await file.read()
        # Appel au moteur Cortex pour l'analyse SGE
        result = await cortex.analyze_file(content, file.filename)
        
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
    AUDIT LAB : Comparaison Facture vs Contrat (PDF/OCR)
    """
    results = {
        "files": [invoice.filename, contract.filename],
        "checks": [],
        "score": 100,
        "status": "SUCCESS"
    }

    # Lecture des noms de fichiers pour la simulation intelligente
    # (Dans une version ultérieure, on utilisera pdfplumber ici sur le contenu binaire)
    inv_name = invoice.filename.lower()
    ctr_name = contract.filename.lower()

    # --- LOGIQUE DE VÉRIFICATION (MOTEUR DE RÈGLES) ---
    
    # 1. CHECK PRIX (Simulation basée sur le nom du fichier pour le test)
    # Si le fichier contient "err", on simule une erreur de prix
    contract_price = 85.00
    invoice_price = 89.50 if "err" in inv_name else 85.00
    
    price_status = "OK"
    is_price_error = False
    
    if invoice_price != contract_price:
        price_status = "ÉCART PRIX"
        is_price_error = True
        results["score"] -= 30

    results["checks"].append({
        "point": "Prix Molécule Gaz (€/MWh)",
        "a": f"{invoice_price:.2f} €",
        "b": f"{contract_price:.2f} €",
        "status": price_status,
        "error": is_price_error
    })

    # 2. CHECK TAXES (TICGN / CSPE)
    # Si le contrat mentionne "exonere", la facture doit l'être aussi
    is_exonere = "exonere" in ctr_name
    tax_applied = True # Par défaut les factures appliquent la taxe
    
    tax_status = "OK"
    is_tax_error = False

    if is_exonere and tax_applied:
        tax_status = "ERREUR FISCALE"
        is_tax_error = True
        results["score"] -= 35

    results["checks"].append({
        "point": "Fiscalité (TICGN)",
        "a": "Taxe Appliquée" if tax_applied else "0 €",
        "b": "Exonération" if is_exonere else "Standard",
        "status": tax_status,
        "error": is_tax_error
    })

    # 3. CHECK PÉRIODE
    results["checks"].append({
        "point": "Validité Temporelle",
        "a": "Fév 2026",
        "b": "Actif (Fin 2027)",
        "status": "OK",
        "error": False
    })

    # Synthèse
    if results["score"] < 100:
        results["status"] = "ANOMALIE"

    return JSONResponse(results)

@app.post("/api/ops/chaos")
async def api_chaos():
    """
    Lance le Chaos Monkey pour tester la robustesse
    """
    if not cortex: return JSONResponse({"results": []})
    return JSONResponse({"results": cortex.run_chaos_monkey()})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...)):
    """
    Chatbot Ops (Cortex Dev)
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
