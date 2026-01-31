# main.py V6.6 - REAL DATA + FIXED ROUTING
import os
import json
import secrets
import logging
from datetime import datetime
import io

# DATA SCIENCE CORE
import pandas as pd
import numpy as np

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

app = FastAPI(title="ENERGISTRAT V6.6", version="ROUTING FIX")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates" if os.path.exists("templates") else ".")

# --- HELPER : ANALYSEUR DE FICHIER RÉEL ---
def process_real_file(content: bytes, filename: str):
    try:
        df = None
        if filename.endswith('.csv'):
            try: df = pd.read_csv(io.BytesIO(content), sep=';', parse_dates=True)
            except: df = pd.read_csv(io.BytesIO(content), sep=',', parse_dates=True)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(content))
        
        if df is None: raise ValueError("Format non supporté")

        # Normalisation des colonnes
        df.columns = [c.lower().strip() for c in df.columns]
        
        # Recherche intelligente des colonnes
        date_col = next((c for c in df.columns if 'date' in c or 'horodate' in c or 'time' in c), df.columns[0])
        val_col = next((c for c in df.columns if 'puissance' in c or 'p(kw)' in c or 'val' in c or 'conso' in c), df.columns[1])

        # Nettoyage
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col, val_col]).sort_values(by=date_col)
        
        if df[val_col].dtype == object:
             df[val_col] = df[val_col].astype(str).str.replace(',', '.').astype(float)

        dates = df[date_col].dt.strftime('%Y-%m-%d %H:%M').tolist()
        values = df[val_col].fillna(0).tolist()
        
        # Calculs KPIs
        talon = float(np.percentile(values, 10))
        average_val = float(np.mean(values))
        average_curve = [average_val] * len(values)
        
        # Ratio Weekend
        df['weekday'] = df[date_col].dt.weekday
        week_data = df[df['weekday'] < 5][val_col]
        weekend_data = df[df['weekday'] >= 5][val_col]
        
        avg_week = week_data.mean() if not week_data.empty else 1
        avg_weekend = weekend_data.mean() if not weekend_data.empty else 0
        inactivity_ratio = int((avg_weekend / avg_week) * 100) if avg_week > 0 else 0

        # Diagnostic
        diag = "Profil Standard."
        status = "OK"
        if inactivity_ratio > 70:
            diag = "ALERTE : Forte consommation le Weekend. Oubli GTC ?"
            status = "WARNING"
        elif talon > (max(values) * 0.5):
            diag = "ALERTE : Talon très élevé (>50% Pmax). Optimisation requise."
            status = "WARNING"

        return {
            "dates": dates,
            "values": values,
            "average": average_curve,
            "kpi": {
                "conso_totale": int(sum(values)),
                "p_max": float(max(values)),
                "talon": int(talon),
                "inactivity_ratio": inactivity_ratio,
                "diagnosis": diag,
                "status": status,
                "points_traites": len(values)
            }
        }

    except Exception as e:
        print(f"Erreur Calculation: {e}")
        raise e

# --- API OPS ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"success": False, "error": "PIN Incorrect"}, status_code=401)

    try:
        content = await file.read()
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6)
        json_filename = f"{target}_{timestamp}_{secure_token}.json"
        
        ext = file.filename.split('.')[-1].lower()
        final_data = {}
        
        if ext in ['csv', 'xls', 'xlsx']:
            analysis = process_real_file(content, file.filename)
            final_data = {
                "success": True,
                "kpi": analysis['kpi'],
                "chart": { "labels": analysis['dates'], "values": analysis['values'], "average": analysis['average'] },
                "ai_insight": f"Analyse Réelle : {analysis['kpi']['points_traites']} points traités. {analysis['kpi']['diagnosis']}",
                "retail_data": None
            }
        else:
            if CORTEX_AVAILABLE: final_data = await cortex.analyze_file(content, file.filename, target_profile=target)
            else: raise HTTPException(400, "PDF non supporté sans Cortex.")

        final_data["meta"] = {"profile": target, "filename": json_filename, "token": secure_token, "date": timestamp}

        with open(os.path.join(DATA_DIR, json_filename), "w") as f:
            json.dump(final_data, f)
            
        return JSONResponse({
            "success": True,
            "filename": json_filename,
            "token": secure_token,
            "secure_link": f"/dashboard/{target}?file={json_filename}&token={secure_token}",
            "kpi": final_data['kpi'],
            "chart": final_data['chart'],
            "ai_insight": final_data['ai_insight']
        })

    except Exception as e:
        return JSONResponse({"success": False, "error": f"Erreur: {str(e)}"})

@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    path = os.path.join(DATA_DIR, os.path.basename(filename))
    if not os.path.exists(path) or token not in filename: raise HTTPException(403)
    return FileResponse(path, media_type='application/json')

@app.post("/api/ops/audit")
async def audit_ep(invoice: UploadFile = File(...), contract: UploadFile = File(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({}, 401)
    if CORTEX_AVAILABLE: return JSONResponse(cortex.analyze_invoice_real(await invoice.read(), await contract.read()))
    return JSONResponse({"score": 0, "status": "NO_ENGINE", "checks": []})

@app.post("/api/ops/chaos")
async def chaos_ep(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse([], 401)
    return JSONResponse({"results": cortex.run_chaos_monkey() if CORTEX_AVAILABLE else []})

@app.post("/api/ops/chat")
async def chat_ep(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse("Auth Failed", 401)
    return JSONResponse({"response": cortex.ask_agent(message) if CORTEX_AVAILABLE else message})

# ---------------------------------------------------------
# NAVIGATION ROBUSTE (C'est ici que je corrige le 404)
# ---------------------------------------------------------

# 1. Route explicite pour OPS (Règle le problème du lien depuis Index)
@app.get("/ops")
@app.get("/ops.html")
async def r_ops(request: Request):
    if os.path.exists("ops.html"): return FileResponse("ops.html")
    if os.path.exists("templates/ops.html"): return templates.TemplateResponse("ops.html", {"request": request})
    return HTMLResponse("<h1>Ops Dashboard Not Found</h1>", 404)

# 2. Route explicite pour INDEX
@app.get("/")
@app.get("/index.html")
async def r_idx(request: Request):
    if os.path.exists("templates/index.html"): return templates.TemplateResponse("index.html", {"request": request})
    if os.path.exists("index.html"): return FileResponse("index.html")
    return await r_ops(request) # Fallback vers Ops si pas d'index

# 3. Catch-All pour les autres pages (Vitrine, Dashboards Clients)
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    # Fichier statique racine
    if os.path.isfile(path_name): return FileResponse(path_name)
    
    # Template HTML (avec ou sans extension)
    target = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"templates/{target}"):
        return templates.TemplateResponse(target, {"request": request})
    
    return HTMLResponse(f"<h1>404 - {path_name} Introuvable</h1>", 404)
