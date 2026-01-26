const SupplierUI = {
    init: () => {
        SupplierUI.switchTab('risk');
    },

    switchTab: (tabId) => {
        // MAJ Navigation
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        document.getElementById(`nav-${tabId}`).classList.add('active');
        
        // MAJ Titre
        const titles = {
            'risk': 'Pilotage du Risque',
            'deals': 'Flash Market',
            'pricing': 'Gestion des Barèmes'
        };
        document.getElementById('page-title').innerText = titles[tabId];

        // Rendu Contenu
        const container = document.getElementById('content-area');
        container.innerHTML = '';
        
        if(tabId === 'risk') SupplierRisk.render(container);
        if(tabId === 'deals') SupplierDeals.render(container);
        if(tabId === 'pricing') SupplierPricing.render(container);

        // MAJ Cortex
        SupplierUI.updateCortex(tabId);
    },

    updateCortex: (context) => {
        const feed = document.getElementById('cortex-feed');
        let html = '';
        
        if(context === 'risk') {
            html += `<div class="insight-card"><strong>⚠️ Alerte Dérive</strong>OPH Habitat dépasse son CAR de +14%. Risque pénalité réseau.</div>`;
            html += `<div class="insight-card"><strong>🧠 Conseil Stratégique</strong>Proposez un avenant de volume pour sécuriser la marge sur l'Industrie.</div>`;
        } else if (context === 'deals') {
            html += `<div class="insight-card"><strong>⚡ Opportunité</strong>Syndicat Eaux 31 : Client historique fiable. Prix cible conseillé : 142€/MWh.</div>`;
        } else {
            html += `<div class="insight-card"><strong>✅ Conformité</strong>Vos barèmes Q1-2026 sont actifs et valides.</div>`;
        }
        
        feed.innerHTML = html;
    }
};