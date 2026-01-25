const mockData = {
    PME: {
        volume: 482,
        budget: 92.4,
        compliance: "B+",
        complianceLabel: "Conformité Tertiaire",
        assets: [
            { name: "Siège Social", id: "PDL-001", type: "Bureaux", metric: "1200 m²", status: "ok" },
            { name: "Usine Sud", id: "PDL-002", type: "Industrie", metric: "4500 m²", status: "warn" }
        ],
        alerts: [
            { site: "Usine Sud", msg: "Dépassement Puissance", level: "warn" },
            { site: "Siège", msg: "Facture Février dispo", level: "ok" }
        ]
    },
    OPH: {
        volume: 1250,
        budget: 310, // k€
        compliance: "C",
        complianceLabel: "DPE Moyen Parc",
        assets: [
            { name: "Résidence Les Lilas", id: "PCE-999", type: "Collectif", metric: "45 Logements", status: "ok", dpe: "D" },
            { name: "Tour Kennedy", id: "PDL-888", type: "IGH", metric: "120 Logements", status: "warn", dpe: "E" },
            { name: "Le Parc", id: "PDL-777", type: "Pavillonnaire", metric: "12 Logements", status: "ok", dpe: "C" }
        ],
        alerts: [
            { site: "Tour Kennedy", msg: "Anomalie Chaufferie (GTB)", level: "warn" },
            { site: "Les Lilas", msg: "Régularisation Charges", level: "ok" }
        ]
    },
    PARTICULIER: {
        volume: 8.5, // MWh
        budget: 1.8, // k€
        compliance: "A",
        complianceLabel: "Mon DPE",
        assets: [
            { name: "Maison Principale", id: "PDL-123", type: "Résidentiel", metric: "110 m²", status: "ok" }
        ],
        alerts: [
            { site: "Maison", msg: "Relevé Enedis validé", level: "ok" }
        ]
    }
};