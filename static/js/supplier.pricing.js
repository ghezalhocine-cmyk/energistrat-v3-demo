const SupplierPricing = {
    render: (container) => {
        container.innerHTML = `
            <div class="bento-grid">
                <div class="bento-card col-span-4">
                    <div class="upload-zone">
                        <div style="font-size:2rem; margin-bottom:1rem;">📂</div>
                        <div style="font-weight:bold; margin-bottom:0.5rem;">Déposer une nouvelle grille tarifaire</div>
                        <div style="color:var(--c-text-muted); font-size:0.8rem;">Format .XLSX ou .CSV (Modèle V3)</div>
                    </div>
                </div>

                <div class="bento-card col-span-4">
                    <div class="card-title">Historique des Barèmes</div>
                    <table class="data-table">
                        <thead>
                            <tr><th>Nom Fichier</th><th>Date</th><th>Lignes</th><th>Statut</th><th>Action</th></tr>
                        </thead>
                        <tbody>
                            ${SupplierPricing.rows()}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    },

    rows: () => {
        return SupplierData.grids.map(g => `
            <tr>
                <td style="font-family:monospace;">${g.name}</td>
                <td>${g.date}</td>
                <td>${g.items}</td>
                <td><span class="status-pill ${g.status === 'Active' ? 'status-ok' : ''}" style="${g.status !== 'Active' ? 'background:#334155; color:#94A3B8' : ''}">${g.status}</span></td>
                <td><a href="#" style="color:var(--c-cyan); text-decoration:none;">⬇️</a></td>
            </tr>
        `).join('');
    }
};