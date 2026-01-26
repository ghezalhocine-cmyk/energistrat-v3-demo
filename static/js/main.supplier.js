document.addEventListener('DOMContentLoaded', () => {
    if (typeof SupplierUI !== 'undefined') {
        SupplierUI.init();
    } else {
        console.error("Erreur chargement modules Supplier");
    }
});