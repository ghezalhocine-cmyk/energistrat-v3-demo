# main.py V6.2 - NO REGRESSION EDITION
import os
import json
import shutil
import logging
import secrets
import random
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- CONFIGURATION SÉCURITÉ ---
ADMIN_PIN = "BOSS_V5"
DATA_DIR = "data_store"

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

# Import Moteur (avec Fallback)
try:
    from cortex_engine import cortex
    CORTEX_AVAILABLE = True
except ImportError:
    cortex = None
    CORTEX_AVAILABLE = False

app = FastAPI(title="ENERGISTRAT V6.2", version="STABLE")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates" if os.path.exists("templates") else ".")

# ---------------------------------------------------------
# 1. SÉCURITÉ : LE GARDIEN
# ---------------------------------------------------------
async def verify_admin(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN:
        raise HTTPException(status_code=401, detail="PIN OPS INCORRECT")
    return True

# ---------------------------------------------------------
# 2. API : LE COFFRE-FORT (Accès Client Sécurisé)
# ---------------------------------------------------------
@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(DATA_DIR, safe_filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    
    if token not in safe_filename:
        raise HTTPException(status_code=403, detail="TICKET SÉCURITÉ INVALIDE.")

    return FileResponse(path=file_path, media_type='application/json')

# ---------------------------------------------------------
# 3. API OPS : INGESTION & INTELLIGENCE
# ---------------------------------------------------------
@app.post("/api/ops/analyze")
async def api_analyze(
    file: UploadFile = File(...), 
    target: str = Form("demo"),
    x_admin_token: str = Header(None)
):
    if x_admin_token != ADMIN_PIN:
        return JSONResponse({"success": False, "error": "PIN Incorrect"}, status_code=401)

    try:
        content = await file.read()
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6)
        json_filename = f"{target}_{timestamp}_{secure_token}.json"
        json_path = os.path.join(DATA_DIR, json_filename)
        
        final_data = {}

        if CORTEX_AVAILABLE:
            final_data = await cortex.analyze_file(content, file.filename, target_profile=target)
        else:
            # MOCK DATA (Fallback)
            base_conso = random.randint(300, 500)
            labels = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"]
            values = [base_conso + random.randint(-50, 50) for _ in range(12)]
            average = [sum(values)/12] * 12
            
            # Données Retail Mockées Spécifiques
            retail_mock = {
                "benchmark": [
                    {"nom": "Magasin Lyon Part-Dieu", "conso": 450, "ratio": "180 kWh/m2", "status": "TOP PERFORMER"},
                    {"nom": "Magasin Bordeaux Lac", "conso": 520, "ratio": "210 kWh/m2", "status": "NORMAL"},
                    {"nom": "Hyper Sud Marseille", "conso": 890, "ratio": "340 kWh/m2", "status": "ALERTE FROID"}
                ],
                "froid_analysis": {
                    "ratio": 42, "is_alert": True, "message": "Dérive température positive (+6°C) détectée."
                }
            }

            final_data = {
                "success": True,
                "kpi": {"points_traites": 35040, "conso": sum(values), "ratio_froid": 42},
                "chart": {"labels": labels, "values": values, "average": average},
                "retail_data": retail_mock if target == 'retail' else None,
                "ai_insight": f"Analyse V6.2 pour {target}. Profil de charge traité."
            }

        final_data["meta"] = {
            "profile": target, "filename": json_filename, "security_token": secure_token, "date": timestamp
        }

        with open(json_path, "w") as f:
            json.dump(final_data, f)
            
        return JSONResponse({
            "success": True,
            "filename": json_filename,
            "token": secure_token,
            "secure_link": f"/dashboard/{target}?file={json_filename}&token={secure_token}",
            "kpi": final_data.get("kpi"),
            "chart": final_data.get("chart"),
            "retail_data": final_data.get("retail_data"),
            "ai_insight": final_data.get("ai_insight")
        })

    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/audit")
async def api_audit(invoice: UploadFile = File(...), contract: UploadFile = File(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"status": "AUTH_ERROR"}, status_code=401)
    
    if not CORTEX_AVAILABLE: 
        return JSONResponse({
            "score": 78, "status": "OPTIMISABLE",
            "checks": [
                {"point": "Puissance", "a": "250 kVA", "b": "250 kVA", "status": "OK", "error": False},
                {"point": "Taxes", "a": "Plein Tarif", "b": "Exonération", "status": "ERREUR", "error": True}
            ]
        })
    try:
        result = cortex.analyze_invoice_real(await invoice.read(), await contract.read())
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"score": 0, "status": "ERROR", "checks": []})

@app.post("/api/ops/chaos")
async def api_chaos(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"results": []}, status_code=401)
    if not CORTEX_AVAILABLE: return JSONResponse({"results": [{"test": "Mock Chaos", "status": "PASS"}]})
    return JSONResponse({"results": cortex.run_chaos_monkey()})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"response": "Auth Failed"})
    if not CORTEX_AVAILABLE: return JSONResponse({"response": f"Cortex (Simulé): {message}"})
    return JSONResponse({"response": cortex.ask_agent(message)})

# ---------------------------------------------------------
# 4. ROUTES HTML & NAVIGATION (CORRECTIF VITRINE)
# ---------------------------------------------------------

@app.get("/")
@app.get("/index.html")
async def landing(request: Request):
    # Essaie de servir index.html depuis templates, sinon ops
    if os.path.exists("templates/index.html"):
        return templates.TemplateResponse("index.html", {"request": request})
    return FileResponse("ops.html") if os.path.exists("ops.html") else HTMLResponse("<h1>System Online</h1>")

# Route Spécifique Dashboard (avec gestion .html optionnel)
@app.get("/dashboard/{profil}")
async def dashboard_route(request: Request, profil: str):
    clean_name = profil.replace(".html", "")
    filename = f"{clean_name}.html"
    if os.path.exists(f"templates/{filename}"):
        return templates.TemplateResponse(filename, {"request": request})
    return HTMLResponse("<h1>Dashboard Introuvable</h1>", status_code=404)

# ROUTE UNIVERSELLE (Celle qui manquait pour la vitrine)
# Elle capture tout (ex: /industry.html, /presentation.html, /style.css)
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    # 1. Est-ce un fichier statique à la racine ? (CSS, JS, IMG)
    if os.path.isfile(path_name):
        return FileResponse(path_name)
    
    # 2. Est-ce un template HTML ? (ex: industry.html)
    if path_name.endswith(".html"):
        if os.path.exists(f"templates/{path_name}"):
            return templates.TemplateResponse(path_name, {"request": request})
    
    # 3. Est-ce un template sans extension ? (ex: /industry)
    potential_html = f"{path_name}.html"
    if os.path.exists(f"templates/{potential_html}"):
        return templates.TemplateResponse(potential_html, {"request": request})

    return HTMLResponse(f"<h1>404 - {path_name} Introuvable</h1>", status_code=404)
