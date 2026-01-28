import pandas as pd
import numpy as np
import io

class CortexEngine:
    def __init__(self):
        self.kwh_price_elec = 0.18  # €/kWh moyen
        self.kwh_price_gaz = 0.09   # €/kWh moyen

    def detect_delimiter(self, content_bytes):
        """Détecte si le CSV utilise ; ou ,"""
        try:
            sample = content_bytes[:1024].decode('utf-8', errors='ignore')
            if sample.count(';') > sample.count(','):
                return ';'
            return ','
        except:
            return ';'

    async def analyze_file(self, file_content, filename):
        try:
            # 1. CHARGEMENT OPTIMISÉ
            # On utilise un buffer pour éviter d'écrire sur le disque
            buffer = io.BytesIO(file_content)

            if filename.lower().endswith('.csv'):
                sep = self.detect_delimiter(file_content)
                # On force les types pour économiser la mémoire (float32 au lieu de 64)
                df = pd.read_csv(buffer, sep=sep, low_memory=False)
            else:
                df = pd.read_excel(buffer)

            # 2. STANDARDISATION DES COLONNES (Mapping ENEDIS / GRDF)
            # On nettoie les noms de colonnes (minuscule, sans espaces)
            df.columns = [str(c).lower().strip().replace(' ', '_').replace('é', 'e').replace('è', 'e') for c in df.columns]
            
            # Dictionnaire de synonymes pour trouver la Date
            possible_date_cols = ['date', 'horodate', 'horodatage', 'timestamp', 'temps', 'date_releve', 'jour']
            col_date = next((c for c in df.columns if any(x in c for x in possible_date_cols)), None)

            # Dictionnaire de synonymes pour trouver la Puissance/Conso
            # P10 = Puissance 10 min (Enedis), Index = Index de consommation
            possible_val_cols = ['puissance', 'p_active', 'p10', 'conso', 'kwh', 'valeur', 'index', 'ea_soutiree']
            col_val = next((c for c in df.columns if any(x in c for x in possible_val_cols)), None)

            if not col_date or not col_val:
                return {
                    "success": False, 
                    "error": f"Format non reconnu. Colonnes trouvées : {list(df.columns)}. Il faut une colonne 'Date' et une colonne 'Puissance/Conso'."
                }

            # 3. TRAITEMENT TEMPOREL (Le plus lourd)
            # Conversion intelligente (tente ISO, puis format français DD/MM/YYYY)
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            
            # Suppression des lignes sans date valide
            df = df.dropna(subset=[col_date])
            
            # Tri chronologique (Indispensable pour les courbes)
            df = df.sort_values(by=col_date)
            df = df.set_index(col_date)

            # Nettoyage des valeurs (virgules en points, conversion numérique)
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').astype(float)

            # 4. CALCULS MÉTIERS (Data Science)
            
            # Gestion du pas de temps (10 min vs 1h vs Index)
            # On calcule l'écart moyen entre deux points pour deviner le pas
            if len(df) > 1:
                time_diff = df.index.to_series().diff().median().total_seconds()
            else:
                time_diff = 600 # Défaut 10 min

            # Si c'est de la Puissance (kW) au pas 10 min -> Énergie = P * (10/60)
            # Si c'est des Index (kWh) -> Énergie = Index_N - Index_N-1
            
            is_index = 'index' in col_val
            
            if is_index:
                # C'est un index (cumulatif), on calcule le delta
                df['conso_kwh'] = df[col_val].diff().fillna(0)
                # On élimine les sauts négatifs (changement de compteur ou reset)
                df['conso_kwh'] = df['conso_kwh'].apply(lambda x: x if x > 0 else 0)
            else:
                # C'est de la puissance instantanée ou moyenne (kW)
                # Formule : E (kWh) = P (kW) * (Delta_T_secondes / 3600)
                df['conso_kwh'] = df[col_val] * (time_diff / 3600)

            # KPI CLÉS
            volume_total_kwh = df['conso_kwh'].sum()
            pic_puissance_kw = df[col_val].max() if not is_index else df['conso_kwh'].max() * (3600/time_diff)
            
            # Talon (Moyenne de la consommation entre 00h et 04h du matin)
            try:
                talon_kw = df.between_time('00:00', '04:00')[col_val].mean()
            except:
                talon_kw = 0 # Si pas de données de nuit

            # 5. RESAMPLING (Compression pour l'affichage Web)
            # On ne peut pas envoyer 500k points au navigateur.
            # On agrège par JOUR (Somme des kWh, Max des kW)
            
            df_daily = df['conso_kwh'].resample('D').sum()
            
            # Protection contre les NaN (jours vides)
            df_daily = df_daily.fillna(0)

            # On garde les 365 derniers jours max pour le graph
            df_daily = df_daily.tail(365)

            # 6. SORTIE JSON
            return {
                "success": True,
                "filename": filename,
                "kpi": {
                    "volume_mwh": round(volume_total_kwh / 1000, 2),
                    "pic_kw": round(pic_puissance_kw, 2),
                    "talon_kw": round(talon_kw, 2),
                    "budget_estime_elec": round(volume_total_kwh * self.kwh_price_elec, 0),
                    "points_traites": len(df)
                },
                "chart": {
                    "labels": df_daily.index.strftime('%d/%m').tolist(),
                    "values": df_daily.round(1).tolist()
                }
            }

        except Exception as e:
            print(f"ERREUR CORTEX : {e}") # Log serveur
            return {"success": False, "error": f"Erreur d'analyse : {str(e)}"}

# Instance
cortex = CortexEngine()
