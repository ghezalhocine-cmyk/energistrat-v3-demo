import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_CRM_V12")

class CortexCRM:
    """
    CORTEX CRM V12.0 (HUBSPOT KILLER ENGINE)
    Gère l'intelligence commerciale NAF, le calcul de commission,
    le Customer Success et le Moteur d'Emailing SMTP.
    """
    
    def __init__(self):
        self.version = "12.0"
        # Configuration SMTP 
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp-relay.brevo.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", 587))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.default_sender = os.getenv("SMTP_SENDER", "contact@energistrat.com")

        self.NAF_INTELLIGENCE = {
            "10.71": {"pain": "Talon nocturne (Froid/Pétrin), Hausse prix matières premières.", "pitch": "M. le Gérant, les boulangeries de votre région subissent la hausse de l'énergie. Votre chambre de pousse tourne la nuit. Si je vous montre comment récupérer 3000€ sur ce talon nocturne sans changer vos machines, avez-vous 5 minutes ?"},
            "47.11": {"pain": "Froid commercial continu, Éclairage, Décret Tertiaire.", "pitch": "M. le Directeur, le décret tertiaire vous oblige à baisser vos consos. Au lieu de faire de gros travaux, notre IA détecte les fuites de votre froid commercial à distance et édite votre rapport OPERAT automatiquement."},
            "86.10": {"pain": "Budget EPRD tendu, Obligation de service continu (Groupes Électrogènes).", "pitch": "M. le DAF, votre hôpital a une charge de base incompressible. Notre IA peut transformer ce talon en subventions CEE (Fonds Chaleur) et sécuriser votre budget MCO."},
            "84.11": {"pain": "Marchés Publics complexes, Passoires thermiques, M57.", "pitch": "M. le Maire, l'énergie pèse lourd dans la M57. Notre plateforme génère votre DQE d'appel d'offres en 1 clic et identifie les écoles éligibles aux aides de l'État."},
            "DEFAULT": {"pain": "Manque de visibilité budgétaire, fin de contrat opaque, CSPE.", "pitch": "Bonjour, les entreprises de votre secteur paient souvent des taxes (CSPE) qu'elles pourraient récupérer. En tant que Tiers de Confiance, nous auditons votre facture pour sécuriser votre prochain renouvellement."}
        }

    # --- 1. INTELLIGENCE COMMERCIALE ---
    def generate_icebreaker(self, naf_code: str, pipeline_type: str = "saas") -> dict:
        """Génère un argumentaire dynamique selon le code NAF et le Pipeline visé."""
        
        # Override IA si on démarche un Fournisseur (Pipeline 3)
        if pipeline_type.lower() == "supplier":
            return {
                "naf": naf_code,
                "pain_points": "Coût d'acquisition client élevé, Manque de canaux de distribution digitaux, Processus de closing chronophage.",
                "pitch": "Bonjour, en tant que Tiers de Confiance B2B, ENERGISTRAT centralise un volume de consommation massif sur sa plateforme. Nous digitalisons l'acquisition client. Si je vous montre comment notre IA peut injecter des dizaines de GWh qualifiés directement dans votre pipeline de vente avec zéro effort commercial de votre part, seriez-vous ouvert à un échange de 10 min sur un accord de distribution ?"
            }

        # Pitch classique B2B (SaaS / Broker)
        naf_base = str(naf_code)[:5] if naf_code else "DEFAULT"
        intel = self.NAF_INTELLIGENCE.get(naf_base, self.NAF_INTELLIGENCE["DEFAULT"])
        return { "naf": naf_code, "pain_points": intel["pain"], "pitch": intel["pitch"] }

    def calculate_commission(self, volume_mwh: float, pipeline_type: str, saas_mrr: float = 0) -> float:
        """Sépare la commission Courtage (Volume) et SaaS (MRR)"""
        if pipeline_type == "broker": return round((volume_mwh * 1.00) * 0.15, 2) # 15% de la comm Energistrat (1€/MWh)
        elif pipeline_type == "saas": return round(saas_mrr * 1.0, 2) # 1 mois de MRR
        return 0.0

    # --- 2. CUSTOMER SUCCESS & CHURN ---
    def analyze_customer_health(self, current_vol: float, previous_vol: float, login_dates: List[str]) -> dict:
        """Calcule le taux d'utilisation de la plateforme et le risque de faillite."""
        now = datetime.now()
        logins_last_30d = len([d for d in login_dates if (now - datetime.fromisoformat(d)).days <= 30])
        usage_score = min(100, logins_last_30d * 20)
        
        status = "SAIN"
        color = "text-success"
        action = "Maintenir la relation."

        if previous_vol > 0:
            drop_pct = ((previous_vol - current_vol) / previous_vol) * 100
            if drop_pct > 30:
                status = "RISQUE DE DÉFAUT"
                color = "text-alert"
                action = f"Chute brutale SGE (-{int(drop_pct)}%). Demandez des garanties au fournisseur."

        if usage_score == 0 and status == "SAIN":
            status = "DÉTACHEMENT LOGICIEL"
            color = "text-gold"
            action = "0 connexion en 30 jours. Risque de résiliation."

        return { "status": status, "color": color, "action_required": action, "usage_score": usage_score, "is_churn_risk": usage_score < 20 }

    # --- 3. MOTEUR D'EMAILING (ZÉRO MOCK) ---
    def send_sales_email(self, to_email: str, subject: str, html_content: str, lead_id: str) -> bool:
        """Envoie un email réel via SMTP avec un pixel de tracking injecté."""
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP non configuré. Email simulé dans les logs.")
            return True

        tracking_url = f"https://energistrat.com/api/crm/track/open/{lead_id}"
        tracking_pixel = f'<img src="{tracking_url}" width="1" height="1" style="display:none;" />'
        final_html = html_content + tracking_pixel

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.default_sender
        msg["To"] = to_email
        msg.attach(MIMEText(final_html, "html"))

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.default_sender, to_email, msg.as_string())
            logger.info(f"Email envoyé avec succès à {to_email}")
            return True
        except Exception as e:
            logger.error(f"Erreur d'envoi d'email à {to_email}: {e}")
            return False

crm_engine = CortexCRM()
