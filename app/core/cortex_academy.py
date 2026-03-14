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
    et les Simulateurs de Vente (Battle Cards).
    """

    def __init__(self):
        self.version = "12.4"
        self._seed_curriculum_if_empty()

    def _seed_curriculum_if_empty(self):
        """Initialise les 7 Piliers dans Firestore si la base est vide."""
        if not db: return
        
        modules = db.get_all_lms_modules()
        if len(modules) > 0:
            return # Déjà initialisé

        logger.info("🟢 CORTEX ACADEMY : Seeding des 7 Piliers dans Firestore...")
        
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
            
        # Création d'une Battle Card d'exemple (Question type École de Vente)
        db.save_lms_question("Q_BATTLE_1", {
            "module_id": "MOD_6",
            "type": "BATTLE_CARD",
            "scenario": "Le DAF d'une industrie de plasturgie (3 sites) vous dit : 'Je suis déjà géré par un courtier, c'est gratuit et je n'ai pas le budget pour un SaaS'.",
            "options":[
                {"id": "A", "text": "Notre SaaS n'est pas si cher, je peux vous faire une remise de 20%.", "is_correct": False, "feedback": "Erreur (Vendeur de tapis) : Tu as baissé ton pantalon sur le prix sans défendre la valeur."},
                {"id": "B", "text": "Le courtage n'est pas gratuit, il prend des marges. Nous sommes meilleurs.", "is_correct": False, "feedback": "Erreur (Agressif) : Tu attaques son choix actuel frontalement. Il va se braquer."},
                {"id": "C", "text": "Je comprends. Si je vous montre, données à l'appui, que les marges cachées de ce courtage vous coûtent 3x le prix de notre SaaS tout en vous privant de vos data, m'accordez-vous 10 min ?", "is_correct": True, "feedback": "Parfait (Tiers de Confiance) : Recadrage financier (ROI) et curiosité piquée."}
            ]
        })

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
            message = "Aïe... La réglementation est stricte. Tu devras revoir cette notion demain."

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
                # Question jamais vue, on l'ajoute à la file (max 5 nouvelles par jour)
                if len(questions_due) < 5:
                    questions_due.append(q)

        return questions_due[:10] # On limite l'Arène à 10 combats par jour

academy_engine = CortexAcademy()
