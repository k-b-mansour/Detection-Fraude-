# BC05 — image de service pour l'API de scoring.
#
# Dépendances allégées (requirements-api.txt) : pas de psycopg2, confluent-kafka,
# tensorflow, matplotlib ni evidently — cette image ne sert que des prédictions,
# elle n'entraîne rien. Contexte de build = racine du dépôt (voir docker-compose.yml)
# pour pouvoir embarquer le modèle du BC03 sans dupliquer de code entre blocs.
FROM python:3.10-slim

# libgomp1 : runtime OpenMP requis par LightGBM au chargement — absent de
# l'image slim, l'omettre plante le démarrage avec "libgomp.so.1: cannot
# open shared object file" au premier joblib.load() du modèle.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY bc05_api_monitoring/requirements-api.txt .
# --trusted-host : contourne l'inspection SSL du proxy d'entreprise de cet
# environnement de développement (certificat non reconnu par le conteneur) —
# sans incidence sur un environnement réseau standard.
RUN pip install --no-cache-dir \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org \
    -r requirements-api.txt

COPY bc05_api_monitoring/__init__.py bc05_api_monitoring/__init__.py
COPY bc05_api_monitoring/api bc05_api_monitoring/api
COPY bc03_modeles_supervises/models/modele_lightgbm.joblib bc03_modeles_supervises/models/modele_lightgbm.joblib
COPY bc03_modeles_supervises/outputs/resume_bc03.json bc03_modeles_supervises/outputs/resume_bc03.json

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "bc05_api_monitoring.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
