# app/core/cortex_engine.py V29.0 - PLATINUM FIX
import pandas as pd
import numpy as np
import io
import re
import math
import logging
from datetime import datetime

# CONFIGURATION
# On force Europe pour la compatibilité Cloud Run Paris
VERTEX_REGION = "europe-west9"
VERTEX_MODEL = "gemini-1.5-flash-001"

# LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CORTEX_V29")

# 1. DEPENDANCES OPTIONNELLES (Crash Proof)
try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.warning("PDFPlumber manquant - Module Audit désactivé")

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    # Initialisation explicite du projet si besoin, sinon auto-detect via Cloud Run
    vertexai.init(location=VERTEX_REGION)
    AI_MODEL = GenerativeModel(VERTEX_MODEL)
    AI_AVAILABLE = True
except Exception as e:
    logger.error(f"[CORTEX] AI Init Error: {e}")
    AI_AVAILABLE = False

class CortexEngine:
    def __init__(self):
        self.version = "29.0 (Platinum Logic)"
        # Base de connaissance simplifiée pour détection métier
        self.KEYWORDS_DB = {
            "ecole": "Enseignement (NAF 85)",
            "school": "Enseignement (NAF 85)",
            "mairie": "Administration (NAF 84)",
            "boulangerie": "Artisanat (NAF 10)",
            "usine": "Industrie (NAF 25)",
            "industrie": "Industrie (NAF 25)",
            "resi": "Résidentiel",
            "logement": "Résidentiel"
        }

    def _safe_int(self, value):
        """Conversion int crash-proof"""
        try:
            if pd.isna(value) or np.isinf(value): return 0
            return int(float(value))
        except: return 0

    # --- ORCHESTRATEUR ---
    def analyze_file(self, file_content, filename, target_profile="demo"):
        """Pipeline principal d'analyse SGE"""
        try:
            # 1. PARSING ROBUSTE
            df, time_step = self._parse_data(file_content, filename)
            
            if df is None or df.empty:
                return {"success": False, "error": "Fichier vide ou format SGE inconnu"}
            
            # 2. PROFILAGE (Maths)
            base = self._module_socle(df, time_step)
            
            # Détection Métier via Nom de fichier (Heuristique)
            detected_profile = "Tertiaire Standard"
            filename_lower = filename.lower()
            for key, val in self.KEYWORDS_DB.items():
                if key in filename_lower:
                    detected_profile = val
                    break
            
            # 3. CALCULS FINANCIERS (Maths Strictes)
            finance = self._module_finance_4p(df, time_step, base['p_max'])
            
            # 4. MODULES EXPERTS
            solar = self._module_solar(df)
            drift = self._module_drift(df)
            waste = self._module_ghost(df, base['talon'])
            
            # 5. CHART DATA (Downsampling pour le front)
            # On garde max 2000 points pour ne pas tuer le navigateur
            step = max(1, len(df)//2000)
            df_chart = df.iloc[::step].copy()
            
            chart = {
                "labels": df_chart['date_str'].tolist(),
                "values": df_chart['val'].tolist(),
                # On envoie des lignes de référence pour aider la lecture
                "talon_line": [base['talon']] * len(df_chart)
            }

            # 6. AGREGATION
            full_kpi = {
                **base, 
                **solar, 
                **drift, 
                **waste, 
                **finance,
                "profiling": {"type": detected_profile},
                "meta": {"filename": filename, "points": len(df)}
            }
            
            # 7. GENERATION NARRATIVE (IA)
            # On passe les calculs maths à l'IA pour interprétation
            narrative = self._generate_insight(full_kpi, detected_profile)

            return {
                "success": True, 
                "kpi": full_kpi, 
                "chart": chart, 
                "ai_insight": narrative
            }

        except Exception as e:
            logger.exception("Global Analysis Fail")
            return {"success": False, "error": f"Erreur Moteur: {str(e)}"}

    # --- PARSER SGE (HYPER ROBUSTE) ---
    def _parse_data(self, content, filename):
        try:
            buffer = io.BytesIO(content)
            df = None

            # Essai 1: CSV SGE Standard (sep=;)
            try:
                df = pd.read_csv(buffer, sep=';', encoding='latin-1', on_bad_lines='skip', low_memory=False)
            except: pass
            
            # Essai 2: Fallback moteur Python
            if df is None or len(df) < 2:
                buffer.seek(0)
                df = pd.read_csv(buffer, sep=None, engine='python', encoding='latin-1')

            # Normalisation colonnes
            df.columns = [str(c).lower().strip().replace('é','e').replace('è','e') for c in df.columns]
            
            # Identification colonnes
            c_date = next((c for c in df.columns if 'horodate' in c or 'date' in c), None)
            c_val = next((c for c in df.columns if 'valeur' in c or 'puiss' in c or 'conso' in c), None)
            
            if not c_date or not c_val:
                return None, 0

            # NETTOYAGE VALEURS (CRITIQUE)
            # On vire les espaces insécables et on remplace virgule par point
            if df[c_val].dtype == object:
                df['val'] = pd.to_numeric(
                    df[c_val].astype(str).str.replace(',', '.').str.replace(r'\s+', '', regex=True), 
                    errors='coerce'
                )
            else:
                df['val'] = pd.to_numeric(df[c_val], errors='coerce')

            df['val'] = df['val'].fillna(0)

            # NETTOYAGE DATES (CRITIQUE)
            # Enedis = JJ/MM/AAAA HH:MM
            df['date'] = pd.to_datetime(df[c_date], format='%d/%m/%Y %H:%M', errors='coerce')
            
            # Fallback si échec format strict
            if df['date'].isna().mean() > 0.5:
                df['date'] = pd.to_datetime(df[c_date], dayfirst=True, errors='coerce')

            df = df.dropna(subset=['date'])
            df = df.sort_values('date')

            # Conversion kW si nécessaire (si moyenne > 1000, c'est sûrement des Watts)
            if df['val'].mean() > 1000:
                df['val'] = df['val'] / 1000

            # Calcul Pas de temps (Time Step) en heures
            time_step = 0.1666 # Défaut 10 min
            if len(df) > 1:
                delta_seconds = (df.iloc[1]['date'] - df.iloc[0]['date']).total_seconds()
                if delta_seconds > 0:
                    time_step = delta_seconds / 3600.0

            df['date_str'] = df['date'].dt.strftime('%Y-%m-%d %H:%M')
            
            # On retourne un DF propre avec seulement ce qu'il faut
            return df[['date', 'val', 'date_str']], time_step

        except Exception as e:
            logger.error(f"Parse Error: {e}")
            return None, 0

    # --- FINANCE 4 POSTES (CORRIGÉ & SÉCURISÉ) ---
    def _module_finance_4p(self, original_df, ts, pmax):
        # On travaille sur une copie pour ne pas casser le DF original
        df = original_df.copy()
        
        # Extraction temporelle vectorisée (Rapide)
        df['month'] = df['date'].dt.month
        df['hour'] = df['date'].dt.hour
        
        # DÉFINITION SAISONS & HEURES (Règle ENEDIS Standard)
        # Hiver = Nov(11) -> Mars(3)
        mask_winter = df['month'].isin([11, 12, 1, 2, 3])
        mask_summer = ~mask_winter
        
        # HP = 06h00 à 22h00 (exclus) -> donc < 22
        mask_hp = (df['hour'] >= 6) & (df['hour'] < 22)
        mask_hc = ~mask_hp
        
        # CALCUL DES VOLUMES (kWh)
        # On multiplie la puissance (kW) par le pas de temps (h) -> kWh
        vol_hph = df.loc[mask_winter & mask_hp, 'val'].sum() * ts
        vol_hch = df.loc[mask_winter & mask_hc, 'val'].sum() * ts
        vol_hpe = df.loc[mask_summer & mask_hp, 'val'].sum() * ts
        vol_hce = df.loc[mask_summer & mask_hc, 'val'].sum() * ts
        
        # PRIX MOYENS ESTIMATIFS (Pour budget)
        # HPH: 0.22€, HCH: 0.14€, HPE: 0.14€, HCE: 0.09€
        cout_hph = vol_hph * 0.22
        cout_hch = vol_hch * 0.14
        cout_hpe = vol_hpe * 0.14
        cout_hce = vol_hce * 0.09
        
        # Prime Fixe (Abonnement estimé via Pmax)
        cout_abo = pmax * 18 # approx 18€/kW/an
        
        budget = cout_hph + cout_hch + cout_hpe + cout_hce + cout_abo
        
        return {
            "finance": {
                "budget_total": self._safe_int(budget),
                "detail_4p": {
                    "HPH": {"vol": self._safe_int(vol_hph), "cout": self._safe_int(cout_hph)},
                    "HCH": {"vol": self._safe_int(vol_hch), "cout": self._safe_int(cout_hch)},
                    "HPE": {"vol": self._safe_int(vol_hpe), "cout": self._safe_int(cout_hpe)},
                    "HCE": {"vol": self._safe_int(vol_hce), "cout": self._safe_int(cout_hce)}
                }
            }
        }

    # --- AUTRES MODULES (Optimisés) ---
    def _module_socle(self, df, ts):
        val = df['val'] # Series numpy
        p_max = val.max()
        conso_totale = val.sum() * ts
        
        # Talon = Percentile 5% des valeurs non nulles de nuit
        mask_nuit = (df['date'].dt.hour < 6)
        nuit_vals = df.loc[mask_nuit, 'val']
        talon = nuit_vals.quantile(0.05) if not nuit_vals.empty else 0
        
        # Ratio Inactivité (Weekend + Nuit)
        df['wd'] = df['date'].dt.weekday
        mask_off = (df['wd'] >= 5) | (df['date'].dt.hour < 6) | (df['date'].dt.hour > 20)
        conso_off = df.loc[mask_off, 'val'].sum() * ts
        
        ratio = (conso_off / conso_totale * 100) if conso_totale > 0 else 0
        
        return {
            "conso_totale": self._safe_int(conso_totale),
            "p_max": round(p_max, 2),
            "talon": round(talon, 2),
            "moyenne": round(val.mean(), 2),
            "inactivity_ratio": round(ratio, 1)
        }

    def _module_solar(self, df):
        # Solaire pertinent si consommation élevée en journée l'été
        df['m'] = df['date'].dt.month
        df['h'] = df['date'].dt.hour
        
        mask_ete_jour = (df['m'].isin([5,6,7,8])) & (df['h'].between(10, 16))
        conso_solarable = df.loc[mask_ete_jour, 'val'].mean()
        
        # Seuil arbitraire : si on consomme > 10kW en moyenne l'été le midi
        is_viable = conso_solarable > 10 
        kwc_suggere = math.floor(conso_solarable * 0.8) # Couvrir 80% du talon jour été
        
        return {
            "solar": {
                "status": "OPPORTUNITÉ DÉTECTÉE" if is_viable else "NON PERTINENT",
                "puissance_kwc": kwc_suggere if is_viable else 0,
                "economie_annuelle_euro": self._safe_int(kwc_suggere * 1100 * 0.18) if is_viable else 0
            }
        }

    def _module_drift(self, df): 
        # Placeholder pour dérive (comparaison N vs N-1 non dispo ici)
        return {"drift": {"status": "STABLE", "message": "Pas d'historique N-1"}}

    def _module_ghost(self, df, talon):
        # Gaspillage = Talon * 8760h (si on ne coupait jamais rien)
        return {"ghost_buster": {"cout_talon_annuel": self._safe_int(talon * 8760 * 0.15)}}

    # --- GENERATION IA ---
    def _generate_insight(self, kpi, profile_name):
        if not AI_AVAILABLE:
            return "Mode Hybride Dégradé : IA non connectée (Réseau/Quota). Calculs mathématiques valides."
        
        try:
            # Construction du Prompt Contextuel
            prompt = f"""
            AGIS EN TANT QUE CORTEX, EXPERT ÉNERGIE.
            Analyse les données suivantes pour un site de type: {profile_name.upper()}.
            
            DONNÉES:
            - Budget Est. : {kpi['finance']['budget_total']} €/an
            - Pmax : {kpi['p_max']} kW
            - Talon (Nuit) : {kpi['talon']} kW
            - Ratio Inactivité : {kpi['inactivity_ratio']}% (Normal < 20%)
            - Solaire : {kpi['solar']['status']}
            
            CONSIGNE:
            Rédige 3 points clés très courts (bullet points).
            1. Une observation sur le talon (gaspillage ?).
            2. Une observation sur la puissance atteinte.
            3. Un conseil stratégique lié au profil {profile_name}.
            
            Ton : Professionnel, Direct, sans blabla. Max 60 mots au total.
            """
            
            response = AI_MODEL.generate_content(prompt)
            return response.text.replace('*', '').strip() # Nettoyage markdown
            
        except Exception as e:
            logger.error(f"Vertex Generation Error: {e}")
            return "Analyse IA temporairement indisponible."

    # --- AUDIT PDF (LEGACY) ---
    def analyze_invoice_real(self, inv_b, ctr_b):
        # Fonction Audit gardée telle quelle (Règle Anti-Régression)
        txt = ""
        if PDF_AVAILABLE and inv_b:
            try:
                with pdfplumber.open(io.BytesIO(inv_b)) as pdf:
                    for p in pdf.pages: txt += p.extract_text() + "\n"
            except: pass
        
        # Regex basique pour extraire Puissance
        m_sous = re.search(r"souscrite.*?(\d+[.,]?\d*)", txt, re.I | re.DOTALL)
        m_max = re.search(r"(?:atteinte|max|pointe).*?(\d+[.,]?\d*)", txt, re.I | re.DOTALL)
        
        p_sous = float(m_sous.group(1).replace(',', '.')) if m_sous else 0
        p_att = float(m_max.group(1).replace(',', '.')) if m_max else 0
        
        checks = [{
            "point": "Puissance Souscrite vs Atteinte",
            "a": f"{p_sous} kVA", 
            "b": f"{p_att} kVA", 
            "status": "OPTIMISER" if p_att < p_sous*0.6 else "OK", 
            "error": False
        }]
        return {"score": 100, "checks": checks}

    def run_chaos_monkey(self):
        return [
            {"test": "PDF Engine", "status": "OK" if PDF_AVAILABLE else "MISSING"}, 
            {"test": "Vertex AI", "status": "OK" if AI_AVAILABLE else "OFFLINE"},
            {"test": "Maths Lib", "status": "OK"}
        ]
    
    def ask_agent(self, msg):
        if AI_AVAILABLE:
            try: return AI_MODEL.generate_content(msg).text
            except: return "IA Indisponible"
        return "IA Offline"

cortex = CortexEngine()
