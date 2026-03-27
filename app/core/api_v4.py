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

class ExtinctionRequest(BaseModel):
    ghost_savings_eur: float
    surface_m2: float
    reduction_pct: float

class SubventionRequest(BaseModel):
    cout_travaux_eur: float
    aides_api_eur: float

@router.post("/simulate/extinction")
async def simulate_extinction(payload: ExtinctionRequest):
    """Moteur de calcul ROI pour l'extinction nocturne et GTB"""
    try:
        savings = payload.ghost_savings_eur * (payload.reduction_pct / 100.0)
        # CAPEX estimé : 15€/m² pour une GTB/Horloges (ou 2500€ par défaut)
        capex = payload.surface_m2 * 15.0 if payload.surface_m2 > 0 else 2500.0
        roi_months = (capex / savings) * 12 if savings > 0 else 999.0
        
        return {
            "success": True,
            "results": {
                "savings_eur": savings,
                "capex_eur": capex,
                "roi_months": round(roi_months, 1),
                "is_profitable": roi_months < 36 # Si ROI < 3 ans, c'est très rentable
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/simulate/subventions")
async def simulate_subventions(payload: SubventionRequest):
    """Moteur de calcul des restes à charge (Fonds Vert / CEE)"""
    try:
        total_aides = payload.aides_api_eur
        
        # Intelligence CORTEX : Si pas d'aide API spécifique, on applique le taux Fonds Vert par défaut (30%)
        if total_aides == 0 and payload.cout_travaux_eur > 0:
            total_aides = payload.cout_travaux_eur * 0.30
            
        # Plafond légal de subventionnement public (100%)
        if total_aides > payload.cout_travaux_eur:
            total_aides = payload.cout_travaux_eur
            
        reste_a_charge = payload.cout_travaux_eur - total_aides
        pct_financement = (total_aides / payload.cout_travaux_eur) * 100 if payload.cout_travaux_eur > 0 else 0
        
        return {
            "success": True,
            "results": {
                "total_aides_eur": total_aides,
                "reste_a_charge_eur": reste_a_charge,
                "pct_financement": round(pct_financement, 1)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
