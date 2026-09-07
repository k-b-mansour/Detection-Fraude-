# BC05 — API temps réel, monitoring, conteneurisation, CI/CD

Sert le modèle LightGBM du [BC03](../bc03_modeles_supervises/README.md) via une API FastAPI
conteneurisée, avec explicabilité SHAP par requête, enrichissement optionnel depuis le feature
store Redis du [BC01](../bc01_socle_donnees/docs/BC01.md), monitoring de dérive Evidently AI et
pipeline CI/CD GitHub Actions.

## Démarrage

```bash
# API (conteneurisée, via le docker-compose racine)
docker compose up -d --build api      # écoute sur http://localhost:8001

# Tests
pip install -r bc05_api_monitoring/requirements-api.txt pytest httpx
pytest bc05_api_monitoring/tests/ -v  # 7/7

# Monitoring de dérive
python bc05_api_monitoring/scripts/drift_report.py
```

| Interface | URL |
|---|---|
| API (santé) | http://localhost:8001/health |
| API (Swagger) | http://localhost:8001/docs |

Document détaillé : [docs/bc05-explication.pdf](docs/bc05-explication.pdf).

## Résultats clés (dernier run)

- **Latence** : 24-60 ms par prédiction (conteneurisée) — largement sous la contrainte de 200 ms
- **Explicabilité** : top 5 facteurs SHAP recalculés à la volée pour chaque requête (RGPD Art. 22)
- **Tests** : 7/7 (santé, score légitime vs suspect, latence, validation Pydantic, enrichissement Redis)
- **Monitoring** : 9,1 % de dérive en scénario normal (pas d'alerte) / 27,3 % en scénario simulé
  (alerte, seuil 20 %) — voir le rapport pour l'explication du signal naturel sur `mois` (artefact
  du split temporel du BC03, pas une vraie dérive de comportement)
- **CI/CD** : `.github/workflows/ci-cd.yml` (tests + build + healthcheck + publication GHCR sur
  `main`) — chaque étape rejouée et vérifiée en local ; l'exécution sur de vrais runners GitHub
  nécessite un dépôt distant, non configuré dans cette session

## Deux incidents Docker réels, documentés dans le rapport

1. Échec SSL de `pip install` (proxy réseau local) → `--trusted-host`
2. `libgomp.so.1` manquant (image `slim`, requis par LightGBM) → `apt-get install libgomp1`
