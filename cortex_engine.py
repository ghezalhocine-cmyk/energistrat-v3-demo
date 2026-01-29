import pandas as pd
import numpy as np
import io
from datetime import datetime

class CortexEngine:
    def __init__(self):
        self.kwh_price_elec = 0.18

    def safe_value(self, val):
        try:
            if pd.isna(val) or np.isinf(val): return 0.0
            return float(val)
        except: return 0.0

    async def analyze_file(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # 1. LECTURE ROBUSTE (Encodage Enedis souvent CP1252 ou Latin-1)
            encodings = ['utf-8', 'cp1252', 'latin-1', 'iso-8859-1']
            if filename.lower().endswith('.csv'):
                for enc in encodings:
                    try:
                        buffer.seek(0)
                        # On force le point-virgule car c'est le standard SGE
                        df = pd.read_csv(buffer, sep=None, engine='python', encoding=enc)
                        if len(df.columns) > 1: break
                    except: continue
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty: return {"success": False, "error": "Lecture impossible (Encodage)"}

            # 2. NETTOYAGE EN-TÊTES
            # On garde les noms originaux pour vérifier l'unité plus tard, mais on crée une version clean
            clean_cols = [str(c).lower().strip().replace('é', 'e').replace('è', 'e') for c in df.columns]
            
            # MAPPING SGE ENEDIS
            col_date = next((df.columns[i] for i, c in enumerate(clean_cols) if c in ['horodate', 'date', 'timestamp']), None)
            col_val  = next((df.columns[i] for i, c in enumerate(clean_cols) if c in ['valeur', 'puissance', 'p10', 'conso']), None)
            col_unit = next((df.columns[i] for i, c in enumerate(clean_cols) if 'unite' in c), None)

            if not col_date or not col_val:
                return {"success": False, "error": f"Colonnes SGE (Horodate/Valeur) introuvables. Trouvé: {list(df.columns)}"}

            # 3. CONVERSION DES UNITÉS (W -> kW)
            # Si une colonne unité existe et contient "W", on divise par 1000
            factor = 1.0
            if col_unit:
                unit_val = str(df[col_unit].iloc[0]).upper()
                if 'KW' not in unit_val and 'W' in unit_val:
                    factor = 0.001 # Conversion Watt vers kW

            # 4. TRAITEMENT TEMPOREL
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date).set_index(col_date)
            
            # Nettoyage numérique
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').str.replace(' ', '')
            
            df[col_val] = pd.to_numeric(df[col_val], errors='coerce').fillna(0)
            
            # Application du facteur (W -> kW)
            df[col_val] = df[col_val] * factor

            # 5. CALCULS KPI
            # Pour du P10 (Puissance 10 min), l'énergie en kWh = Puissance(kW) / 6
            vol_kwh = df[col_val].sum() / 6
            pic_kw = df[col_val].max()
            talon_kw = df[col_val].min()
            
            # 6. RESAMPLING (Moyenne journalière pour affichage fluide)
            df_daily = df[col_val].resample('D').mean().fillna(0).tail(365)

            return {
                "success": True,
                "kpi": {
                    "volume_mwh": round(self.safe_value(vol_kwh / 1000), 2),
                    "pic_kw": round(self.safe_value(pic_kw), 2),
                    "talon_kw": round(self.safe_value(talon_kw), 2),
                    "points_traites": len(df)
                },
                "chart": {
                    "labels": df_daily.index.strftime('%d/%m').tolist(),
                    "values": [self.safe_value(x) for x in df_daily.tolist()]
                }
            }

        except Exception as e:
            return {"success": False, "error": f"Crash Moteur : {str(e)}"}

    # Mocks inchangés
    def run_chaos_monkey(self): return [{"test": "Test SGE", "status": "✅ PASS", "detail": "OK"}]
    def simulate_audit(self, file_name): return {"compliant": True, "anomalies": [], "montant_detecte": 0}
    def ask_agent(self, query): return "Prêt pour analyse SGE."

cortex = CortexEngine()
