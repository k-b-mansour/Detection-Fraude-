# Serveur de suivi MLflow — backend PostgreSQL (base `mlflow` de l'instance BC01),
# artefacts servis en proxy (--serve-artifacts) sur un volume Docker.
#
# L'image officielle ghcr.io/mlflow/mlflow n'embarque ni le driver PostgreSQL ni
# psycopg2 : on installe donc mlflow + psycopg2-binary sur une base python-slim.
FROM python:3.11-slim

# --trusted-host : contourne l'inspection SSL du proxy d'entreprise de cet
# environnement de dev (même contrainte que bc05_api_monitoring/Dockerfile) —
# sans effet sur un réseau standard.
RUN pip install --no-cache-dir \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org \
    mlflow==3.16.0 psycopg2-binary==2.9.9

COPY mlflow-server/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health', timeout=2)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
