import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_CRM_V10")

class CortexCRM:
    """
    CORTEX CRM V10.0 (SALES WORKSPACE ENGINE)
    Moteur d'intelligence commerciale : Kanban, Icebreakers NAF, et Scoring SGE.
    """
    
    def __init__(self):
        # Base de connaissances sectorielles pour l'approche commerciale (Icebreakers)
        self.NAF_INTELLIGENCE = {
            "10.71": { # Boulangeries
                "pain_points": "Talon nocturne (Froid/Pétrin), Hausse prix matières premières.",
                "icebreaker": "M. le Gérant, les boulangeries de votre région subissent de plein fouet la hausse de l'énergie. Votre chambre de pousse tourne la nuit. Si je vous montre comment récupérer 3000€ sur ce talon nocturne sans changer vos machines, avez-vous 5 minutes ?"
            },
            "47.11": { # Supermarchés
                "pain_points": "Froid commercial continu, Éclairage, Loi ELAN (Décret Tertiaire).",
                "icebreaker": "M. le Directeur, le décret tertiaire vous oblige à baisser vos consos. Au lieu de faire des travaux, notre IA peut détecter les fuites de votre froid commercial à distance et éditer votre rapport OPERAT automatiquement."
            },
            "86.10": { # Hôpitaux
                "pain_points": "Budget EPRD tendu, Qualité de l'air, Obligation de service continu.",
                "icebreaker": "M. le DAF, votre hôpital a une charge de base incompressible. Notre IA peut transformer ce talon en subventions CEE (Fonds Chaleur) et sécuriser votre budget MCO."
            },
            "84.11": { # Mairies (Générique Public)
                "pain_points": "Marchés Publics complexes, Passoires thermiques (Écoles), Éclairage Public.",
                "icebreaker": "M. le Maire, l'énergie pèse lourd dans la M57. Notre plateforme génère votre DQE d'appel d'offres en 1 clic et identifie les écoles éligibles aux aides de l'État."
            },
            "DEFAULT": {
                "pain_points": "Manque de visibilité budgétaire, fin de contrat opaque.",
                "icebreaker": "Bonjour, les entreprises de votre taille paient souvent des taxes (CSPE) qu'elles pourraient récupérer. Notre Tiers de Confiance audite votre facture en 3 secondes."
            }
        }

    def generate_icebreaker(self, naf_code: str) -> dict:
        """Fournit les munitions commerciales selon le code NAF du prospect."""
        naf_base = str(naf_code)[:5] if naf_code else "DEFAULT"
        intel = self.NAF_INTELLIGENCE.get(naf_base, self.NAF_INTELLIGENCE["DEFAULT"])
        return {
            "naf": naf_code,
            "pain_points": intel["pain_points"],
            "pitch": intel["icebreaker"]
        }

    def analyze_company_health(self, current_vol: float, previous_vol: float, login_count_30d: int) -> dict:
        """
        Croise la donnée SGE et l'usage SaaS pour sortir un Health Score.
        """
        health_status = "STABLE"
        health_color = "text-success"
        health_msg = "Activité normale."

        # 1. Alerte Économique (Chute SGE)
        if previous_vol > 0:
            drop_pct = ((previous_vol - current_vol) / previous_vol) * 100
            if drop_pct > 30:
                health_status = "RISQUE ÉCONOMIQUE"
                health_color = "text-alert"
                health_msg = f"Chute brutale de la conso SGE (-{int(drop_pct)}%). Risque de faillite ou arrêt de production."
            elif drop_pct < -20:
                health_status = "CROISSANCE"
                health_color = "text-cyan"
                health_msg = "Forte hausse de conso. Nouveaux équipements ? Proposez une optimisation TURPE."

        # 2. Alerte Logiciel (Risque de Churn)
        churn_risk = False
        if login_count_30d == 0:
            churn_risk = True
            if health_status == "STABLE":
                health_status = "DÉTACHEMENT LOGICIEL"
                health_color = "text-gold"
                health_msg = "Le client ne s'est pas connecté à son Dashboard depuis 30 jours. Appelez-le pour un point."

        return {
            "status": health_status,
            "color": health_color,
            "message": health_msg,
            "churn_risk": churn_risk
        }

    def calculate_commission(self, volume_mwh: float, is_saas: bool, saas_mrr: float = 0) -> float:
        """
        Calcul de la prime du commercial pour la gamification.
        """
        # Commission Courtage : 1€/MWh (La boite) -> Le commercial prend 10% par ex.
        broker_com = (volume_mwh * 1.00) * 0.10 
        # Commission SaaS : 1er mois de MRR
        saas_com = saas_mrr * 1.0 
        
        return round(broker_com + saas_com, 2)

crm_engine = CortexCRM()
