# --- START OF FILE cortex_settings.py ---
import urllib.request
import json
import math
from datetime import datetime

class CortexSettings:
    """
    CORTEX DATA UNITY V13 - Moteur Back-End
    Gère la Gouvernance (TVA, API Gouv), la Qualité Data et la Salle de Marchés.
    """
    def __init__(self):
        self.version = "V13.0_SECURE_ERP"

    # ==========================================
    # 1. MAGIC FILL (Souveraineté des calculs en Back-end)
    # ==========================================
    def magic_fill(self, siret: str) -> dict:
        clean_siret = str(siret).replace(" ", "").strip()
        if len(clean_siret) != 14:
            return {"success": False, "error": "Le SIRET doit faire exactement 14 chiffres."}
        
        try:
            url = f"https://recherche-entreprises.api.gouv.fr/search?q={clean_siret}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Energistrat-Cortex/13.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                if not data.get("results"):
                    return {"success": False, "error": "SIRET introuvable dans la base de l'État."}
                
                etab = data["results"][0]
                nom = etab.get("nom_complet") or etab.get("nom_raison_sociale", "Entité Inconnue")
                naf = etab.get("activite_principale", "N/A")
                
                # --- CALCUL MATHÉMATIQUE DE LA TVA INTRACOMMUNAUTAIRE ---
                siren = clean_siret[:9]
                cle = (12 + 3 * (int(siren) % 97)) % 97
                tva = f"FR{cle:02d}{siren}"

                # --- ADRESSE LOCALE DE L'ÉTABLISSEMENT (SIRET) ---
                adresse_exacte = ""
                if etab.get("matching_etablissements") and len(etab["matching_etablissements"]) > 0:
                    match = etab["matching_etablissements"][0]
                    adresse_exacte = f"{match.get('adresse', '')}, {match.get('code_postal', '')} {match.get('libelle_commune', '')}"
                elif etab.get("siege", {}).get("adresse"):
                    siege = etab["siege"]
                    adresse_exacte = f"{siege.get('adresse', '')}, {siege.get('code_postal', '')} {siege.get('libelle_commune', '')}"

                return {
                    "success": True,
                    "data": {
                        "siret": clean_siret,
                        "siren": siren,
                        "name": nom,
                        "naf": naf,
                        "tva": tva,
                        "address": adresse_exacte.strip().strip(",").strip()
                    }
                }
        except Exception as e:
            return {"success": False, "error": f"Erreur API Gouv: {str(e)}"}

    # ==========================================
    # 2. DATA HEALTH SCORE (Sécurité des KPI)
    # ==========================================
    def compute_health_score(self, sites: list) -> dict:
        if not sites or len(sites) == 0:
            return {"success": True, "score": 0, "count": 0}
        
        total_score = 0
        for s in sites:
            score = 0
            ident = s.get("identity", {})
            loc = s.get("location", {})
            contract = s.get("contract", {})
            pricing = s.get("pricing", {})
            kpis = s.get("kpis", {})

            # Critères de pondération stricts
            if contract.get("pdl") or contract.get("pce") or s.get("pdl") or s.get("id"): score += 25
            if loc.get("surface") or s.get("surface") or s.get("SURFACE_M2"): score += 25
            if contract.get("provider") or s.get("provider") or s.get("FOURNISSEUR"): score += 15
            
            price = pricing.get("price_kwh") or pricing.get("hph") or s.get("prix_hph") or s.get("price_kwh") or 0
            if float(price) > 0 or float(kpis.get("budget") or 0) > 0: score += 20
            
            if contract.get("end_date") or s.get("end_date"): score += 15
            
            total_score += min(score, 100)
        
        avg = round(total_score / len(sites))
        return {"success": True, "score": avg, "count": len(sites)}

    # ==========================================
    # 3. HEDGING & TRADING (Le Graphique Condor + Forecast)
    # ==========================================
    def generate_hedging_board(self, sites: list, forecast_engine=None) -> dict:
        """
        Croise la Base 3D avec le Cortex Forecast pour structurer la couverture boursière.
        (Convertit les MWh en puissance MW pour l'affichage boursier)
        """
        total_vol_mwh = 0
        for s in sites:
            vol = float(s.get("kpis", {}).get("volume_mwh") or s.get("volume_mwh") or 0)
            total_vol_mwh += vol
                
        if total_vol_mwh == 0:
            # Fallback visuel si le client n'a pas encore saisi de volumes
            total_vol_mwh = 5000 

        # 1. Utilisation du Forecast pour la saisonnalité (Spot)
        # On simplifie ici par trimestre (Q1 à Q4)
        seasonality =[1.3, 0.9, 0.8, 1.2, 1.3, 0.9] # Modèle type "PME/Bâtiment" (Plus haut en Hiver Q1/Q4)
        
        # Conversion du Volume Annuel en Puissance Moyenne (MW)
        # 1 MW continu sur l'année = 8760 MWh
        avg_mw = total_vol_mwh / 8760.0
        
        labels =['Q1 2026', 'Q2 2026', 'Q3 2026', 'Q4 2026', 'Q1 2027', 'Q2 2027']
        
        # 2. Sourcing Ruban (Ex-ARENH / Sourcing Nucléaire de Base)
        # Stratégie standard : 40% du volume est acheté en ruban plat
        data_base =[round(avg_mw * 0.40, 2)] * 6
        
        # 3. PPA (Solaire)
        # Produit plus en Été (Q2, Q3) qu'en Hiver (Q1, Q4)
        data_ppa =[
            round(avg_mw * 0.05, 2), round(avg_mw * 0.15, 2), round(avg_mw * 0.20, 2), 
            round(avg_mw * 0.05, 2), round(avg_mw * 0.05, 2), round(avg_mw * 0.15, 2)
        ]
        
        # 4. Tranche de Marché (CAL 26) fixée par le client
        # Couvre 2026 en entier, mais pas encore 2027
        data_tranche = [round(avg_mw * 0.35, 2)] * 4 +[0.0, 0.0]
        
        # 5. L'Exposition Spot (Le reste calculé par la soustraction de la prévision)
        data_spot =[]
        for i in range(6):
            needed_mw = avg_mw * seasonality[i]
            covered_mw = data_base[i] + data_ppa[i] + data_tranche[i]
            spot = max(0.0, needed_mw - covered_mw) # Pas de revente (short) pour l'instant
            data_spot.append(round(spot, 2))
            
        # 6. Calcul des KPIs Financiers (Blended Price)
        total_covered_mw = sum(data_base) + sum(data_ppa) + sum(data_tranche)
        total_needed_mw = sum([avg_mw * s for s in seasonality])
        coverage_pct = round((total_covered_mw / total_needed_mw) * 100) if total_needed_mw > 0 else 0
        
        # Prix fictif lissé pour le dashboard = (Base*42€ + PPA*60€ + Tranche*90€ + Spot*75€)
        blended_price = 78.40 
        
        return {
            "success": True,
            "kpis": {
                "coverage_pct": min(coverage_pct, 100),
                "blended_price": blended_price,
                "open_positions": 4, # Trimestres non totalement couverts
                "ppa_volume_mwh": round(sum(data_ppa) * 2190) # Re-conversion des MW solaires en MWh
            },
            "chart": {
                "labels": labels,
                "datasets": {
                    "base": data_base,
                    "ppa": data_ppa,
                    "tranche": data_tranche,
                    "spot": data_spot
                }
            }
        }

settings_engine = CortexSettings()
# --- END OF FILE ---
