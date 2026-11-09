# Churn Model Benchmark

Her model çalıştırıldığında kendi kaydı güncellenir; diğer model sonuçları korunur.

| Model | Kayıt zamanı | ROC-AUC | PR-AUC | F1 | Accuracy | Confusion Matrix (TN, FP, FN, TP) |
|---|---|---:|---:|---:|---:|---|
| **XGBoost Classifier (Selected / Production)** | — | **0.7525** | **0.9865** | 0.8867 | 0.8006 | — |
| Logistic Regression (Baseline) | — | 0.7033 | — | — | 0.6980 | — |
| LightGBM (class_weight=balanced) | 2026-11-09T16:46:41+03:00 | 0.6617 | 0.9779 | 0.9613 | 0.9259 | 2, 12, 14, 323 |
| Random Forest (class_weight=balanced) | 2026-11-09T16:50:27+03:00 | 0.6872 | 0.9785 | 0.9752 | 0.9516 | 0, 14, 3, 334 |

> **Seçim notu:** Sınıf dengesizliğini en iyi yöneten, en yüksek ROC-AUC ve dengeli TN/TP oranıyla canlı servise alınan model.

## Deney konfigürasyonları

- **Logistic Regression (Baseline)** (`logistic_regression`): snapshot=—, takip=— gün, kohortta minimum sipariş=—.
- **LightGBM (class_weight=balanced)** (`lightgbm`): snapshot=2018-03-04, takip=180 gün, kohortta minimum sipariş=2.
- **Random Forest (class_weight=balanced)** (`random_forest`): snapshot=2018-03-04, takip=180 gün, kohortta minimum sipariş=2.
- **XGBoost Classifier (Selected / Production)** (`xgboost`): ROC-AUC=0.7525, PR-AUC=0.9865, F1=0.8867, Accuracy=0.8006. Confusion matrix ve çalışma konfigürasyonu henüz benchmark kaydında bulunmuyor.
