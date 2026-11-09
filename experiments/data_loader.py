"""Load the historical repeat-customer cohort and prepare a stratified split."""

import sys
from pathlib import Path

import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl"))
from extract import connection_settings  # noqa: E402
import psycopg  # noqa: E402

FEATURES = [
    "recency_days",
    "frequency",
    "monetary",
    "avg_item_price",
    "avg_review_score",
]
TARGET = "churn"
HORIZON_DAYS = 180
MIN_HISTORICAL_ORDERS = 2


def load_customer_cohort() -> tuple[pd.DataFrame, object]:
    """Build features before the snapshot and churn labels over the next 180 days."""
    query = """
        WITH bounds AS (
            SELECT MAX(order_purchase_timestamp)::date AS max_date
            FROM gold.fact_orders
            WHERE order_purchase_timestamp IS NOT NULL
        ), params AS (
            SELECT max_date - (%(horizon)s * INTERVAL '1 day') AS snapshot_date,
                   max_date + INTERVAL '1 day' AS observation_end
            FROM bounds
        ), historical AS (
            SELECT f.*
            FROM gold.fact_orders AS f
            CROSS JOIN params AS p
            WHERE f.order_purchase_timestamp < p.snapshot_date
              AND f.customer_unique_id IS NOT NULL
        ), customer_features AS (
            SELECT h.customer_unique_id,
                   (p.snapshot_date::date - MAX(h.order_purchase_timestamp)::date)::integer AS recency_days,
                   COUNT(*)::integer AS frequency,
                   SUM(h.total_product_amount)::double precision AS monetary
            FROM historical AS h
            CROSS JOIN params AS p
            GROUP BY h.customer_unique_id, p.snapshot_date
        ), item_features AS (
            SELECT h.customer_unique_id, AVG(i.price)::double precision AS avg_item_price
            FROM historical AS h
            JOIN gold.fact_order_items AS i ON i.order_id = h.order_id
            GROUP BY h.customer_unique_id
        ), review_features AS (
            SELECT h.customer_unique_id, AVG(r.review_score)::double precision AS avg_review_score
            FROM historical AS h
            JOIN silver.order_reviews AS r ON r.order_id = h.order_id
            GROUP BY h.customer_unique_id
        ), future_repeat AS (
            SELECT DISTINCT f.customer_unique_id
            FROM gold.fact_orders AS f
            CROSS JOIN params AS p
            WHERE f.order_purchase_timestamp >= p.snapshot_date
              AND f.order_purchase_timestamp < p.observation_end
              AND f.customer_unique_id IS NOT NULL
        )
        SELECT c.customer_unique_id, c.recency_days, c.frequency, c.monetary,
               i.avg_item_price, r.avg_review_score,
               CASE WHEN f.customer_unique_id IS NULL THEN 1 ELSE 0 END AS churn
        FROM customer_features AS c
        LEFT JOIN item_features AS i USING (customer_unique_id)
        LEFT JOIN review_features AS r USING (customer_unique_id)
        LEFT JOIN future_repeat AS f USING (customer_unique_id)
        WHERE c.frequency >= %(min_frequency)s
    """
    with psycopg.connect(**connection_settings()) as connection:
        data = pd.read_sql_query(
            query,
            connection,
            params={
                "horizon": HORIZON_DAYS,
                "min_frequency": MIN_HISTORICAL_ORDERS,
            },
        )
        snapshot_date = pd.read_sql_query(
            "SELECT (MAX(order_purchase_timestamp)::date - %s)::date FROM gold.fact_orders",
            connection,
            params=(HORIZON_DAYS,),
        ).iloc[0, 0]

    if data.empty:
        raise RuntimeError("Gold tablolarından eğitim müşterisi üretilemedi.")
    data[TARGET] = data[TARGET].astype(int)
    return data, snapshot_date


def load_data(random_state: int = 42):
    """Return imputed/scaled 80:20 stratified train/test data and cohort metadata."""
    data, snapshot_date = load_customer_cohort()
    class_counts = data[TARGET].value_counts()
    if len(class_counts) != 2 or class_counts.min() < 2:
        raise RuntimeError(f"Stratified split için iki sınıfta da en az 2 kayıt gerekli: {class_counts.to_dict()}")

    x_train, x_test, y_train, y_test = train_test_split(
        data[FEATURES],
        data[TARGET],
        test_size=0.20,
        random_state=random_state,
        stratify=data[TARGET],
    )
    imputer = SimpleImputer(strategy="median")
    x_train_imputed = imputer.fit_transform(x_train)
    x_test_imputed = imputer.transform(x_test)
    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train_imputed)
    x_test_scaled = scaler.transform(x_test_imputed)

    metadata = {
        "snapshot_date": snapshot_date,
        "horizon_days": HORIZON_DAYS,
        "min_historical_orders": MIN_HISTORICAL_ORDERS,
        "class_counts": class_counts.to_dict(),
        "total_rows": len(data),
        "features": FEATURES.copy(),
        "imputer": imputer,
        "scaler": scaler,
    }
    return x_train_scaled, x_test_scaled, y_train, y_test, metadata
