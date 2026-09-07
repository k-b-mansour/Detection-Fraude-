"""
BC05 — Tests de l'API de scoring.

Exécutés localement par pytest et par le pipeline CI/CD (.github/workflows/ci-cd.yml)
à chaque push. Nécessitent le modèle du BC03 déjà entraîné
(bc03_modeles_supervises/models/modele_lightgbm.joblib) — pas de base de données ni
de Redis requis : le test_client_id_inconnu vérifie justement que l'API dégrade
proprement en l'absence de Redis/feature store.

Usage :
    pytest bc05_api_monitoring/tests/ -v
"""
import pytest
from fastapi.testclient import TestClient

from bc05_api_monitoring.api.main import app


@pytest.fixture(scope="module")
def client():
    # Le contexte "with" est nécessaire pour déclencher le cycle de vie
    # (chargement du modèle, connexion Redis) — un TestClient(app) simple,
    # hors contexte, ne l'exécute jamais et chaque requête échouerait.
    with TestClient(app) as c:
        yield c

TRANSACTION_LEGITIME = {
    "montant": 42.5, "distance_domicile_km": 8.0, "revenu_mensuel_net": 2400.0,
    "heure": 14, "jour_semaine": 3, "mois": 6,
    "is_weekend": False, "is_nuit": False,
    "authentification": "puce_pin", "canal": "puce", "segment": "particulier",
}

TRANSACTION_SUSPECTE = {
    "montant": 850.0, "distance_domicile_km": 320.5, "revenu_mensuel_net": 2100.0,
    "heure": 3, "jour_semaine": 5, "mois": 7,
    "is_weekend": False, "is_nuit": True,
    "authentification": "none", "canal": "en_ligne", "segment": "particulier",
}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    corps = r.json()
    assert corps["status"] == "ok"
    assert 0.0 <= corps["auc_roc_reference"] <= 1.0
    assert 0.0 <= corps["seuil_optimise"] <= 1.0


def test_predict_transaction_legitime(client):
    r = client.post("/api/v1/predict", json=TRANSACTION_LEGITIME)
    assert r.status_code == 200
    corps = r.json()
    assert 0.0 <= corps["score"] <= 1.0
    assert corps["risk_level"] in ("faible", "moyen", "eleve")
    assert len(corps["top_features"]) == 5
    assert corps["features_temps_reel"] is None  # pas de client_id fourni


def test_predict_transaction_suspecte_score_plus_eleve(client):
    score_legit = client.post("/api/v1/predict", json=TRANSACTION_LEGITIME).json()["score"]
    score_suspect = client.post("/api/v1/predict", json=TRANSACTION_SUSPECTE).json()["score"]
    assert score_suspect > score_legit


def test_predict_latence_sous_200ms(client):
    r = client.post("/api/v1/predict", json=TRANSACTION_SUSPECTE)
    assert r.json()["latence_ms"] < 200


def test_predict_canal_invalide_rejete(client):
    payload = {**TRANSACTION_LEGITIME, "canal": "virement_bancaire_inexistant"}
    r = client.post("/api/v1/predict", json=payload)
    assert r.status_code == 422  # erreur de validation Pydantic, pas une exception serveur


def test_predict_montant_negatif_rejete(client):
    payload = {**TRANSACTION_LEGITIME, "montant": -10.0}
    r = client.post("/api/v1/predict", json=payload)
    assert r.status_code == 422


def test_predict_client_id_inconnu_pas_enrichi(client):
    payload = {**TRANSACTION_LEGITIME, "client_id": "id-qui-nexiste-pas"}
    r = client.post("/api/v1/predict", json=payload)
    assert r.status_code == 200
    assert r.json()["features_temps_reel"] is None
