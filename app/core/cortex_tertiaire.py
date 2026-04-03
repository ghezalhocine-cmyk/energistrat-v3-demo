# --- START OF FILE cortex_tertiaire.py ---
import logging
from typing import Dict, Any

class CortexTertiaire:
    """
    CORTEX TERTIAIRE V1.0 (LOI ELAN / OPERAT)
    Moteur de conformité légale et trajectoire carbone.
    """
    def __init__(self):
        self.logger = logging.getLogger("CortexTertiaire")
        self.targets = { "2030": 0.60, "2040": 0.50, "2050": 0.40 } # -40%, -50%, -60%

    def generate_operat_declaration(self, site_data: Dict[str, Any], ademe_data: Dict[str, Any], ref_year: int) -> Dict[str, Any]:
        try:
            # 1. EXTRACTION DES DONNÉES BRUTES
            ident = site_data.get("identity", {})
            loc = site_data.get("location", {})
            
            siret = str(ident.get("siret", "")).strip()
            surface = float(loc.get("surface") or 0.0)
            
            intensity_reelle = float(ademe_data.get("energy", {}).get("intensity_kwh_m2") or 0.0)
            intensity_ref = float(ademe_data.get("energy", {}).get("baseline_kwh_m2") or 250.0)

            # 2. CALCULS DE LA TRAJECTOIRE (L'ESCALIER LÉGAL)
            target_2030 = intensity_ref * self.targets["2030"]
            target_2040 = intensity_ref * self.targets["2040"]
            target_2050 = intensity_ref * self.targets["2050"]

            # Calcul de la progression actuelle vs Objectif 2030
            progress_pct = 0.0
            if intensity_ref > target_2030:
                total_drop_needed = intensity_ref - target_2030
                current_drop = intensity_ref - intensity_reelle
                progress_pct = (current_drop / total_drop_needed) * 100

            # 3. AUDIT DE COMPLÉTUDE (SÉCURITÉ LÉGALE)
            checks = {
                "siret_valid": len(siret) >= 9,
                "surface_valid": surface >= 1000,
                "conso_valid": intensity_reelle > 0
            }
            # La surface < 1000 ne bloque pas l'export (le client peut vouloir déclarer volontairement), 
            # mais l'absence de SIRET ou de Conso est bloquante.
            is_export_ready = checks["siret_valid"] and checks["conso_valid"]

            # 4. GÉNÉRATION DU PAYLOAD OPERAT (Format attendu par l'API de l'État)
            operat_payload = {
                "identifiant_siret": siret,
                "nom_etablissement": ident.get("site_name", ""),
                "adresse": loc.get("address", ""),
                "code_postal": loc.get("zip_code", ""),
                "ville": loc.get("city", ""),
                "categorie_activite_naf": ident.get("naf", ""),
                "surface_assujettie_m2": surface,
                "annee_reference": ref_year,
                "consommation_reference_kwh_m2": round(intensity_ref),
                "consommation_actuelle_kwh_m2": round(intensity_reelle),
                "objectif_2030_kwh_m2": round(target_2030),
                "objectif_2040_kwh_m2": round(target_2040),
                "objectif_2050_kwh_m2": round(target_2050)
            }

            return {
                "success": True,
                "audit": checks,
                "is_export_ready": is_export_ready,
                "metrics": {
                    "intensity_ref": round(intensity_ref),
                    "intensity_reelle": round(intensity_reelle),
                    "target_2030": round(target_2030),
                    "target_2040": round(target_2040),
                    "target_2050": round(target_2050),
                    "progress_pct": round(progress_pct, 1)
                },
                "operat_payload": operat_payload if is_export_ready else None
            }

        except Exception as e:
            self.logger.error(f"Erreur Cortex Tertiaire : {e}")
            return {"success": False, "error": str(e)}

tertiaire_engine = CortexTertiaire()
# --- END OF FILE cortex_tertiaire.py ---
