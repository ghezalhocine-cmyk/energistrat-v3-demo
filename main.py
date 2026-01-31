# main.py V5.7 - SECURITY + INTERACTIVITY RESTORED
import os
import json
import shutil
import logging
import secrets
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- CONFIGURATION ---
ADMIN_PIN = "BOSS_V5"
DATA_DIR = "data_store"

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

# Import Cortex ou Fallback
try:
    from cortex_engine import cortex
    CORTEX_AVAILABLE = True
except ImportError:
    cortex = None
    CORTEX_AVAILABLE = False

app = FastAPI(title="ENERGISTRAT V5.7", version="OPS RESTORED")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates" if os.path.exists("templates") else ".")

# --- SÉCURITÉ ---
async def verify_admin(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN:
        raise HTTPException(status_code=401, detail="PIN INCORRECT")
    return True

# --- API COFFRE-FORT ---
@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(DATA_DIR, safe_filename)
    if not os.path.exists(file_path): raise HTTPException(404, "Fichier introuvable")
    if token not in safe_filename: raise HTTPException(403, "Token invalide")
    return FileResponse(file_path, media_type='application/json')

# --- API UPLOAD & ANALYSE (CORRIGÉE) ---
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    profile: str = Form(...),
    siret: str = Form("UNKNOWN"),
    x_admin_token: str = Header(None) # On le récupère ici manuellement pour gérer l'erreur proprement
):
    if x_admin_token != ADMIN_PIN:
        return JSONResponse({"status": "error", "message": "PIN Incorrect"}, status_code=401)

    try:
        # 1. Traitement Fichier
        content = await file.read()
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6)
        safe_siret = siret.replace(" ", "")
        json_filename = f"{safe_siret}_{profile}_{timestamp}_{secure_token}.json"
        json_path = os.path.join(DATA_DIR, json_filename)

        # 2. INTELLIGENCE (Cortex ou Mock)
        final_data = {}
        if CORTEX_AVAILABLE:
            final_data = await cortex.analyze_file(content, file.filename, target_profile=profile)
        else:
            # MOCK ROBUSTE pour que le graphique s'affiche
            # Génération d'une fausse courbe de charge
            import random
            labels = [f"{i}h" for i in range(24)]
            values = [random.randint(50, 150) for _ in range(24)]
            average = [sum(values)/len(values)] * 24
            
            final_data = {
                "success": True,
                "kpi": {"conso": sum(values), "ratio_froid": 35, "budget": sum(values)*0.15},
                "chart": {"labels": labels, "values": values, "average": average},
                "ai_insight": "Analyse CORTEX simulée (Moteur Offline). Données générées pour test visuel."
            }

        # 3. Métadonnées Sécurité
        final_data["meta"] = {
            "siret": safe_siret,
            "profile": profile,
            "filename": json_filename,
            "security_token": secure_token
        }

        # 4. Sauvegarde
        with open(json_path, "w") as f:
            json.dump(final_data, f)

        # 5. RÉPONSE RICHE (Pour l'UI Ops)
        # C'est ICI que ça manquait : on renvoie 'chart' et 'kpi' au frontend
        return {
            "status": "success",
            "filename": json_filename,
            "token": secure_token,
            "secure_link": f"/dashboard/{profile}?file={json_filename}&token={secure_token}",
            # Données pour l'affichage immédiat
            "kpi": final_data.get("kpi"),
            "chart": final_data.get("chart"),
            "ai_insight": final_data.get("ai_insight")
        }

    except Exception as e:
        logging.error(f"Erreur: {str(e)}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

# --- API AUDIT (CORRIGÉE) ---
@app.post("/api/ops/audit")
async def api_audit(
    invoice: UploadFile = File(...), 
    contract: UploadFile = File(...),
    x_admin_token: str = Header(None)
):
    # Vérification PIN
    if x_admin_token != ADMIN_PIN: return JSONResponse({"score": 0, "status": "AUTH_ERROR", "checks": []}, status_code=401)
    
    if not CORTEX_AVAILABLE:
        # Mock Audit pour que tu voies le tableau se remplir
        return JSONResponse({
            "score": 85,
            "status": "OPTIMISABLE",
            "checks": [
                {"point": "Puissance Souscrite", "a": "150 kVA", "b": "150 kVA", "status": "OK", "error": False},
                {"point": "Formule Tarifaire", "a": "FTA", "b": "FTB", "status": "MISMATCH", "error": True},
                {"point": "Taxes (CSPE)", "a": "Exonéré", "b": "Non", "status": "ALERT", "error": True}
            ]
        })
    
    try:
        inv_bytes = await invoice.read()
        ctr_bytes = await contract.read()
        result = cortex.analyze_invoice_real(inv_bytes, ctr_bytes)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"score": 0, "status": "CRASH", "error": str(e)})

# --- API CHAOS & CHAT ---
@app.post("/api/ops/chaos")
async def api_chaos(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"results": []}, status_code=401)
    if not CORTEX_AVAILABLE: return JSONResponse({"results": [{"test": "Mock Test", "status": "PASS"}]})
    return JSONResponse({"results": cortex.run_chaos_monkey()})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"response": "Auth Failed"})
    if not CORTEX_AVAILABLE: return JSONResponse({"response": f"Echo: {message}"})
    return JSONResponse({"response": cortex.ask_agent(message)})

# --- ROUTES HTML ---
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
