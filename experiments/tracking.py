"""Shared, append-preserving experiment benchmark tracking."""

import json
from datetime import datetime
from pathlib import Path


EXPERIMENTS_DIR = Path(__file__).resolve().parent
JSON_PATH = EXPERIMENTS_DIR / "benchmark_results.json"
MARKDOWN_PATH = EXPERIMENTS_DIR / "benchmark_results.md"


def save_result(model_key: str, model_name: str, metrics: dict, metadata: dict):
    """Upsert one model's latest result, preserving every other benchmark entry."""
    if JSON_PATH.exists():
        with JSON_PATH.open("r", encoding="utf-8") as file:
            results = json.load(file)
    else:
        results = {"models": {}}
    results.setdefault("models", {})[model_key] = {
        "model_name": model_name,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "metadata": metadata,
        "metrics": metrics,
    }

    temporary_json = JSON_PATH.with_suffix(".json.tmp")
    with temporary_json.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(results, file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    temporary_json.replace(JSON_PATH)

    rows = [
        "# Churn Model Benchmark",
        "",
        "Her model çalıştırıldığında kendi kaydı güncellenir; diğer model sonuçları korunur.",
        "",
        "| Model | Kayıt zamanı | ROC-AUC | PR-AUC | F1 | Accuracy | Confusion Matrix (TN, FP, FN, TP) |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for result in results["models"].values():
        values = result.get("metrics", {})
        show = lambda key: "—" if values.get(key) is None else f"{values[key]:.4f}"
        confusion = values.get("confusion_matrix")
        if confusion:
            tn, fp = confusion[0]
            fn, tp = confusion[1]
            confusion_text = f"{tn}, {fp}, {fn}, {tp}"
        else:
            confusion_text = "—"
        rows.append(
            f"| {result['model_name']} | {result.get('recorded_at') or '—'} | "
            f"{show('roc_auc')} | {show('pr_auc')} | {show('f1')} | "
            f"{show('accuracy')} | {confusion_text} |"
        )
    rows.extend(["", "## Deney konfigürasyonları", ""])
    for key, result in results["models"].items():
        metadata = result.get("metadata", {})
        rows.append(
            f"- **{result['model_name']}** (`{key}`): "
            f"snapshot={metadata.get('snapshot_date', '—')}, "
            f"takip={metadata.get('horizon_days', '—')} gün, "
            f"kohortta minimum sipariş={metadata.get('min_historical_orders', '—')}."
        )
    MARKDOWN_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")
