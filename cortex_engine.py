import pandas as pd
import numpy as np
import io
import random
from datetime import datetime

class CortexEngine:
    def __init__(self):
        self.kwh_price_elec = 0.18
        self.kwh_price_gaz = 0.09

    async def analyze_file(self, file_content, filename):
        try:
            buffer = io.BytesIO(file_content)
            df = None
            
            # --- 1. LECTURE INTELLIGENTE (MULTI-SÉPARATEUR) ---
            if filename.lower().endswith('.csv'):
                # On teste les séparateurs les plus courants un par un
                separators = [';', ',', '\t', '|']
                for sep in separators:
                    try:
                        buffer.seek(0) # On rembobine le fichier au début
                        # On essaie de lire
                        temp_df = pd.read_csv(buffer, sep=sep, low_memory=False, encoding='utf-8')
                        
                        # CRITÈRE DE SUCCÈS : A-t-on plus d'une colonne ?
                        if len(temp_df.columns) > 1:
                            df = temp_df
                            print(f"DEBUG: Séparateur '{sep}' détecté avec succès.")
                            break
                    except:
                        continue # On essaie le suivant
                
                # Si toujours rien, on tente l'encodage 'latin-1' (Excel vieux format)
                if df is None:
                    buffer.seek(0)
                    df = pd.read_csv(buffer, sep=';', encoding='latin-1')

            else:
                # Excel (.xlsx)
                df = pd.read_excel(buffer)

            if df is None or df.empty:
                return {"success": False, "error": "Fichier vide ou format illisible."}

            # --- 2. NETTOYAGE DES COLONNES ---
            # On met tout en minuscule et on nettoie
            df.columns = [str(c).lower().strip().replace('"', '').replace("'", "") for c in df.columns]
            
            # --- 3. RECHERCHE DES CHAMPS ---
            # Liste des synonymes possibles
            possible_date = ['date', 'horodate', 'heure', 'time', 'timestamp', 'jour', 'dt']
            possible_val = ['puissance', 'p10', 'conso', 'valeur', 'index', 'kwh', 'kw', 'p_w']

            col_date = next((c for c in df.columns if any(x in c for x in possible_date)), None)
            col_val = next((c for c in df.columns if any(x in c for x in possible_val)), None)

            # Si on ne trouve pas, on renvoie une erreur précise
            if not col_date or not col_val:
                return {
                    "success": False, 
                    "error": f"Colonnes introuvables. J'ai lu : {list(df.columns)}. Vérifiez le séparateur (;)."
                }

            # --- 4. TRAITEMENT DATA ---
            # Conversion Date
            df[col_date] = pd.to_datetime(df[col_date], dayfirst=True, errors='coerce')
            df = df.dropna(subset=[col_date]).sort_values(by=col_date).set_index(col_date)
            
            # Conversion Nombre (Virgule française)
            if df[col_val].dtype == object:
                df[col_val] = df[col_val].astype(str).str.replace(',', '.').astype(float)

            # --- 5. CALCULS KPI ---
            vol = df[col_val].sum()
            # Si pas 'kwh' dans le nom, on suppose que c'est du kW 10min -> on divise par 6
            if 'kwh' not in col_val and 'index' not in col_val:
                vol = vol / 6

            pic = df[col_val].max()
            
            # Resampling (Moyenne journalière pour le graph)
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

    # --- FONCTIONS ANNEXES (Chatbot & Mock) ---
    def run_chaos_monkey(self):
        return [{"test": "Test CSV", "status": "✅ PASS", "detail": "Lecture OK"}]

    def simulate_audit(self, file_name):
        return {"compliant": False, "anomalies": ["TVA Erronée"], "montant_detecte": 1250.50}

    def ask_agent(self, query):
        q = query.lower()
        if 'bonjour' in q: return "Bonjour ! Prêt à analyser vos données."
        if 'csv' in q: return "Format CSV attendu : Date;Puissance (séparateur point-virgule)."
        return "Je suis à l'écoute. Chargez un fichier pour commencer."

cortex = CortexEngine()
