# main.py V5.6 - HYBRID SECURITY & INTELLIGENCE
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

# --- 1. CONFIGURATION & SÉCURITÉ ---
ADMIN_PIN = "BOSS_V5"  # Ton Code PIN Maître
DATA_DIR = "data_store"

# Création des dossiers critiques
os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

# Tentative d'import du moteur Cortex
try:
    from cortex_engine import cortex
    CORTEX_AVAILABLE = True
except ImportError:
    cortex = None
    CORTEX_AVAILABLE = False

app = FastAPI(title="ENERGISTRAT V5.6", version="SECURE INTELLIGENCE")

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montage des fichiers statiques (CSS/JS/Images uniquement)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuration Templates (Gestion robuste : cherche dans templates/ ou root)
templates = Jinja2Templates(directory="templates" if os.path.exists("templates") else ".")

# ---------------------------------------------------------
# 2. SÉCURITÉ : LE GARDIEN
# ---------------------------------------------------------
async def verify_admin(x_admin_token: str = Header(None)):
    """Vérifie le PIN pour toute action Ops sensible"""
    if x_admin_token != ADMIN_PIN:
        # On log l'tentative d'intrusion
        print(f"⚠️  Tentative d'accès non autorisé avec token: {x_admin_token}")
        raise HTTPException(status_code=401, detail="ACCÈS REFUSÉ : Code PIN Incorrect.")
    return True

# ---------------------------------------------------------
# 3. API : LE COFFRE-FORT (Accès Client)
# ---------------------------------------------------------
@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    """
    Route unique pour lire les données JSON.
    Vérifie que le token est présent dans le nom du fichier.
    """
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(DATA_DIR, safe_filename)

    # 1. Existence
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    # 2. Sécurité (Le token DOIT être dans le nom du fichier)
    if token not in safe_filename:
        raise HTTPException(status_code=403, detail="TICKET INVALIDE.")

    return FileResponse(path=file_path, media_type='application/json')

# ---------------------------------------------------------
# 4. API : L'USINE OPS (Upload & Intelligence)
# ---------------------------------------------------------
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    profile: str = Form(...),
    siret: str = Form("UNKNOWN"),
    authorized: bool = Depends(verify_admin) # Protection PIN
):
    """
    Ingestion unifiée : Sécurité V5.5 + Intelligence CORTEX
    """
    try:
        # A. Sauvegarde temporaire pour analyse
        temp_filename = f"temp_{file.filename}"
        content = await file.read()
        with open(temp_filename, "wb") as f:
            f.write(content)
        
        # B. Génération des clés de sécurité
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6)
        safe_siret = siret.replace(" ", "")
        
        # Nommage sécurisé
        json_filename = f"{safe_siret}_{profile}_{timestamp}_{secure_token}.json"
        json_path = os.path.join(DATA_DIR, json_filename)

        # C. INTELLIGENCE HYBRIDE
        final_data = {}
        
        if CORTEX_AVAILABLE:
            # Si Cortex est là, on l'utilise pour avoir de la vraie data
            print(f"🧠 CORTEX ANALYSE : {file.filename} pour {profile}")
            # On passe le contenu binaire ou le chemin
            analysis_result = await cortex.analyze_file(content, file.filename, target_profile=profile)
            final_data = analysis_result
        else:
            # Fallback : Données Mockées (Si Cortex HS ou absent)
            print("⚠️ CORTEX ABSENT : Utilisation Mock Data")
            final_data = {
                "success": True,
                "kpi": {"conso": 1250, "ratio_froid": 42, "budget": 180},
                "chart": {"labels": ["Jan", "Fev"], "values": [100, 120]},
                "ai_insight": "Analyse simulée (Mode Secours)."
            }

        # D. Enrichissement avec les métadonnées de sécurité
        final_data["meta"] = {
            "siret": safe_siret,
            "profile": profile,
            "date": timestamp,
            "filename": json_filename,
            "security_token": secure_token
        }

        # E. Persistance Sécurisée
        with open(json_path, "w") as f:
            json.dump(final_data, f)

        # Nettoyage
        if os.path.exists(temp_filename): os.remove(temp_filename)

        return {
            "status": "success", 
            "filename": json_filename,
            "token": secure_token,
            "secure_link": f"/dashboard/{profile}?file={json_filename}&token={secure_token}"
        }

    except Exception as e:
        logging.error(f"Erreur Upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Autres Outils Ops (Protégés) ---

@app.post("/api/ops/audit")
async def api_audit(
    invoice: UploadFile = File(...), 
    contract: UploadFile = File(...),
    x_admin_token: str = Header(None) # Protection manuelle ici si besoin, ou via Depends
):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    if not CORTEX_AVAILABLE: 
        return JSONResponse({"score": 0, "checks": [], "status": "ENGINE_OFF"})
    
    try:
        inv_bytes = await invoice.read()
        ctr_bytes = await contract.read()
        result = cortex.analyze_invoice_real(inv_bytes, ctr_bytes)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"score": 0, "status": "ERROR", "error": str(e)})

@app.post("/api/ops/chaos")
async def api_chaos(authorized: bool = Depends(verify_admin)):
    if not CORTEX_AVAILABLE: return JSONResponse({"results": [{"test": "Cortex", "status": "OFFLINE"}]})
    return JSONResponse({"results": cortex.run_chaos_monkey()})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), authorized: bool = Depends(verify_admin)):
    if not CORTEX_AVAILABLE: return JSONResponse({"response": "Cortex Offline."})
    return JSONResponse({"response": cortex.ask_agent(message)})

# ---------------------------------------------------------
# 5. ROUTES FRONTEND (HTML)
# ---------------------------------------------------------

def get_template_response(request: Request, filename: str):
    """Helper pour servir un template ou un fichier statique root"""
    # 1. Priorité au dossier templates/
    if os.path.isfile(f"templates/{filename}"):
        return templates.TemplateResponse(filename, {"request": request})
    # 2. Fallback à la racine (pour déploiement simple)
    if os.path.isfile(filename):
        return FileResponse(filename)
    # 3. 404
    return HTMLResponse("<h1>404 - Page Introuvable</h1>", status_code=404)

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html")
async def landing(request: Request):
    # Si pas d'index, on renvoie vers ops
    if not os.path.exists("templates/index.html") and not os.path.exists("index.html"):
        return await ops_dashboard(request)
    return get_template_response(request, "index.html")

@app.get("/ops")
@app.get("/ops.html")
async def ops_dashboard(request: Request):
    return get_template_response(request, "ops.html")

# Route dynamique pour les dashboards (Retail, Industry, etc.)
@app.get("/dashboard/{profil}")
async def read_dashboard(request: Request, profil: str):
    # Nettoyage du nom (ex: "retail" ou "retail.html")
    clean_profil = profil.replace(".html", "")
    filename = f"{clean_profil}.html"
    return get_template_response(request, filename)

# Route générique pour les fichiers CSS/JS s'ils sont à la racine (fallback)
@app.get("/{filename}")
async def read_root_static(filename: str):
    allowed = ['.css', '.js', '.png', '.jpg', '.svg', '.ico', '.html']
    if any(filename.endswith(ext) for ext in allowed):
        if os.path.isfile(filename):
            return FileResponse(filename)
    return JSONResponse({"status": "404 Not Found"}, status_code=404)
