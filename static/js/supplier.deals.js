const SupplierDeals = {
    render: (container) => {
        container.innerHTML = `
            <div class="bento-grid">
                <div class="bento-card col-span-4 flash-accent" style="flex-direction:row; align-items:center; justify-content:space-between;">
                    <div>
                        <div class="card-title" style="color:var(--c-cyan)">LIVE MARKET</div>
                        <div style="font-size:1.2rem; font-weight:bold;">2 Opportunités actives</div>
                    </div>
                    <div style="text-align:right;">
                        <div class="card-title">Volume Dispo</div>
                        <div class="card-value">5.1 GWh</div>
                    </div>
                </div>
                ${SupplierDeals.cards()}
            </div>
        `;
    },

    cards: () => {
        return SupplierData.deals.map(d => `
            <div class="bento-card col-span-2">
                <div style="display:flex; justify-content:space-between; margin-bottom:1rem;">
                    <span class="status-pill" style="background:var(--c-abysse); border:1px solid var(--c-cyan); color:var(--c-cyan);">${d.energy}</span>
                    <span style="color:var(--c-danger); font-weight:bold; font-family:monospace;">⏱ ${d.timer}</span>
                </div>
                <h3 style="font-size:1.2rem; font-weight:bold; margin-bottom:0.5rem;">${d.client}</h3>
                <div style="color:var(--c-text-muted); margin-bottom:1.5rem;">Volume: ${d.vol} • Score: ${d.score}/100</div>
                
                <div style="display:flex; gap:1rem; margin-top:auto;">
                    <button class="action-btn secondary" style="flex:1">Ignorer</button>
                    <button class="action-btn supplier" style="flex:1">Se Positionner</button>
                </div>
            </div>
        `).join('');
    }
};