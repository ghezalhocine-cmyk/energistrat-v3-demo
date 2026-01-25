const ProfileManager = {
    current: 'PME', // Default

    definitions: {
        PME: {
            vocab: { budget: "Budget Annuel", asset: "Sites", assetCol1: "Site", assetCol3: "Surface" },
            modules: { rse: true, game: true },
            benchmarkRef: "Marché Moyen"
        },
        OPH: {
            vocab: { budget: "Charges Énergie", asset: "Résidences", assetCol1: "Résidence", assetCol3: "Nb Logements" },
            modules: { rse: true, game: true },
            benchmarkRef: "Prix Repère Gaz"
        },
        PARTICULIER: {
            vocab: { budget: "Facture Annuelle", asset: "Logement", assetCol1: "Lieu", assetCol3: "Surface" },
            modules: { rse: false, game: false }, // Hide complex modules
            benchmarkRef: "TRV Électricité"
        }
    },

    setProfile: function(profileKey) {
        this.current = profileKey;
        app.ui.refreshAll();
    },

    getDef: function() {
        return this.definitions[this.current];
    }
};