import pandas as pd
import numpy as np
import holidays
import io
import os
import json
from datetime import datetime, timedelta

class CortexAggregator:
    """
    CORTEX AGGREGATOR V2 - LONG TERM PROJECTION
    Génère des courbes de charge prévisionnelles multi-sites (N+1, N+2, N+3)
    PAS DE TEMPS : 60 Minutes (Optimisé pour projection financière).
    """

    def __init__(self):
        # Initialisation des jours fériés France
        self.fr_holidays = holidays.France()
        self.base_dir = os.getcwd()
        self.data_dir = os.path.join(self.base_dir, "data")

    def get_site_dna(self, site_id):
        """Récupère l'ADN énergétique du site (Talon, Pmax, Profil)."""
        clean_id = site_id.replace('/', '_').replace(' ', '_').strip()
        path = os.path.join(self.data_dir, f"{clean_id}.json")
        
        if not os.path.exists(path):
            return None

        try:
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
        except Exception:
            return None

    def generate_curve_for_site(self, dna, start_date, end_date):
        """
        Génère une courbe 60min (1H) réaliste sur 3 ans.
        """
        # --- CHANGEMENT MAJEUR : FREQ='1H' ---
        dates = pd.date_range(start=start_date, end=end_date, freq='1H')
        df = pd.DataFrame(index=dates)
        
        # Détection du type de jour
        df['weekday'] = df.index.weekday
        df['hour'] = df.index.hour
        
        # Mapping des jours fériés (Optimisé)
        years = range(start_date.year, end_date.year + 1)
        holiday_dates = set()
        for y in years:
            holiday_dates.update(self.fr_holidays.get(y).keys())
            
        # Logique vectorielle
        # 1. Base = Talon
        df['power'] = dna['talon']

        # 2. Identification Jours Ouvrés (Lundi-Vendredi et Pas Férié)
        # On crée un masque booléen
        is_weekend = df.index.weekday >= 5
        is_holiday = df.index.normalize().isin(holiday_dates)
        is_working_day = ~(is_weekend | is_holiday)

        # 3. Profil Heures Ouvrées (7h-19h)
        is_working_hour = (df['hour'] >= 7) & (df['hour'] <= 19)
        
        # Application de la charge
        mask_active = is_working_day & is_working_hour
        
        # Ajout de variabilité (Bruit)
        noise = np.random.normal(1.0, 0.05, size=len(df))
        
        # Formule : Talon + (Delta * 0.85)
        # On ne monte pas à 100% de Pmax tout le temps (moyenne foisonnée)
        load_add = (dna['pmax'] - dna['talon']) * 0.85
        
        df.loc[mask_active, 'power'] = (dna['talon'] + load_add) * noise[mask_active]

        return df['power']

    def aggregate_sites(self, site_ids, years=3):
        """
        Point d'entrée principal.
        """
        # Calcul de la plage de dates (3 ans complets à partir du prochain 1er Janvier)
        next_year = datetime.now().year + 1
        start_date = datetime(next_year, 1, 1, 0, 0) 
        end_date = datetime(next_year + years - 1, 12, 31, 23, 0)
        
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
        Formate en CSV SGE (Pas Horaire PT60M).
        """
        output = io.StringIO()
        
        # Header SGE Standard
        output.write("Identifiant PRM;Date de debut;Date de fin;Grandeur physique;Grandeur metier;Etape metier;Unite;Horodate;Valeur;Nature;Pas;Indice de qualite;Etat compl.\n")
        
        # Conversion en Watts (Standard SGE)
        df = series.to_frame(name='val')
        df['val_w'] = (df['val'] * 1000).astype(int)
        
        # Écriture optimisée
        # On utilise PT60M pour le pas horaire
        for ts, row in df.iterrows():
            ts_str = ts.isoformat()
            val = row['val_w']
            line = f"AGGREGAT_VIRTUEL;;;PA;CONS;BEST;W;{ts_str};{val};R;PT60M;;\n"
            output.write(line)
            
        return output.getvalue()

aggregator = CortexAggregator()
