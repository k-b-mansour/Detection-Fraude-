"""BC05 — Schémas Pydantic de l'API de scoring."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TransactionInput(BaseModel):
    """Une transaction à scorer, mêmes variables que le modèle du BC03."""

    montant: float = Field(..., gt=0, examples=[89.90])
    distance_domicile_km: float = Field(..., ge=0, examples=[12.4])
    revenu_mensuel_net: float = Field(..., gt=0, examples=[2400.0])
    heure: int = Field(..., ge=0, le=23, examples=[14])
    jour_semaine: int = Field(..., ge=1, le=7, description="1 = lundi ... 7 = dimanche", examples=[3])
    mois: int = Field(..., ge=1, le=12, examples=[6])
    is_weekend: bool = Field(..., examples=[False])
    is_nuit: bool = Field(..., examples=[False])
    authentification: Literal["puce_pin", "3ds", "none"] = Field(..., examples=["puce_pin"])
    canal: Literal["en_ligne", "puce", "sans_contact", "distributeur"] = Field(..., examples=["puce"])
    segment: Literal["particulier", "premium", "professionnel"] = Field(..., examples=["particulier"])
    client_id: Optional[str] = Field(
        None, description="Si fourni et connu de Redis, enrichit la réponse avec les compteurs temps réel du BC01"
    )


class FeatureContribution(BaseModel):
    feature: str
    impact: float


class FraudPrediction(BaseModel):
    score: float
    seuil_defaut: float
    seuil_optimise: float
    is_fraud_seuil_defaut: bool
    is_fraud_seuil_optimise: bool
    risk_level: Literal["faible", "moyen", "eleve"]
    top_features: list[FeatureContribution]
    features_temps_reel: Optional[dict] = None
    latence_ms: float
    version_modele: str


class HealthResponse(BaseModel):
    status: str
    version_modele: str
    auc_roc_reference: float
    seuil_optimise: float
    uptime_s: float
