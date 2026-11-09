"""Train and evaluate one class-balanced Random Forest churn model."""

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)

try:
    from .data_loader import load_data
    from .tracking import save_result
except ImportError:  # Supports running this file directly from the project root.
    from data_loader import load_data
    from tracking import save_result


def main():
    x_train, x_test, y_train, y_test, metadata = load_data()
    model = RandomForestClassifier(
        n_estimators=100,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )
    model.fit(x_train, y_train)

    probabilities = model.predict_proba(x_test)[:, 1]
    predictions = model.predict(x_test)
    matrix = confusion_matrix(y_test, predictions, labels=[0, 1])
    metrics = {
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "pr_auc": float(average_precision_score(y_test, probabilities)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "accuracy": float(accuracy_score(y_test, predictions)),
        "confusion_matrix": matrix.astype(int).tolist(),
    }
    run_metadata = {
        "snapshot_date": str(metadata["snapshot_date"]),
        "horizon_days": int(metadata["horizon_days"]),
        "min_historical_orders": int(metadata["min_historical_orders"]),
        "total_rows": int(metadata["total_rows"]),
        "train_rows": len(y_train),
        "test_rows": len(y_test),
        "class_counts": {str(key): int(value) for key, value in metadata["class_counts"].items()},
        "features": metadata["features"],
        "class_weight": "balanced",
        "n_estimators": 100,
    }

    print("=" * 62)
    print("RANDOM FOREST · CHURN EXPERIMENT")
    print("=" * 62)
    print(f"Snapshot date        : {metadata['snapshot_date']}")
    print(f"Repeat window        : {metadata['horizon_days']} days")
    print(f"Cohort               : customers with >= {metadata['min_historical_orders']} historical orders")
    print(f"Rows / train / test  : {metadata['total_rows']:,} / {len(y_train):,} / {len(y_test):,}")
    print(f"Class counts         : {metadata['class_counts']}")
    print("-" * 62)
    print(f"ROC-AUC              : {metrics['roc_auc']:.4f}")
    print(f"PR-AUC (avg precision): {metrics['pr_auc']:.4f}")
    print(f"F1-Score             : {metrics['f1']:.4f}")
    print(f"Accuracy             : {metrics['accuracy']:.4f}")
    print("Confusion Matrix     : [[TN, FP], [FN, TP]]")
    print(matrix)

    save_result("random_forest", "Random Forest (class_weight=balanced)", metrics, run_metadata)
    print("Benchmark result saved to experiments/benchmark_results.json and .md")
    print("=" * 62)


if __name__ == "__main__":
    main()
