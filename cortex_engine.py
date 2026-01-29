import pandas as pd
import numpy as np
import io
import random
from datetime import datetime

class CortexEngine:
    def __init__(self):
        self.kwh_price_elec = 0.18
        self.kwh_price_gaz = 0.09

    # --- FONCTION DE NETTOYAGE (ANTI-CRASH JSON) ---
    def safe_value(self, val):
        """Transforme NaN ou Infinity en 0 pour le JSON"""
        try:
            if pd.isna(val) or np.isinf(val):
                return 0.0
            return float(val)
        except:
            return 0.0

    async def analyze_file(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # 1. CHARGEMENT ROBUSTE (Mode "Python Engine")
            if filename.lower().endswith('.csv'):
                try:
                    # TENTATIVE 1 : Autodétection intelligente
                    df = pd.read_csv(buffer, sep=None, engine='python', encoding='utf-8')
                except:
                    # TENTATIVE 2 : Force le point-virgule et encodage Windows (Excel)
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')
            else:
                # Excel (.xlsx)
                df = pd.read_excel(buffer)

            if df is None or df.empty:
                return {"success": False, "error": "Fichier vide ou illisible."}

            # 2. VÉRIFICATION DE LA STRUCTURE
            # Si on a qu'une seule colonne, c'est que le séparateur a échoué
            if len(df.columns) < 2:
                # Dernière chance : on essaie la virgule
                buffer.seek(0)
                try:
                    df = pd.read_csv(buffer, sep=',')
                except: pass
                
                if len(df.columns) < 2:
                    return {"success": False, "error": f"Échec lecture colonnes. J'ai lu : {list(df.columns)}. Vérifiez vos séparateurs (;)."}

            # 3. NETTOYAGE COLONNES
            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            
            # Recherche des colonnes
            possible_date = ['date', 'horodate', 'heure', 'time', 'timestamp', 'jour', 'dt']
            col_date = next((c for c in df.columns if any(x in c for x in possible_date)), None)
            
            possible_val = ['puissance', 'p10', 'conso', 'valeur', 'index', 'kwh', 'kw', 'p_w']
            col_val = next((c for c in df.columns if any(x in c for x in possible_val)), None)

            if not col_date or not col_val:
                return {"success": False, "error": f"Colonnes introuvables. Trouvé: {list(df.columns)}. Il faut 'Date' et 'Puissance'."}

            # 4. TRAITEMENT DATA
            # Conversion Date
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date).set_index(col_date)
            
            # Conversion Nombre (Virgule française)
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').astype(float)

            # Nettoyage des NaN
            df[col_val] = df[col_val].fillna(0)

            # 5. CALCULS KPI
            vol = df[col_val].sum()
            # Si pas 'kwh' ou 'index' dans le nom, on suppose kW 10min -> /6
            if 'kwh' not in col_val and 'index' not in col_val:
                vol = vol / 6

            pic = df[col_val].max()
            talon = df[col_val].min()
            
            # 6. RESAMPLING (Moyenne journalière)
            df_daily = df[col_val].resample('D').mean()
            df_daily = df_daily.replace([np.inf, -np.inf], np.nan).fillna(0)
            df_daily = df_daily.tail(365)

            return {
                "success": True,
                "kpi": {
                    "volume_mwh": round(self.safe_value(vol / 1000), 2),
                    "pic_kw": round(self.safe_value(pic), 2),
                    "talon_kw": round(self.safe_value(talon), 2),
                    "points_traites": len(df)
                },
                "chart": {
                    "labels": df_daily.index.strftime('%d/%m').tolist(),
                    "values": [self.safe_value(x) for x in df_daily.tolist()]
                }
            }

        except Exception as e:
            return {"success": False, "error": f"Erreur Python : {str(e)}"}

    # --- MOCKS ---
    def run_chaos_monkey(self):
        return [{"test": "Test CSV", "status": "✅ PASS", "detail": "Lecture OK"}]

    def simulate_audit(self, file_name):
        return {"compliant": False, "anomalies": ["TVA Erronée"], "montant_detecte": 1250.50}

    def ask_agent(self, query):
        q = query.lower()
        if 'bonjour' in q: return "Bonjour ! Prêt à analyser vos données."
        return "Je suis à l'écoute. Chargez un fichier pour commencer."

cortex = CortexEngine()
