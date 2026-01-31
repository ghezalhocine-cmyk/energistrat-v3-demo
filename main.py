# main.py V7.4 - GROUP AGGREGATION & ROBUST ENGINE
import os
import json
import secrets
import logging
from datetime import datetime
import io

# --- DATA SCIENCE CORE ---
import pandas as pd
import numpy as np

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- IMPORT DU MOTEUR DE STOCKAGE ---
from storage_engine import db

# --- 1. CONFIGURATION ---
ADMIN_PIN = "BOSS_V5"
DATA_DIR = "data_store"

# Création des dossiers critiques
os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists("static"): os.makedirs("static")
if not os.path.exists("templates"): os.makedirs("templates")

# Tentative d'import du moteur Cortex (IA)
try:
    from cortex_engine import cortex
    CORTEX_AVAILABLE = True
except ImportError:
    cortex = None
    CORTEX_AVAILABLE = False

app = FastAPI(title="ENERGISTRAT V7.4", version="AGGREGATION")

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montage des fichiers statiques
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates" if os.path.exists("templates") else ".")

# --- 2. MOTEUR DE CALCUL PANDAS ROBUSTE (V7.2) ---
def process_real_file(content: bytes, filename: str):
    """
    Lit un fichier binaire (Excel/CSV), nettoie les données et calcule les KPIs énergétiques.
    Exclut les zéros pour le calcul du Talon.
    """
    try:
        df = None
        if filename.endswith('.csv'):
            try: df = pd.read_csv(io.BytesIO(content), sep=';', parse_dates=True)
            except: df = pd.read_csv(io.BytesIO(content), sep=',', parse_dates=True)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(content))
        
        if df is None: raise ValueError("Format non supporté")

        # Normalisation
        df.columns = [c.lower().strip() for c in df.columns]
        date_col = next((c for c in df.columns if 'date' in c or 'horodate' in c or 'time' in c), df.columns[0])
        val_col = next((c for c in df.columns if 'puissance' in c or 'p(kw)' in c or 'val' in c or 'conso' in c), df.columns[1])

        # Nettoyage
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col, val_col]).sort_values(by=date_col)
        
        if df[val_col].dtype == object: 
            df[val_col] = df[val_col].astype(str).str.replace(',', '.').astype(float)
        
        # Remplacement NaN par 0
        df[val_col] = df[val_col].fillna(0)

        dates = df[date_col].dt.strftime('%Y-%m-%d %H:%M').tolist()
        values = df[val_col].tolist()
        
        # --- CALCULS MÉTIERS ---
        
        # 1. Talon (Baseload) : On ignore les zéros (coupures)
        positive_values = [v for v in values if v > 0]
        if positive_values:
            talon = float(np.percentile(positive_values, 10))
        else:
            talon = 0.0

        average_val = float(np.mean(values))
        average_curve = [average_val] * len(values)
        
        # 2. Ratio Inactivité
        df['weekday'] = df[date_col].dt.weekday
        week_data = df[df['weekday'] < 5][val_col]
        weekend_data = df[df['weekday'] >= 5][val_col]
        
        avg_week = week_data[week_data > 0].mean() if not week_data.empty else 1
        avg_weekend = weekend_data[weekend_data > 0].mean() if not weekend_data.empty else 0
        
        if pd.isna(avg_week) or avg_week == 0: inactivity_ratio = 0
        else: inactivity_ratio = int((avg_weekend / avg_week) * 100)

        # 3. Diagnostic
        diag = "Profil Standard."
        status = "OK"
        p_max = float(max(values))
        
        if inactivity_ratio > 70: 
            diag, status = "ALERTE : Forte consommation Weekend.", "WARNING"
        elif talon > (p_max * 0.5): 
            diag, status = "ALERTE : Talon élevé (>50% Pmax).", "WARNING"

        return {
            "dates": dates,
            "values": values,
            "average": average_curve,
            "kpi": {
                "conso_totale": int(sum(values)),
                "p_max": p_max,
                "talon": int(talon),
                "inactivity_ratio": inactivity_ratio,
                "diagnosis": diag,
                "status": status,
                "points_traites": len(values)
            }
        }
    except Exception as e:
        print(f"Erreur Maths: {e}")
        raise e

# --- 3. API OPS : ANALYSE & STOCKAGE ---
@app.post("/api/ops/analyze")
async def api_analyze(
    file: UploadFile = File(...), 
    target: str = Form("demo"), 
    site_name: str = Form("Site_Principal"), 
    x_admin_token: str = Header(None)
):
    if x_admin_token != ADMIN_PIN: return JSONResponse({"success": False, "error": "PIN Incorrect"}, 401)
    
    try:
        content = await file.read()
        token = secrets.token_urlsafe(6)
        ext = file.filename.split('.')[-1].lower()
        final_data = {}
        
        # BRANCHE DONNÉES (CSV/EXCEL)
        if ext in ['csv', 'xls', 'xlsx']:
            analysis = process_real_file(content, file.filename)
            final_data = {
                "success": True,
                "kpi": analysis['kpi'],
                "chart": { 
                    "labels": analysis['dates'], 
                    "values": analysis['values'], 
                    "average": analysis['average'] 
                },
                "ai_insight": f"Analyse V7.4 : {analysis['kpi']['points_traites']} points traités.",
                "retail_data": None
            }
        # BRANCHE PDF (CORTEX)
        else:
            if CORTEX_AVAILABLE: 
                final_data = await cortex.analyze_file(content, file.filename, target_profile=target)
            else: 
                raise HTTPException(400, "Format non supporté.")

        # Enrichissement Meta
        final_data["meta"] = {
            "client_group": target,
            "site": site_name,
            "original_filename": file.filename,
            "token": token,
            "ingestion_date": datetime.now().isoformat()
        }

        # --- SAUVEGARDE VIA STORAGE ENGINE ---
        saved_path, entry_log = db.save_analysis(target, site_name, final_data)
        phys_filename = os.path.basename(saved_path)

        return JSONResponse({
            "success": True,
            "filename": phys_filename,
            "token": token,
            "secure_link": f"/dashboard/{target}?file={phys_filename}&token={token}",
            "kpi": final_data['kpi'],
            "chart": final_data['chart'],
            "ai_insight": final_data.get('ai_insight'),
            "storage_log": f"Stocké dans {target}/{site_name}"
        })

    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

# --- 4. API OUTILS & STRUCTURE ---

# Liste des clients (Arborescence)
@app.get("/api/ops/structure")
async def get_structure(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({}, 401)
    return JSONResponse(db.get_client_structure())

# --- NOUVEAUTÉ V7.4 : ROUTE D'AGRÉGATION ---
@app.get("/api/ops/aggregate/{client}")
async def aggregate_client(client: str, x_admin_token: str = Header(None)):
    """
    Calcule les totaux pour un groupe client donné via le Storage Engine.
    """
    if x_admin_token != ADMIN_PIN: return JSONResponse({"error": "Unauthorized"}, 401)
    return JSONResponse(db.aggregate_client_data(client))

# Endpoint Sécurisé (Vault)
@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    # Recherche récursive dans le data_store
    found_path = None
    for root, dirs, files in os.walk("data_store"):
        if filename in files:
            found_path = os.path.join(root, filename)
            break
            
    if not found_path or token not in filename: raise HTTPException(403)
    return FileResponse(found_path, media_type='application/json')

# Outils Ops (Audit, Chaos, Chat)
@app.post("/api/ops/audit")
async def audit_ep(invoice: UploadFile = File(...), contract: UploadFile = File(...), x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN: return JSONResponse({}, 401)
    if not CORTEX_AVAILABLE: 
        return JSONResponse({"score": 75, "status": "OPTIMISABLE", "checks": []})
    return JSONResponse(cortex.analyze_invoice_real(await invoice.read(), await contract.read()))

@app.post("/api/ops/chaos")
async def chaos_ep(x_admin_token: str = Header(None)):
    return JSONResponse({"results": cortex.run_chaos_monkey() if CORTEX_AVAILABLE else []})

@app.post("/api/ops/chat")
async def chat_ep(message: str = Form(...), x_admin_token: str = Header(None)):
    return JSONResponse({"response": cortex.ask_agent(message) if CORTEX_AVAILABLE else message})

# --- 5. NAVIGATION ROBUSTE ---

@app.get("/ops")
@app.get("/ops.html")
async def r_ops(request: Request):
    if os.path.exists("ops.html"): return FileResponse("ops.html")
    if os.path.exists("templates/ops.html"): return templates.TemplateResponse("ops.html", {"request": request})
    return HTMLResponse("<h1>Ops Not Found</h1>", 404)

@app.get("/")
@app.get("/index.html")
async def r_idx(request: Request):
    if os.path.exists("templates/index.html"): return templates.TemplateResponse("index.html", {"request": request})
    if os.path.exists("index.html"): return FileResponse("index.html")
    return await r_ops(request)

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if os.path.isfile(path_name): return FileResponse(path_name)
    target = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"templates/{target}"): return templates.TemplateResponse(target, {"request": request})
    return HTMLResponse("404", 404)
