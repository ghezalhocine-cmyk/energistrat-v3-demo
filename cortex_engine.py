import pandas as pd
import numpy as np
import io

class CortexEngine:
    def __init__(self):
        self.kwh_price = 0.18 # Prix moyen par défaut

    async def analyze_file(self, file_content, filename):
        """
        Analyse un fichier CSV ou Excel et retourne les KPI et les données pour les graphiques.
        """
        try:
            # 1. Lecture du fichier
            if filename.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(file_content), sep=';') # Séparateur standard France
            else:
                df = pd.read_excel(io.BytesIO(file_content))

            # 2. Nettoyage et Standardisation (On suppose une colonne 'Date' et 'Conso')
            # Pour le test, on va être flexible sur les noms de colonnes
            cols = [c.lower() for c in df.columns]
            df.columns = cols
            
            # Recherche de la colonne consommation
            conso_col = next((c for c in ['conso', 'kwh', 'puissance', 'p10', 'valeur'] if c in cols), None)
            date_col = next((c for c in ['date', 'horodatage', 'time'] if c in cols), None)

            if not conso_col:
                return {"error": "Colonne consommation introuvable (nommez-la 'conso' ou 'kwh')"}

            # 3. Calculs CORTEX (La vraie intelligence)
            total_conso = df[conso_col].sum()
            max_pic = df[conso_col].max()
            cout_estime = total_conso * self.kwh_price
            
            # Simulation d'optimisation (Ex: on coupe les pics > 90% du max)
            optim_gain = df[df[conso_col] > (max_pic * 0.9)][conso_col].sum() * 0.15 # 15% d'économie sur les pics

            # 4. Préparation des données pour Chart.js (Liste de valeurs)
            # On prend les 12 premières valeurs ou une moyenne pour simplifier l'affichage
            chart_data = df[conso_col].head(12).tolist()
            chart_labels = df[date_col].head(12).tolist() if date_col else [f"P{i}" for i in range(12)]

            return {
                "success": True,
                "kpi": {
                    "volume_total": round(total_conso, 2),
                    "pic_puissance": round(max_pic, 2),
                    "budget_annuel": round(cout_estime, 2),
                    "economie_potentielle": round(optim_gain, 2),
                    "score_vitality": int(np.random.randint(60, 95)) # Simulé pour l'instant
                },
                "chart": {
                    "labels": chart_labels,
                    "values": chart_data
                }
            }

        except Exception as e:
            return {"error": str(e)}

# Instance globale
cortex = CortexEngine()
