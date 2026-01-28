import pandas as pd
import numpy as np
import io
import random
from datetime import datetime

class CortexEngine:
    def __init__(self):
        self.kwh_price_elec = 0.18
        self.kwh_price_gaz = 0.09

    def detect_delimiter(self, content_bytes):
        try:
            sample = content_bytes[:2048].decode('utf-8', errors='ignore')
            if ';' in sample: return ';'
            if ',' in sample: return ','
            return ';'
        except: return ';'

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
            
            # 1. CHARGEMENT
            if filename.lower().endswith('.csv'):
                sep = self.detect_delimiter(file_content)
                try:
                    df = pd.read_csv(buffer, sep=sep, low_memory=False, encoding='utf-8')
                except:
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=sep, low_memory=False, encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty:
                return {"success": False, "error": "Fichier vide ou illisible."}

            # 2. NETTOYAGE COLONNES
            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            
            possible_date = ['date', 'horodate', 'heure', 'time', 'timestamp', 'jour', 'dt']
            col_date = next((c for c in df.columns if any(x in c for x in possible_date)), None)
            
            possible_val = ['puissance', 'p10', 'conso', 'valeur', 'index', 'kwh', 'kw', 'p_w']
            col_val = next((c for c in df.columns if any(x in c for x in possible_val)), None)

            if not col_date or not col_val:
                return {"success": False, "error": f"Colonnes introuvables. Trouvé: {list(df.columns)}"}

            # 3. TRAITEMENT
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date).set_index(col_date)
            
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').astype(float)

            # Nettoyage des NaN dans les données brutes
            df[col_val] = df[col_val].fillna(0)

            # 4. CALCULS
            vol = df[col_val].sum()
            if 'kwh' not in col_val and 'index' not in col_val:
                vol = vol / 6

            pic = df[col_val].max()
            talon = df[col_val].min()
            
            # 5. RESAMPLING (Moyenne journalière)
            df_daily = df[col_val].resample('D').mean()
            
            # *** CRUCIAL : REMPLACER LES NAN/INF PAR 0 ***
            df_daily = df_daily.replace([np.inf, -np.inf], np.nan).fillna(0)
            
            # On limite à 365 points pour ne pas surcharger le graph
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
                    "values": [self.safe_value(x) for x in df_daily.tolist()] # Double sécurité
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
