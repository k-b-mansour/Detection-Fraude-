"""
BC05 — API de scoring temps réel.

Sert le modèle LightGBM entraîné et sauvegardé au BC03, avec explicabilité
SHAP par prédiction (même technique qu'au BC03, appliquée ici en ligne).
Le score s'accompagne de deux lectures du seuil (défaut 0,5 / optimisé
0,98, cf. bc03-explication-v2.pdf section 6), et, si un client_id connu
est fourni, des compteurs temps réel du feature store Redis du BC01.

Démarrage :
    uvicorn bc05_api_monitoring.api.main:app --host 0.0.0.0 --port 8000
"""
import json
import logging
import os
import time
from contextlib import asynccontextmanager

import joblib
import numpy as np
import pandas as pd
import redis
import shap
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .schemas import FeatureContribution, FraudPrediction, HealthResponse, TransactionInput

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("bc05-api")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH = os.path.join(BASE_DIR, "bc03_modeles_supervises", "models", "modele_lightgbm.joblib")
RESUME_PATH = os.path.join(BASE_DIR, "bc03_modeles_supervises", "outputs", "resume_bc03.json")

FEATURE_COLUMNS = [
    "montant", "distance_domicile_km", "revenu_mensuel_net", "heure", "jour_semaine", "mois",
    "is_weekend", "is_nuit", "authentification", "canal", "segment",
]
SEUIL_DEFAUT = 0.5
VERSION_MODELE = "lightgbm-bc03-v1"

_etat = {}


@asynccontextmanager
async def cycle_de_vie(app: FastAPI):
    t0 = time.perf_counter()
    _etat["pipeline"] = joblib.load(MODEL_PATH)
    _etat["prep"] = _etat["pipeline"].named_steps["prep"]
    _etat["modele"] = _etat["pipeline"].named_steps["clf"]
    _etat["noms_features"] = (
        ["montant", "distance_domicile_km", "revenu_mensuel_net", "heure", "jour_semaine", "mois",
         "is_weekend", "is_nuit"]
        + list(_etat["prep"].named_transformers_["cat"].get_feature_names_out(
            ["authentification", "canal", "segment"]))
    )
    _etat["explainer"] = shap.TreeExplainer(_etat["modele"])

    with open(RESUME_PATH, encoding="utf-8") as f:
        resume = json.load(f)
    _etat["auc_roc_reference"] = resume["modeles"]["lightgbm"]["auc_roc"]
    _etat["seuil_optimise"] = resume["seuil_optimal_lightgbm"]

    try:
        _etat["redis"] = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6380")),
            decode_responses=True, socket_connect_timeout=0.5,
        )
        _etat["redis"].ping()
        log.info("Connecté au feature store Redis (BC01)")
    except Exception as exc:
        _etat["redis"] = None
        log.warning("Redis indisponible, l'API fonctionnera sans enrichissement temps réel (%s)", exc)

    _etat["demarre_a"] = time.perf_counter()
    log.info("Modèle chargé en %.0f ms (version=%s, AUC référence=%.4f, seuil optimisé=%.2f)",
              (time.perf_counter() - t0) * 1000, VERSION_MODELE, _etat["auc_roc_reference"], _etat["seuil_optimise"])
    yield
    _etat.clear()


app = FastAPI(
    title="API de scoring fraude — projet portfolio RNCP",
    description="Détection de fraude carte bancaire en temps réel (< 200 ms), modèle LightGBM du BC03.",
    version="1.0.0",
    lifespan=cycle_de_vie,
)


def _explication_binaire(expl: shap.Explanation) -> shap.Explanation:
    """Normalise la sortie SHAP vers la classe positive (fraude) — même
    logique que bc03_modeles_supervises/scripts/explicabilite_shap.ipynb."""
    values = expl.values
    base_values = expl.base_values
    if values.ndim == 3:
        values = values[:, :, 1]
    if np.ndim(base_values) == 2:
        base_values = base_values[:, 1]
    return shap.Explanation(values=values, base_values=base_values, data=expl.data, feature_names=expl.feature_names)


def _features_temps_reel(client_id: str | None) -> dict | None:
    if not client_id or _etat.get("redis") is None:
        return None
    try:
        nb_tx = _etat["redis"].get(f"feat:{client_id}:nb_tx_1h")
        montant_cumul = _etat["redis"].get(f"feat:{client_id}:montant_cumul_1h")
        if nb_tx is None and montant_cumul is None:
            return None
        return {
            "nb_tx_1h": int(nb_tx) if nb_tx else 0,
            "montant_cumul_1h": round(float(montant_cumul), 2) if montant_cumul else 0.0,
        }
    except Exception as exc:
        log.warning("Lecture Redis échouée pour client_id=%s : %s", client_id, exc)
        return None


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        version_modele=VERSION_MODELE,
        auc_roc_reference=_etat["auc_roc_reference"],
        seuil_optimise=_etat["seuil_optimise"],
        uptime_s=round(time.perf_counter() - _etat["demarre_a"], 1),
    )


@app.post("/api/v1/predict", response_model=FraudPrediction)
def predict(transaction: TransactionInput):
    t0 = time.perf_counter()
    donnees = transaction.model_dump(exclude={"client_id"})
    df = pd.DataFrame([donnees])[FEATURE_COLUMNS]

    try:
        proba = float(_etat["pipeline"].predict_proba(df)[0, 1])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Échec du scoring : {exc}")

    X_enc = _etat["prep"].transform(df)
    explication = _explication_binaire(_etat["explainer"](X_enc))
    contributions = sorted(
        zip(_etat["noms_features"], explication.values[0]), key=lambda t: abs(t[1]), reverse=True
    )[:5]

    seuil_optimise = _etat["seuil_optimise"]
    if proba >= seuil_optimise:
        risk_level = "eleve"
    elif proba >= SEUIL_DEFAUT:
        risk_level = "moyen"
    else:
        risk_level = "faible"

    latence_ms = (time.perf_counter() - t0) * 1000

    return FraudPrediction(
        score=round(proba, 4),
        seuil_defaut=SEUIL_DEFAUT,
        seuil_optimise=seuil_optimise,
        is_fraud_seuil_defaut=proba >= SEUIL_DEFAUT,
        is_fraud_seuil_optimise=proba >= seuil_optimise,
        risk_level=risk_level,
        top_features=[FeatureContribution(feature=f, impact=round(float(v), 4)) for f, v in contributions],
        features_temps_reel=_features_temps_reel(transaction.client_id),
        latence_ms=round(latence_ms, 2),
        version_modele=VERSION_MODELE,
    )


@app.exception_handler(Exception)
async def gestion_erreurs(request, exc):
    log.exception("Erreur non gérée")
    return JSONResponse(status_code=500, content={"detail": "Erreur interne du serveur de scoring"})
