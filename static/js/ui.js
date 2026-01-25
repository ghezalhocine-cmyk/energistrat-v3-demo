const app = {
    data: mockData,
    profiles: ProfileManager,
    
    ui: {
        currentTab: 'overview',

        refreshAll: function() {
            const profile = app.profiles.current;
            const def = app.profiles.getDef();
            const data = app.data[profile];

            // 1. Update Vocabulary Labels
            document.getElementById('lbl-budget').innerText = def.vocab.budget;
            document.getElementById('lbl-compliance').innerText = data.complianceLabel;
            document.getElementById('asset-label').innerText = def.vocab.asset;

            // 2. Update KPI Values
            document.getElementById('kpi-volume').innerHTML = `${data.volume} <span style="font-size:1rem; color:var(--c-text-muted)">MWh</span>`;
            document.getElementById('kpi-budget').innerHTML = `${data.budget} <span style="font-size:1rem; color:var(--c-text-muted)">k€</span>`;
            document.getElementById('kpi-compliance').innerText = data.compliance;

            // 3. Toggle Modules Visibility
            const toggle = (id, show) => {
                const el = document.getElementById(id);
                if(show) el.classList.remove('hidden'); else el.classList.add('hidden');
            };
            toggle('nav-rse', def.modules.rse);
            toggle('nav-game', def.modules.game);

            // 4. Render Tables & Charts
            this.renderAssetsTable(profile, def, data);
            this.renderAlerts(data.alerts);
            this.renderBenchmark(def.benchmarkRef);

            // 5. Update Cortex
            Cortex.update(this.currentTab);
        },

        switchTab: function(tabId) {
            this.currentTab = tabId;
            
            // UI Toggle
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            document.querySelector(`.nav-item[onclick="app.ui.switchTab('${tabId}')"]`).classList.add('active');
            
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.getElementById(`tab-${tabId}`).classList.add('active');

            // Title Update
            const titles = {
                overview: "Vue d'ensemble",
                conso: "Consommation",
                assets: app.profiles.getDef().vocab.asset,
                broker: "Courtage & Éthique",
                rse: "Réglementaire",
                game: "Challenges"
            };
            document.getElementById('page-title').innerText = titles[tabId];

            Cortex.update(tabId);
        },

        renderAssetsTable: function(profile, def, data) {
            // Header
            const thead = document.getElementById('assets-header');
            let headerHTML = `<th>${def.vocab.assetCol1}</th><th>Identifiant</th><th>Type</th><th>${def.vocab.assetCol3}</th>`;
            if(profile === 'OPH') headerHTML += `<th>DPE</th>`; // OPH Specific
            headerHTML += `<th>Statut</th>`;
            thead.innerHTML = headerHTML;

            // Body
            const tbody = document.querySelector('#assets-table tbody');
            tbody.innerHTML = '';
            data.assets.forEach(site => {
                let row = `<tr>
                    <td>${site.name}</td>
                    <td>${site.id}</td>
                    <td>${site.type}</td>
                    <td>${site.metric}</td>`;
                
                if(profile === 'OPH') {
                    let color = site.dpe === 'D' || site.dpe === 'E' ? 'var(--c-warning)' : 'var(--c-success)';
                    row += `<td style="font-weight:bold; color:${color}">${site.dpe}</td>`;
                }

                row += `<td><span class="status-pill status-${site.status}">${site.status === 'ok' ? 'Complet' : 'Attention'}</span></td></tr>`;
                tbody.innerHTML += row;
            });
            document.getElementById('asset-count').innerText = data.assets.length;
        },

        renderAlerts: function(alerts) {
            const table = document.getElementById('alerts-table');
            table.innerHTML = '';
            alerts.forEach(a => {
                table.innerHTML += `<tr>
                    <td>${a.site}</td>
                    <td>${a.msg}</td>
                    <td><span class="status-pill status-${a.level}">${a.level === 'warn' ? 'Action' : 'Info'}</span></td>
                </tr>`;
            });
        },

        renderBenchmark: function(refName) {
            const div = document.getElementById('benchmark-container');
            div.innerHTML = `
                <div>
                    <div style="display:flex; justify-content:space-between; font-size:0.8rem; margin-bottom:0.2rem;">
                        <span style="color:var(--c-success); font-weight:bold;">VOUS</span>
                        <span>185 €</span>
                    </div>
                    <div style="width:100%; height:6px; background:rgba(255,255,255,0.1); border-radius:3px;">
                        <div style="width:60%; height:100%; background:var(--c-success); border-radius:3px;"></div>
                    </div>
                </div>
                <div>
                    <div style="display:flex; justify-content:space-between; font-size:0.8rem; margin-bottom:0.2rem;">
                        <span style="color:var(--c-text-muted);">${refName}</span>
                        <span>210 €</span>
                    </div>
                    <div style="width:100%; height:6px; background:rgba(255,255,255,0.1); border-radius:3px;">
                        <div style="width:75%; height:100%; background:var(--c-warning); border-radius:3px;"></div>
                    </div>
                </div>
            `;
        }
    }
};