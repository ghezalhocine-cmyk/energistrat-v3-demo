const Cortex = {
    insights: {
        PME: {
            overview: "<strong>Situation Maîtrisée</strong><br>Votre consommation industrielle est stable. Attention au dépassement de puissance sur l'Usine Sud.",
            broker: "<strong>Conseil Stratégique</strong><br>Les marchés à terme 2027 baissent. C'est le moment de lancer un appel d'offres anticipé."
        },
        OPH: {
            overview: "<strong>Focus Charges</strong><br>La Tour Kennedy consomme 15% de plus que la moyenne de votre parc. Vérifiez la régulation chaufferie.",
            broker: "<strong>Achat Groupé</strong><br>Pour vos 1200 logements, nous pouvons négocier un contrat unique multi-sites pour réduire les coûts de gestion."
        },
        PARTICULIER: {
            overview: "<strong>Économies</strong><br>Vous avez consommé moins que l'année dernière ! Bravo.",
            broker: "<strong>Protection Prix</strong><br>Votre offre actuelle est inférieure au Tarif Réglementé (TRV). Ne changez rien."
        }
    },

    update: function(tabId) {
        const container = document.getElementById('cortex-messages');
        const profile = ProfileManager.current;
        
        // Default generic message if specific insight missing
        let msg = this.insights[profile][tabId] || 
                 `<strong>Analyse CORTEX</strong><br>J'analyse vos données ${ProfileManager.getDef().vocab.asset.toLowerCase()} pour optimiser votre budget.`;

        container.innerHTML = `<div class="insight-card">${msg}</div>`;
        
        // Add Mandatory Regulatory Disclaimer for Pros
        if (profile !== 'PARTICULIER') {
            container.innerHTML += `<div style="font-size:0.7rem; color:var(--c-text-muted); margin-top:1rem;">Données conservées 5 ans (Conformité légale).</div>`;
        }
    }
};