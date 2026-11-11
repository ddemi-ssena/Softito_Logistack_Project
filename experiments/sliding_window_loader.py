"""Build leakage-safe temporal churn windows from the Gold PostgreSQL schema."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit
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
SNAPSHOT_DATES = ("2017-10-01", "2017-12-15", "2018-03-04")


WINDOW_QUERY = """
    WITH params AS (
        SELECT %(snapshot_date)s::date AS snapshot_date,
               (%(snapshot_date)s::date + (%(horizon)s * INTERVAL '1 day')) AS observation_end
    ), historical AS (
        SELECT f.*
        FROM gold.fact_orders AS f
        CROSS JOIN params AS p
        WHERE f.order_purchase_timestamp < p.snapshot_date
          AND f.customer_unique_id IS NOT NULL
    ), customer_features AS (
        SELECT h.customer_unique_id,
               (p.snapshot_date - MAX(h.order_purchase_timestamp)::date)::integer AS recency_days,
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
    ), future_orders AS (
        SELECT DISTINCT f.customer_unique_id
        FROM gold.fact_orders AS f
        CROSS JOIN params AS p
        WHERE f.order_purchase_timestamp >= p.snapshot_date
          AND f.order_purchase_timestamp < p.observation_end
          AND f.customer_unique_id IS NOT NULL
    )
    SELECT p.snapshot_date,
           c.customer_unique_id,
           c.recency_days,
           c.frequency,
           c.monetary,
           i.avg_item_price,
           r.avg_review_score,
           CASE WHEN f.customer_unique_id IS NULL THEN 1 ELSE 0 END::integer AS churn
    FROM customer_features AS c
    CROSS JOIN params AS p
    LEFT JOIN item_features AS i USING (customer_unique_id)
    LEFT JOIN review_features AS r USING (customer_unique_id)
    LEFT JOIN future_orders AS f USING (customer_unique_id)
    WHERE c.frequency >= %(min_frequency)s
    ORDER BY c.customer_unique_id
"""


def load_window(connection, snapshot_date: str) -> pd.DataFrame:
    """Load one snapshot cohort and its 180-day outcome from Gold tables."""
    data = pd.read_sql_query(
        WINDOW_QUERY,
        connection,
        params={
            "snapshot_date": snapshot_date,
            "horizon": HORIZON_DAYS,
            "min_frequency": MIN_HISTORICAL_ORDERS,
        },
    )
    if not data.empty:
        data["snapshot_date"] = pd.to_datetime(data["snapshot_date"])
        data[TARGET] = data[TARGET].astype(int)
    return data


def load_data():
    """Return scaled group-safe splits, labels, group IDs, and cohort metadata."""
    with psycopg.connect(**connection_settings()) as connection:
        windows = {date: load_window(connection, date) for date in SNAPSHOT_DATES}

    for date, frame in windows.items():
        if frame.empty:
            raise RuntimeError(f"{date} snapshot için Gold tablolarından örnek üretilemedi.")
        print(
            f"Snapshot {date}: {len(frame):,} örnek | "
            f"sınıflar {{0: {(frame[TARGET] == 0).sum():,}, 1: {(frame[TARGET] == 1).sum():,}}}"
        )

    data = pd.concat(windows.values(), ignore_index=True)
    if data.empty or data["customer_unique_id"].nunique() < 2:
        raise RuntimeError("GroupShuffleSplit için en az iki farklı müşteri gerekli.")

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.20, random_state=42)
    train_idx, test_idx = next(
        splitter.split(data[FEATURES], data[TARGET], groups=data["customer_unique_id"])
    )
    train = data.iloc[train_idx]
    test = data.iloc[test_idx]
    scaler = StandardScaler()
    x_train = scaler.fit_transform(train[FEATURES])
    x_test = scaler.transform(test[FEATURES])
    y_train = train[TARGET].reset_index(drop=True)
    y_test = test[TARGET].reset_index(drop=True)
    train_groups = train["customer_unique_id"].reset_index(drop=True)
    test_groups = test["customer_unique_id"].reset_index(drop=True)

    overlap = set(train_groups).intersection(test_groups)
    if overlap:
        raise RuntimeError(f"Leakage guard failed: {len(overlap)} customers occur in both splits.")

    def distribution(labels: pd.Series) -> dict[int, int]:
        counts = labels.value_counts().to_dict()
        return {0: int(counts.get(0, 0)), 1: int(counts.get(1, 0))}

    print("-" * 68)
    print(f"Total pooled rows       : {len(data):,}")
    print(f"Train rows / customers  : {len(train):,} / {train_groups.nunique():,}")
    print(f"Test rows / customers   : {len(test):,} / {test_groups.nunique():,}")
    print(f"Train class counts      : {distribution(y_train)} (0 / 1)")
    print(f"Test class counts       : {distribution(y_test)} (0 / 1)")
    print("Customer overlap        : 0")
    print("-" * 68)

    metadata = {
        "windows": {date: len(frame) for date, frame in windows.items()},
        "total_rows": len(data),
        "train_rows": len(train),
        "test_rows": len(test),
        "train_class_counts": distribution(y_train),
        "test_class_counts": distribution(y_test),
        "features": FEATURES.copy(),
        "horizon_days": HORIZON_DAYS,
        "scaler": scaler,
    }
    return x_train, x_test, y_train, y_test, train_groups, test_groups, metadata


if __name__ == "__main__":
    load_data()
