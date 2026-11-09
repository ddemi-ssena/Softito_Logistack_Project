"""Train a temporal 90-day repeat-purchase (churn) classifier from Gold data."""

import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, average_precision_score, confusion_matrix, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


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
HORIZON_DAYS = 180
MIN_HISTORICAL_ORDERS = 2
MODEL_PATH = ROOT / "models" / "churn_model.joblib"


def load_training_data():
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
        SELECT c.recency_days, c.frequency, c.monetary, i.avg_item_price,
               v.avg_review_score,
               CASE WHEN r.customer_unique_id IS NULL THEN 1 ELSE 0 END AS churn
        FROM customer_features AS c
        LEFT JOIN item_features AS i USING (customer_unique_id)
        LEFT JOIN review_features AS v USING (customer_unique_id)
        LEFT JOIN future_repeat AS r USING (customer_unique_id)
        WHERE c.frequency >= %(min_frequency)s
    """
    with psycopg.connect(**connection_settings()) as connection:
        data = pd.read_sql_query(
            query,
            connection,
            params={"horizon": HORIZON_DAYS, "min_frequency": MIN_HISTORICAL_ORDERS},
        )
        snapshot = pd.read_sql_query(
            "SELECT (MAX(order_purchase_timestamp)::date - %s)::date AS snapshot_date FROM gold.fact_orders",
            connection,
            params=(HORIZON_DAYS,),
        ).iloc[0, 0]
    if data.empty:
        raise RuntimeError("Gold fact_orders did not produce any supervised churn examples.")
    data["churn"] = data["churn"].astype(int)
    return data, snapshot


def main():
    data, snapshot_date = load_training_data()
    counts = data["churn"].value_counts()
    if len(counts) != 2 or counts.min() < 2:
        raise RuntimeError(f"Both churn classes need at least two rows; got {counts.to_dict()}")

    x_train, x_test, y_train, y_test = train_test_split(
        data[FEATURES],
        data["churn"],
        test_size=0.2,
        random_state=42,
        stratify=data["churn"],
    )
    preprocessor = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    x_train_scaled = preprocessor.fit_transform(x_train)
    x_test_scaled = preprocessor.transform(x_test)
    model = XGBClassifier(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.04,
        subsample=0.85,
        colsample_bytree=0.9,
        reg_lambda=2.0,
        scale_pos_weight=float((y_train == 0).sum() / max(1, (y_train == 1).sum())),
        eval_metric="logloss",
        random_state=42,
        n_jobs=4,
    )
    model.fit(x_train_scaled, y_train)
    probabilities = model.predict_proba(x_test_scaled)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    print(f"Snapshot: {snapshot_date}; churn horizon: {HORIZON_DAYS} days")
    print(f"Examples: {len(data):,}; churn rate: {data['churn'].mean():.3%}")
    print(f"Cohort: customers with at least {MIN_HISTORICAL_ORDERS} historical orders; class counts: {counts.to_dict()}")
    print(f"Train/test: {len(x_train):,}/{len(x_test):,} (80/20 stratified)")
    print(f"ROC-AUC: {roc_auc_score(y_test, probabilities):.4f}")
    print(f"PR-AUC (average precision): {average_precision_score(y_test, probabilities):.4f}")
    print(f"F1: {f1_score(y_test, predictions, zero_division=0):.4f}")
    print(f"Accuracy: {accuracy_score(y_test, predictions):.4f}")
    print("Confusion matrix [[TN, FP], [FN, TP]]:")
    print(confusion_matrix(y_test, predictions, labels=[0, 1]))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "preprocessor": preprocessor,
            "features": FEATURES,
            "snapshot_date": str(snapshot_date),
            "horizon_days": HORIZON_DAYS,
            "min_historical_orders": MIN_HISTORICAL_ORDERS,
        },
        MODEL_PATH,
    )
    print(f"Saved model: {MODEL_PATH}")


if __name__ == "__main__":
    main()
