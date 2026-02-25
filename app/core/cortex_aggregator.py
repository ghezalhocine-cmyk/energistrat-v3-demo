import pandas as pd
import numpy as np
import holidays
import io
import os
import json
from datetime import datetime, timedelta

class CortexAggregator:
    """
    CORTEX AGGREGATOR
    Génère des courbes de charge prévisionnelles multi-sites (N+1, N+2, N+3)
    en respectant le calendrier français (Fériés, Week-ends).
    Agrège le tout en un "PDL Virtuel" au format SGE.
    """

    def __init__(self):
        self.fr_holidays = holidays.France()
        self.base_dir = os.getcwd()
        self.data_dir = os.path.join(self.base_dir, "data")

    def get_site_dna(self, site_id):
        """Récupère l'ADN énergétique du site (Talon, Pmax, Profil)."""
        # Nettoyage ID
        clean_id = site_id.replace('/', '_').replace(' ', '_').strip()
        path = os.path.join(self.data_dir, f"{clean_id}.json")
        
        if not os.path.exists(path):
            return None

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        kpis = data.get('kpis', {})
        return {
            "name": data.get('identity', {}).get('site_name', 'Site Inconnu'),
            "pdl": data.get('contract', {}).get('pdl', '000000'),
            "pmax": float(kpis.get('pmax_kw', 100)),
            "talon": float(kpis.get('talon_kw', 20)),
            "typologie": data.get('location', {}).get('typologie', 'Indus')
        }

    def generate_curve_for_site(self, dna, start_date, end_date):
        """
        Génère une courbe 10min réaliste sur la période donnée
        en fonction du calendrier (Ouvré vs Férié/WE).
        """
        # Création de l'index temporel (10 min)
        dates = pd.date_range(start=start_date, end=end_date, freq='10T')
        df = pd.DataFrame(index=dates)
        
        # Détection du type de jour
        # 0=Lundi ... 6=Dimanche
        df['weekday'] = df.index.weekday
        df['hour'] = df.index.hour
        
        # Fonction rapide pour détecter les fériés
        def is_off_day(ts):
            if ts.weekday() >= 5: return True # Samedi Dimanche
            if ts.date() in self.fr_holidays: return True # Férié
            return False

        # On applique la logique vectorielle (plus rapide)
        # 1. Par défaut : Tout est au Talon
        df['power'] = dna['talon']

        # 2. Jours Ouvrés (Lundi-Vendredi, hors fériés)
        # On ne peut pas vectoriser facilement holidays(), on fait une map
        date_series = df.index.normalize() # Juste la date
        unique_dates = date_series.unique()
        off_days = {d: (d in self.fr_holidays or d.weekday() >= 5) for d in unique_dates}
        
        df['is_off'] = df.index.normalize().map(off_days)

        # 3. Application du Profil d'Activité (Heures ouvrées 7h-19h)
        # Si Jour Ouvré ET Heure entre 7h et 19h -> On monte vers Pmax
        mask_active = (~df['is_off']) & (df['hour'] >= 7) & (df['hour'] <= 19)
        
        # On ajoute un peu de "bruit" aléatoire pour faire réaliste
        noise = np.random.normal(1.0, 0.05, size=len(df)) # +/- 5%
        
        df.loc[mask_active, 'power'] = (dna['talon'] + (dna['pmax'] - dna['talon']) * 0.85) * noise[mask_active]

        return df['power']

    def aggregate_sites(self, site_ids, years=3):
        """
        Point d'entrée principal.
        """
        start_date = datetime(datetime.now().year + 1, 1, 1) # 1er Janv N+1
        end_date = datetime(datetime.now().year + years, 12, 31, 23, 50)
        
        global_curve = None
        
        for site_id in site_ids:
            dna = self.get_site_dna(site_id)
            if not dna: continue
            
            site_curve = self.generate_curve_for_site(dna, start_date, end_date)
            
            if global_curve is None:
                global_curve = site_curve
            else:
                global_curve = global_curve.add(site_curve, fill_value=0)
                
        if global_curve is None: return None

        return self.format_to_sge_csv(global_curve)

    def format_to_sge_csv(self, series):
        """
        Formate la série Pandas en fichier CSV strictement identique à Enedis.
        """
        output = io.StringIO()
        
        # Header SGE Standard
        output.write("Identifiant PRM;Date de debut;Date de fin;Grandeur physique;Grandeur metier;Etape metier;Unite;Horodate;Valeur;Nature;Pas;Indice de qualite;Etat compl.\n")
        
        # Préparation des données
        # Format SGE : 2026-01-01T00:10:00+01:00
        # Valeur en Watts (donc kW * 1000)
        
        df = series.to_frame(name='val')
        df['val_w'] = (df['val'] * 1000).astype(int)
        
        # Pour aller vite, on écrit ligne à ligne ou on utilise to_csv avec un formatteur
        # SGE est un peu pénible avec les dates, on fait simple pour l'instant
        
        for ts, row in df.iterrows():
            # Format ISO 8601 strict pour SGE
            ts_str = ts.isoformat()
            val = row['val_w']
            # Ligne SGE fictive (PDL Virtuel Aggregé)
            line = f"AGGREGAT_VIRTUEL;;;PA;CONS;BEST;W;{ts_str};{val};R;PT10M;;\n"
            output.write(line)
            
        return output.getvalue()

aggregator = CortexAggregator()
