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
        """Tente de deviner le séparateur CSV"""
        try:
            sample = content_bytes[:2048].decode('utf-8', errors='ignore')
            if ';' in sample: return ';'
            if ',' in sample: return ','
            return ';' # Défaut
        except:
            return ';'

    async def analyze_file(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # 1. CHARGEMENT
            if filename.lower().endswith('.csv'):
                sep = self.detect_delimiter(file_content)
                # On essaie de lire, si erreur d'encodage on tente 'latin-1' (fréquent Excel)
                try:
                    df = pd.read_csv(buffer, sep=sep, low_memory=False, encoding='utf-8')
                except UnicodeDecodeError:
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=sep, low_memory=False, encoding='latin-1')
            else:
                df = pd.read_excel(buffer)

            if df is None or df.empty:
                return {"success": False, "error": "Le fichier est vide ou illisible."}

            # 2. NETTOYAGE DES COLONNES
            # On met tout en minuscule et on enlève les espaces inutiles
            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            
            # LOG DEBUG (Sera visible si erreur)
            cols_found = list(df.columns)

            # 3. RECHERCHE INTELLIGENTE
            # Mots-clés acceptés pour la Date
            possible_date = ['date', 'horodate', 'heure', 'time', 'timestamp', 'jour', 'dt']
            col_date = next((c for c in df.columns if any(x in c for x in possible_date)), None)
            
            # Mots-clés acceptés pour la Puissance
            possible_val = ['puissance', 'p10', 'conso', 'valeur', 'index', 'kwh', 'kw', 'p_w']
            col_val = next((c for c in df.columns if any(x in c for x in possible_val)), None)

            # 4. DIAGNOSTIC PRÉCIS SI ÉCHEC
            if not col_date or not col_val:
                msg = f"Colonnes non reconnues. J'ai trouvé : {cols_found}. "
                if not col_date: msg += "Il manque une colonne 'Date'. "
                if not col_val: msg += "Il manque une colonne 'Puissance' ou 'Conso'."
                return {"success": False, "error": msg}

            # 5. TRAITEMENT
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date).set_index(col_date)
            
            # Conversion numérique (gestion de la virgule française)
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').astype(float)

            # Calculs
            vol = df[col_val].sum()
            # Si ce sont des kW 10min, on divise par 6 pour avoir des kWh
            # Si l'entête contient 'kwh', on ne divise pas
            if 'kwh' not in col_val and 'index' not in col_val:
                vol = vol / 6

            pic = df[col_val].max()
            
            # Resampling pour affichage léger
            df_daily = df[col_val].resample('D').mean().fillna(0).tail(365)

            return {
                "success": True,
                "kpi": {
                    "volume_mwh": round(vol / 1000, 2),
                    "pic_kw": round(pic, 2),
                    "talon_kw": round(df[col_val].min(), 2),
                    "points_traites": len(df)
                },
                "chart": {
                    "labels": df_daily.index.strftime('%d/%m').tolist(),
                    "values": df_daily.round(1).tolist()
                }
            }

        except Exception as e:
            return {"success": False, "error": f"Erreur Python : {str(e)}"}

    # --- SIMULATIONS & IA (MOCK) ---
    def run_chaos_monkey(self):
        # ... (Garde ton code existant ici ou remets celui d'avant) ...
        return [{"test": "Test Connexion", "status": "✅ PASS", "detail": "OK"}]

    def simulate_audit(self, file_name):
        return {"compliant": False, "anomalies": ["TVA Erronée"], "montant_detecte": 1250.50}

    def ask_agent(self, query):
        q = query.lower()
        if 'gemini' in q or 'google' in q:
            return "🤖 <strong>Architecture Google :</strong><br>Je suis actuellement un module Python optimisé.<br>La connexion Vertex AI (Gemini) est prête à être activée dans le `main.py`."
        if 'csv' in q or 'erreur' in q:
            return "⚠️ <strong>Conseil Import :</strong><br>Vérifiez que votre CSV a bien une colonne nommée <code>Date</code> et une nommée <code>Puissance</code>.<br>Le séparateur doit être ';' ou ','."
        return "Commande reçue. Analyse en cours..."

cortex = CortexEngine()
