"""Train and evaluate XGBoost on pooled, group-safe temporal churn windows."""

from xgboost import XGBClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)

try:
    from .sliding_window_loader import load_data
except ImportError:  # Supports direct execution from the project root.
    from sliding_window_loader import load_data


def main():
    x_train, x_test, y_train, y_test, train_groups, test_groups, metadata = load_data()
    # Positive label is churn=1; use the natural train negative/positive ratio.
    scale_pos_weight = float((y_train == 0).sum() / (y_train == 1).sum())
    threshold = 0.50

    model = XGBClassifier(
        random_state=42,
        n_estimators=100,
        learning_rate=0.05,
        max_depth=4,
        colsample_bytree=0.8,
        subsample=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric="logloss",
    )
    model.fit(x_train, y_train)

    probabilities = model.predict_proba(x_test)[:, 1]
    predictions = (probabilities >= threshold).astype(int)
    matrix = confusion_matrix(y_test, predictions, labels=[0, 1])
    metrics = {
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "pr_auc": float(average_precision_score(y_test, probabilities)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "accuracy": float(accuracy_score(y_test, predictions)),
    }

    baseline = {"roc_auc": 0.7525, "test_rows": 351, "tn": 14}
    print("=" * 72)
    print("SLIDING WINDOW · XGBOOST CHURN EXPERIMENT")
    print("=" * 72)
    print(f"scale_pos_weight       : {scale_pos_weight:.4f}")
    print(f"Decision threshold     : {threshold:.2f} (fixed)")
    print(f"Group split customers  : {train_groups.nunique():,} train / {test_groups.nunique():,} test")
    print(f"ROC-AUC                : {metrics['roc_auc']:.4f}")
    print(f"PR-AUC (avg precision) : {metrics['pr_auc']:.4f}")
    print(f"F1-Score               : {metrics['f1']:.4f}")
    print(f"Accuracy               : {metrics['accuracy']:.4f}")
    print("Confusion Matrix       : [[TN, FP], [FN, TP]]")
    print(matrix)
    print("\nEski tek snapshot XGBoost ile karşılaştırma")
    print("+----------------------+----------------------+----------------------+")
    print("| Metrik               | Tek snapshot         | Sliding window       |")
    print("+----------------------+----------------------+----------------------+")
    print(f"| ROC-AUC              | {baseline['roc_auc']:<20.4f} | {metrics['roc_auc']:<20.4f} |")
    print(f"| Test örneği          | {baseline['test_rows']:<20,} | {len(y_test):<20,} |")
    print(f"| TN                   | {baseline['tn']:<20,} | {int(matrix[0, 0]):<20,} |")
    print("+----------------------+----------------------+----------------------+")


if __name__ == "__main__":
    main()
