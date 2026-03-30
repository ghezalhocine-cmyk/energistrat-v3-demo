# --- START OF FILE cortex_ademe.py ---
import urllib.request
import urllib.parse
import json
import logging

class CortexAdeme:
    """
    CORTEX ADEME ENGINE V1.0
    Moteur dédié à l'analyse foncière, au Décret Tertiaire (Operat) et au DPE.
    """
    def __init__(self):
        self.logger = logging.getLogger("CortexAdeme")
        self.version = "1.0 (DPE & Valeur Verte)"

    def fetch_surface_ademe(self, address: str, zip_code: str = "") -> float:
        """Interroge l'Open Data ADEME pour récupérer la surface utile d'un bâtiment."""
        if not address: return 0.0
        try:
            query = urllib.parse.quote(f"{address} {zip_code}".strip())
            url = f"https://data.ademe.fr/data-fair/api/v1/datasets/dpe-v2-tertiaire-2/lines?q={query}&size=1&select=surface_utile"
            req = urllib.request.Request(url, headers={'User-Agent': 'Energistrat-Cortex/12.8'})
            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read().decode())
                if data.get("results") and len(data["results"]) > 0:
                    return float(data["results"][0].get("surface_utile", 0.0))
        except Exception as e:
            self.logger.error(f"Erreur API ADEME: {e}")
        return 0.0

    def analyze_immo(self, site_data: dict) -> dict:
        """Calcule l'étiquette DPE et l'impact sur la valeur foncière."""
        ident = site_data.get('identity', {})
        loc = site_data.get('location', {})
        kpis = site_data.get('kpis', {})
        
        naf = str(ident.get('naf', 'DEFAULT')).upper()
        volume_mwh = float(kpis.get('volume_mwh') or site_data.get('volume_mwh') or 0)
        volume_kwh = volume_mwh * 1000
        
        surface = float(loc.get('surface') or 0)
        surface_updated = False
        
        # 1. Fallback API ADEME si surface inconnue
        if surface == 0:
            ademe_surf = self.fetch_surface_ademe(loc.get('address', ''), loc.get('zip_code', ''))
            if ademe_surf > 0:
                surface = ademe_surf
                surface_updated = True
                
        if surface == 0 or volume_kwh == 0:
            return {"error": "Surface foncière (m²) ou Volume (kWh) manquants pour calculer le DPE."}
            
        # 2. Calcul de l'Intensité (kWh/m²/an)
        intensity = volume_kwh / surface
        
        # 3. Baseline sectoriel simplifié (Cibles ADEME)
        baseline = 180 # Standard Bureaux
        if naf.startswith('84'): baseline = 150 # Administration / Mairie
        elif naf.startswith('86'): baseline = 400 # Santé / Hôpital
        elif naf.startswith('47'): baseline = 300 # Retail / Supermarché
        elif naf.startswith('1') or naf.startswith('2') or naf.startswith('3'): baseline = 250 # Industrie
        
        # 4. Moteur de Notation DPE & Valeur Verte (Décote/Surcote)
        decote_pct = 0
        if intensity < baseline * 0.4: note = "A"; decote_pct = 12
        elif intensity < baseline * 0.6: note = "B"; decote_pct = 7
        elif intensity < baseline * 0.9: note = "C"; decote_pct = 3
        elif intensity < baseline * 1.2: note = "D"; decote_pct = 0
        elif intensity < baseline * 1.5: note = "E"; decote_pct = -5
        elif intensity < baseline * 2.0: note = "F"; decote_pct = -12
        else: note = "G"; decote_pct = -20
        
        # 5. Estimation Financière (Hypothèse marché foncier à 2000€/m² lissé)
        valeur_theorique = surface * 2000
        impact_foncier = valeur_theorique * (decote_pct / 100.0)
        
        return {
            "success": True,
            "surface_updated": surface_updated,
            "new_surface": surface,
            "site": { "sector": f"Code NAF: {naf}" },
            "energy": { "intensity_kwh_m2": round(intensity), "baseline_kwh_m2": baseline },
            "dpe": { "note": note, "is_passoire": note in["F", "G"] },
            "finance": { "valeur_theorique": round(valeur_theorique), "impact_foncier": round(impact_foncier), "decote_pct": decote_pct }
        }

ademe_engine = CortexAdeme()
# --- END OF FILE cortex_ademe.py ---
