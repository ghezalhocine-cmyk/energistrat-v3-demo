import os
import json
import glob
import uuid
import math
import io
import traceback
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, Request, UploadFile, File, Form, Header, HTTPException, Response
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    import pandas as pd
    PANDAS_READY = True
except ImportError:
    PANDAS_READY = False

try:
    from app.core.cortex_ingest import ingest
    from app.core.cortex_engine import cortex
    from app.core.cortex_physics import physics
except ImportError:
    try:
        import cortex_ingest as ingest
        import cortex_engine as cortex
        import cortex_physics as physics
    except: pass

app = FastAPI(title="ENERGISTRAT V3", version="DIAMOND-V1107")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.getcwd()
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR, exist_ok=True)
TEMPLATE_DIR = os.path.join(BASE_DIR, "app/templates")
if not os.path.exists(TEMPLATE_DIR): TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATE_DIR)
STATIC_DIR = os.path.join(BASE_DIR, "static")
if not os.path.exists(STATIC_DIR): STATIC_DIR = os.path.join(BASE_DIR, "app/static")
if os.path.exists(STATIC_DIR): app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class MarketUpdateModel(BaseModel):
    elec: Dict[str, Any]
    gaz: Dict[str, Any]
    trve: Optional[Dict[str, Any]] = None
    targets: Optional[Dict[str, Any]] = None

def json_compliant(data):
    if isinstance(data, dict): return {k: json_compliant(v) for k, v in data.items()}
    elif isinstance(data, list): return [json_compliant(v) for v in data]
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data): return 0.0
    return data

def get_safe_id(raw_id):
    return str(raw_id).replace('/', '_').replace(' ', '_').replace('+', '').replace(',', '').strip()

def find_site_file(target_id):
    safe_target = get_safe_id(target_id)
    direct_path = os.path.join(DATA_DIR, f"{safe_target}.json")
    if os.path.exists(direct_path): return direct_path
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for p in files:
        try:
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stored_id = str(data.get('identity', {}).get('id', ''))
                if get_safe_id(stored_id) == safe_target:
                    return p
        except: continue
    return None

def get_market_ref():
    path = os.path.join(DATA_DIR, "market_ref.json")
    if os.path.exists(path):
        try:
            with open(path, 'r') as f: return json.load(f)
        except: pass
    return {
        "updated_at": datetime.now().isoformat(),
        "elec": { "cal_n1": 85.0 }, "gaz": { "peg_n1": 35.0 },
        "trve": { "elec_c5": 230.0 }, "targets": { "c5": 190.0 }
    }

# --- API ---

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        raw_id = data.get("identity", {}).get("id") or f"CLI_{uuid.uuid4().hex[:8]}"
        data["identity"]["id"] = raw_id
        safe_id = get_safe_id(raw_id)
        file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "id": raw_id})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/update_site")
async def api_update_site(request: Request):
    try:
        payload = await request.json()
        site_id = payload.get('id')
        if not site_id: return JSONResponse({"error": "ID manquant"}, 400)
        file_path = find_site_file(site_id)
        if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
        with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
        
        if 'location' in payload: data['location'] = {**data.get('location', {}), **payload['location']}
        if 'technical' in payload: data['technical'] = {**data.get('technical', {}), **payload['technical']}
        
        with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        return JSONResponse({"success": True, "message": "Sauvegardé"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    try:
        content = await file.read()
        sites = ingest.parse_mass_import_unified(content)
        if not sites: return JSONResponse({"success": False, "error": "Fichier illisible."})
        saved = 0
        for s in sites:
            try:
                raw_id = s.get('identity', {}).get('id') or f"GEN_{uuid.uuid4().hex[:8]}"
                s['identity']['id'] = raw_id
                safe_id = get_safe_id(raw_id)
                file_path = os.path.join(DATA_DIR, f"{safe_id}.json")
                with open(file_path, 'w', encoding='utf-8') as f: json.dump(s, f, indent=4, ensure_ascii=False)
                saved += 1
            except: pass
        return JSONResponse({"success": True, "imported": len(sites), "saved": saved})
    except ValueError as ve: return JSONResponse({"success": False, "error": str(ve)})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/dashboard/fleet")
async def get_fleet_data(response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    raw_sites = []
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for p in files:
        if "master" in p or "market" in p: continue
        try:
            with open(p, 'r', encoding='utf-8') as f: data = json.load(f)
            fin = cortex.enrich_site_financials(data)
            data['computed_financials'] = fin
            raw_sites.append(data)
        except: continue
    analysis = cortex.analyze_portfolio(raw_sites)
    fleet_list = []
    all_cities, all_providers = set(), set()
    for s in raw_sites:
        if "CLI_" in str(s.get('identity',{}).get('id')): continue
        fin = s['computed_financials']
        contract = s.get('contract', {})
        city = fin['meta']['city']
        prov = contract.get('provider', 'Inconnu')
        if city: all_cities.add(city)
        if prov: all_providers.add(prov)
        
        raw_id = s.get('identity',{}).get('id')
        safe_id = get_safe_id(raw_id)
        
        fleet_list.append({
            "id": safe_id,
            "name": fin['meta']['site_label'],
            "city": city,
            "zip": s.get('location', {}).get('zip_code', ''),
            "volume": fin['volume_mwh'],
            "energy": "gaz" if fin['meta']['is_gas'] else "elec",
            "segment": contract.get('segment', '-'),
            "provider": prov,
            "budget": fin['budget_annual'],
            "landing": fin['landing_forecast'],
            "alert": fin['kpis']['pmc_eur_mwh'] > 300,
            "ghost_savings": fin['kpis']['ghost_savings']
        })
    response_data = {
        "fleet": fleet_list, "count": len(fleet_list),
        "green_league": analysis.get('green_league'),
        "global_kpis": analysis.get('global'),
        "filters_meta": { "cities": sorted(list(all_cities)), "providers": sorted(list(all_providers)), "segments": ["C5", "C4", "C3", "C2", "C1", "T1", "T2", "T3"], "lots": ["Lot 1", "Lot 2"] }
    }
    return JSONResponse(json_compliant(response_data))

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str, response: Response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    file_path = find_site_file(client_id)
    if not file_path: return JSONResponse({"error": "Site introuvable"}, 404)
    with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
    
    financials = cortex.enrich_site_financials(data)
    market_ref = get_market_ref()
    
    is_gas = financials['meta']['is_gas']
    market_analysis = cortex.analyze_market_position(
        financials['kpis']['unit_price_kwh'],
        market_ref,
        is_gas
    )
    contract = data.get('contract', {})
    pricing = financials['pricing_details']
    
    display_segment = financials.get('display_overrides', {}).get('segment', contract.get('segment'))

    response_data = {
        "energy_type": "gaz" if is_gas else "elec",
        "identity": data.get('identity', {}),
        "location": data.get('location', {}),
        "contract": {
            "pdl": contract.get('pdl'),
            "provider": financials['meta'].get('provider'),
            "segment": display_segment,
            "start_date": contract.get('start_date'),
            "end_date": contract.get('end_date'),
            "power": contract.get('power'),
            "p_max": contract.get('p_max'),
            "fta": contract.get('fta'),
            "grd": contract.get('grd'),
            "cja": contract.get('cja'),
            "profil": contract.get('profil'),
            "tarif_acheminement": contract.get('tarif_acheminement'),
            "power_details": contract.get('power_details', {})
        },
        "pricing": pricing,
        "kpis": {
            "volume_mwh": financials['volume_mwh'],
            "budget": financials['budget_annual'],
            "pmc": financials['kpis']['pmc_eur_mwh']
        },
        "cortex_insight": {
            "message": "Analyse CORTEX terminée.",
            "conseil": "Prix optimisé." if market_analysis['status'] == 'OPTIMISÉ' else "Surveillez ce contrat."
        },
        "market_analysis": market_analysis,
        "electricity_price": financials['kpis']['unit_price_kwh']
    }
    return JSONResponse(json_compliant(response_data))

@app.post("/api/ops/market/update")
async def api_update_market(data: MarketUpdateModel, x_admin_token: str = Header(None)):
    try:
        new_payload = data.dict()
        new_payload["updated_at"] = datetime.now().isoformat()
        ref_path = os.path.join(DATA_DIR, "market_ref.json")
        with open(ref_path, "w") as f: json.dump(new_payload, f, indent=4)
        return JSONResponse({"success": True})
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/physics/solar")
async def api_solar_sim(request: Request):
    try:
        payload = await request.json()
        address = payload.get('address', '')
        surface = float(payload.get('surface_roof', 0))
        price = float(payload.get('electricity_price', 0.20))
        lat, lon = physics.get_coordinates_from_address(address)
        return JSONResponse(physics.simulate_solar_roi(lat, lon, surface, price))
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/api/tools/template/{template_type}")
async def download_template(template_type: str):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    stream = io.BytesIO()
    try:
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if "import_elec" in template_type or "template_csv" == template_type:
                df = pd.DataFrame(columns=[
                    "ENTITE", "NOM_SITE", "ADRESSE_SITE", "CP", "VILLE", "SIRET_SITE", "REF_COPRO", 
                    "NAF", "CEE_ELIGIBLE", "GO_PERCENT", "COMPTEUR_PRODUCTION", "PDL", "SEGMENT", "FTA", "GRD", 
                    "TYPOLOGIE", "PUISSANCE_SOUSCRITE", "POINTE_MAX", 
                    "PS_HPH", "PS_HCH", "PS_HPE", "PS_HCE", 
                    "CONSO_HPH", "CONSO_HCH", "CONSO_HPE", "CONSO_HCE", 
                    "VOLUME_ANNUEL", "COMMENTAIRE", "DATE_DEBUT", "DATE_FIN", "FOURNISSEUR", 
                    "ABONNEMENT", "PRIX_HPH", "PRIX_HCH", "PRIX_HPE", "PRIX_HCE", "TAXES", 
                    "SURFACE_M2", "CODE_INSEE"
                ])
                df.to_excel(writer, index=False)
            elif "import_gaz" in template_type or "template_csv_gaz" == template_type:
                df = pd.DataFrame(columns=[
                    "ENTITE", "NOM_SITE", "ADRESSE_SITE", "CP", "VILLE", "SIRET_SITE", "NAF", 
                    "CEE_ELIGIBLE", "PCE", "CAR_MWH", "CJA_MWH_J", "SEGMENT_GAZ", "PROFIL", 
                    "TARIF_ACHEM", "GRD", "DATE_DEBUT", "DATE_FIN", "FOURNISSEUR", 
                    "ABONNEMENT", "PRIX_MOLECULE", "TERME_STOCK", "TAXES", "INSEE", "SURFACE_M2"
                ])
                df.to_excel(writer, index=False)
            elif "bpu" in template_type:
                df = pd.DataFrame(columns=["PRIX_HPH", "ABONNEMENT"])
                df.to_excel(writer, index=False)
            else:
                df = pd.DataFrame(columns=["A", "B"])
                df.to_excel(writer, index=False)
        stream.seek(0)
        filename = "Template_Import_GAZ.xlsx" if "gaz" in template_type else "Template_Import_ELEC.xlsx"
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})
    except:
        stream = io.StringIO()
        pd.DataFrame().to_csv(stream)
        return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")

@app.get("/api/settings/template_csv")
async def route_template_elec(): return await download_template("import_elec")
@app.get("/api/settings/template_csv_gaz")
async def route_template_gaz(): return await download_template("import_gaz")

@app.get("/app/assets/{filename}")
async def get_static_asset(filename: str):
    if "template" in filename: return await download_template("import_elec")
    if "bpu" in filename: return await download_template("bpu")
    return JSONResponse({"error": "File not found"}, 404)

@app.post("/api/ops/simulate_offer")
async def api_simulate_offer(file: UploadFile = File(...)):
    try:
        content = await file.read()
        current_sites = []
        files = glob.glob(os.path.join(DATA_DIR, "*.json"))
        for p in files:
            if "master" in p: continue
            try:
                with open(p, 'r', encoding='utf-8') as f: current_sites.append(json.load(f))
            except: continue
        res = cortex.simulate_budget_from_bpu(content, current_sites)
        return JSONResponse(json_compliant(res))
    except Exception as e: return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo")):
    content = await file.read()
    res = cortex.analyze_load_curve(content, file.filename)
    return JSONResponse(json_compliant(res))

# --- GENERATE TENDER PRO (BPU DETAILLÉ) ---
@app.post("/api/ops/generate_tender")
async def generate_tender(request: Request):
    if not PANDAS_READY: return JSONResponse({"error": "Pandas missing"}, 500)
    try:
        body = await request.json()
        site_ids = body.get('site_ids', [])
        selected_sites = []
        for sid in site_ids:
            file_path = find_site_file(sid)
            if file_path:
                with open(file_path, 'r', encoding='utf-8') as f: selected_sites.append(json.load(f))
        
        df_dqe = cortex.generate_dqe_structure(selected_sites)
        df_elec = df_dqe[df_dqe['Type'] == 'ELEC']
        df_gaz = df_dqe[df_dqe['Type'] == 'GAZ']
        
        # BPU ELEC PRO (Reprise des sites)
        if not df_elec.empty:
            df_bpu_elec = df_elec[["PDL", "Nom du site", "CP", "Ville", "Segment", "Vol. Annuel"]].copy()
            df_bpu_elec["OFFRE_NOM"] = ""
            df_bpu_elec["PRIX_HPH_EUR_KWH"] = ""
            df_bpu_elec["PRIX_HCH_EUR_KWH"] = ""
            df_bpu_elec["PRIX_HPE_EUR_KWH"] = ""
            df_bpu_elec["PRIX_HCE_EUR_KWH"] = ""
            df_bpu_elec["ABONNEMENT_EUR_AN"] = ""
        else:
            df_bpu_elec = pd.DataFrame()

        # BPU GAZ PRO (Reprise des sites)
        if not df_gaz.empty:
            df_bpu_gaz = df_gaz[["PDL", "Nom du site", "CP", "Ville", "Vol. Annuel"]].copy()
            df_bpu_gaz = df_bpu_gaz.rename(columns={"PDL": "PCE"})
            df_bpu_gaz["OFFRE_NOM"] = ""
            df_bpu_gaz["PRIX_MOLECULE_EUR_MWH"] = ""
            df_bpu_gaz["ABONNEMENT_EUR_AN"] = ""
            df_bpu_gaz["TERME_STOCKAGE_EUR_MWH"] = ""
        else:
            df_bpu_gaz = pd.DataFrame()

        stream = io.BytesIO()
        with pd.ExcelWriter(stream, engine='openpyxl') as writer:
            if not df_elec.empty: 
                df_elec.to_excel(writer, index=False, sheet_name="DATA_ELEC")
                df_bpu_elec.to_excel(writer, index=False, sheet_name="REPONSE_ELEC")
            
            if not df_gaz.empty: 
                df_gaz.to_excel(writer, index=False, sheet_name="DATA_GAZ")
                df_bpu_gaz.to_excel(writer, index=False, sheet_name="REPONSE_GAZ")
            
            if df_elec.empty and df_gaz.empty: 
                df_dqe.to_excel(writer, index=False, sheet_name="TOUT")

        stream.seek(0)
        timestamp = datetime.now().strftime("%Y%m%d")
        return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename=DQE_Energistrat_{timestamp}.xlsx"})
    except Exception as e: return JSONResponse({"error": str(e)}, 500)

@app.get("/")
async def view_landing(request: Request): return templates.TemplateResponse("index.html", {"request": request})
@app.get("/onboarding")
async def view_onboarding(request: Request): return templates.TemplateResponse("onboarding.html", {"request": request})
@app.get("/processing")
async def view_processing(request: Request): return templates.TemplateResponse("processing.html", {"request": request})
@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    if profile == "retail": return templates.TemplateResponse("retail.html", {"request": request})
    t = f"{profile}.html"
    if os.path.exists(os.path.join(TEMPLATE_DIR, t)): return templates.TemplateResponse(t, {"request": request, "profile": profile})
    return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})
@app.get("/settings")
async def view_settings(request: Request): return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/partner/settings")
async def view_partner_settings(request: Request):
    if "supplier" in request.headers.get("referer", ""): return templates.TemplateResponse("settings_partner.html", {"request": request})
    return templates.TemplateResponse("settings.html", {"request": request})
@app.get("/ops/market")
async def view_ops_market(request: Request): return templates.TemplateResponse("ops_market.html", {"request": request})
@app.get("/{page_name}")
async def serve_dynamic(request: Request, page_name: str):
    if any(x in page_name for x in [".js", ".css", ".png", ".jpg"]): return JSONResponse({}, 404)
    c = page_name if page_name.endswith(".html") else f"{page_name}.html"
    if os.path.exists(os.path.join(TEMPLATE_DIR, c)): return templates.TemplateResponse(c, {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})
@app.get("/{full_path:path}")
async def catch_all_deep(request: Request, full_path: str):
    if any(x in full_path for x in ["static", "assets", "favicon"]): return JSONResponse({}, 404)
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
