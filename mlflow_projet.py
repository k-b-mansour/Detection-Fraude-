"""Suivi d'expériences MLflow — configuration partagée BC03 / BC04.

Un serveur de suivi tourne dans le `docker-compose` racine (service `mlflow`) :

  - UI        : http://localhost:5000
  - backend   : PostgreSQL (base `mlflow`, même instance que le socle BC01)
  - artefacts : volume Docker `mlflow_artifacts`, servis en proxy par le serveur
                (`--serve-artifacts`) — les notebooks n'ont donc pas besoin d'un
                accès disque partagé, tout passe par HTTP.

Si le serveur est injoignable (Docker non démarré), on bascule automatiquement
sur un backend **SQLite local** (`mlruns/mlflow.db`, artefacts dans
`mlruns/artifacts/`) pour que les notebooks restent exécutables hors
infrastructure. MLflow 3 a retiré le backend « fichier » historique (`./mlruns`
brut), d'où SQLite pour le repli. L'appelant récupère l'URI effectif.

Usage (dans un notebook des blocs BC03/BC04) :

    import os, sys
    sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), "..", "..")))
    from mlflow_projet import init_mlflow
    import mlflow

    init_mlflow("bc03_modeles_supervises")
    with mlflow.start_run(run_name="lightgbm"):
        mlflow.log_params(...); mlflow.log_metric(...)
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import mlflow

_DIR_LOCAL = Path(__file__).resolve().parent / "mlruns"
_STORE_LOCAL = "sqlite:///" + (_DIR_LOCAL / "mlflow.db").as_posix()
_ARTEFACTS_LOCAL = (_DIR_LOCAL / "artifacts").as_uri()


def _serveur_joignable(uri: str, timeout: float = 2.0) -> bool:
    """Sonde rapide de `<uri>/health` (timeout court, sans les retries du
    client MLflow qui feraient attendre le notebook de longues secondes)."""
    if not uri.startswith(("http://", "https://")):
        return True  # backend base de données ou autre : rien à sonder
    try:
        with urllib.request.urlopen(uri.rstrip("/") + "/health", timeout=timeout):
            return True
    except Exception:
        return False


def init_mlflow(experiment: str) -> str:
    """Configure MLflow pour l'expérience donnée.

    Cible le serveur défini par MLFLOW_TRACKING_URI (défaut : http://localhost:5000).
    S'il ne répond pas sur /health, bascule sur le backend SQLite local `mlruns/`.
    Retourne l'URI de suivi effectif.
    """
    uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    repli = not _serveur_joignable(uri)
    if repli:
        _DIR_LOCAL.mkdir(parents=True, exist_ok=True)
        uri = _STORE_LOCAL
        print(f"[mlflow_projet] serveur injoignable — repli SQLite local : {uri}")

    mlflow.set_tracking_uri(uri)
    if repli and mlflow.get_experiment_by_name(experiment) is None:
        mlflow.create_experiment(experiment, artifact_location=_ARTEFACTS_LOCAL)
    mlflow.set_experiment(experiment)
    return mlflow.get_tracking_uri()
