# Churn Model Benchmark

Her model çalıştırıldığında kendi kaydı güncellenir; diğer model sonuçları korunur.

| Model | Kayıt zamanı | ROC-AUC | PR-AUC | F1 | Accuracy | Confusion Matrix (TN, FP, FN, TP) |
|---|---|---:|---:|---:|---:|---|
| **Sliding Window XGBoost (Production)** | 2026-11-11 | **0.7398** | **0.9781** | **0.8998** | **0.8230** | **20, 19, 109, 575** |
| Logistic Regression (Baseline) | — | 0.7033 | — | — | 0.6980 | — |

> **Seçim notu:** Üç sabit snapshot'ı temporal pooling ile birleştirerek eğitim verisi 1.753'ten 3.678 satıra çıkarıldı. `customer_unique_id` bazlı GroupShuffleSplit ile müşteri çakışması önlendi (Customer Overlap: 0); sliding-window XGBoost bu daha geniş test havuzunda üretim modeli olarak seçildi.

## Sliding Window üretim koşusu

- Snapshot'lar: 2017-10-01, 2017-12-15, 2018-03-04; her biri 180 günlük takip aralığı kullanır.
- Toplam örnek: 3.678; train/test: 2.955 / 723; testte gerçek sınıf dağılımı (0 / 1): 39 / 684.
- `scale_pos_weight=120/2835≈0.0423`; karar eşiği=0.50; `max_depth=4`, `learning_rate=0.05`, `n_estimators=100`, `subsample=0.8`, `colsample_bytree=0.8`, `random_state=42`.
- Confusion matrix düzeni: `[[TN, FP], [FN, TP]]`.

## Deney konfigürasyonları

- **Logistic Regression (Baseline)** (`logistic_regression`): snapshot=—, takip=— gün, kohortta minimum sipariş=—.
- **LightGBM (class_weight=balanced)** (`lightgbm`): snapshot=2018-03-04, takip=180 gün, kohortta minimum sipariş=2.
- **Random Forest (class_weight=balanced)** (`random_forest`): snapshot=2018-03-04, takip=180 gün, kohortta minimum sipariş=2.
- **Sliding Window XGBoost (Production)** (`train_churn.py`): ROC-AUC=0.7398, PR-AUC=0.9781, F1=0.8998, Accuracy=0.8230; confusion matrix=[[20, 19], [109, 575]].
