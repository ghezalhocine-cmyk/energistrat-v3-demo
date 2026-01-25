window.addEventListener('DOMContentLoaded', () => {
    // Init Chart (visual placeholder)
    const bars = document.getElementById('overview-chart');
    if (bars) {
        [40, 60, 45, 70, 55, 80].forEach((h, i) => {
            const b = document.createElement('div'); b.className='bar'; 
            setTimeout(()=>b.style.height=h+'%', i*100);
            bars.appendChild(b);
        });
    }
    
    // Start App
    if (typeof app !== 'undefined' && app.ui) {
        app.ui.refreshAll(); // Loads default profile (PME)
    } else {
        console.error("ENERGISTRAT ERROR: 'app' module not loaded correctly.");
    }
});