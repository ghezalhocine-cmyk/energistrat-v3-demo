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

# --- BLOC DIAGNOSTIC IMPORT (AJOUT SÉCURITÉ EXCEL) ---
try:
    import pandas as pd
    import openpyxl
    EXCEL_ENGINE_READY = True
except ImportError as e:
    print(f"!!! ERREUR CRITIQUE !!! Moteur Excel manquant : {e}")
    EXCEL_ENGINE_READY = False

# IMPORT DES MOTEURS
from app.core.cortex_engine import cortex
from app.core.storage_engine import storage 

app = FastAPI(title="ENERGISTRAT V3", version="PROD")

# CONFIGURATION DU CHEMIN (EVOLUTION : FORCE PATH)
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    if os.path.exists("data"): 
        DATA_DIR = "data"
    else: 
        os.makedirs(DATA_DIR, exist_ok=True)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
if os.path.exists("static"): 
    app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/health")
async def health_check(): 
    return {
        "status": "ONLINE", 
        "cortex": cortex.version, 
        "storage": storage.version,
        "excel_engine": "READY" if EXCEL_ENGINE_READY else "MISSING"
    }

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

# --- MARKET WATCH ENGINE (EVOLUTION DIAMOND : HISTORY) ---
def get_market_ref():
    path = f"{DATA_DIR}/market_ref.json"
    if os.path.exists(path):
        try:
            with open(path, 'r') as f: 
                return json.load(f)
        except: 
            pass
    return {
        "updated_at": datetime.now().isoformat(),
        "elec": { "cal_n1": 82.50, "cal_n2": 76.00, "trend": "BAISSIER" },
        "gaz": { "peg_n1": 39.40, "peg_n2": 36.10, "trend": "STABLE" }
    }

@app.get("/api/market/current")
async def api_get_market(): 
    return JSONResponse(get_market_ref())

@app.post("/api/ops/market/update")
async def api_update_market(data: MarketUpdateModel, x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": 
        raise HTTPException(status_code=401, detail="Accès refusé")
    try:
        # 1. Préparation de la nouvelle donnée
        new_payload = data.dict()
        new_payload["updated_at"] = datetime.now().isoformat()
        
        ref_path = f"{DATA_DIR}/market_ref.json"
        hist_path = f"{DATA_DIR}/market_history.json"
        
        # 2. Logique d'Historisation (Avant écrasement)
        if os.path.exists(ref_path):
            try:
                # On lit la version actuelle (qui va devenir "l'ancienne")
                with open(ref_path, 'r') as f: 
                    old_data = json.load(f)
                
                # On charge l'historique existant ou on le crée
                history = []
                if os.path.exists(hist_path):
                    try:
                        with open(hist_path, 'r') as f: 
                            history = json.load(f)
                    except: 
                        history = [] 
                
                # On ajoute l'ancienne version à l'historique
                history.append(old_data)
                
                # Rotation : On ne garde que les 104 dernières semaines (2 ans) pour ne pas saturer
                if len(history) > 104: 
                    history = history[-104:]
                
                # Sauvegarde de l'historique
                with open(hist_path, 'w') as f: 
                    json.dump(history, f, indent=4)
                
            except Exception as e:
                print(f"[WARNING] Market History Failed: {str(e)}")

        # 3. Mise à jour du Référentiel LIVE (Cortex V43 lit ce fichier)
        with open(ref_path, "w") as f: 
            json.dump(new_payload, f, indent=4)
        
        return JSONResponse({"success": True, "updated_at": new_payload["updated_at"], "history_archived": True})
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

# --- API DASHBOARD / FLEET (BI & ANALYTICS - CORTEX V45 CONNECTED) ---
@app.get("/api/dashboard/fleet")
async def get_fleet_data():
    raw_sites = []
    files = glob.glob(f"{DATA_DIR}/*.json")
    
    # 1. Chargement des données brutes
    for p in files:
        if "master_index" in p or "market_ref" in p or "market_history" in p: 
            continue
        try:
            with open(p, 'r') as f: 
                data = json.load(f)
            if not data or 'identity' not in data: 
                continue
            
            # Enrichissement KPI basique (Cortex V44)
            try: 
                kpis = cortex.enrich_fleet_kpis(data)
            except: 
                kpis = {"budget_annual": 0, "ghost_savings": 0, "landing_forecast": 0, "is_alert_landing": False, "volume_mwh": 0}
            data['kpis'] = kpis 
            
            raw_sites.append(data)
        except: 
            continue
    
    # 2. Appel du Cerveau (Intelligence Collective V45)
    # Cortex calcule maintenant les parts de marché et normalise les fournisseurs
    analysis_result = cortex.analyze_portfolio(raw_sites)
    
    # 3. Formatage pour le Frontend
    fleet_list = []
    
    # Ensembles pour les filtres (Optimisation Backend)
    all_cities = set()
    all_providers = set()
    all_segments = set()
    all_lots = set()

    for s in raw_sites:
        c, i, pr = s.get('contract',{}), s.get('identity',{}), s.get('pricing',{})
        loc = s.get('location', {})
        kpis = s.get('kpis', {})
        is_gaz = "T" in str(c.get('segment','')) or "gaz" in str(pr.get('hph','')).lower()
        
        # Récupération des données normalisées par Cortex si disponibles
        cortex_data = next((x for x in analysis_result.get('raw_data', []) if x['nom_site'] == i.get('site_name')), {})
        
        provider = cortex_data.get('fournisseur') or c.get('provider', 'Inconnu')
        city = loc.get('city', loc.get('address','-').split(',')[-1].strip())
        segment = c.get('segment','--')
        lot = i.get('lot_name','Hors Lot')

        # Collecte pour les filtres
        if city and city != '-': all_cities.add(city)
        if provider: all_providers.add(provider)
        if segment: all_segments.add(segment)
        if lot: all_lots.add(lot)

        fleet_list.append({
            "id": i.get('id', 'unknown'),
            "name": i.get('site_name', i.get('name', 'Site')),
            "city": city,
            "zip": loc.get('zip_code', ''),
            "volume": kpis.get('volume_mwh', 0),
            "energy": "gaz" if is_gaz else "elec",
            "segment": segment,
            "lot": lot,
            "provider": provider, # Champ normalisé
            "power": cortex._safe_float(c.get('power',0)),
            "budget": kpis['budget_annual'],
            "ghost_savings": kpis['ghost_savings'],
            "landing": kpis['landing_forecast'],
            "alert": kpis.get('is_alert_landing', False)
        })

    return JSONResponse({
        "fleet": fleet_list, 
        "count": len(fleet_list),
        "green_league": analysis_result.get('green_league'),
        "cortex": analysis_result.get('cortex'),
        "global_kpis": analysis_result.get('kpis'),
        "market_share": analysis_result.get('market_share'), # Pour le camembert
        "filters_meta": { # NOUVEAU : Pour les listes déroulantes
            "cities": sorted(list(all_cities)),
            "providers": sorted(list(all_providers)),
            "segments": sorted(list(all_segments)),
            "lots": sorted(list(all_lots))
        }
    })

@app.get("/api/dashboard/data/{client_id}")
async def get_dashboard_data(client_id: str):
    path = f"{DATA_DIR}/{client_id}.json"
    if not os.path.exists(path): 
        return JSONResponse({"error": "Client introuvable"})
    
    with open(path, 'r') as f: 
        data = json.load(f)
    
    # Enrichissement Live
    try:
        market = get_market_ref()
        pricing = data.get('pricing', {})
        contract = data.get('contract', {}) 
        is_gaz = "T" in str(contract.get('segment',''))
        segment = str(contract.get('segment', 'C5'))
        
        market_price = market['gaz']['peg_n1'] if is_gaz else market['elec']['cal_n1']
        client_price = float(str(pricing.get('hph', '0')).replace(',', '.').replace(' ', ''))
        
        # Appel Cortex V44 (Fix Unit + TRVE)
        data["market_analysis"] = cortex.analyze_market_position(
            client_price, 
            market_price, 
            "gaz" if is_gaz else "elec",
            segment=segment
        )
    except:
        data["market_analysis"] = {"status": "NEUTRE", "action": "-", "color": "gray"}

    data["energy_type"] = "gaz" if "T" in str(data.get('contract',{}).get('segment','')) else "elec"
    data["cortex_insight"] = {"message": "Analyse standard.", "conseil": "RAS.", "status": "OK", "color": "green"}
    
    return JSONResponse(data)

# --- API OPS (ADMIN & ANALYSE) ---
@app.post("/api/ops/analyze")
async def api_analyze(file: UploadFile = File(...), target: str = Form("demo"), site_name: str = Form("Site_1"), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": 
        return JSONResponse({}, 401)
    try:
        content = await file.read()
        detected_pdl = None
        filename_match = re.search(r'(\d{14})', file.filename)
        if filename_match: 
            detected_pdl = filename_match.group(1)
        if not detected_pdl:
            try:
                content_str = content.decode('latin-1', errors='ignore')[:1000]
                content_match = re.search(r'\b(\d{14})\b', content_str)
                if content_match: 
                    detected_pdl = content_match.group(1)
            except: 
                pass
        site_data = None
        if detected_pdl: 
            site_data = storage.find_site_by_pdl(detected_pdl)
        res = cortex.analyze_file(content, file.filename, target_profile=target, known_site_data=site_data)
        if res.get("success"): 
            res["secure_link"] = f"/dashboard/{target}?site={site_name}"
            if site_data: 
                res["reconciled"] = True
        return JSONResponse(res)
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/ops/audit")
async def api_audit(invoice: UploadFile = File(...), contract: UploadFile = File(None), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": 
        return JSONResponse({}, 401)
    try:
        inv = await invoice.read()
        ctr = await contract.read() if contract else None
        return JSONResponse(cortex.analyze_invoice_real(inv, ctr))
    except Exception as e: 
        return JSONResponse({"score": 0, "checks": [], "error": str(e)})

@app.post("/api/ops/chat")
async def api_chat(message: str = Form(...), x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": 
        return JSONResponse({}, 401)
    return JSONResponse({"response": cortex.ask_agent(message)})

@app.post("/api/ops/chaos")
async def api_chaos(x_admin_token: str = Header(None)):
    if x_admin_token != "BOSS_V5": 
        return JSONResponse({}, 401)
    return JSONResponse(cortex.run_chaos_monkey())

# --- API TENDER (GENERATION EXCEL - EVOLUTION) ---
@app.post("/api/ops/generate_tender")
async def generate_tender(payload: TenderRequest):
    # Check Moteur
    if not EXCEL_ENGINE_READY:
        raise HTTPException(status_code=503, detail="CRITIQUE: Librairie 'openpyxl' manquante.")

    selected_sites = []
    for site_id in payload.site_ids:
        if not site_id or "master" in site_id: 
            continue
        
        # Lecture via Storage (Chemin unifié)
        data = storage.get_client_settings(site_id)
        if data: 
            selected_sites.append(data)
    
    if not selected_sites:
        raise HTTPException(status_code=400, detail="Aucun site valide sélectionné.")

    try:
        # Appel Cortex V39/41
        excel_content = cortex.generate_advanced_tender_excel(selected_sites)
        
        if not excel_content or len(excel_content) == 0:
            raise HTTPException(status_code=500, detail="Erreur Interne : Excel vide.")
        
        timestamp = datetime.now().strftime("%Y%m%d")
        filename = f"DCE_Energistrat_{len(selected_sites)}sites_{timestamp}.xlsx"

        return StreamingResponse(
            io.BytesIO(excel_content), 
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        print(f"[CRASH TENDER] {e}")
        raise HTTPException(status_code=500, detail=f"Crash Serveur : {str(e)}")

# --- API SETTINGS & IMPORT ---
@app.post("/api/settings/import_csv")
async def api_import_csv(file: UploadFile = File(...)):
    try:
        content = await file.read()
        sites = cortex.parse_mass_import_v5(content)
        if not sites: 
            return JSONResponse({"success": False, "error": "Format incorrect"})
        saved = 0
        for s in sites:
            cid = s['identity'].get('id')
            if not cid: 
                continue
            storage.save_client_settings(cid, s)
            saved += 1
        return JSONResponse({"success": True, "imported": saved})
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/save_client")
async def api_save_client(request: Request):
    try:
        data = await request.json()
        client_id = data.get("identity", {}).get("id") or "draft_client"
        res = storage.save_client_settings(client_id, data)
        return JSONResponse(res)
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.post("/api/settings/propagate_tariff")
async def propagate_tariff(payload: PropagationRequest):
    return JSONResponse({"success": True, "updated_count": 1}) 

@app.post("/api/partner/save_config")
async def api_save_partner(request: Request):
    try:
        data = await request.json()
        res = storage.save_partner_config("main_partner", data)
        return JSONResponse(res)
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

# --- API TICKETING ---
@app.post("/api/support/ticket")
async def create_ticket(request: Request):
    try:
        data = await request.json()
        res = storage.create_ticket(data)
        return JSONResponse(res)
    except Exception as e: 
        return JSONResponse({"success": False, "error": str(e)})

@app.get("/api/support/tickets")
async def get_tickets():
    tickets = storage.list_tickets()
    return JSONResponse({"tickets": tickets})

# --- TEMPLATES CSV ---
@app.get("/api/settings/template_csv")
async def get_import_template():
    # Template Elec Expert V6 (DQE)
    headers = [ 
        "ENTITE", "NOM_SITE", "ADRESSE_SITE", "CP", "VILLE", 
        "SIRET_SITE", "NAF", "CEE_ELIGIBLE", "GO_PERCENT", "COMPTEUR_PRODUCTEUR",
        "PDL", "SEGMENT", "FTA", "GRD", "TYPOLOGIE",
        "PUISSANCE_SOUSCRITE_MAX", "POINTE_MAX", 
        "PS_HPH", "PS_HCH", "PS_HPE", "PS_HCE", # Puissances Souscrites
        "CONSO_HPH", "CONSO_HCH", "CONSO_HPE", "CONSO_HCE", # Volumes Consommés
        "VOLUME_ANNUEL_TOTAL", "COMMENTAIRES", "DATE_DEBUT", "DATE_FIN",
        "FOURNISSEUR", "PRIX_MOLECULE", "ABONNEMENT"
    ]
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(headers)
    writer.writerow([ 
        "Mairie de Lyon", "Ecole J.Ferry", "10 Rue de la Paix", "69002", "Lyon",
        "12345678900012", "8411Z", "OUI", "100", "NON",
        "30000000000000", "C4", "CU", "Enedis", "Bâtiment",
        "60", "45", # Max
        "60", "50", "40", "30", # PS par poste
        "15000", "10000", "8000", "4000", # Conso par poste
        "37000", "Site à rénover", "01/01/2025", "31/12/2026",
        "EDF", "120.50", "350.00"
    ])
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=template_dqe_expert.csv"})

@app.get("/api/settings/template_csv_gaz")
async def get_import_template_gaz():
    # Template Gaz V1
    headers = [ "SIRET", "RAISON_SOCIALE", "NOM_SITE", "ADRESSE", "PCE", "CAR_MWH", "SEGMENT_GAZ", "LOT", "ABO_AN", "PRIX_MWH", "TAXES" ]
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(headers)
    writer.writerow([ "12345678900012", "Mon Entreprise", "Chaufferie Bât A", "10 Rue de la Paix", "04500000000000", "150", "T2", "Lot Chauffage", "250.00", "45.50", "8.44" ])
    stream.seek(0)
    return StreamingResponse(iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=template_import_gaz_v1.csv"})

# --- ROUTES HTML (VUES) ---
@app.get("/nexus")
async def view_nexus(request: Request): 
    return templates.TemplateResponse("nexus.html", {"request": request})

@app.get("/dashboard/{profile}")
async def view_dashboard(request: Request, profile: str):
    f = f"{profile}.html"
    if os.path.exists(f"app/templates/{f}"): 
        return templates.TemplateResponse(f, {"request": request})
    if os.path.exists("app/templates/dashboard.html"): 
        return templates.TemplateResponse("dashboard.html", {"request": request, "profile": profile})
    return JSONResponse({"error": f"Template missing: {f}"}, 404)

@app.get("/partner/settings")
async def view_settings(request: Request): 
    return templates.TemplateResponse("settings.html", {"request": request})

@app.get("/{path_name:path}")
async def catch_all(request: Request, path_name: str):
    if path_name in ["", "/"]: 
        return templates.TemplateResponse("index.html", {"request": request})
    clean = path_name if path_name.endswith(".html") else f"{path_name}.html"
    if os.path.exists(f"app/templates/{clean}"): 
        return templates.TemplateResponse(clean, {"request": request})
    return JSONResponse({"error": "Page not found"}, 404)
