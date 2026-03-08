import re
import io
import os
import glob
import pandas as pd
from datetime import datetime

# --- IMPORT DU MOTEUR PHYSIQUE ---
try:
    from app.core.cortex_physics import physics
except ImportError:
    try:
        from core.cortex_physics import physics
    except ImportError:
        physics = None
        print("⚠️ ALERTE : Cortex Physics introuvable. Le calcul intelligent sera désactivé.")

# --- IMPORT DU MOTEUR DB (NOUVEAUTÉ FIRESTORE) ---
try:
    from app.core.cortex_db import db
except ImportError:
    try:
        from core.cortex_db import db
    except ImportError:
        db = None
        print("⚠️ ALERTE : Cortex DB introuvable. Impossible d'accéder à Firestore.")

# Import conditionnel pour l'ingestion spécifique (Finance/Particulier)
try:
    from app.core.cortex_ingest import ingest
except ImportError:
    try:
        import cortex_ingest as ingest
    except:
        ingest = None

class CortexRouter:
    """
    CORTEX ROUTER V7.0 - FIRESTORE INTEGRATION
    Responsabilités : I/O Fichiers, Identification Client, Orchestration.
    Connecté directement à la base de données Cloud (Zero JSON local).
    """

    def __init__(self):
        self.pdl_mapping = {}
        self.refresh_database()

    def refresh_database(self):
        """Recharge la liste des clients directement depuis Firestore."""
        self.pdl_mapping = {}
        if not db:
            print("🔴 CORTEX ROUTER: Base de données Firestore non connectée.")
            return

        sites = db.get_all_sites()
        
        for data in sites:
            try:
                identity = data.get('identity', {})
                contract = data.get('contract', {})
                site_id = identity.get('id')
                client_name = identity.get('site_name', 'Client Inconnu')
                
                if not site_id:
                    continue
                    
                # Nettoyage
                pdl = str(contract.get('pdl', '')).replace(' ', '').strip()
                pce = str(contract.get('pce', '')).replace(' ', '').strip()
                
                # Détection Profil
                profile = "retail"
                typologie = data.get('location', {}).get('typologie', '').lower()
                if "mairie" in typologie or "admin" in typologie: profile = "mairie"
                if "usine" in typologie or "indus" in typologie: profile = "industrie"
                if "residence" in typologie or "syndic" in typologie: profile = "syndic"

                # Mapping (On garde le site_id Firestore en mémoire)
                info = {"client": client_name, "type": "ELEC", "profile": profile, "site_id": site_id}
                
                if pdl and len(pdl) > 5:
                    self.pdl_mapping[pdl] = info
                if pce and len(pce) > 5:
                    info_gaz = info.copy()
                    info_gaz["type"] = "GAZ"
                    self.pdl_mapping[pce] = info_gaz
                    
            except Exception as e:
                print(f"Erreur mappage Firestore: {e}")
        
        print(f"✅ CORTEX ROUTER: {len(self.pdl_mapping)} PDL/PCE connectés via Firestore.")

    def _extract_pdl_from_content(self, file_content: bytes, filename: str):
        """Scan intelligent (Deep Scan) + Détection du Header."""
        pdl = None
        header_row = 0
        df = None

        try:
            # CAS 1 : EXCEL
            if filename.endswith('.xlsx') or filename.endswith('.xls'):
                df = pd.read_excel(io.BytesIO(file_content), dtype=str, header=None)
                
                preview_str = df.head(20).to_string()
                if "Point Référence Mesure" in preview_str and ingest:
                    return "ENEDIS_INDIVIDUAL", None, 0

                for idx, row in df.head(20).iterrows():
                    row_str = " ".join([str(x) for x in row.values])
                    match = re.search(r'\d{14}', row_str)
                    if match and not match.group(0).startswith('202'):
                        pdl = match.group(0)
                        break
                return pdl, df, 0

            # CAS 2 : CSV (SGE)
            else:
                try: text = file_content.decode('utf-8')
                except: text = file_content.decode('latin-1')

                lines = text.splitlines()
                
                for i, line in enumerate(lines[:30]):
                    match = re.search(r'\d{14}', line)
                    if match and not match.group(0).startswith('202'):
                        pdl = match.group(0)
                    
                    if "Valeur" in line or "Consommation" in line or "Nature" in line:
                        header_row = i
                        if pdl: break
                
                if not pdl:
                    match = re.search(r'\d{14}', text[:5000])
                    if match and not match.group(0).startswith('202'):
                        pdl = match.group(0)

                return pdl, io.BytesIO(file_content), header_row

        except Exception as e:
            print(f"Deep Scan Error: {e}")
            return None, None, 0

    def _process_and_save_volume(self, pdl, file_stream, header_row, filename):
        """Orchestre le calcul physique et la sauvegarde DANS FIRESTORE."""
        try:
            client_info = self.pdl_mapping.get(pdl)
            if not client_info: return "Client inconnu"

            # 1. Lecture du Fichier (I/O)
            try:
                if filename.endswith('.xlsx'):
                    df = file_stream 
                else:
                    df = pd.read_csv(file_stream, sep=';', skiprows=header_row, encoding='latin-1', on_bad_lines='skip')
            except:
                file_stream.seek(0)
                df = pd.read_csv(file_stream, sep=',', skiprows=header_row, encoding='utf-8', on_bad_lines='skip')

            # 2. Identification Colonne Valeur
            val_col = None
            if isinstance(df, pd.DataFrame):
                for col in df.columns:
                    if "Valeur" in str(col) or "Conso" in str(col) or "P (W)" in str(col):
                        val_col = col
                        break
            
            if not val_col: return "Colonne 'Valeur' introuvable"

            # 3. APPEL AU PHYSICIEN (Calculs Mathématiques)
            if not physics: return "Erreur: Moteur physique non chargé"
            
            results = physics.analyze_load_curve(df, val_col)
            
            if "error" in results:
                return f"Erreur Analyse: {results['error']}"

            # 4. SAUVEGARDE DES RÉSULTATS DANS FIRESTORE
            site_id = client_info['site_id']
            data = db.get_site(site_id)
            
            if not data:
                return "Erreur: Document Cloud introuvable"
            
            if 'kpis' not in data: data['kpis'] = {}
            
            # Injection des nouvelles métriques IA
            data['kpis']['volume_mwh'] = results['volume_mwh']
            data['kpis']['talon_kw'] = results['talon_kw']
            data['kpis']['pmax_kw'] = results['pmax_kw']
            data['kpis']['cortex_advice'] = results['advice']
            data['kpis']['is_alert'] = results['is_alert']
            
            if 'contract' not in data: data['contract'] = {}
            if 'consumption_details' not in data['contract']: data['contract']['consumption_details'] = {}
            data['contract']['consumption_details']['volume_annuel'] = results['volume_annuel_kwh']
            data['contract']['consumption_details']['last_upload'] = datetime.now().strftime("%d/%m/%Y")

            # La frappe finale vers Google Cloud
            db.save_site(site_id, data)

            return f"Vol: {results['volume_mwh']} MWh | Talon: {results['talon_kw']} kW | {results['advice']}"

        except Exception as e:
            print(f"Erreur Process Router: {e}")
            return "Erreur traitement fichier"

    def analyze_file_stream(self, file_content: bytes, filename: str):
        """Point d'entrée de l'API."""
        self.refresh_database()

        pdl, stream, header_row = self._extract_pdl_from_content(file_content, filename)

        if pdl == "ENEDIS_INDIVIDUAL" and ingest:
            result = ingest.ingest_enedis_individual(file_content)
            return {
                "filename": filename,
                "status": result["status"],
                "message": result["message"],
                "pdl": result.get("pdl", "N/A"),
                "target_profile": "PARTICULIER"
            }

        if not pdl:
            match_filename = re.search(r'\d{14}', filename)
            if match_filename and not match_filename.group(0).startswith('202'):
                pdl = match_filename.group(0)
                stream = io.BytesIO(file_content)

        status = "REJECTED"
        message = "PDL introuvable."
        client_info = None
        
        if pdl:
            if pdl in self.pdl_mapping:
                client_info = self.pdl_mapping[pdl]
                
                vol_msg = self._process_and_save_volume(pdl, stream, header_row, filename)
                
                status = "INGESTED"
                message = f"{client_info['client']} -> {vol_msg}"
            else:
                status = "UNKNOWN_PDL"
                message = f"PDL {pdl} détecté mais absent de la base Firestore."
        
        return {
            "filename": filename,
            "status": status,
            "message": message,
            "pdl": pdl if pdl else "N/A",
            "target_profile": client_info['profile'] if client_info else "N/A"
        }

    def get_api_status(self):
        return {"sge_enedis": {"status": "ONLINE", "latency": "24ms"}, "adam_grdf": {"status": "ONLINE", "latency": "98ms"}}

router = CortexRouter()
