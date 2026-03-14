import uuid
import math
from datetime import datetime, timedelta
import logging

# On importe le DB connector (Zero Mock)
from app.core.cortex_db import db

logger = logging.getLogger("CORTEX_ACADEMY_V12")

class CortexAcademy:
    """
    CORTEX ACADEMY V12.4 - MOTEUR LMS ENTREPRISE
    Gère le Curriculum (7 Piliers), la Spaced Repetition (SuperMemo-2),
    et injecte automatiquement le Payload Pédagogique Ultime au démarrage.
    """

    def __init__(self):
        self.version = "12.4"
        self._seed_curriculum_if_empty()

    def _seed_curriculum_if_empty(self):
        """Initialise les 7 Piliers et les 12 Cas Pratiques dans Firestore si la base est vide."""
        if not db: return
        
        modules = db.get_all_lms_modules()
        if len(modules) > 0:
            return # Déjà initialisé, on ne fait rien pour ne pas écraser la base

        logger.info("🟢 CORTEX ACADEMY : Auto-Seeding du Payload Pédagogique Ultime dans Firestore...")
        
        # 1. CRÉATION DES PILIERS
        pillars =[
            {"id": "MOD_1", "level": 1, "title": "Héritage et Géopolitique", "desc": "Le modèle français, fin des TRV, chocs gaziers de 2022 et 2026 (Iran/USA).", "xp_reward": 500},
            {"id": "MOD_2", "level": 2, "title": "Fondations & Réglementation", "desc": "TURPE, CSPE, CEE, Décret Tertiaire, nomenclature M57 pour le public.", "xp_reward": 600},
            {"id": "MOD_3", "level": 3, "title": "Marchés & Pricing", "desc": "Prix Fixe vs Indexé (ARENH, SPOT), Clics, lecture de grilles complexes.", "xp_reward": 800},
            {"id": "MOD_4", "level": 4, "title": "L'Écosystème du Courtage", "desc": "Pourquoi le courtage classique est toxique. Marges cachées et transparence.", "xp_reward": 400},
            {"id": "MOD_5", "level": 5, "title": "L'Arme ENERGISTRAT", "desc": "Formation à la Démo Client SaaS (Data Unity, Moteur Physique, CPQ).", "xp_reward": 1000},
            {"id": "MOD_6", "level": 6, "title": "École de Vente d'Élite", "desc": "Méthodologie MEDDIC, SPIN Selling et Traitement des objections.", "xp_reward": 1500},
            {"id": "MOD_7", "level": 7, "title": "Prospective & Avenir", "desc": "VNU, Corporate PPA, Modélisation du BP Énergétique à 5 ans.", "xp_reward": 2000}
        ]

        for p in pillars:
            db.save_lms_module(p["id"], {
                "title": p["title"],
                "description": p["desc"],
                "level": p["level"],
                "xp_reward": p["xp_reward"],
                "created_at": datetime.now().isoformat()
            })
            
        # 2. CRÉATION DE LA BIBLIOTHÈQUE D'EXPERTISE (LES QUESTIONS)
        questions =[
            # --- PILIER 1 : GÉOPOLITIQUE ---
            {
                "id": "Q_GEO_2026_01",
                "module_id": "MOD_1",
                "type": "SCÉNARIO DE CRISE",
                "scenario": "Mars 2026. Le détroit d'Ormuz est sous blocus suite à l'escalade militaire USA/Iran. Le GNL qatari ne passe plus. Votre client voit le PEG exploser et son contrat finit dans 2 mois. Que lui conseillez-vous ?",
                "options":[
                    {"id": "A", "text": "Attendre le mois prochain. La géopolitique se calme toujours.", "is_correct": False, "feedback": "Erreur fatale (Spéculation). Un Tiers de Confiance ne joue pas au casino avec le budget d'une usine."},
                    {"id": "B", "text": "Fixer 100% de son volume sur 3 ans immédiatement.", "is_correct": False, "feedback": "Erreur (Achat de panique). Fixer 100% au plus haut d'une crise, c'est condamner le client sur 3 ans."},
                    {"id": "C", "text": "Couvrir 30% du volume en prix fixe (SWAP) pour sécuriser le talon, et laisser le reste indexé au SPOT avec des alertes CORTEX.", "is_correct": True, "feedback": "Parfait (Risk Management). Tu lisses le risque financier tout en gardant des fenêtres de tir."}
                ]
            },
            # --- PILIER 3 : MARCHÉS ---
            {
                "id": "Q_MKT_MERIT_01",
                "module_id": "MOD_3",
                "type": "TECHNIQUE MARCHÉ",
                "scenario": "Un client demande : 'Pourquoi le prix de mon électricité augmente alors que la France produit 70% de nucléaire ? C'est une arnaque !'",
                "options":[
                    {"id": "A", "text": "C'est le mécanisme du 'Merit Order'. Le prix de gros européen est fixé par la dernière centrale appelée (souvent à gaz).", "is_correct": True, "feedback": "Excellente réponse. Le Merit Order est la base de la formation des prix."},
                    {"id": "B", "text": "C'est à cause de l'ARENH qui force EDF à vendre à perte.", "is_correct": False, "feedback": "L'ARENH a eu des effets pervers, mais ce n'est pas ce qui fixe le prix de gros sur le marché SPOT."},
                    {"id": "C", "text": "C'est parce que les courtiers prennent trop de marges.", "is_correct": False, "feedback": "Erreur. C'est un discours de café du commerce, pas d'un auditeur technique."}
                ]
            },
            # --- PILIER 2 : RÉGLEMENTATION ---
            {
                "id": "Q_REG_TURPE_01",
                "module_id": "MOD_2",
                "type": "AUDIT FACTURE",
                "scenario": "Vous analysez la facture d'une PME fonctionnant en 2x8. Sa version tarifaire (TURPE) est en 'Courte Utilisation' (CU). Que déduisez-vous ?",
                "options":[
                    {"id": "A", "text": "C'est normal, la Longue Utilisation (LU) est pour la grande industrie.", "is_correct": False, "feedback": "Faux. Le choix CU/LU dépend de la durée d'utilisation de la puissance, pas de la taille."},
                    {"id": "B", "text": "Il y a une anomalie. Avec une forte conso de nuit, elle devrait sûrement être en Moyenne (MU) ou Longue Utilisation (LU).", "is_correct": True, "feedback": "Exact ! Changer pour LU permet de payer l'électron moins cher la nuit. Optimisation validée."},
                    {"id": "C", "text": "La version tarifaire n'a aucun impact financier.", "is_correct": False, "feedback": "Hérésie. L'acheminement (TURPE) représente environ 30% de la facture."}
                ]
            },
            {
                "id": "Q_REG_PUBLIC_01",
                "module_id": "MOD_2",
                "type": "SECTEUR PUBLIC",
                "scenario": "RDV avec une Mairie. Sur quelle taxe énergétique pouvez-vous souvent récupérer des fonds rétroactivement pour une commune (M57) ?",
                "options":[
                    {"id": "A", "text": "La TVA, en demandant un taux réduit à 5,5%.", "is_correct": False, "feedback": "Faux. La TVA à 5,5% ne s'applique que sur l'abonnement, pas sur la consommation brute."},
                    {"id": "B", "text": "La CTA, car les mairies en sont exonérées.", "is_correct": False, "feedback": "Faux. Personne n'est exonéré de la CTA."},
                    {"id": "C", "text": "La CSPE (TICFE). Selon les activités, elle peut bénéficier d'exonérations avec rétroactivité sur 2 à 3 ans.", "is_correct": True, "feedback": "Bingo ! C'est le 'Golden Ticket' pour signer une mairie et financer le SaaS via le ROI généré."}
                ]
            },
            # --- PILIER 4 : COURTAGE ---
            {
                "id": "Q_ECO_BROKER_01",
                "module_id": "MOD_4",
                "type": "CORTEX ETHICS",
                "scenario": "Comment un courtier en énergie 'gratuit' gagne-t-il réellement sa vie ?",
                "options":[
                    {"id": "A", "text": "Il est payé par l'État via des subventions.", "is_correct": False, "feedback": "Totalement faux. L'État ne subventionne pas les courtiers privés."},
                    {"id": "B", "text": "Il ajoute une marge cachée (commission) dans le prix du KWh proposé par le fournisseur.", "is_correct": True, "feedback": "C'est la faille du système ! Une marge de 2€/MWh sur 10 GWh = 20 000€ pris au client en silence."},
                    {"id": "C", "text": "Il vend les données personnelles du client.", "is_correct": False, "feedback": "Non. La source de revenus massive reste la marge cachée dans l'électron."}
                ]
            },
            # --- PILIER 6 : ÉCOLE DE VENTE ---
            {
                "id": "Q_SALES_MEDDIC_01",
                "module_id": "MOD_6",
                "type": "BATTLE CARD",
                "scenario": "Le prospect dit : 'Je n'ai pas le temps de me connecter à un énième logiciel.' Quelle est votre parade (SPIN Selling) ?",
                "options":[
                    {"id": "A", "text": "Notre interface est très belle, cela ne prendra que 5 minutes.", "is_correct": False, "feedback": "Erreur. Tu essaies de lui vendre le design alors qu'il manque de temps."},
                    {"id": "B", "text": "CORTEX tourne en arrière-plan. Vous ne vous connectez pas. Il vous alerte par SMS si vous dépassez votre puissance. C'est un bouclier autonome.", "is_correct": True, "feedback": "Exceptionnel ! Tu as transformé l'objection 'pas le temps' en argument d'automatisation."},
                    {"id": "C", "text": "Je vous appellerai personnellement tous les mois.", "is_correct": False, "feedback": "Mauvais. Tu te transformes en assistant non scalable."}
                ]
            },
            {
                "id": "Q_SALES_CHAMPION_01",
                "module_id": "MOD_6",
                "type": "BATTLE CARD",
                "scenario": "Votre 'Champion' (Acheteur) adore ENERGISTRAT, mais dit : 'Le DAF va bloquer car il refuse toute dépense logicielle.' Que faites-vous ?",
                "options":[
                    {"id": "A", "text": "Proposer une période d'essai gratuite.", "is_correct": False, "feedback": "Faux. Le gratuit n'a pas de valeur. Tu repousses l'échéance."},
                    {"id": "B", "text": "Abandonner le deal.", "is_correct": False, "feedback": "Attitude de perdant."},
                    {"id": "C", "text": "Armons-nous. Donnez-moi vos factures. Demain, on présente au DAF un rapport montrant que le SaaS s'autofinance en 2 mois.", "is_correct": True, "feedback": "Méthode MEDDIC parfaite. Tu utilises ton Champion pour prouver le ROI à l'Economic Buyer."}
                ]
            },
            # --- PILIER 7 : PROSPECTIVE ---
            {
                "id": "Q_FUTUR_CPPA_01",
                "module_id": "MOD_7",
                "type": "PROSPECTIVE VNU",
                "scenario": "Un Directeur Industriel veut signer un 'Corporate PPA' solaire sur 15 ans. Pourquoi a-t-il besoin de notre SaaS ?",
                "options":[
                    {"id": "A", "text": "ENERGISTRAT va modéliser sa Courbe de Charge (Data Unity) pour dimensionner la part exacte de son talon qui doit rester chez un fournisseur classique.", "is_correct": True, "feedback": "Masterclass. Un PPA mal dimensionné est un cauchemar financier. Seul un SaaS peut faire ce profilage."},
                    {"id": "B", "text": "Un CPPA se gère directement, le SaaS ne sert à rien.", "is_correct": False, "feedback": "Erreur. L'intégration d'un PPA dans un budget (Sleeving) nécessite un logiciel lourd."},
                    {"id": "C", "text": "Parce que nous installons les panneaux.", "is_correct": False, "feedback": "Faux. Nous sommes un Tiers de Confiance, pas un installateur."}
                ]
            }
        ]

        for q in questions:
            db.save_lms_question(q["id"], q)

        logger.info("🔥 MISSION ACCOMPLIE : Payload Pédagogique Ultime déployé avec succès.")

    # ==========================================
    # SPACED REPETITION SYSTEM (SM-2 Algorithme)
    # ==========================================
    def process_answer(self, uid: str, question_id: str, is_correct: bool) -> dict:
        """Traite une réponse et met à jour l'algorithme d'apprentissage espacé (SRS)."""
        progress = db.get_user_lms_progress(uid)
        
        # Initialisation de la queue SRS si absente
        if "srs_queue" not in progress:
            progress["srs_queue"] = {}

        now = datetime.now()
        q_stats = progress["srs_queue"].get(question_id, {
            "interval": 1, 
            "ease_factor": 2.5, 
            "next_review": now.isoformat()
        })

        if is_correct:
            # Succès : On augmente l'intervalle de révision (Science SuperMemo-2)
            new_interval = math.ceil(q_stats["interval"] * q_stats["ease_factor"])
            q_stats["interval"] = new_interval
            q_stats["ease_factor"] = min(3.0, q_stats["ease_factor"] + 0.1)
            q_stats["next_review"] = (now + timedelta(days=new_interval)).isoformat()
            
            # Gain d'XP dynamique
            xp_gained = 50 * q_stats["interval"]
            progress["xp"] += xp_gained
            message = f"Excellente réponse ! Prochaine révision dans {new_interval} jours. (+{xp_gained} XP)"
        else:
            # Échec : On réinitialise l'apprentissage (Pénalité)
            q_stats["interval"] = 1
            q_stats["ease_factor"] = max(1.3, q_stats["ease_factor"] - 0.2)
            q_stats["next_review"] = (now + timedelta(days=1)).isoformat()
            message = "Aïe... CORTEX exige l'excellence. Tu devras revoir cette notion demain."

        progress["srs_queue"][question_id] = q_stats
        
        # Level UP system (1000 XP = 1 Level)
        old_level = progress.get("level", 1)
        new_level = max(1, (progress["xp"] // 1000) + 1)
        progress["level"] = new_level
        
        level_up = (new_level > old_level)

        db.save_user_lms_progress(uid, progress)

        return {
            "success": is_correct,
            "message": message,
            "new_xp": progress["xp"],
            "level_up": level_up,
            "current_level": new_level
        }

    def get_daily_training(self, uid: str) -> list:
        """Génère la session du jour (L'Arène) basée sur les faiblesses passées."""
        progress = db.get_user_lms_progress(uid)
        srs_queue = progress.get("srs_queue", {})
        
        now = datetime.now()
        questions_due =[]

        all_questions = db.get_all_lms_questions()
        
        for q in all_questions:
            q_id = q["id"]
            if q_id in srs_queue:
                # La question a déjà été vue, est-elle due aujourd'hui ?
                next_rev = datetime.fromisoformat(srs_queue[q_id]["next_review"])
                if now >= next_rev:
                    questions_due.append(q)
            else:
                # Question jamais vue, on l'ajoute à la file
                if len(questions_due) < 5:
                    questions_due.append(q)

        return questions_due[:10] # On limite l'Arène à 10 combats par jour

academy_engine = CortexAcademy()
