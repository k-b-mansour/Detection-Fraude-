#!/bin/sh
# Crée la base `mlflow` sur l'instance PostgreSQL partagée si elle n'existe pas
# (les scripts d'init de bc01_socle_donnees/sql ne se rejouent pas sur un volume
# pg_data déjà initialisé), puis démarre le serveur de suivi MLflow.
set -e

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-fraud_admin}"
PGPASSWORD="${PGPASSWORD:-fraud_secret}"
PGADMINDB="${PGADMINDB:-frauddetect}"
MLFLOW_DB="${MLFLOW_DB:-mlflow}"

export PGPASSWORD

python - <<EOF
import os, time, sys
import psycopg2

host, port = "${PGHOST}", int("${PGPORT}")
user, password = "${PGUSER}", "${PGPASSWORD}"
admin_db, mlflow_db = "${PGADMINDB}", "${MLFLOW_DB}"

for tentative in range(1, 31):
    try:
        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname=admin_db)
        break
    except Exception as exc:
        print(f"[mlflow] attente de PostgreSQL ({tentative}/30) : {exc}")
        time.sleep(2)
else:
    print("[mlflow] PostgreSQL injoignable, abandon", file=sys.stderr)
    sys.exit(1)

conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (mlflow_db,))
    if cur.fetchone() is None:
        cur.execute(f'CREATE DATABASE "{mlflow_db}"')
        print(f"[mlflow] base '{mlflow_db}' créée")
    else:
        print(f"[mlflow] base '{mlflow_db}' déjà présente")
conn.close()
EOF

BACKEND_URI="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${MLFLOW_DB}"

exec mlflow server \
    --backend-store-uri "${BACKEND_URI}" \
    --artifacts-destination /mlartifacts \
    --serve-artifacts \
    --host 0.0.0.0 --port 5000
