# main.py V6.4 - DEEP INSIGHT & EXPERT ANALYTICS
import os
import json
import logging
import secrets
import random
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
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

try:
    from cortex_engine import cortex
    CORTEX_AVAILABLE = True
except ImportError:
    cortex = None
    CORTEX_AVAILABLE = False

app = FastAPI(title="ENERGISTRAT V6.4", version="EXPERT")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates" if os.path.exists("templates") else ".")

# --- SECURITE ---
async def verify_admin(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: raise HTTPException(401, "PIN Incorrect")
    return True

# --- API VAULT ---
@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(DATA_DIR, safe_filename)
    if not os.path.exists(file_path): raise HTTPException(404, "Fichier introuvable.")
    if token not in safe_filename: raise HTTPException(403, "Token invalide.")
    return FileResponse(file_path, media_type='application/json')

# --- API OPS : ANALYSE EXPERTE ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"success": False, "error": "PIN Incorrect"}, status_code=401)

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
            # --- MOTEUR DE SIMULATION EXPERT (V6.4) ---
            dates = []
            values = []
            averages = []
            
            start_date = datetime(datetime.now().year, 1, 1)
            
            # Paramètres de simulation selon le profil
            base_load = 400 if target == 'industry' else (200 if target == 'retail' else 50)
            volatility = 0.3 # 30% de variation
            
            weekend_values = []
            week_values = []

            for i in range(365):
                current_date = start_date + timedelta(days=i)
                date_str = current_date.strftime("%Y-%m-%d")
                
                # Facteurs
                is_weekend = current_date.weekday() >= 5
                season_factor = 1.4 if current_date.month in [12, 1, 2] else 0.9
                day_factor = 0.3 if is_weekend else 1.0 # Baisse drastique le weekend
                
                # Génération valeur
                noise = random.randint(int(-base_load*0.1), int(base_load*0.1))
                val = int((base_load * season_factor * day_factor) + noise)
                val = max(val, int(base_load * 0.2)) # Il reste toujours un "Talon" (frigos, veille)
                
                # Moyenne lissée (Tendance)
                avg = int(base_load * season_factor * (0.5 if is_weekend else 0.9))

                dates.append(date_str)
                values.append(val)
                averages.append(avg)
                
                if is_weekend: weekend_values.append(val)
                else: week_values.append(val)

            # --- CALCUL DES MÉTRIQUES EXPERTES ---
            p_max = max(values)
            conso_total = sum(values)
            
            # 1. Le Talon (Baseload) : Moyenne des 10% valeurs les plus basses
            sorted_vals = sorted(values)
            talon = sum(sorted_vals[:36]) / 36 
            
            # 2. Ratio Inactivité (Weekend / Semaine)
            avg_week = sum(week_values) / len(week_values) if week_values else 1
            avg_weekend = sum(weekend_values) / len(weekend_values) if weekend_values else 0
            inactivity_ratio = int((avg_weekend / avg_week) * 100)
            
            # 3. Diagnostic CORTEX
            diagnosis = "Profil standard."
            status = "OK"
            if inactivity_ratio > 60:
                diagnosis = "⚠️ ALERTE : Consommation weekend excessive (>60% semaine). Vérifier GTC/Chauffage."
                status = "WARNING"
            elif talon > (p_max * 0.4):
                diagnosis = "⚠️ ALERTE : Talon énergétique très élevé. Les équipements ne s'arrêtent jamais."
                status = "WARNING"
            else:
                diagnosis = "✅ EXCELLENT : Le site régule parfaitement ses périodes d'inactivité."
                status = "OPTIMIZED"

            # Mock Retail Spécifique
            retail_mock = {
                "benchmark": [
                    {"nom": "Magasin Lyon", "conso": 450, "ratio": "180", "status": "TOP"},
                    {"nom": "Magasin Paris", "conso": 520, "ratio": "210", "status": "NORMAL"},
                    {"nom": "Hyper Marseille", "conso": 890, "ratio": "340", "status": "ALERTE"}
                ],
                "froid_analysis": {"ratio": 42, "is_alert": True, "message": "Anomalie T°C détectée."}
            }

            final_data = {
                "success": True,
                "kpi": {
                    "points_traites": 365, 
                    "conso": conso_total, 
                    "p_max": p_max,
                    "talon": int(talon),
                    "inactivity_ratio": inactivity_ratio,
                    "diagnosis": diagnosis,
                    "status": status
                },
                "chart": {"labels": dates, "values": values, "average": averages},
                "retail_data": retail_mock if target == 'retail' else None,
                "ai_insight": f"Analyse Experte {target}. {diagnosis}"
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

# --- ROUTES STANDARD (AUDIT/CHAOS/CHAT) ---
@app.post("/api/ops/audit")
async def api_audit(invoice: UploadFile = File(...), contract: UploadFile = File(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"status": "AUTH_ERROR"}, status_code=401)
    if not CORTEX_AVAILABLE: return JSONResponse({"score": 78, "status": "OK", "checks": [{"point": "Test", "a": "A", "b": "B", "status": "OK", "error": False}]})
    try: return JSONResponse(cortex.analyze_invoice_real(await invoice.read(), await contract.read()))
    except: return JSONResponse({"score": 0, "status": "ERROR", "checks": []})

@app.post("/api/ops/chaos")
async def api_chaos(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse([], 401)
    return JSONResponse({"results": cortex.run_chaos_monkey()}) if CORTEX_AVAILABLE else JSONResponse({"results": []})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse("Auth Failed", 401)
    return JSONResponse({"response": cortex.ask_agent(message)}) if CORTEX_AVAILABLE else JSONResponse({"response": f"Echo: {message}"})

# --- NAVIGATION ---
@app.get("/")
@app.get("/index.html")
async def landing(request: Request):
    if os.path.exists("templates/index.html"): return templates.TemplateResponse("index.html", {"request": request})
    return FileResponse("ops.html") if os.path.exists("ops.html") else HTMLResponse("System Online")

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if os.path.isfile(path_name): return FileResponse(path_name)
    if path_name.endswith(".html") and os.path.exists(f"templates/{path_name}"): return templates.TemplateResponse(path_name, {"request": request})
    potential = f"{path_name}.html"
    if os.path.exists(f"templates/{potential}"): return templates.TemplateResponse(potential, {"request": request})
    return HTMLResponse(f"404 - {path_name}", 404)
