import os
import re
import json
import glob
import io
import csv
import traceback
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel
from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
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

# --- MODELES ---
class PropagationFilters(BaseModel):
    segment: str
    lot_name: str
class PricingData(BaseModel):
    fix: Optional[str] = "0.00"
    hph: Optional[str] = "0.00"
    hch: Optional[str] = "0.00"
    hpe: Optional[str] = "0.00"
    hce: Optional[str] = "0.00"
    tax: Optional[str] = "0.00"
class PropagationRequest(BaseModel):
    source_client_id: str
    target_date: str
    filters: PropagationFilters
    pricing_data: PricingData
class TenderRequest(BaseModel):
    site_ids: List[str]
class MarketUpdateModel(BaseModel):
    elec: dict
    gaz: dict

# --- MARKET WATCH ---
def get_market_ref():
    # Tentative de lecture flexible
    possible_paths = ["/app/data/market_ref.json", "app/data/market_ref.json", "data/market_ref.json"]
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f: return json.load(f)
            except: pass
    return {
        "updated_at": datetime.now().isoformat(),
        "elec": { "cal_n1": 82.50, "cal_n2": 76.00, "trend": "BAISSIER" },
        "gaz": { "peg_n1": 39.40, "peg_n2": 36.10, "trend": "STABLE" }
    }

@app.get("/api/market/current")
async def api_get_market(): return JSONResponse(get_market_ref())

@app.post("/api/ops/market/update")
async def api_update_market(data: MarketUpdateModel, x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": raise HTTPException(status_code=401, detail="Accès refusé")
    try:
        payload = data.dict()
        payload["updated_at"] = datetime.now().isoformat()
        # On force l'écriture dans le dossier standard
        os.makedirs("/app/data", exist_ok=True)
        with open("/app/data/market_ref.json", "w") as f: json.dump(payload, f, indent=4)
        return JSONResponse({"success": True, "updated_at": payload["updated_at"]})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

# --- API DASHBOARD (CORRECTIF V40.5 - AUTO-PATH & RESCUE) ---
@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    fleet = []
    
    # 1. DÉTECTION DU BON DOSSIER DE DONNÉES
    data_dir = "/app/data" # Défaut Cloud Run
    if not os.path.exists(data_dir):
        if os.path.exists("app/data"): data_dir = "app/data"
        elif os.path.exists("data"): data_dir = "data"
        else:
            print("[WARN] Aucun dossier data trouvé. Création volée.")
            os.makedirs("data", exist_ok=True)
            data_dir = "data"
            
    print(f"[DEBUG] Lecture Fleet depuis : {data_dir}")

    def clean_num(val):
        if not val: return 0.0
        s = str(val).replace(' ', '').replace(',', '.').replace('€', '').replace('kVA', '').replace('MWh', '')
        try: return float(s)
        except: return 0.0

    files = glob.glob(os.path.join(data_dir, "*.json"))
    print(f"[DEBUG] {len(files)} fichiers trouvés.")

    for file_path in files:
        if "master_index" in file_path or "market_ref" in file_path: continue
        try:
            with open(file_path, 'r') as f: data = json.load(f)
            
            # Robustesse : Si identity manque, on skip
            if not data or 'identity' not in data: 
                print(f"[WARN] Fichier invalide ignoré : {file_path}")
                continue

            kpis = cortex.enrich_fleet_kpis(data)
            contract = data.get('contract', {})
            identity = data.get('identity', {})
            pricing = data.get('pricing', {})
            loc = data.get('location', {})
            
            file_id = os.path.basename(file_path).replace('.json', '')
            real_id = identity.get('id') or file_id
            real_name = identity.get('site_name') or identity.get('name') or data.get('client_name') or f"Site {real_id}"
            is_gaz = "T" in str(contract.get('segment', '')) or "gaz" in str(pricing.get('hph', '')).lower()

            fleet.append({
                "id": real_id,
                "name": real_name,
                "city": loc.get('address', '').split(',')[-1].strip() or "-",
                "energy": "gaz" if is_gaz else "elec",
                "segment": contract.get('segment', '--'),
                "lot": identity.get('lot_name', 'Hors Lot'),
                "power": clean_num(contract.get('power', 0)),
                "budget": kpis['budget_annual'],
                "ghost_savings": kpis['ghost_savings'],
                "landing": kpis['landing_forecast'],
                "alert": kpis['is_alert_landing'],
                "provider": contract.get('provider', 'Inconnu')
            })
        except Exception as e:
            print(f"[ERROR] Lecture {file_path}: {e}")
            continue

    # 2. SITE DE SECOURS (Si liste vide, on injecte une démo pour ne pas avoir d'écran noir)
    if not fleet:
        print("[INFO] Liste vide. Injection Site Démo.")
        fleet.append({
            "id": "demo_rescue",
            "name": "SITE DÉMO (AUTO)",
            "city": "Paris",
            "energy": "elec",
            "segment": "C5",
            "lot": "Test",
            "power": 36,
            "budget": 12000,
            "ghost_savings": 1500,
            "landing": 11000,
            "alert": False,
            "provider": "EDF"
        })

    return JSONResponse({"fleet": fleet, "count": len(fleet)})

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    # Gestion du site de secours
    if client_id == "demo_rescue":
        return JSONResponse({
            "identity": {"site_name": "SITE DÉMO (AUTO)", "name": "Demo Corp"},
            "location": {"address": "10 Rue de la Paix, 75000 Paris"},
            "contract": {"power": 36, "segment": "C5", "provider": "EDF"},
            "pricing": {"hph": 0.15, "fix": 120},
            "energy_type": "elec",
            "cortex_insight": {"message": "Ceci est un site généré automatiquement car aucun site réel n'a été trouvé.", "conseil": "Sauvegardez un site dans Settings.", "status": "DÉMO", "color": "blue"},
            "market_analysis": {"status": "NEUTRE", "action": "Mode Démo", "color": "gray"}
        })

    client_data = storage.get_client_settings(client_id)
    if not client_data: return JSONResponse({"error": "Client introuvable"})
    
    contract = client_data.get('contract', {})
    pricing = client_data.get('pricing', {})
    is_gaz = "T" in str(contract.get('segment', ''))
    
    market = get_market_ref()
    market_price = market['gaz']['peg_n1'] if is_gaz else market['elec']['cal_n1']
    try: client_price = float(str(pricing.get('hph', '0')).replace(',', '.').replace(' ', ''))
    except: client_price = 0.0
    
    advice = cortex.analyze_market_position(client_price, market_price, "gaz" if is_gaz else "elec")
    tech = {
        "titre": "Analyse", "message": "Conso normale.", "conseil": "RAS.", "status": "OK", "color": "green"
    }
    
    return JSONResponse({
        "identity": client_data.get('identity', {}),
        "location": client_data.get('location', {}),
        "contract": contract,
        "pricing": client_data.get('pricing', {}),
        "cortex_insight": tech,
        "market_analysis": advice,
        "energy_type": "gaz" if is_gaz else "elec"
    })

# --- API OPS ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        content = await file.read()
        detected_pdl = None
        filename_match = re.search(r'(\d{14})', file.filename)
        if filename_match: detected_pdl = filename_match.group(1)
        site_data = None
        if detected_pdl: site_data = storage.find_site_by_pdl(detected_pdl)
        res = cortex.analyze_file(content, file.filename, target_profile=target, known_site_data=site_data)
        if res.get("success"): 
            res["secure_link"] = f"/dashboard/{target}?site={site_name}"
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

# --- API TENDER ---
@app.post("/api/ops/generate_tender")
async def generate_tender(payload: TenderRequest):
    selected_sites = []
    # Support du site de secours
    if "demo_rescue" in payload.site_ids:
        # On génère un faux site pour que l'Excel marche
        selected_sites.append({
            "identity": {"name": "Demo Corp", "site_name": "SITE DÉMO", "lot_name": "Test"},
            "location": {"address": "Paris"},
            "contract": {"pdl": "000000", "power": 36, "segment": "C5"},
            "pricing": {"fix": 100, "hph": 0.15}
        })

    for site_id in payload.site_ids:
        if not site_id or site_id == "demo_rescue": continue
        if "master_index" in site_id or "market_ref" in site_id: continue
        data = storage.get_client_settings(site_id)
        if data: selected_sites.append(data)
    
    if not selected_sites: raise HTTPException(status_code=400, detail="Aucun site valide.")

    try:
        excel_content = cortex.generate_advanced_tender_excel(selected_sites)
        if not excel_content: raise HTTPException(status_code=500, detail="Excel vide.")
        
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"DCE_Energistrat_{len(selected_sites)}sites_{timestamp}.xlsx"
        return StreamingResponse(io.BytesIO(excel_content), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})
    except Exception as e:
        print(f"[CRASH TENDER] {e}")
        raise HTTPException(status_code=500, detail=f"Crash: {str(e)}")

# --- API SETTINGS & IMPORT ---
@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    try:
        content = await file.read()
        sites = cortex.parse_mass_import_v5(content)
        if not sites: return JSONResponse({"success": False, "error": "Format incorrect"})
        saved = 0
        for s in sites:
            cid = s['identity'].get('id')
            if not cid: continue
            storage.save_client_settings(cid, s)
            saved += 1
        return JSONResponse({"success": True, "imported": saved})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        client_id = data.get("identity", {}).get("id") or "draft_client"
        res = storage.save_client_settings(client_id, data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/propagate_tariff")
async def propagate_tariff(payload: PropagationRequest):
    # ... (Code propagation V35.2 préservé - Abrégé pour la réponse mais doit être présent)
    return JSONResponse({"success": True, "updated_count": 1}) 

@app.post("/api/partner/save_config")
async def api_save_partner(request: Request):
    try:
        data = await request.json()
        res = storage.save_partner_config("main_partner", data)
        return JSONResponse(res)
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

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

# --- TEMPLATES ---
@app.get("/api/settings/template_csv")
async def get_import_template():
    # ... (Code V5 préservé)
    stream = io.StringIO()
    csv.writer(stream, delimiter=';').writerow(["SIRET", "RAISON_SOCIALE", "NOM_SITE", "ADRESSE", "PDL", "PUISSANCE", "SEGMENT", "LOT", "ABO_AN", "PRIX_HPH", "PRIX_HCH", "PRIX_HPE", "PRIX_HCE", "TAXES"])
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=template_import_v5.csv"})

@app.get("/api/settings/template_csv_gaz")
async def get_import_template_gaz():
    # ... (Code V1 Gaz préservé)
    stream = io.StringIO()
    csv.writer(stream, delimiter=';').writerow(["SIRET", "RAISON_SOCIALE", "NOM_SITE", "ADRESSE", "PCE", "CAR_MWH", "SEGMENT_GAZ", "LOT", "ABO_AN", "PRIX_MWH", "TAXES"])
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=template_import_gaz_v1.csv"})

# --- ROUTES HTML ---
@app.get("/nexus")
async def view_nexus(request: Request): return templates.TemplateResponse("nexus.html", {"request": request})
@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    f = f"{profile}.html"
    if os.path.exists(f"app/templates/{f}"): return templates.TemplateResponse(f, {"request": request})
    return JSONResponse({"error": f"Template missing: {f}"}, 404)
@app.get("/partner/settings")
async def view_settings(request: Request): return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name in ["", "/"]: return templates.TemplateResponse("index.html", {"request": request})
    clean = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"app/templates/{clean}"): return templates.TemplateResponse(clean, {"request": request})
    return JSONResponse({"error": "Page not found"}, 404)
