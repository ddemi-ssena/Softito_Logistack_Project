FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY api ./api
COPY dashboard ./dashboard
COPY etl ./etl
COPY ingestion ./ingestion
COPY models ./models
COPY .streamlit ./.streamlit

EXPOSE 8000 8501
