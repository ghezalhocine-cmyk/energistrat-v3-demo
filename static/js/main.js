/**
 * ENERGISTRAT V3 - GLOBAL JAVASCRIPT
 * Gestion des interactions UI, Notifications et Utilitaires.
 */

const App = {
    // --- 1. SYSTÈME DE NOTIFICATIONS (TOASTS) ---
    // Remplace les alert() par des notifications élégantes
    toast: function(message, type = 'info') {
        // Création du conteneur si inexistant
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 10px;';
            document.body.appendChild(container);
        }

        // Configuration des couleurs selon le type
        const colors = {
            'info': 'border-blue-500 text-blue-400 bg-gray-900',
            'success': 'border-green-500 text-green-400 bg-gray-900',
            'error': 'border-red-500 text-red-400 bg-gray-900',
            'warn': 'border-yellow-500 text-yellow-400 bg-gray-900'
        };
        
        const icon = {
            'info': '<i class="fa-solid fa-circle-info"></i>',
            'success': '<i class="fa-solid fa-circle-check"></i>',
            'error': '<i class="fa-solid fa-triangle-exclamation"></i>',
            'warn': '<i class="fa-solid fa-bell"></i>'
        };

        const theme = colors[type] || colors['info'];

        // Création de la bulle
        const toast = document.createElement('div');
        toast.className = `flex items-center gap-3 px-4 py-3 rounded-lg border-l-4 shadow-2xl transform transition-all duration-300 translate-x-10 opacity-0 ${theme}`;
        toast.innerHTML = `
            <div class="text-lg">${icon[type] || icon['info']}</div>
            <div class="text-sm font-medium font-sans">${message}</div>
        `;

        container.appendChild(toast);

        // Animation Entrée
        requestAnimationFrame(() => {
            toast.classList.remove('translate-x-10', 'opacity-0');
        });

        // Suppression auto après 4 secondes
        setTimeout(() => {
            toast.classList.add('opacity-0', 'translate-x-10');
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    },

    // --- 2. FORMATAGE DES NOMBRES ---
    formatters: {
        currency: (value) => {
            return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' }).format(value);
        },
        number: (value) => {
            return new Intl.NumberFormat('fr-FR').format(value);
        },
        kwh: (value) => {
            return new Intl.NumberFormat('fr-FR').format(value) + ' kWh';
        }
    },

    // --- 3. UI HELPERS ---
    ui: {
        toggleSidebar: () => {
            const sidebar = document.querySelector('aside');
            if(sidebar) sidebar.classList.toggle('hidden');
        },
        
        // Effet de chargement sur un bouton
        setLoading: (btnElement, isLoading, text = 'Chargement...') => {
            if (isLoading) {
                btnElement.dataset.originalText = btnElement.innerHTML;
                btnElement.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin mr-2"></i> ${text}`;
                btnElement.disabled = true;
                btnElement.classList.add('opacity-75', 'cursor-not-allowed');
            } else {
                btnElement.innerHTML = btnElement.dataset.originalText;
                btnElement.disabled = false;
                btnElement.classList.remove('opacity-75', 'cursor-not-allowed');
            }
        }
    }
};

// Initialisation globale
document.addEventListener('DOMContentLoaded', () => {
    console.log('⚡ ENERGISTRAT V3 Core Loaded');
});
