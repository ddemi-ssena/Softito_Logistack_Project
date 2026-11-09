import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import health, metrics, predictions, segments, streaming


app = FastAPI(
    title="RetailPulse API",
    description="Analytics and streaming metrics for RetailPulse.",
    version="1.0.0",
)

origins = [
    origin.strip()
    for origin in os.getenv(
        "API_CORS_ORIGINS",
        "http://localhost:8501,http://127.0.0.1:8501",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(segments.router)
app.include_router(streaming.router)
app.include_router(predictions.router)
