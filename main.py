# main.py V6.6 - REAL DATA ENGINE + ROUTING FIX (FINAL)
import os
import json
import secrets
import logging
from datetime import datetime
import io

# --- DATA SCIENCE CORE (Moteur Réel) ---
import pandas as pd
import numpy as np

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- 1. CONFIGURATION ---
ADMIN_PIN = "BOSS_V5"
DATA_DIR = "data_store"

# Création des dossiers nécessaires
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

app = FastAPI(title="ENERGISTRAT V6.6", version="REAL DATA & ROUTING")

# Middleware CORS (Autorise tout pour le MVP)
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

# --- 2. HELPER : ANALYSEUR DE FICHIER RÉEL (PANDAS) ---
def process_real_file(content: bytes, filename: str):
    """
    Lit un fichier binaire (Excel/CSV), nettoie les données et calcule les KPIs énergétiques.
    """
    try:
        df = None
        # Détection du format
        if filename.endswith('.csv'):
            try: df = pd.read_csv(io.BytesIO(content), sep=';', parse_dates=True)
            except: df = pd.read_csv(io.BytesIO(content), sep=',', parse_dates=True)
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(content))
        
        if df is None: raise ValueError("Format de fichier non supporté (CSV ou Excel requis)")

        # Normalisation des noms de colonnes (minuscule, sans espace)
        df.columns = [c.lower().strip() for c in df.columns]
        
        # Recherche intelligente des colonnes Date et Puissance
        date_col = next((c for c in df.columns if 'date' in c or 'horodate' in c or 'time' in c), None)
        val_col = next((c for c in df.columns if 'puissance' in c or 'p(kw)' in c or 'val' in c or 'conso' in c), None)

        # Fallback si colonnes non trouvées par nom : on prend la 1ère et 2ème
        if not date_col: date_col = df.columns[0]
        if not val_col: val_col = df.columns[1]

        # Nettoyage des données
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col, val_col]).sort_values(by=date_col)
        
        # Gestion des virgules (ex: "12,5" -> 12.5)
        if df[val_col].dtype == object:
             df[val_col] = df[val_col].astype(str).str.replace(',', '.').astype(float)

        # Extraction des listes pour le Frontend
        dates = df[date_col].dt.strftime('%Y-%m-%d %H:%M').tolist()
        values = df[val_col].fillna(0).tolist()
        
        if not values: raise ValueError("Fichier vide ou illisible")

        # --- CALCULS MÉTIERS (KPIs) ---
        
        # 1. Talon (Baseload) : On prend le 10ème centile
        talon = float(np.percentile(values, 10))
        
        # 2. Moyenne
        average_val = float(np.mean(values))
        average_curve = [average_val] * len(values)
        
        # 3. Ratio Inactivité (Weekend vs Semaine)
        df['weekday'] = df[date_col].dt.weekday # 0=Lundi, 6=Dimanche
        week_data = df[df['weekday'] < 5][val_col]
        weekend_data = df[df['weekday'] >= 5][val_col]
        
        avg_week = week_data.mean() if not week_data.empty else 1
        avg_weekend = weekend_data.mean() if not weekend_data.empty else 0
        inactivity_ratio = int((avg_weekend / avg_week) * 100) if avg_week > 0 else 0

        # 4. Diagnostic Automatique
        diag = "Profil de consommation standard."
        status = "OK"
        p_max = float(max(values))
        
        if inactivity_ratio > 75:
            diag = "ALERTE : Forte consommation le Weekend (>75% semaine). Vérifier GTC/Chauffage."
            status = "WARNING"
        elif talon > (p_max * 0.6):
            diag = "ALERTE : Talon très élevé (>60% Pmax). Optimisation possible."
            status = "WARNING"
        elif inactivity_ratio < 20:
            diag = "EXCELLENT : Très bonne gestion de l'intermittence."
            status = "OPTIMIZED"

        return {
            "dates": dates,
            "values": values,
            "average": average_curve,
            "kpi": {
                "conso_totale": int(sum(values)), # Somme des points (Attention à l'unité de temps)
                "p_max": p_max,
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

# --- 3. API OPS (UPLOAD & ANALYSE) ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), x_admin_token: str = Header(None)):
    # Vérification PIN
    if x_admin_token != ADMIN_PIN: 
        return JSONResponse({"success": False, "error": "PIN Incorrect"}, status_code=401)

    try:
        content = await file.read()
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6)
        json_filename = f"{target}_{timestamp}_{secure_token}.json"
        
        # Détection extension
        ext = file.filename.split('.')[-1].lower()
        final_data = {}
        
        # BRANCHE 1 : FICHIER DATA (CSV/EXCEL) -> Moteur Pandas
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
                "ai_insight": f"Analyse Réelle : {analysis['kpi']['points_traites']} points traités. {analysis['kpi']['diagnosis']}",
                "retail_data": None # On désactive le mock retail pour afficher la vraie donnée
            }
        
        # BRANCHE 2 : FICHIER PDF -> Moteur Cortex (si dispo)
        else:
            if CORTEX_AVAILABLE: 
                final_data = await cortex.analyze_file(content, file.filename, target_profile=target)
            else: 
                raise HTTPException(400, "Format non supporté sans Cortex. Utilisez CSV ou Excel.")

        # Ajout des Métadonnées
        final_data["meta"] = {
            "profile": target, 
            "filename": json_filename, 
            "token": secure_token, 
            "date": timestamp
        }

        # Sauvegarde sur disque
        with open(os.path.join(DATA_DIR, json_filename), "w") as f:
            json.dump(final_data, f)
            
        # Réponse au Frontend Ops
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

# --- 4. API COFFRE-FORT & OUTILS ---

@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    path = os.path.join(DATA_DIR, os.path.basename(filename))
    if not os.path.exists(path) or token not in filename: 
        raise HTTPException(403, "Accès Refusé")
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
# 5. NAVIGATION ROBUSTE (CORRECTION 404)
# ---------------------------------------------------------

# Route explicite pour OPS (Règle le problème du lien depuis Index)
@app.get("/ops")
@app.get("/ops.html")
async def r_ops(request: Request):
    if os.path.exists("ops.html"): return FileResponse("ops.html")
    if os.path.exists("templates/ops.html"): return templates.TemplateResponse("ops.html", {"request": request})
    return HTMLResponse("<h1>Ops Dashboard Not Found - Check Deployment</h1>", 404)

# Route explicite pour INDEX
@app.get("/")
@app.get("/index.html")
async def r_idx(request: Request):
    if os.path.exists("templates/index.html"): return templates.TemplateResponse("index.html", {"request": request})
    if os.path.exists("index.html"): return FileResponse("index.html")
    # Si pas d'index, on redirige vers Ops
    return await r_ops(request)

# Catch-All pour les autres pages (Vitrine, Dashboards Clients)
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    # Fichier statique racine (ex: style.css)
    if os.path.isfile(path_name): return FileResponse(path_name)
    
    # Template HTML (avec ou sans extension .html)
    target = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"templates/{target}"):
        return templates.TemplateResponse(target, {"request": request})
    
    return HTMLResponse(f"<h1>404 - Page {path_name} Introuvable</h1>", 404)
