import os
import re
import json
import glob
import io
import csv
import traceback # AJOUT POUR DEBUG
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

# --- MODELES DE DONNEES ---
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
    path = "/app/data/market_ref.json"
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
        with open("/app/data/market_ref.json", "w") as f: json.dump(payload, f, indent=4)
        return JSONResponse({"success": True, "updated_at": payload["updated_at"]})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

# --- API DASHBOARD / FLEET (CORRECTIF V40.3 - FILTRAGE FANTOMES) ---
@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    DATA_DIR = "/app/data"
    fleet = []
    
    def clean_num(val):
        if not val: return 0.0
        s = str(val).replace(' ', '').replace(',', '.').replace('€', '').replace('kVA', '').replace('MWh', '')
        try: return float(s)
        except: return 0.0

    try:
        files = glob.glob(os.path.join(DATA_DIR, "*.json"))
        for file_path in files:
            # FILTRE 1 : Ignorer les fichiers système ou temporaires
            filename = os.path.basename(file_path)
            if "master_index" in filename or "market_ref" in filename: continue

            try:
                with open(file_path, 'r') as f: data = json.load(f)
                
                # FILTRE 2 : Ignorer les fichiers vides/corrompus
                if not data or 'identity' not in data: continue

                kpis = cortex.enrich_fleet_kpis(data)
                contract = data.get('contract', {})
                identity = data.get('identity', {})
                pricing = data.get('pricing', {})
                loc = data.get('location', {})
                
                file_id = filename.replace('.json', '')
                real_id = identity.get('id') or file_id
                real_name = identity.get('site_name') or identity.get('name') or data.get('client_name') or f"Site {real_id}"

                is_gaz = "T" in str(contract.get('segment', '')) or "gaz" in str(pricing.get('hph', '')).lower()
                power = clean_num(contract.get('power', 0))

                fleet.append({
                    "id": real_id,
                    "name": real_name,
                    "city": loc.get('address', '').split(',')[-1].strip() or "-",
                    "energy": "gaz" if is_gaz else "elec",
                    "segment": contract.get('segment', '--'),
                    "lot": identity.get('lot_name', 'Hors Lot'),
                    "power": power,
                    "budget": kpis['budget_annual'],
                    "ghost_savings": kpis['ghost_savings'],
                    "landing": kpis['landing_forecast'],
                    "alert": kpis['is_alert_landing'],
                    "provider": contract.get('provider', 'Inconnu')
                })
            except Exception as e:
                print(f"[WARN] Skipped file {file_path}: {e}")
                continue
        return JSONResponse({"fleet": fleet, "count": len(fleet)})
    except Exception as e: return JSONResponse({"error": str(e)})

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    # Sécurité : Empêcher la lecture des fichiers système
    if "master" in client_id or "market" in client_id: return JSONResponse({"error": "Accès interdit"})

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
    
    tech_insight = {
        "titre": "Analyse Chauffage" if is_gaz else "Surveillance Puissance",
        "message": "Consommation conforme." if is_gaz else f"Optimisation possible.",
        "conseil": "Vérifiez régulations." if is_gaz else "Analysez pics de charge.",
        "status": "NORMAL",
        "color": "green" if is_gaz else "yellow"
    }
    
    response = {
        "identity": client_data.get('identity', {}),
        "location": client_data.get('location', {}),
        "contract": contract,
        "pricing": client_data.get('pricing', {}),
        "cortex_insight": tech_insight,
        "market_analysis": advice,
        "energy_type": "gaz" if is_gaz else "elec"
    }
    return JSONResponse(response)

# --- API OPS ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": return JSONResponse({}, 401)
    try:
        content = await file.read()
        detected_pdl = None
        filename_match = re.search(r'(\d{14})', file.filename)
        if filename_match: detected_pdl = filename_match.group(1)
        if not detected_pdl:
            try:
                content_str = content.decode('latin-1', errors='ignore')[:1000]
                content_match = re.search(r'\b(\d{14})\b', content_str)
                if content_match: detected_pdl = content_match.group(1)
            except: pass
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

# --- API TENDER (GENERATION EXCEL V40.3 - DEBUG) ---
@app.post("/api/ops/generate_tender")
async def generate_tender(payload: TenderRequest):
    """
    Génère le DCE Excel. Avec LOGS D'ERREUR PRÉCIS.
    """
    print(f"[TENDER] Reçu demande pour {len(payload.site_ids)} sites: {payload.site_ids}")
    
    selected_sites = []
    for site_id in payload.site_ids:
        if not site_id: continue
        # Ignore le site master_index s'il est sélectionné par erreur
        if "master_index" in site_id: continue
        
        data = storage.get_client_settings(site_id)
        if data: selected_sites.append(data)
    
    if not selected_sites:
        print("[TENDER] Aucun site valide trouvé après filtrage.")
        raise HTTPException(status_code=400, detail="Aucun site valide sélectionné (ou site fantôme ignoré).")

    try:
        # APPEL CORTEX
        excel_content = cortex.generate_advanced_tender_excel(selected_sites)
        
        if not excel_content or len(excel_content) == 0:
            print("[TENDER] Cortex a renvoyé un contenu vide.")
            raise HTTPException(status_code=500, detail="Erreur Interne : Génération Excel vide. Vérifiez 'openpyxl'.")
        
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"DCE_Energistrat_{len(selected_sites)}sites_{timestamp}.xlsx"

        print(f"[TENDER] Succès. Taille fichier: {len(excel_content)} bytes.")
        
        return StreamingResponse(
            io.BytesIO(excel_content), 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        error_msg = f"Crash Moteur : {str(e)} | Trace: {traceback.format_exc()}"
        print(f"[TENDER ERROR] {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)

# --- API SETTINGS & IMPORT ---
@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    try:
        content = await file.read()
        sites = cortex.parse_mass_import_v5(content)
        if not sites: return JSONResponse({"success": False, "error": "Format incorrect ou fichier vide"})
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
    DATA_DIR = "/app/data"
    updated_count = 0
    errors = []
    source_path = os.path.join(DATA_DIR, f"{payload.source_client_id}.json")
    if not os.path.exists(source_path):
        found = glob.glob(os.path.join(DATA_DIR, f"*{payload.source_client_id}*.json"))
        if found: source_path = found[0]
        else: raise HTTPException(status_code=404, detail="Site source introuvable")
    try:
        with open(source_path, 'r') as f:
            source_data = json.load(f)
            scope_siren = source_data.get('identity', {}).get('siret', '')[:9] 
    except Exception as e: raise HTTPException(status_code=500, detail=f"Erreur lecture source: {str(e)}")
    if not scope_siren or len(scope_siren) < 9: raise HTTPException(status_code=400, detail="Impossible de définir le périmètre (SIREN source invalide)")
    all_files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for file_path in all_files:
        try:
            if file_path == source_path: continue
            with open(file_path, 'r') as f: client = json.load(f)
            client_siret = client.get('identity', {}).get('siret', '')
            if not client_siret.startswith(scope_siren): continue 
            client_segment = client.get('contract', {}).get('segment', '--')
            if client_segment != payload.filters.segment: continue
            client_lot = client.get('identity', {}).get('lot_name', '')
            if client_lot != payload.filters.lot_name: continue
            if 'tariff_history' not in client: client['tariff_history'] = []
            current_pricing = client.get('pricing', {})
            if current_pricing and (current_pricing.get('hph') or current_pricing.get('fix')):
                history_entry = { "archived_at": datetime.now().isoformat(), "end_date": payload.target_date, "pricing": current_pricing, "provider": client.get('contract', {}).get('provider', 'Unknown') }
                client['tariff_history'].append(history_entry)
            client['pricing'] = payload.pricing_data.dict()
            client['last_update'] = datetime.now().isoformat()
            client['sync_status'] = "PROPAGATED"
            with open(file_path, 'w') as f: json.dump(client, f, indent=4)
            updated_count += 1
        except Exception as e:
            print(f"[ERROR] Failed to propagate to {file_path}: {e}")
            errors.append(str(e))
            continue
    return {"success": True, "source_siren": scope_siren, "scanned": len(all_files), "updated_count": updated_count, "errors": errors}

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

# --- TEMPLATES CSV ---
@app.get("/api/settings/template_csv")
async def get_import_template():
    headers = [ "SIRET", "RAISON_SOCIALE", "NOM_SITE", "ADRESSE", "PDL", "PUISSANCE", "SEGMENT", "LOT", "ABO_AN", "PRIX_HPH", "PRIX_HCH", "PRIX_HPE", "PRIX_HCE", "TAXES" ]
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(headers)
    writer.writerow([ "12345678900012", "Mon Entreprise", "Site Principal", "10 Rue de la Paix 75000 Paris", "30000000000000", "36", "C5", "Lot 1", "150.00", "0.15", "0.10", "0.08", "0.04", "22.5" ])
    stream.seek(0)
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=template_import_v5.csv"
    return response

@app.get("/api/settings/template_csv_gaz")
async def get_import_template_gaz():
    headers = [ "SIRET", "RAISON_SOCIALE", "NOM_SITE", "ADRESSE", "PCE", "CAR_MWH", "SEGMENT_GAZ", "LOT", "ABO_AN", "PRIX_MWH", "TAXES" ]
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(headers)
    writer.writerow([ "12345678900012", "Mon Entreprise", "Chaufferie Bât A", "10 Rue de la Paix", "04500000000000", "150", "T2", "Lot Chauffage", "250.00", "45.50", "8.44" ])
    stream.seek(0)
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=template_import_gaz_v1.csv"
    return response

# --- ROUTES HTML (VUES) ---
@app.get("/nexus")
async def view_nexus(request: Request): return templates.TemplateResponse("nexus.html", {"request": request})
@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    f = f"{profile}.html"
    if os.path.exists(f"app/templates/{f}"): return templates.TemplateResponse(f, {"request": request})
    if os.path.exists("app/templates/dashboard.html"): return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})
    return JSONResponse({"error": f"Template missing: {f}"}, 404)
@app.get("/partner/settings")
async def view_settings(request: Request): return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name in ["", "/"]: return templates.TemplateResponse("index.html", {"request": request})
    clean = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"app/templates/{clean}"): return templates.TemplateResponse(clean, {"request": request})
    return JSONResponse({"error": "Page not found"}, 404)
