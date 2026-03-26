from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Initialisation du Routeur V4 (Indépendant et Sécurisé)
router = APIRouter()

# ==========================================
# 1. MODÈLES DE DONNÉES (Sécurité stricte)
# ==========================================
class EbitdaRequest(BaseModel):
    ca_k_eur: float
    marge_nette_pct: float
    multiple_valo: float
    gains_energie_eur: float

class TurpeRequest(BaseModel):
    puissance_souscrite_kVA: float
    puissance_max_atteinte_kW: float
    puissance_cible_kVA: float

# ==========================================
# 2. ENDPOINTS V4 (Logique Métier CORTEX)
# ==========================================

@router.get("/status")
async def v4_status():
    """Route de test (Ping) pour valider que le moteur tourne sur Cloud Run."""
    return {
        "status": "ONLINE", 
        "version": "V4.0", 
        "message": "Le moteur CORTEX V4 est branché et opérationnel."
    }

@router.post("/simulate/ebitda")
async def simulate_ebitda(payload: EbitdaRequest):
    """Moteur M&A / Valorisation d'entreprise (Rapatrié du Front-End)"""
    try:
        ca_reel = payload.ca_k_eur * 1000
        marge = payload.marge_nette_pct / 100.0
        
        # Ingénierie Financière
        val_creation = payload.gains_energie_eur * payload.multiple_valo
        nouvelle_marge = (((ca_reel * marge) + payload.gains_energie_eur) / ca_reel) * 100 if ca_reel > 0 else 0
        equivalent_ca = (payload.gains_energie_eur / marge) if marge > 0 else 0

        return {
            "success": True,
            "results": {
                "val_creation_eur": val_creation,
                "nouvelle_marge_pct": round(nouvelle_marge, 2),
                "equivalent_ca_eur": equivalent_ca
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/simulate/turpe")
async def simulate_turpe(payload: TurpeRequest):
    """Moteur d'optimisation Tarifaire (Rapatrié du Front-End)"""
    try:
        diff = payload.puissance_souscrite_kVA - payload.puissance_cible_kVA
        savings = diff * 15  # Prime fixe estimée
        warning = ""
        
        if payload.puissance_cible_kVA < payload.puissance_max_atteinte_kW:
            penalty = (payload.puissance_max_atteinte_kW - payload.puissance_cible_kVA) * 20
            savings -= penalty
            warning = f"Risque de dépassement / disjonction l'hiver. Pénalité estimée : {round(penalty)} €"
        elif payload.puissance_cible_kVA == payload.puissance_souscrite_kVA:
            warning = "Abonnement Actuel."
            
        return {
            "success": True,
            "results": {
                "savings_eur": savings,
                "is_profitable": savings > 0,
                "warning_message": warning
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
