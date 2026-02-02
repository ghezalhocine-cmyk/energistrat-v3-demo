from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.core.storage_engine import storage
from app.core.cortex_engine import cortex
import os

app = FastAPI(title="ENERGISTRAT V3", version="3.0")

# Montage des fichiers statiques (CSS/JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Configuration des Templates (HTML)
templates = Jinja2Templates(directory="app/templates")

# --- ROUTES SYSTEME ---

@app.get("/")
async def root(request: Request):
    """Page d'accueil (Landing Page)"""
    # Pour l'instant on renvoie vers ops, on changera plus tard vers index.html
    return templates.TemplateResponse("ops.html", {"request": request, "version": "V3.0"})

@app.get("/health")
async def health_check():
    """Vérification Santé Cloud Run"""
    is_writable = os.access("/app/data", os.W_OK)
    return {
        "status": "ONLINE",
        "storage_writable": is_writable, 
        "version_cortex": cortex.version,
        "sites_managed": len(storage.index.get("sites", {}))
    }

# --- ROUTES API ---

@app.post("/api/v1/ingest/webhook")
async def ingest_api_data(site_id: str, connector_id: str, payload: dict):
    """Webhook pour recevoir les données API externes"""
    # 1. Vérification
    site = storage.index["sites"].get(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site inconnu")
        
    # 2. Sauvegarde brute
    file_path = storage.save_api_raw_data(site_id, connector_id, payload)
    
    # 3. Audit
    storage.log_audit("SYSTEM", "API_WEBHOOK", site_id, {"ref": file_path})
    
    return {"status": "RECEIVED", "ref": file_path}
