# Dockerfile V3 - Architecture Enterprise "app"
FROM python:3.10-slim

# Configuration de l'environnement Python
# PYTHONPATH=/app est vital pour que Python trouve le module "app.core"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PYTHONPATH=/app

WORKDIR /app

# 1. Installation des dépendances (Mise en cache Docker pour build rapide)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copie de la structure applicative V3
# On prend le dossier local 'app' et on le met dans '/app/app' du conteneur
COPY app/ ./app/

# 3. Gestion des fichiers statiques (CSS/JS/Images)
# On copie ton dossier 'statique' local vers le dossier standard 'static' du serveur
COPY statique/ ./static/

# 4. Création du point de montage pour les données (Volume Persistant)
RUN mkdir -p /app/data

# 5. Lancement de l'application
# Note le changement : 'app.main:app' au lieu de 'main:app'
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
