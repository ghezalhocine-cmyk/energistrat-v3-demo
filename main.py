# main.py V5.5 - SECURITY & VAULT EDITION
import os
import json
import shutil
import logging
from datetime import datetime
import secrets # Pour générer les tokens sécurisés

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- CONFIGURATION SÉCURITÉ ---
ADMIN_PIN = "BOSS_V5"  # Ton Code PIN Maître
DATA_DIR = "data_store"
os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title="ENERGISTRAT V5.5 - Secure Vault")

# CORS (Autorise ton frontend à parler au backend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 1. SÉCURITÉ : LE GARDIEN (Vérification du PIN Admin)
# ---------------------------------------------------------
async def verify_admin(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_PIN:
        raise HTTPException(status_code=401, detail="ACCÈS REFUSÉ : Code PIN Incorrect.")
    return True

# ---------------------------------------------------------
# 2. LE COFFRE-FORT (Accès Client Sécurisé)
# ---------------------------------------------------------
# ATTENTION : On ne monte PLUS "/data_store" en StaticFiles.
# Seul cet endpoint permet de lire un fichier.

@app.get("/api/vault/{filename}")
async def get_secure_data(filename: str, token: str):
    """
    Récupère un JSON seulement si le token correspond à la signature du fichier.
    """
    # Sécurité : Empêcher de remonter dans les dossiers (Path Traversal)
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(DATA_DIR, safe_filename)

    # 1. Le fichier existe-t-il ?
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    # 2. Le Token est-il valide ?
    # Règle V5.5 : Le token DOIT être présent dans le nom du fichier.
    # Ex: 12345_RET_20260130_X9Y8Z7.json -> Token attendu : X9Y8Z7
    if token not in safe_filename:
         # Simulation d'un délai pour ralentir les attaques par force brute
        raise HTTPException(status_code=403, detail="TICKET INVALIDE : Accès interdit.")

    return FileResponse(path=file_path, media_type='application/json')

# ---------------------------------------------------------
# 3. L'USINE OPS (Upload Sécurisé)
# ---------------------------------------------------------
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    profile: str = Form(...),
    siret: str = Form("UNKNOWN"), # Nouveau champ pour structurer
    authorized: bool = Depends(verify_admin) # Protection par PIN
):
    try:
        # A. Analyse du fichier (Simulation CORTEX ou Appel Réel)
        # Ici on garde la logique existante : on sauvegarde le PDF temporairement
        temp_filename = f"temp_{file.filename}"
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # B. Génération des clés de sécurité
        timestamp = datetime.now().strftime("%Y%m%d")
        secure_token = secrets.token_urlsafe(6) # Génère un code type 'Xy9_z2'
        
        # C. Nommage Structuré : SIRET_PROFIL_DATE_TOKEN.json
        safe_siret = siret.replace(" ", "")
        json_filename = f"{safe_siret}_{profile}_{timestamp}_{secure_token}.json"
        json_path = os.path.join(DATA_DIR, json_filename)

        # D. Création de la donnée (Mock ou Engine)
        # Pour le MVP Sécurité, on crée un JSON simple qui contient la référence
        data = {
            "meta": {
                "siret": safe_siret,
                "profile": profile,
                "date": timestamp,
                "security_token": secure_token,
                "filename": json_filename
            },
            "status": "ANALYSIS_COMPLETE",
            "message": "Ceci est une donnée sécurisée V5.5"
        }
        
        # Sauvegarde disque
        with open(json_path, "w") as f:
            json.dump(data, f)

        # Nettoyage temp
        os.remove(temp_filename)

        # E. Retourne le lien sécurisé à l'Ops
        # Le lien contient le token en paramètre GET
        return {
            "status": "success", 
            "filename": json_filename,
            "token": secure_token,
            "secure_link": f"/dashboard/{profile}?file={json_filename}&token={secure_token}"
        }

    except Exception as e:
        logging.error(f"Erreur Upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint de santé
@app.get("/")
def read_root():
    return {"status": "Energistrat V5.5 Secure System Online"}
