"""Train the production churn model from pooled temporal snapshots."""

import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "experiments"))
from extract import connection_settings  # noqa: E402
from sliding_window_loader import (  # noqa: E402
    FEATURES,
    HORIZON_DAYS,
    MIN_HISTORICAL_ORDERS,
    SNAPSHOT_DATES,
    load_window,
)
import psycopg  # noqa: E402

MODEL_PATH = ROOT / "models" / "churn_model.joblib"
RANDOM_STATE = 42
TEST_SIZE = 0.20


def load_training_data() -> pd.DataFrame:
    """Load and pool the three fixed, fully observed 180-day windows."""
    with psycopg.connect(**connection_settings()) as connection:
        windows = {}
        for date in SNAPSHOT_DATES:
            print(f"Loading snapshot {date}...", flush=True)
            windows[date] = load_window(connection, date)

    for date, data in windows.items():
        if data.empty:
            raise RuntimeError(f"Gold tables produced no training examples for snapshot {date}.")
        print(
            f"Snapshot {date}: {len(data):,} rows; "
            f"class counts {{0: {(data['churn'] == 0).sum():,}, 1: {(data['churn'] == 1).sum():,}}}"
        )
    pooled = pd.concat(windows.values(), ignore_index=True)
    if pooled.empty or pooled["customer_unique_id"].nunique() < 2:
        raise RuntimeError("At least two distinct customers are required for GroupShuffleSplit.")
    return pooled


def main():
    data = load_training_data()
    splitter = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    train_idx, test_idx = next(
        splitter.split(data[FEATURES], data["churn"], groups=data["customer_unique_id"])
    )
    train = data.iloc[train_idx]
    test = data.iloc[test_idx]

    train_groups = set(train["customer_unique_id"])
    test_groups = set(test["customer_unique_id"])
    overlap = train_groups.intersection(test_groups)
    if overlap:
        raise RuntimeError(f"Customer leakage detected: {len(overlap)} customers cross splits.")

    scaler = StandardScaler()
    x_train = scaler.fit_transform(train[FEATURES])
    x_test = scaler.transform(test[FEATURES])
    y_train = train["churn"].astype(int)
    y_test = test["churn"].astype(int)

    # Keep the experimentally validated ratio. It is derived from the pooled
    # experiment's training class counts (120 negatives / 2,835 positives).
    scale_pos_weight = 120 / 2835
    model = XGBClassifier(
        max_depth=4,
        learning_rate=0.05,
        n_estimators=100,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        random_state=RANDOM_STATE,
        eval_metric="logloss",
    )
    model.fit(x_train, y_train)

    probabilities = model.predict_proba(x_test)[:, 1]
    predictions = (probabilities >= 0.50).astype(int)
    matrix = confusion_matrix(y_test, predictions, labels=[0, 1])

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "scaler": scaler,
            # The API currently calls this key; keep it as a compatibility alias.
            "preprocessor": scaler,
            "features": FEATURES,
            "snapshot_dates": list(SNAPSHOT_DATES),
            "horizon_days": HORIZON_DAYS,
            "min_historical_orders": MIN_HISTORICAL_ORDERS,
            "decision_threshold": 0.50,
            "scale_pos_weight": scale_pos_weight,
            "train_class_counts": {int(k): int(v) for k, v in y_train.value_counts().items()},
        },
        MODEL_PATH,
    )

    print("=" * 68)
    print("PRODUCTION SLIDING WINDOW · XGBOOST CHURN MODEL")
    print("=" * 68)
    print(f"Pooled rows             : {len(data):,}")
    print(f"Train/test rows         : {len(train):,} / {len(test):,}")
    print(f"Train/test customers    : {len(train_groups):,} / {len(test_groups):,}")
    print(f"Customer overlap        : {len(overlap)}")
    print(f"Train classes (0 / 1)   : {(y_train == 0).sum():,} / {(y_train == 1).sum():,}")
    print(f"Test classes (0 / 1)    : {(y_test == 0).sum():,} / {(y_test == 1).sum():,}")
    print(f"scale_pos_weight        : {scale_pos_weight:.6f}")
    print("Decision threshold     : 0.50")
    print(f"ROC-AUC                 : {roc_auc_score(y_test, probabilities):.4f}")
    print(f"PR-AUC                  : {average_precision_score(y_test, probabilities):.4f}")
    print(f"F1-Score                : {f1_score(y_test, predictions, zero_division=0):.4f}")
    print(f"Accuracy                : {accuracy_score(y_test, predictions):.4f}")
    print("Confusion Matrix        : [[TN, FP], [FN, TP]]")
    print(matrix)
    print(f"Saved production bundle : {MODEL_PATH}")


if __name__ == "__main__":
    main()
