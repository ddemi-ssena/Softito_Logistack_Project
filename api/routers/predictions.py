"""Model inference endpoints."""

from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
from fastapi import APIRouter, HTTPException

from api.schemas import ChurnPredictionRequest, ChurnPredictionResponse


router = APIRouter(prefix="/api/v1/predict", tags=["predictions"])
MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "churn_model.joblib"


@lru_cache(maxsize=1)
def load_model_bundle():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(f"Trained churn model is missing: {MODEL_PATH}")
    return joblib.load(MODEL_PATH)


@router.post("/churn", response_model=ChurnPredictionResponse)
def predict_churn(request: ChurnPredictionRequest):
    try:
        bundle = load_model_bundle()
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"Churn model could not be loaded: {error}") from error

    values = request.model_dump()
    features = bundle["features"]
    frame = pd.DataFrame([{name: values[name] for name in features}], columns=features)
    transformed = bundle["preprocessor"].transform(frame)
    probability = float(bundle["model"].predict_proba(transformed)[0, 1])
    prediction = probability >= 0.5
    if probability >= 0.70:
        risk, action = "Yüksek", "Kişiye özel indirim kuponu gönder"
    elif probability >= 0.40:
        risk, action = "Orta", "Sadakat programı ve ürün önerisi sun"
    else:
        risk, action = "Düşük", "Düzenli iletişim ve yeni ürün önerileriyle etkileşimi sürdür"
    return ChurnPredictionResponse(
        churn_prediction=prediction,
        churn_probability=probability,
        risk_level=risk,
        action_recommendation=action,
    )
