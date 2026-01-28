# Utilisation d'une image Python légère officielle
FROM python:3.10-slim

# Définition du dossier de travail dans le conteneur
WORKDIR /app

# Copie des dépendances et installation
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie de tout le reste du code (main.py, templates, static)
COPY . .

# Cloud Run injecte la variable PORT au démarrage
# On utilise la variable d'environnement $PORT
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}