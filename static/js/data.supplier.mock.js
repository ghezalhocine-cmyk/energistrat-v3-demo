const SupplierData = {
    portfolio: [
        { id: "S1", name: "Mairie St-Lys", segment: "Public", drift: -6.7, status: "WATCH", vol: "450 MWh" },
        { id: "S2", name: "Fonderie Albi", segment: "Indus", drift: +3.2, status: "OK", vol: "12 GWh" },
        { id: "S3", name: "OPH Habitat", segment: "Logement", drift: +14.2, status: "CRITICAL", vol: "2.1 GWh" }
    ],
    deals: [
        { id: "D1", client: "Syndicat Eaux 31", vol: "4.2 GWh", energy: "ELEC", score: 92, timer: "04:12:00" },
        { id: "D2", client: "Clinique Pasteur", vol: "850 MWh", energy: "GAZ", score: 78, timer: "23:59:00" }
    ],
    grids: [
        { name: "GRID_ELEC_Q1_26", date: "25/01/26", items: 450, status: "Active" },
        { name: "GRID_GAZ_DEC25", date: "15/12/25", items: 120, status: "Archived" }
    ]
};