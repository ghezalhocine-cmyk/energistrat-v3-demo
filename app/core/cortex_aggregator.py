import pandas as pd
import numpy as np
import holidays
import io
import os
import json
from datetime import datetime

class CortexAggregator:
    """
    CORTEX AGGREGATOR V3 - PRODUCTION READY
    Génération courbe SGE 3 Ans / Pas 60 min (Standard Marché).
    Architecture : "Skeleton First" pour éviter les erreurs d'alignement temporel.
    """

    def __init__(self):
        # On pré-charge les jours fériés sur une large plage pour couvrir N+3
        # Cela évite les erreurs si on dépasse l'année en cours
        self.fr_holidays = holidays.France(years=range(2024, 2030))
        self.base_dir = os.getcwd()
        self.data_dir = os.path.join(self.base_dir, "data")

    def get_site_dna(self, site_id):
        """Récupère les paramètres physiques du site (ADN)."""
        if not site_id: return None
        
        clean_id = str(site_id).replace('/', '_').replace(' ', '_').strip()
        path = os.path.join(self.data_dir, f"{clean_id}.json")
        
        if not os.path.exists(path): return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            kpis = data.get('kpis', {})
            
            # On sécurise les valeurs pour éviter les calculs sur None
            pmax = float(kpis.get('pmax_kw', 0))
            talon = float(kpis.get('talon_kw', 0))
            
            # Si pas de données physiques, on met des valeurs par défaut minimales
            if pmax == 0: pmax = 100.0
            if talon == 0: talon = 20.0
            
            return {
                "pmax": pmax,
                "talon": talon
            }
        except: return None

    def aggregate_sites(self, site_ids, years=3):
        """
        Point d'entrée : Génère l'agrégat des courbes.
        """
        # 1. Définition du Calendrier Maître (Le Squelette)
        # Du 1er Janvier N+1 au 31 Décembre N+Years
        next_year = datetime.now().year + 1
        start_date = datetime(next_year, 1, 1, 0, 0)
        end_date = datetime(next_year + years - 1, 12, 31, 23, 0)
        
        # On crée une Série vide alignée sur le calendrier final (Pas 60 min)
        # C'est la clé pour éviter les bugs de concaténation et les trous
        master_index = pd.date_range(start=start_date, end=end_date, freq='1H')
        global_load = pd.Series(0.0, index=master_index)
        
        sites_processed = 0

        # 2. Boucle d'addition
        for site_id in site_ids:
            dna = self.get_site_dna(site_id)
            if not dna: continue
            
            # Génération de la courbe du site
            site_curve = self._generate_curve(master_index, dna)
            
            # Addition vectorielle (rapide et sûre)
            global_load = global_load.add(site_curve, fill_value=0)
            sites_processed += 1

        if sites_processed == 0: return None

        # 3. Export au format SGE
        return self._format_sge(global_load)

    def _generate_curve(self, index, dna):
        """Calcule la puissance pour un site donné sur l'index fourni."""
        df = pd.DataFrame(index=index)
        df['weekday'] = df.index.weekday
        df['hour'] = df.index.hour
        
        # Détection Fériés (Vectorisée via map pour rapidité)
        # On convertit l'index en date simple pour comparer avec holidays
        # C'est ici que la librairie holidays est critique
        is_holiday = df.index.normalize().map(lambda x: x in self.fr_holidays)
        is_weekend = df['weekday'] >= 5
        
        # Jours Ouvrés = Ni Weekend, Ni Férié
        is_working_day = ~(is_weekend | is_holiday)
        
        # Heures Ouvrées (7h-19h)
        is_active_hour = (df['hour'] >= 7) & (df['hour'] <= 19)
        
        # Masque d'activité (Quand l'usine tourne)
        mask_active = is_working_day & is_active_hour
        
        # Initialisation au Talon (Nuit/WE)
        df['power'] = dna['talon']
        
        # Ajout de la charge sur les heures actives
        # Formule : Talon + 85% du delta Pmax (Foisonnement)
        delta_load = (dna['pmax'] - dna['talon']) * 0.85
        
        # Bruit aléatoire (5%) pour simuler la vie réelle
        noise = np.random.normal(1.0, 0.05, size=len(df))
        
        # Application de la charge
        df.loc[mask_active, 'power'] = (dna['talon'] + delta_load)
        
        # Application du bruit partout
        df['power'] = df['power'] * noise
        
        # Sécurité : Pas de puissance négative
        df['power'] = df['power'].clip(lower=0)
        
        return df['power']

    def _format_sge(self, series):
        """Formatage strict SGE pour ré-import."""
        output = io.StringIO()
        
        # Header Enedis Standard
        output.write("Identifiant PRM;Date de debut;Date de fin;Grandeur physique;Grandeur metier;Etape metier;Unite;Horodate;Valeur;Nature;Pas;Indice de qualite;Etat compl.\n")
        
        # Nettoyage des NaNs (CRITIQUE pour éviter le crash .astype(int))
        series = series.fillna(0)
        
        # Conversion kW -> Watts (Standard SGE)
        vals_w = (series * 1000).astype(int)
        
        # Écriture ligne à ligne
        for ts, val in vals_w.items():
            ts_str = ts.isoformat()
            # PT60M = Pas Horaire
            line = f"AGGREGAT_VIRTUEL;;;PA;CONS;BEST;W;{ts_str};{val};R;PT60M;;\n"
            output.write(line)
            
        return output.getvalue()

aggregator = CortexAggregator()
