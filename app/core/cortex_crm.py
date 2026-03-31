# --- START OF FILE cortex_crm.py ---
import os
import logging
from datetime import datetime
import urllib.parse

logger = logging.getLogger("CORTEX_CRM_V12_8")

class CortexCRM:
    """
    CORTEX CRM V12.8 (SALES & SUCCESS)
    Générateur d'Icebreakers NAF, URLs Mailto dynamiques, Liens d'Agenda.
    """
    def __init__(self):
        self.version = "12.8"

    # --- 1. INTELLIGENCE COMMERCIALE (NAF PREFIXES) ---
    def generate_icebreaker(self, naf_code: str, pipeline_type: str = "saas", client_name: str = "Client") -> dict:
        """Analyse le NAF pour générer les Pain Points, l'argumentaire et préparer l'email de prospection."""
        naf = str(naf_code).strip()
        pain = "Manque de visibilité budgétaire, CSPE, fin de contrat."
        pitch = "Bonjour, en tant que Tiers de Confiance, nous auditons vos factures pour détecter les pénalités et sécuriser vos renouvellements."
        
        # Moteur Heuristique NAF
        if naf.startswith(("10", "11", "13", "16", "17", "20", "22", "24", "25", "27", "28", "29")):
            pain = "Talon nocturne, Dépassements de puissance (TURPE), Hausse des matières premières."
            pitch = f"M. le Directeur, en tant qu'industriel, votre charge de base est incompressible. Notre IA peut identifier des anomalies sur vos appels de puissance et activer le bouclier fiscal CSPE pour récupérer du cash immédiat."
        elif naf.startswith(("47", "45", "46")): # Retail & Commerce
            pain = "Froid commercial continu, Éclairage, Obligations Décret Tertiaire."
            pitch = f"Bonjour, le décret tertiaire vous oblige à réduire vos consommations. Plutôt que de financer des audits lourds, notre logiciel détecte les dérives de votre froid commercial à distance et automatise votre déclaration OPERAT."
        elif naf.startswith("86"): # Santé
            pain = "Budget tendu, Groupes Électrogènes, Continuité de service."
            pitch = "M. le DAF, votre établissement a une charge vitale incompressible. Notre plateforme transforme ce talon en subventions (CEE / Fonds Chaleur) pour soulager votre budget."
        elif naf.startswith("84"): # Public / Mairie
            pain = "Marchés Publics complexes, Passoires thermiques, M57."
            pitch = "M. le Maire, l'énergie explose dans la M57. CORTEX génère le DQE de vos appels d'offres en un clic et identifie les subventions de l'État pour rénover vos écoles."

        # Génération du lien MAILTO pré-rempli
        subject = f"Optimisation de vos contrats d'énergie - {client_name}"
        mail_body = f"{pitch}\n\nAvez-vous 10 minutes la semaine prochaine pour une démonstration de notre plateforme de supervision ?\n\nCordialement,"
        
        mailto_link = f"mailto:?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(mail_body)}"

        return {
            "naf": naf,
            "pain_points": pain,
            "pitch": pitch,
            "mailto_link": mailto_link
        }

    # --- 2. GESTION DES RENDEZ-VOUS (DOCTOLIB / CALENDAR) ---
    def generate_calendar_link(self, client_name: str, description: str = "") -> str:
        """Génère un lien d'ajout rapide pour Google Calendar (Utilisable par le commercial)."""
        title = f"Point Énergie / Démo Plateforme - {client_name}"
        details = f"{description}\n\nLien de la War Room CORTEX : https://energistrat.com/ops_nexus"
        
        # Format Google Calendar Event (Dates par défaut : le lendemain à 10h)
        base_url = "https://calendar.google.com/calendar/render?action=TEMPLATE"
        url = f"{base_url}&text={urllib.parse.quote(title)}&details={urllib.parse.quote(details)}"
        return url

    # --- 3. CUSTOMER SUCCESS & CHURN ---
    def analyze_customer_health(self, current_vol: float, previous_vol: float, financial_anomalies_count: int) -> dict:
        """Score de santé incluant les anomalies FinOps du Dashboard Finance."""
        status = "SAIN"
        color = "text-success"
        action = "RAS. Proposer des Satellites (Upsell)."

        if financial_anomalies_count > 0:
            status = "INSATISFACTION IMMINENTE"
            color = "text-alert"
            action = f"{financial_anomalies_count} anomalie(s) de facturation détectée(s) par l'IA. Appelez le client pour ouvrir un litige fournisseur !"
        elif previous_vol > 0:
            drop_pct = ((previous_vol - current_vol) / previous_vol) * 100
            if drop_pct > 30:
                status = "RISQUE DE DÉFAUT"
                color = "text-gold"
                action = f"Chute brutale SGE (-{int(drop_pct)}%). Le site est-il à l'arrêt ?"

        return { "status": status, "color": color, "action_required": action }

crm_engine = CortexCRM()
# --- END OF FILE cortex_crm.py ---
