import pandas as pd
import numpy as np
import io

class CortexEngine:
    def __init__(self):
        # Prix moyen du marché pour estimation (0.18€/kWh)
        self.kwh_price = 0.18 

    async def analyze_file(self, file_content, filename):
        try:
            # 1. LECTURE DU FICHIER (Excel ou CSV)
            if filename.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(file_content), sep=';', parse_dates=[0], dayfirst=True)
            else:
                df = pd.read_excel(io.BytesIO(file_content))

            # 2. STANDARDISATION DES COLONNES
            # On renomme pour être sûr de trouver les données peu importe le nom dans l'Excel
            df.columns = [c.lower().strip() for c in df.columns]
            
            # Détection intelligente des colonnes
            col_date = next((c for c in df.columns if any(x in c for x in ['date', 'horodatage', 'temps'])), None)
            col_val = next((c for c in df.columns if any(x in c for x in ['puissance', 'p10', 'kw', 'conso', 'valeur'])), None)

            if not col_date or not col_val:
                return {"success": False, "error": "Colonnes 'Date' et 'Puissance' non trouvées."}

            # Conversion en datetime et tri
            df[col_date] = pd.to_datetime(df[col_date])
            df = df.sort_values(by=col_date)
            df = df.set_index(col_date)

            # 3. ANALYSE TECHNIQUE (Sur la donnée brute 10 min)
            # Volume total : Si c'est de la puissance moyenne 10min (kW), l'énergie (kWh) = Somme / 6
            # Si c'est déjà des kWh, c'est juste la somme. On suppose ici du kW moyen (courbe de charge standard).
            volume_total_kwh = df[col_val].sum() / 6 
            
            # Pic de puissance (Le max absolu atteint sur 10 min)
            pic_max_kw = df[col_val].max()
            
            # Talon (Consommation minimale, souvent la nuit)
            talon_min_kw = df[col_val].min()

            # 4. PRÉPARATION GRAPHIQUE (Resampling)
            # On ne peut pas afficher 50k points. On fait une moyenne par JOUR pour le graph.
            df_daily = df[col_val].resample('D').mean()
            
            # On remplace les NaN par 0 (coupures)
            df_daily = df_daily.fillna(0)

            # Formatage pour Chart.js
            chart_labels = df_daily.index.strftime('%d/%m').tolist()
            chart_values = df_daily.round(2).tolist()

            return {
                "success": True,
                "kpi": {
                    "volume_mwh": round(volume_total_kwh / 1000, 2), # En MWh
                    "pic_kw": round(pic_max_kw, 2),
                    "talon_kw": round(talon_min_kw, 2),
                    "budget_estime": round(volume_total_kwh * self.kwh_price, 0)
                },
                "chart": {
                    "labels": chart_labels,
                    "values": chart_values
                }
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

# Instance unique pour l'app
cortex = CortexEngine()
