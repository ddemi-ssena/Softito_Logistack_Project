"""Pydantic response models for the RetailPulse API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KPIResponse(BaseModel):
    total_revenue: float
    total_orders: int
    average_order_value: float | None
    average_delivery_days: float | None


class SegmentSummary(BaseModel):
    segment_name: str
    customer_count: int
    average_recency_days: float | None
    average_frequency: float | None
    average_monetary: float | None


class SegmentResponse(BaseModel):
    total_customers: int
    segments: list[SegmentSummary]


class StreamingStatsResponse(BaseModel):
    total_events: int
    last_event_at: datetime | None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["connected"]


class ChurnPredictionRequest(BaseModel):
    recency_days: int = Field(ge=0)
    frequency: int = Field(ge=1)
    monetary: float = Field(ge=0)
    avg_item_price: float = Field(ge=0)
    avg_review_score: float | None = Field(default=None, ge=1, le=5)


class ChurnPredictionResponse(BaseModel):
    churn_prediction: bool
    churn_probability: float = Field(ge=0, le=1)
    risk_level: Literal["Düşük", "Orta", "Yüksek"]
    action_recommendation: str
