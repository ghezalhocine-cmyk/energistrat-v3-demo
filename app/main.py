import os
import re
import json
import glob
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
# IMPORT DES MOTEURS
from app.core.cortex_engine import cortex
from app.core.storage_engine import storage 

app = FastAPI(title="ENERGISTRAT V3", version="PROD")

# CONFIGURATION
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
if os.path.exists("static"): app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/health")
async def health_check(): return {"status": "ONLINE", "cortex": cortex.version, "storage": storage.version}

# --- MODELES DE DONNEES (PROPAGATION TARIFAIRE V35.2 - 4 POSTES) ---
class PropagationFilters(BaseModel):
    segment: str
    lot_name: str

class PricingData(BaseModel):
    fix: Optional[str] = "0.00"
    hph: Optional[str] = "0.00" # Hiver Pleines
    hch: Optional[str] = "0.00" # Hiver Creuses
    hpe: Optional[str] = "0.00" # ETE PLEINES (AJOUTÉ POUR V22.8)
    hce: Optional[str] = "0.00" # ETE Creuses
    tax: Optional[str] = "0.00"

class PropagationRequest(BaseModel):
    source_client_id: str
    target_date: str
    filters: PropagationFilters
    pricing_data: PricingData

# --- API OPS (ADMIN & ANALYSE - SMART SCAN V19.2) ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        content = await file.read()
        
        # 1. SCAN DU PDL (LOGIQUE EXISTANTE PRÉSERVÉE)
        detected_pdl = None
        
        # A. On cherche D'ABORD dans le nom du fichier (Ex: ..._30000930316907.csv)
        filename_match = re.search(r'(\d{14})', file.filename)
        if filename_match:
            detected_pdl = filename_match.group(1)
            print(f"[SCAN] PDL trouvé dans le nom de fichier : {detected_pdl}")
        
        # B. Sinon, on cherche dans le contenu (Entête)
        if not detected_pdl:
            try:
                content_str = content.decode('latin-1', errors='ignore')[:1000]
                content_match = re.search(r'\b(\d{14})\b', content_str)
                if content_match: detected_pdl = content_match.group(1)
            except: pass

        # 2. RECONCILIATION
        site_data = None
        if detected_pdl:
            site_data = storage.find_site_by_pdl(detected_pdl)
            if site_data:
                print(f"[RECONCILIATION] SUCCÈS : {site_data.get('client_name')} lié au PDL {detected_pdl}")
            else:
                print(f"[RECONCILIATION] ÉCHEC : Le PDL {detected_pdl} est inconnu dans Settings.")

        # 3. APPEL CORTEX
        res = cortex.analyze_file(content, file.filename, target_profile=target, known_site_data=site_data)
        
        if res.get("success"): 
            res["secure_link"] = f"/dashboard/{target}?site={site_name}"
            # Flag pour le frontend
            if site_data: res["reconciled"] = True
            
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/audit")
async def api_audit(invoice: UploadFile = File(...), contract: UploadFile = File(None), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        inv = await invoice.read()
        ctr = await contract.read() if contract else None
        return JSONResponse(cortex.analyze_invoice_real(inv, ctr))
    except Exception as e: return JSONResponse({"score": 0, "checks": [], "error": str(e)})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    return JSONResponse({"response": cortex.ask_agent(message)})

@app.post("/api/ops/chaos")
async def api_chaos(x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    return JSONResponse(cortex.run_chaos_monkey())

# --- API TICKETING ---
@app.post("/api/support/ticket")
async def create_ticket(request: Request):
    try:
        data = await request.json()
        res = storage.create_ticket(data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/support/tickets")
async def get_tickets():
    tickets = storage.list_tickets()
    return JSONResponse({"tickets": tickets})

# --- API SETTINGS (ERP MASTER) ---
@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        # On utilise le SIRET/RNC comme ID (Logique existante préservée)
        client_id = data.get("identity", {}).get("id") or "draft_client"
        res = storage.save_client_settings(client_id, data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

# --- NOUVEAU : ENDPOINT DE PROPAGATION ---
@app.post("/api/settings/propagate_tariff")
async def propagate_tariff(payload: PropagationRequest):
    """
    Moteur de Propagation Tarifaire Intelligent V35.1.
    Règle : On ne propage que au sein de la même entité (SIREN) et sur le même profil technique (Segment + Lot).
    Feature : Historisation automatique des anciens prix.
    """
    DATA_DIR = "/app/data"
    updated_count = 0
    errors = []

    # 1. CHARGEMENT SOURCE (Pour vérifier le SIREN)
    source_path = os.path.join(DATA_DIR, f"{payload.source_client_id}.json")
    if not os.path.exists(source_path):
        # Fallback : Si l'ID est un SIRET complet, on cherche le fichier correspondant
        found = glob.glob(os.path.join(DATA_DIR, f"*{payload.source_client_id}*.json"))
        if found:
            source_path = found[0]
        else:
            raise HTTPException(status_code=404, detail="Site source introuvable")

    try:
        with open(source_path, 'r') as f:
            source_data = json.load(f)
            # Sécurité : On définit le périmètre de propagation (Les 9 premiers chiffres = SIREN)
            scope_siren = source_data.get('identity', {}).get('siret', '')[:9] 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lecture source: {str(e)}")

    if not scope_siren or len(scope_siren) < 9:
        raise HTTPException(status_code=400, detail="Impossible de définir le périmètre (SIREN source invalide)")

    # 2. SCAN DU PARC (Smart Scan)
    all_files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    
    for file_path in all_files:
        try:
            if file_path == source_path: continue

            with open(file_path, 'r') as f:
                client = json.load(f)

            # --- FILTRES DE SÉCURITÉ ---
            
            # A. Filtre PÉRIMÈTRE (Même Entreprise/Groupe)
            client_siret = client.get('identity', {}).get('siret', '')
            if not client_siret.startswith(scope_siren): continue 

            # B. Filtre TECHNIQUE (Même Segment : C5, C4...)
            client_segment = client.get('contract', {}).get('segment', '--')
            if client_segment != payload.filters.segment: continue

            # C. Filtre MÉTIER (Même Lot : "Lot 1", "Ecoles"...)
            # Gestion safe si le champ n'existe pas encore
            client_lot = client.get('identity', {}).get('lot_name', '')
            if client_lot != payload.filters.lot_name: continue

            # --- APPLICATION & HISTORISATION ---

            # 1. Historiser
            if 'tariff_history' not in client: client['tariff_history'] = []
            
            current_pricing = client.get('pricing', {})
            if current_pricing and (current_pricing.get('hph') or current_pricing.get('fix')):
                history_entry = {
                    "archived_at": datetime.now().isoformat(),
                    "end_date": payload.target_date,
                    "pricing": current_pricing,
                    "provider": client.get('contract', {}).get('provider', 'Unknown')
                }
                client['tariff_history'].append(history_entry)

            # 2. Mettre à jour (Avec support des 4 postes)
            client['pricing'] = payload.pricing_data.dict()
            client['last_update'] = datetime.now().isoformat()
            client['sync_status'] = "PROPAGATED"

            # 3. Sauvegarder
            with open(file_path, 'w') as f:
                json.dump(client, f, indent=4)
            
            updated_count += 1

        except Exception as e:
            print(f"[ERROR] Failed to propagate to {file_path}: {e}")
            errors.append(str(e))
            continue

    return {
        "success": True,
        "source_siren": scope_siren,
        "scanned": len(all_files),
        "updated_count": updated_count,
        "errors": errors
    }

@app.post("/api/partner/save_config")
async def api_save_partner(request: Request):
    try:
        data = await request.json()
        res = storage.save_partner_config("main_partner", data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

# --- PARCOURS CLIENT ---
@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/login/{profile}")
async def view_login(request: Request, profile: str): return templates.TemplateResponse("login.html", {"request": request, "profile": profile})
@app.get("/processing")
async def view_processing(request: Request, target: str = "demo"): return templates.TemplateResponse("processing.html", {"request": request, "target": target})
@app.get("/partner/settings")
async def view_partner_settings(request: Request): return templates.TemplateResponse("settings_partner.html", {"request": request})

@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    f = f"{profile}.html"
    if os.path.exists(f"app/templates/{f}"): return templates.TemplateResponse(f, {"request": request})
    if os.path.exists("app/templates/dashboard.html"): return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})
    return JSONResponse({"error": f"Template missing: {f}"}, 404)

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name in ["", "/"]: return templates.TemplateResponse("index.html", {"request": request})
    clean = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"app/templates/{clean}"): return templates.TemplateResponse(clean, {"request": request})
    return JSONResponse({"error": "Page not found"}, 404)
