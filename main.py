# main.py V6.5 - REAL DATA ENGINE (NO MOCK)
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

# Import Cortex (Optionnel, pour le PDF/Chat)
try:
    from cortex_engine import cortex
    CORTEX_AVAILABLE = True
except ImportError:
    cortex = None
    CORTEX_AVAILABLE = False

app = FastAPI(title="ENERGISTRAT V6.5", version="REAL DATA")

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
    """
    Lit un fichier binaire (Excel/CSV), trouve la courbe de charge, et calcule les KPIs.
    """
    try:
        # 1. Chargement en DataFrame Pandas
        df = None
        if filename.endswith('.csv'):
            # Tente différents séparateurs classiques SGE
            try: df = pd.read_csv(io.BytesIO(content), sep=';', parse_dates=True)
            except: df = pd.read_csv(io.BytesIO(content), sep=',', parse_dates=True)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(content))
        
        if df is None: raise ValueError("Format non supporté (CSV/Excel requis)")

        # 2. Nettoyage et Recherche de Colonnes
        # On cherche une colonne date et une colonne valeur
        df.columns = [c.lower().strip() for c in df.columns]
        
        # Identification colonne Date
        date_col = next((c for c in df.columns if 'date' in c or 'horodate' in c or 'time' in c), None)
        # Identification colonne Puissance (P, Puissance, Charge, Value, kW)
        val_col = next((c for c in df.columns if 'puissance' in c or 'p(kw)' in c or 'val' in c or 'conso' in c), None)

        if not date_col or not val_col:
            # Fallback : Si on trouve pas, on prend 1ere et 2eme colonne
            date_col = df.columns[0]
            val_col = df.columns[1]

        # Conversion et Tri
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col, val_col]).sort_values(by=date_col)
        
        # Nettoyage des valeurs (virgules en points, conversion float)
        if df[val_col].dtype == object:
             df[val_col] = df[val_col].astype(str).str.replace(',', '.').astype(float)

        dates = df[date_col].dt.strftime('%Y-%m-%d %H:%M').tolist()
        values = df[val_col].fillna(0).tolist()
        
        # 3. CALCULS MATHÉMATIQUES RÉELS
        # Talon : On prend le 10ème percentile (les 10% de valeurs les plus basses = bruit de fond)
        talon = float(np.percentile(values, 10))
        
        # Moyenne
        average_val = float(np.mean(values))
        average_curve = [average_val] * len(values) # Ligne droite pour le graph
        
        # Ratio Inactivité (Weekend vs Semaine)
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
                "conso_totale": int(sum(values)), # Somme brute des points (Attention à l'unité temporelle, ici c'est des kW * pas de temps)
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

# --- ROUTES API ---

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"success": False, "error": "PIN Incorrect"}, status_code=401)

    try:
        content = await file.read()
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6)
        json_filename = f"{target}_{timestamp}_{secure_token}.json"
        
        # --- MOTEUR RÉEL ---
        # Si c'est un PDF, on laisse Cortex (ou erreur). Si c'est CSV/Excel, on calcule.
        ext = file.filename.split('.')[-1].lower()
        
        final_data = {}
        
        if ext in ['csv', 'xls', 'xlsx']:
            # CALCUL MATHÉMATIQUE
            analysis = process_real_file(content, file.filename)
            
            final_data = {
                "success": True,
                "kpi": analysis['kpi'],
                "chart": {
                    "labels": analysis['dates'],
                    "values": analysis['values'],
                    "average": analysis['average']
                },
                "ai_insight": f"Analyse Réelle : {analysis['kpi']['points_traites']} points traités. {analysis['kpi']['diagnosis']}",
                "retail_data": None # On désactive le mock retail pour se focus sur la vraie data
            }
        else:
            # Fallback PDF (Cortex)
            if CORTEX_AVAILABLE:
                final_data = await cortex.analyze_file(content, file.filename, target_profile=target)
            else:
                raise HTTPException(400, "Format PDF non supporté sans Cortex. Utilisez CSV/Excel.")

        # Metadonnées
        final_data["meta"] = {"profile": target, "filename": json_filename, "token": secure_token, "date": timestamp}

        # Sauvegarde
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
        return JSONResponse({"success": False, "error": f"Erreur Analyse: {str(e)}"})

# --- ROUTES SÉCURITÉ & NAVIGATION (INCHANGÉES) ---
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

@app.get("/")
@app.get("/index.html")
async def r_idx(request: Request): return templates.TemplateResponse("index.html", {"request": request}) if os.path.exists("templates/index.html") else FileResponse("ops.html")

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if os.path.isfile(path_name): return FileResponse(path_name)
    if path_name.endswith(".html") and os.path.exists(f"templates/{path_name}"): return templates.TemplateResponse(path_name, {"request": request})
    return HTMLResponse("404", 404)
