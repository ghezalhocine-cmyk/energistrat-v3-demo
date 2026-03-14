import uuid
import sys
from datetime import datetime

# Import du connecteur Firestore CORTEX (Zero Mock)
try:
    from app.core.cortex_db import db
except ImportError:
    try:
        from core.cortex_db import db
    except ImportError:
        print("🔴 ERREUR : Impossible de trouver cortex_db. Assurez-vous d'être à la racine du projet.")
        sys.exit(1)

def seed_ultimate_payload():
    print("🟢 CORTEX ACADEMY : Initialisation du Payload Pédagogique Ultime...")

    if not db or not db.db:
        print("🔴 ERREUR : Base Firestore non connectée.")
        sys.exit(1)

    # LA BIBLIOTHÈQUE D'EXPERTISE (12 SCÉNARIOS DE CLASSE ENTREPRISE)
    questions =[
        # ==========================================
        # PILIER 1 : GÉOPOLITIQUE & MARCHÉS (NIVEAU 1 & 3)
        # ==========================================
        {
            "id": "Q_GEO_2026_01",
            "module_id": "MOD_1",
            "type": "SCÉNARIO DE CRISE",
            "scenario": "Mars 2026. Le détroit d'Ormuz est sous blocus suite à l'escalade militaire USA/Iran. Le GNL (Gaz Naturel Liquéfié) qatari ne passe plus. Votre client (Industrie lourde) voit le PEG exploser et son contrat finit dans 2 mois. Que lui conseillez-vous ?",
            "options":[
                {
                    "id": "A",
                    "text": "Attendre le mois prochain. La géopolitique se calme toujours et les prix redescendront.",
                    "is_correct": False,
                    "feedback": "Erreur fatale (Spéculation). Un Tiers de Confiance ne joue pas au casino avec le budget d'une usine. Attendre sans filet est suicidaire."
                },
                {
                    "id": "B",
                    "text": "Fixer 100% de son volume sur 3 ans immédiatement pour bloquer la casse avant que ça ne monte plus haut.",
                    "is_correct": False,
                    "feedback": "Erreur (Achat de panique). Fixer 100% au plus haut d'une crise, c'est condamner le client à payer le prix fort pendant 3 ans même si la guerre s'arrête demain."
                },
                {
                    "id": "C",
                    "text": "Couvrir 30% du volume de base en prix fixe (SWAP) pour sécuriser le talon, et laisser le reste indexé au SPOT avec des alertes CORTEX pour fixer par 'Clics' dès que les méthaniers US compenseront l'offre.",
                    "is_correct": True,
                    "feedback": "Parfait (Stratégie de Couverture). Tu lisses le risque financier (Risk Management) tout en gardant des fenêtres de tir si le marché se détend. C'est la posture CORTEX."
                }
            ]
        },
        {
            "id": "Q_MKT_MERIT_01",
            "module_id": "MOD_3",
            "type": "TECHNIQUE MARCHÉ",
            "scenario": "Un client vous demande : 'Pourquoi le prix de mon électricité augmente alors que la France produit 70% de nucléaire ? C'est une arnaque !' Comment expliquez-vous le mécanisme européen ?",
            "options":[
                {
                    "id": "A",
                    "text": "C'est le mécanisme du 'Merit Order'. Le prix de gros de l'électricité est fixé par la dernière centrale appelée pour équilibrer le réseau, souvent une centrale à gaz. Si le gaz flambe, l'électricité flambe.",
                    "is_correct": True,
                    "feedback": "Excellente réponse. Pédagogique et techniquement irréprochable. Le Merit Order (coût marginal) est la base de la formation des prix européens."
                },
                {
                    "id": "B",
                    "text": "C'est à cause de l'ARENH qui force EDF à vendre à perte à ses concurrents, ce qui détruit le marché français.",
                    "is_correct": False,
                    "feedback": "Attention. Même si l'ARENH a eu des effets pervers, ce n'est pas le mécanisme qui fixe le prix de gros sur le marché SPOT européen (Epex Spot)."
                },
                {
                    "id": "C",
                    "text": "C'est parce que les courtiers et les fournisseurs prennent trop de marges sur le dos des consommateurs.",
                    "is_correct": False,
                    "feedback": "Erreur (Démagogie). C'est un discours de café du commerce, pas d'un auditeur ENERGISTRAT. Reste technique."
                }
            ]
        },

        # ==========================================
        # PILIER 2 : RÉGLEMENTATION (TURPE, CSPE, M57) (NIVEAU 2)
        # ==========================================
        {
            "id": "Q_REG_TURPE_01",
            "module_id": "MOD_2",
            "type": "AUDIT FACTURE",
            "scenario": "Vous analysez la facture Enedis d'une PME fonctionnant en 2x8 (forte consommation en Heures Creuses). Vous remarquez que sa version tarifaire (TURPE) est en 'Courte Utilisation' (CU). Que déduisez-vous ?",
            "options":[
                {
                    "id": "A",
                    "text": "C'est normal, c'est une PME, la Longue Utilisation (LU) est réservée à la grande industrie.",
                    "is_correct": False,
                    "feedback": "Faux. Le choix CU/MU/LU dépend du ratio de consommation (durée d'utilisation de la puissance), pas de la taille de l'entreprise."
                },
                {
                    "id": "B",
                    "text": "Il y a une anomalie probable. Avec une forte conso en Heures Creuses, il devrait sûrement être en Moyenne (MU) ou Longue Utilisation (LU). Je peux générer des milliers d'euros de ROI en demandant un changement à Enedis.",
                    "is_correct": True,
                    "feedback": "Exact ! Une entreprise qui tourne la nuit ou en continu a tout intérêt à payer un abonnement de puissance plus cher (LU) pour avoir une part proportionnelle (électron) drastiquement moins chère. Optimisation validée."
                },
                {
                    "id": "C",
                    "text": "La version tarifaire n'a aucun impact financier, seul le prix du KWh fournisseur compte.",
                    "is_correct": False,
                    "feedback": "Hérésie. L'acheminement (TURPE) représente environ 30% de la facture totale. L'ignorer, c'est faire la moitié de son travail."
                }
            ]
        },
        {
            "id": "Q_REG_PUBLIC_01",
            "module_id": "MOD_2",
            "type": "SECTEUR PUBLIC",
            "scenario": "Rendez-vous avec une Mairie. Le budget énergie explose sous la nomenclature comptable M57. Sur quelle taxe énergétique pouvez-vous souvent récupérer des fonds rétroactivement pour une commune ?",
            "options":[
                {
                    "id": "A",
                    "text": "La TVA, en demandant un taux réduit à 5,5% sur toute la facture.",
                    "is_correct": False,
                    "feedback": "Faux. La TVA à 5,5% ne s'applique que sur l'abonnement et la CTA, pas sur la consommation."
                },
                {
                    "id": "B",
                    "text": "La CTA (Contribution Tarifaire d'Acheminement), car les mairies en sont exonérées.",
                    "is_correct": False,
                    "feedback": "Faux. Personne n'est exonéré de la CTA, elle finance les retraites des agents des IEG (EDF/GDF)."
                },
                {
                    "id": "C",
                    "text": "La CSPE (TICFE). Selon les activités de la commune (ex: éclairage public, centres sportifs), elle peut bénéficier de taux réduits ou d'exonérations avec rétroactivité sur 2 à 3 ans.",
                    "is_correct": True,
                    "feedback": "Bingo ! C'est le 'Golden Ticket' pour signer une mairie. Tu récupères du cash du Trésor Public pour eux, ils te perçoivent comme un sauveur, et tu finances le SaaS ENERGISTRAT avec ce ROI."
                }
            ]
        },

        # ==========================================
        # PILIER 3 : ÉCOSYSTÈME & COURTAGE (NIVEAU 4)
        # ==========================================
        {
            "id": "Q_ECO_BROKER_01",
            "module_id": "MOD_4",
            "type": "CORTEX ETHICS",
            "scenario": "Comment un courtier en énergie 'gratuit' gagne-t-il réellement sa vie, et comment l'expliquer à un prospect pour détruire son offre ?",
            "options":[
                {
                    "id": "A",
                    "text": "Il est payé par l'État via des subventions de la CRE (Commission de Régulation de l'Énergie).",
                    "is_correct": False,
                    "feedback": "Absolument faux. La CRE ne finance aucun intermédiaire privé."
                },
                {
                    "id": "B",
                    "text": "Il ajoute une marge cachée (commission) dans le prix du KWh proposé par le fournisseur. Le client paie le courtier à son insu chaque mois via sa facture, souvent sans plafond.",
                    "is_correct": True,
                    "feedback": "C'est la faille du système ! Un courtier qui met 2€/MWh de marge sur un industriel qui consomme 10 GWh va lui prendre 20 000€ par an en silence. Notre SaaS coûte une fraction de ce prix en toute transparence."
                },
                {
                    "id": "C",
                    "text": "Il vend les données personnelles du client à des entreprises de panneaux solaires.",
                    "is_correct": False,
                    "feedback": "Même si certains font du cross-selling, la source de revenus massive (90%) reste la marge cachée dans l'électron."
                }
            ]
        },

        # ==========================================
        # PILIER 4 : ÉCOLE DE VENTE / CLOSING (NIVEAU 6)
        # ==========================================
        {
            "id": "Q_SALES_MEDDIC_01",
            "module_id": "MOD_6",
            "type": "BATTLE CARD (OBJECTION)",
            "scenario": "Rendez-vous de découverte (MEDDIC). Le responsable technique vous dit : 'Je n'ai pas le temps de me connecter à un énième logiciel SaaS pour regarder des graphiques.' Quelle est votre parade (SPIN Selling) ?",
            "options":[
                {
                    "id": "A",
                    "text": "Je comprends, mais notre interface est très belle et facile à utiliser, cela ne prendra que 5 minutes par jour.",
                    "is_correct": False,
                    "feedback": "Erreur (Justification molle). Tu essaies de lui vendre le design. Il n'en a rien à faire, il n'a pas le temps."
                },
                {
                    "id": "B",
                    "text": "Notre logiciel s'appelle CORTEX Sentinel. Il tourne tout seul en arrière-plan. Vous ne vous connectez pas. C'est lui qui vous envoie un SMS automatique si vous dépassez votre Puissance Souscrite ou si le marché chute pour acheter. C'est l'anti-logiciel, c'est un bouclier autonome.",
                    "is_correct": True,
                    "feedback": "Exceptionnel ! Tu as transformé son objection 'pas le temps' en argument 'automatisation/délégation'. C'est le principe même du Tiers de Confiance."
                },
                {
                    "id": "C",
                    "text": "Dans ce cas, je peux vous appeler personnellement tous les mois pour vous faire le résumé de vos consommations.",
                    "is_correct": False,
                    "feedback": "Mauvais. Tu te transformes en assistant personnel non scalable. L'objectif est de vendre la puissance du SaaS, pas ton temps d'esclave."
                }
            ]
        },
        {
            "id": "Q_SALES_CHAMPION_01",
            "module_id": "MOD_6",
            "type": "BATTLE CARD (MEDDIC)",
            "scenario": "Fin du premier RDV avec l'Acheteur Énergie (votre 'Champion'). Il adore ENERGISTRAT, mais il vous dit : 'Le DAF (Economic Buyer) est très dur, il va bloquer car il refuse toute nouvelle dépense logicielle.' Que faites-vous ?",
            "options":[
                {
                    "id": "A",
                    "text": "Vous lui proposez une période d'essai gratuite de 3 mois pour contourner le DAF.",
                    "is_correct": False,
                    "feedback": "Faux. Le gratuit n'a pas de valeur (sauf freemium calculé). Tu repousses l'échéance sans traiter le problème."
                },
                {
                    "id": "B",
                    "text": "Vous abandonnez. Si le DAF bloque, le deal est mort.",
                    "is_correct": False,
                    "feedback": "Attitude de perdant. 80% des ventes B2B Enterprise font face à un DAF réticent au départ."
                },
                {
                    "id": "C",
                    "text": "Vous dites : 'Armons-nous ensemble. Donnez-moi vos factures Enedis. Je vais faire passer CORTEX dessus. Demain, on présente au DAF un rapport montrant que le SaaS s'autofinance en 2 mois via l'optimisation des pénalités de dépassement.'",
                    "is_correct": True,
                    "feedback": "Méthodologie MEDDIC parfaite. Tu utilises ton Champion pour accéder aux 'Metrics' (données), afin de prouver le ROI (retour sur investissement) à l'Economic Buyer."
                }
            ]
        },

        # ==========================================
        # PILIER 5 : PROSPECTIVE & AVENIR (NIVEAU 7)
        # ==========================================
        {
            "id": "Q_FUTUR_CPPA_01",
            "module_id": "MOD_7",
            "type": "PROSPECTIVE VNU",
            "scenario": "Un Directeur Industriel très avancé vous parle de sa volonté de signer un 'Corporate PPA' (Power Purchase Agreement) solaire sur 15 ans. Pourquoi ENERGISTRAT est indispensable pour lui ?",
            "options":[
                {
                    "id": "A",
                    "text": "Parce qu'un parc solaire ne produit pas d'électricité la nuit. ENERGISTRAT va modéliser sa Courbe de Charge (via Data Unity) pour dimensionner la part exacte de son talon qui doit rester chez un fournisseur classique, évitant un déséquilibre financier massif.",
                    "is_correct": True,
                    "feedback": "Niveau Expert (Masterclass). Un PPA mal dimensionné = l'entreprise paie de l'énergie solaire en trop l'été (revendue à perte) et rachète au prix fort la nuit. CORTEX est le seul outil capable de faire ce 'profilage' heure par heure sur 15 ans."
                },
                {
                    "id": "B",
                    "text": "Pour rien, un CPPA se gère directement entre le producteur solaire et l'usine, le SaaS ne sert à rien ici.",
                    "is_correct": False,
                    "feedback": "Erreur de débutant. L'intégration d'un PPA dans un budget énergétique (le 'Sleeving') est un cauchemar comptable que seul un SaaS lourd peut monitorer."
                },
                {
                    "id": "C",
                    "text": "Parce qu'ENERGISTRAT fabrique et installe les panneaux solaires.",
                    "is_correct": False,
                    "feedback": "Faux. Nous sommes un éditeur SaaS / Tiers de Confiance / Courtier 2.0, pas un EPC (installateur)."
                }
            ]
        }
    ]

    saved_count = 0
    for q in questions:
        success = db.save_lms_question(q["id"], q)
        if success:
            saved_count += 1
            print(f"✅ Injecté : {q['id']} ({q['type']})")

    print(f"🔥 MISSION ACCOMPLIE : {saved_count}/{len(questions)} Scénarios de formation ENERGISTRAT déployés dans Firestore.")
    print("Le Campus est maintenant armé pour transformer des débutants en Snipers de l'énergie.")

if __name__ == "__main__":
    seed_ultimate_payload()
