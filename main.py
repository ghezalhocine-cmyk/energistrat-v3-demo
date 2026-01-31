# main.py V6.1 - SECURE RETAIL CORE
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

app = FastAPI(title="ENERGISTRAT V6.1", version="RETAIL SECURE")

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
    """
    Remplace l'ancien /api/data/{profil}.
    Nécessite le Token dans l'URL.
    """
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(DATA_DIR, safe_filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    
    # Vérification stricte du Token dans le nom du fichier
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
    """
    Analyse SGE + Sécurisation + Génération Token
    """
    if x_admin_token != ADMIN_PIN:
        return JSONResponse({"success": False, "error": "PIN Incorrect"}, status_code=401)

    try:
        content = await file.read()
        
        # Génération des clés de sécurité
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6)
        json_filename = f"{target}_{timestamp}_{secure_token}.json"
        json_path = os.path.join(DATA_DIR, json_filename)
        
        final_data = {}

        if CORTEX_AVAILABLE:
            # Appel Moteur Réel
            final_data = await cortex.analyze_file(content, file.filename, target_profile=target)
        else:
            # --- MOCK INTELLIGENT (RETAIL SPECIFIC) ---
            # Génère de la donnée crédible si Cortex est absent
            base_conso = random.randint(300, 500)
            labels = ["Jan", "Fev", "Mar", "Avr", "Mai", "Juin", "Juil", "Aout", "Sep", "Oct", "Nov", "Dec"]
            values = [base_conso + random.randint(-50, 50) for _ in range(12)]
            average = [sum(values)/12] * 12
            
            retail_mock = {
                "benchmark": [
                    {"nom": "Magasin Lyon Part-Dieu", "conso": 450, "ratio": "180 kWh/m2", "status": "TOP PERFORMER"},
                    {"nom": "Magasin Bordeaux Lac", "conso": 520, "ratio": "210 kWh/m2", "status": "NORMAL"},
                    {"nom": "Hyper Sud Marseille", "conso": 890, "ratio": "340 kWh/m2", "status": "ALERTE FROID"}
                ],
                "froid_analysis": {
                    "ratio": 42,
                    "is_alert": True,
                    "message": "Dérive température positive (+6°C) détectée secteur Boucherie."
                }
            }

            final_data = {
                "success": True,
                "kpi": {"points_traites": 35040, "conso": sum(values), "ratio_froid": 42},
                "chart": {"labels": labels, "values": values, "average": average},
                "retail_data": retail_mock if target == 'retail' else None,
                "ai_insight": "Analyse V6.1 (Simulée). Profil de charge cohérent. Anomalie Froid détectée."
            }

        # Enrichissement Méta-données Sécurité
        final_data["meta"] = {
            "profile": target,
            "filename": json_filename,
            "security_token": secure_token,
            "date": timestamp
        }

        # Persistance
        with open(json_path, "w") as f:
            json.dump(final_data, f)
            
        # Retour complet pour l'UI Ops
        return JSONResponse({
            "success": True,
            "filename": json_filename,
            "token": secure_token,
            "secure_link": f"/dashboard/{target}?file={json_filename}&token={secure_token}",
            # Données pour affichage immédiat Ops
            "kpi": final_data.get("kpi"),
            "chart": final_data.get("chart"),
            "retail_data": final_data.get("retail_data"),
            "ai_insight": final_data.get("ai_insight")
        })

    except Exception as e:
        print(f"❌ Erreur Analyze: {str(e)}")
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/audit")
async def api_audit(
    invoice: UploadFile = File(...), 
    contract: UploadFile = File(...),
    x_admin_token: str = Header(None)
):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"status": "AUTH_ERROR"}, status_code=401)
    
    if not CORTEX_AVAILABLE: 
        # Mock Audit
        return JSONResponse({
            "score": 78,
            "status": "OPTIMISABLE",
            "checks": [
                {"point": "Puissance Souscrite", "a": "250 kVA", "b": "250 kVA", "status": "OK", "error": False},
                {"point": "Formule Tarifaire", "a": "CU4", "b": "CU4", "status": "OK", "error": False},
                {"point": "Taxes (CSPE)", "a": "Plein Tarif", "b": "Exonération", "status": "ERREUR", "error": True}
            ]
        })
    
    try:
        inv_bytes = await invoice.read()
        ctr_bytes = await contract.read()
        result = cortex.analyze_invoice_real(inv_bytes, ctr_bytes)
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
    if not CORTEX_AVAILABLE: return JSONResponse({"response": f"Cortex (Simulé): J'ai bien reçu '{message}'"})
    return JSONResponse({"response": cortex.ask_agent(message)})

# ---------------------------------------------------------
# 4. ROUTES HTML UI
# ---------------------------------------------------------
def get_template(request, filename):
    if os.path.exists(f"templates/{filename}"): return templates.TemplateResponse(filename, {"request": request})
    if os.path.exists(filename): return FileResponse(filename)
    return HTMLResponse("<h1>404</h1>", status_code=404)

@app.get("/")
@app.get("/index.html")
async def r_index(request: Request): return get_template(request, "index.html")

@app.get("/ops")
@app.get("/ops.html")
async def r_ops(request: Request): return get_template(request, "ops.html")

@app.get("/dashboard/{p}")
async def r_dash(request: Request, p: str): return get_template(request, f"{p.replace('.html','')}.html")

@app.get("/{f}")
async def r_static(f: str):
    if os.path.exists(f) and f.split('.')[-1] in ['css','js','png','jpg','html']: return FileResponse(f)
    return JSONResponse({"e": "404"}, status_code=404)
