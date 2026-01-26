const SupplierRisk = {
    render: (container) => {
        container.innerHTML = `
            <div class="bento-grid">
                <!-- KPI 1 -->
                <div class="bento-card col-span-1 supplier-accent">
                    <div class="card-title">Volume YTD</div>
                    <div class="card-value">14.5 <span style="font-size:1rem; color:#94A3B8">GWh</span></div>
                    <div class="card-sub trend-down">▼ 1.2% vs Prev</div>
                </div>

                <!-- KPI 2 -->
                <div class="bento-card col-span-1">
                    <div class="card-title">Sites Critiques</div>
                    <div class="card-value" style="color: var(--c-danger)">3</div>
                    <div class="card-sub">Action requise</div>
                </div>

                <!-- CHART -->
                <div class="bento-card col-span-2 row-span-2">
                    <div class="card-title">Analyse Dérive (Forecast vs Real)</div>
                    <div class="chart-container">
                        <canvas id="riskChart"></canvas>
                    </div>
                </div>

                <!-- TABLE -->
                <div class="bento-card col-span-2 row-span-2">
                    <div class="card-title">Top Dérives Portefeuille</div>
                    <table class="data-table">
                        <thead>
                            <tr><th>Site</th><th>Segment</th><th>Drift</th><th>Statut</th></tr>
                        </thead>
                        <tbody>
                            ${SupplierRisk.rows()}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
        SupplierRisk.initChart();
    },

    rows: () => {
        return SupplierData.portfolio.map(s => `
            <tr>
                <td style="font-weight:bold">${s.name}</td>
                <td style="color:var(--c-text-muted)">${s.segment}</td>
                <td style="color:${s.drift > 0 ? 'var(--c-danger)' : 'var(--c-success)'}">${s.drift > 0 ? '+' : ''}${s.drift}%</td>
                <td><span class="status-pill ${s.status === 'OK' ? 'status-ok' : 'status-warn'}">${s.status}</span></td>
            </tr>
        `).join('');
    },

    initChart: () => {
        // ChartJS configuration simplifiée pour matcher le style sombre
        const ctx = document.getElementById('riskChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: ['J', 'F', 'M', 'A', 'M', 'J'],
                datasets: [{
                    label: 'Réel',
                    data: [12, 13, 11, 14, 13, 15],
                    borderColor: '#F97316',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    fill: true
                }, {
                    label: 'Prévision',
                    data: [12.5, 12.5, 12, 13, 13, 14],
                    borderColor: '#94A3B8',
                    borderDash: [5, 5]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { display: false }, ticks: { color: '#94A3B8' } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94A3B8' } }
                }
            }
        });
    }
};