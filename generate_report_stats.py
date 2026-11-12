"""Print verifiable warehouse/model statistics and export report figures."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "etl"))
sys.path.insert(0, str(ROOT / "experiments"))
from extract import connection_settings  # noqa: E402
from sliding_window_loader import FEATURES, SNAPSHOT_DATES, HORIZON_DAYS, MIN_HISTORICAL_ORDERS, load_window  # noqa: E402

FIGURES = ROOT / "report_figures"
K = 4
RANDOM_STATE = 42
CM = np.array([[20, 19], [109, 575]])


def query_frame(connection, sql: str, params=None) -> pd.DataFrame:
    return pd.read_sql_query(sql, connection, params=params)


def existing_tables(connection) -> set[str]:
    rows = connection.execute(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables "
        "WHERE table_type='BASE TABLE' AND table_schema IN ('bronze','silver','gold')"
    ).fetchall()
    return {row[0] for row in rows}


def table_counts(connection, tables: set[str]) -> dict[str, int | None]:
    result = {}
    for schema, table in [
        (s, t) for s, ts in {
            "bronze": ["orders", "customers", "order_items", "order_payments", "order_reviews", "products"],
            "silver": ["orders", "customers", "order_items", "order_payments", "order_reviews", "products"],
            "gold": ["fact_orders", "dim_customers", "fact_order_items", "fact_order_payments", "fact_order_reviews", "dim_products"],
        }.items() for t in ts
    ]:
        key = f"{schema}.{table}"
        result[key] = connection.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()[0] if key in tables else None
    return result


def calculate_metrics(y_true, probabilities, threshold=0.5):
    from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix,
                                 f1_score, precision_score, recall_score, roc_auc_score)

    predictions = (np.asarray(probabilities) >= threshold).astype(int)
    return {
        "precision": precision_score(y_true, predictions, zero_division=0),
        "recall": recall_score(y_true, predictions, zero_division=0),
        "f1": f1_score(y_true, predictions, zero_division=0),
        "accuracy": accuracy_score(y_true, predictions),
        "roc_auc": roc_auc_score(y_true, probabilities),
        "pr_auc": average_precision_score(y_true, probabilities),
        "confusion_matrix": confusion_matrix(y_true, predictions, labels=[0, 1]),
    }


def main():
    FIGURES.mkdir(exist_ok=True)
    with psycopg.connect(**connection_settings()) as connection:
        tables = existing_tables(connection)
        counts = table_counts(connection, tables)
        print("=== LAYER ROW COUNTS (missing table: N/A) ===")
        for name, count in counts.items():
            print(f"{name}: {count if count is not None else 'N/A'}")

        if "gold.fact_orders" not in tables or "gold.dim_customers" not in tables:
            raise RuntimeError("Required Gold order/customer tables are missing; refusing to fabricate report statistics.")

        frequency = query_frame(connection, """
            SELECT customer_unique_id, COUNT(*)::bigint AS orders
            FROM gold.fact_orders WHERE customer_unique_id IS NOT NULL
            GROUP BY customer_unique_id
        """)
        unique_count = len(frequency)
        one_count = int((frequency.orders == 1).sum())
        repeat_count = int((frequency.orders >= 2).sum())
        print("\n=== CUSTOMER ORDER FREQUENCY ===")
        print(f"Unique customers: {unique_count:,}")
        print(f"Exactly one order: {one_count:,} ({one_count / unique_count:.2%})")
        print(f"Repeat (>=2 orders): {repeat_count:,} ({repeat_count / unique_count:.2%})")
        print(f"Maximum orders per customer: {int(frequency.orders.max()):,}")

        print("\n=== NULL CLEANUP / ETL RECORD COUNTS ===")
        for schema, names in {
            "bronze": ["orders", "customers", "order_items", "products", "order_payments", "order_reviews"],
            "silver": ["orders", "customers", "order_items", "products", "order_payments", "order_reviews"],
        }.items():
            for name in names:
                full = f"{schema}.{name}"
                if full not in tables:
                    print(f"{full}: N/A (table missing)")
                    continue
                cols = [row[0] for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                    (schema, name),
                ).fetchall()]
                nulls = {col: connection.execute(f'SELECT COUNT(*) FROM "{schema}"."{name}" WHERE "{col}" IS NULL').fetchone()[0] for col in cols}
                print(f"{full} rows={counts[full]:,}; nulls=" + ", ".join(f"{k}:{v:,}" for k, v in nulls.items() if v))
        if "bronze.orders" in tables:
            eligible, out_range = connection.execute("""
                SELECT COUNT(*) FILTER (WHERE order_purchase_timestamp >= '2017-01-01'::timestamp AND order_purchase_timestamp < '2018-09-01'::timestamp),
                       COUNT(*) FILTER (WHERE order_purchase_timestamp < '2017-01-01'::timestamp OR order_purchase_timestamp >= '2018-09-01'::timestamp OR order_purchase_timestamp IS NULL)
                FROM bronze.orders
            """).fetchone()
            print(f"silver.orders analytic-range candidates={eligible:,}; out-of-range/null purchase timestamp excluded={out_range:,}")
        for name, condition in [
            ("silver.order_items", "order_id IS NULL OR order_item_id IS NULL"),
            ("silver.order_payments", "order_id IS NULL OR payment_sequential IS NULL"),
            ("silver.order_reviews", "review_id IS NULL"),
        ]:
            if name in tables:
                lost = connection.execute(f"SELECT COUNT(*) FROM {name} WHERE {condition}").fetchone()[0]
                print(f"{name} invalid required keys remaining={lost:,}")

        if "gold.mart_customer_rfm" in tables:
            rfm = query_frame(connection, "SELECT customer_unique_id, recency_days, frequency, monetary FROM gold.mart_customer_rfm WHERE customer_unique_id IS NOT NULL AND recency_days>=0 AND frequency>=0 AND monetary>=0 ORDER BY customer_unique_id")
        else:
            rfm = query_frame(connection, """
                WITH ref AS (SELECT MAX(order_purchase_timestamp)::date + 1 AS d FROM gold.fact_orders)
                SELECT f.customer_unique_id, (r.d-MAX(f.order_purchase_timestamp)::date)::int AS recency_days,
                       COUNT(*)::bigint AS frequency, SUM(f.total_product_amount)::numeric AS monetary
                FROM gold.fact_orders f CROSS JOIN ref r WHERE f.customer_unique_id IS NOT NULL
                  AND f.order_status IN ('approved','delivered') GROUP BY f.customer_unique_id,r.d
            """)
        rf = rfm[["recency_days", "frequency", "monetary"]].astype(float)
        valid = np.isfinite(rf.to_numpy()).all(axis=1) & (rf >= 0).all(axis=1).to_numpy()
        dropped_rfm = int((~valid).sum())
        rfm = rfm.loc[valid].reset_index(drop=True)
        model = KMeans(n_clusters=K, n_init=10, random_state=RANDOM_STATE)
        rfm["cluster_id"] = model.fit_predict(StandardScaler().fit_transform(np.log1p(rfm[["recency_days", "frequency", "monetary"]].astype(float))))
        profiles = rfm.groupby("cluster_id")[["recency_days", "frequency", "monetary"]].mean()
        # Name clusters by recency/frequency/monetary profile, with labels tied to data-derived ranking.
        rank = profiles.rank(pct=True)
        scores = rank["frequency"] + rank["monetary"] - rank["recency_days"]
        names = {int(scores.idxmax()): "Champions"}
        rem = [i for i in profiles.index if i not in names]
        at_risk = max(rem, key=lambda i: (rank.loc[i, "frequency"] + rank.loc[i, "monetary"] + rank.loc[i, "recency_days"]))
        names[at_risk] = "At Risk"
        rem = [i for i in rem if i != at_risk]
        hibernating = max(rem, key=lambda i: rank.loc[i, "recency_days"] - rank.loc[i, "frequency"] - rank.loc[i, "monetary"])
        names[hibernating] = "Hibernating"
        names[next(i for i in profiles.index if i not in names)] = "Loyal"
        rfm["segment"] = rfm.cluster_id.map(names)
        print("\n=== K-MEANS RFM ===")
        print(f"k={K}; valid customers={len(rfm):,}; excluded invalid/non-finite RFM rows={dropped_rfm:,}; algorithm=log1p + StandardScaler + KMeans(n_init=10, random_state=42)")
        for cid, prof in profiles.iterrows():
            subset = rfm[rfm.cluster_id == cid]
            print(f"cluster {cid} ({names[int(cid)]}): customers={len(subset):,}; avg_R_recency_days={prof.recency_days:.2f}; avg_F_orders={prof.frequency:.2f}; avg_M={prof.monetary:.2f}")

        # Monthly order volume and product revenue from Gold fact tables.
        monthly = query_frame(connection, """
            SELECT DATE_TRUNC('month', order_purchase_timestamp)::date AS month,
                   COUNT(*)::bigint AS orders, SUM(total_product_amount)::numeric AS revenue
            FROM gold.fact_orders WHERE order_purchase_timestamp >= '2016-01-01' AND order_purchase_timestamp < '2019-01-01'
            GROUP BY 1 ORDER BY 1
        """)

        # Fit the exact production sliding-window split/model so its metrics and importances are real.
        windows = {date: load_window(connection, date) for date in SNAPSHOT_DATES}
        for date, frame in windows.items():
            print(f"Snapshot {date}: rows={len(frame):,}; class0={(frame.churn == 0).sum():,}; class1={(frame.churn == 1).sum():,}")
        data = pd.concat(windows.values(), ignore_index=True)
        from sklearn.model_selection import GroupShuffleSplit
        splitter = GroupShuffleSplit(n_splits=1, test_size=.20, random_state=42)
        train_idx, test_idx = next(splitter.split(data[FEATURES], data.churn, groups=data.customer_unique_id))
        train, test = data.iloc[train_idx], data.iloc[test_idx]
        scaler = StandardScaler()
        x_train = scaler.fit_transform(train[FEATURES]); x_test = scaler.transform(test[FEATURES])
        xgb = XGBClassifier(max_depth=4, learning_rate=.05, n_estimators=100, subsample=.8,
                            colsample_bytree=.8, scale_pos_weight=120/2835, random_state=42,
                            eval_metric="logloss")
        xgb.fit(x_train, train.churn.astype(int))
        xgb_metrics = calculate_metrics(test.churn.astype(int), xgb.predict_proba(x_test)[:, 1])

        # Single-snapshot experiment uses its documented loader and model setup.
        from data_loader import load_data as load_single_snapshot
        sx_train, sx_test, sy_train, sy_test, smeta = load_single_snapshot()
        single = XGBClassifier(max_depth=4, learning_rate=.05, n_estimators=100, subsample=.8,
                               colsample_bytree=.8, scale_pos_weight=float((sy_train == 0).sum()/(sy_train == 1).sum()),
                               random_state=42, eval_metric="logloss")
        single.fit(sx_train, sy_train)
        single_metrics = calculate_metrics(sy_test, single.predict_proba(sx_test)[:, 1])
        print("\n=== SINGLE SNAPSHOT XGBOOST ===")
        print(f"rows={smeta['total_rows']:,}; train={len(sy_train):,}; test={len(sy_test):,}; snapshot={smeta['snapshot_date']}; horizon={smeta['horizon_days']} days")
        print_metrics(single_metrics)
        print("\n=== SLIDING WINDOW XGBOOST ===")
        print(f"rows={len(data):,}; train={len(train):,}; test={len(test):,}; train_customers={train.customer_unique_id.nunique():,}; test_customers={test.customer_unique_id.nunique():,}; overlap={len(set(train.customer_unique_id)&set(test.customer_unique_id))}")
        print_metrics(xgb_metrics)
        print("Feature importances (gain proxy: XGBoost feature_importances_):")
        for name, importance in sorted(zip(FEATURES, xgb.feature_importances_), key=lambda item: item[1], reverse=True):
            print(f"  {name}: {importance:.8f}")

        # Other model experiment metrics are computed from the same repeat cohort/split as the experiment scripts.
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from lightgbm import LGBMClassifier
        from sklearn.impute import SimpleImputer
        # Reproduce baseline experiment's stratified split and preprocessing.
        # Load exact values through existing experiment loader to ensure common split.
        from data_loader import load_customer_cohort, FEATURES as SINGLE_FEATURES
        cohort, _snapshot = load_customer_cohort()
        from sklearn.model_selection import train_test_split
        xx_train, xx_test, yy_train, yy_test = train_test_split(cohort[SINGLE_FEATURES], cohort.churn, test_size=.20, random_state=42, stratify=cohort.churn)
        imp = SimpleImputer(strategy="median"); aa = imp.fit_transform(xx_train); bb = imp.transform(xx_test)
        sc = StandardScaler(); aa = sc.fit_transform(aa); bb = sc.transform(bb)
        model_specs = [
            ("Logistic Regression", LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42)),
            ("Random Forest", RandomForestClassifier(n_estimators=100, random_state=42, class_weight="balanced", n_jobs=-1)),
            ("LightGBM", LGBMClassifier(class_weight="balanced", n_estimators=400, learning_rate=.04, num_leaves=15, max_depth=5, random_state=42, n_jobs=-1, verbosity=-1)),
        ]
        comparison = {}
        for name, estimator in model_specs:
            estimator.fit(aa, yy_train)
            comparison[name] = calculate_metrics(yy_test, estimator.predict_proba(bb)[:, 1])
        comparison["XGBoost (Sliding Window)"] = xgb_metrics
        print("\n=== FOUR-MODEL COMPARISON (baseline common snapshot split; XGBoost sliding-window split) ===")
        for name, metrics in comparison.items():
            print(f"{name}: precision={metrics['precision']:.4f}; recall={metrics['recall']:.4f}; F1={metrics['f1']:.4f}; accuracy={metrics['accuracy']:.4f}; ROC-AUC={metrics['roc_auc']:.4f}; PR-AUC={metrics['pr_auc']:.4f}; CM={metrics['confusion_matrix'].tolist()}")

    # Figures, each based on the queried/modelled values above.
    plt.rcParams.update({"font.size": 10, "axes.titlesize": 14})
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(["1 order", "2+ orders"], [one_count, repeat_count], color=["#7aa6c2", "#ef8a62"])
    for i, v in enumerate([one_count, repeat_count]): ax.text(i, v, f"{v:,}\n{v/unique_count:.1%}", ha="center", va="bottom")
    ax.set(title="Customer order frequency cohort", ylabel="Unique customers"); fig.tight_layout(); fig.savefig(FIGURES/"fig1_order_frequency.png", dpi=300); plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(10, 5)); ax1.bar(monthly.month, monthly.orders, width=20, color="#8bb8d8", label="Orders")
    ax1.set_ylabel("Orders"); ax1.set_xlabel("Month"); ax2=ax1.twinx(); ax2.plot(monthly.month, monthly.revenue, color="#d65f5f", marker="o", markersize=2, label="Revenue")
    ax2.set_ylabel("Product revenue"); ax1.set_title("Monthly order volume and revenue (2016–2018)"); fig.tight_layout(); fig.savefig(FIGURES/"fig2_monthly_trend.png", dpi=300); plt.close(fig)

    seg = rfm.segment.value_counts().reindex(["Champions", "Loyal", "At Risk", "Hibernating"], fill_value=0)
    fig, ax=plt.subplots(figsize=(8,5)); ax.bar(seg.index, seg.values, color=["#4c9f70", "#78a6d0", "#e6ad55", "#9a86bd"])
    for i,v in enumerate(seg.values): ax.text(i,v,f"{v:,}\n{v/len(rfm):.1%}",ha="center",va="bottom")
    ax.set(title="K-Means RFM customer segments", ylabel="Customers"); fig.tight_layout(); fig.savefig(FIGURES/"fig3_rfm_segments.png",dpi=300); plt.close(fig)

    names=list(comparison); fig, ax=plt.subplots(figsize=(10,5)); x=np.arange(len(names)); w=.36
    ax.bar(x-w/2,[comparison[n]["roc_auc"] for n in names],w,label="ROC-AUC"); ax.bar(x+w/2,[comparison[n]["f1"] for n in names],w,label="F1")
    ax.set_xticks(x,names,rotation=15,ha="right"); ax.set_ylim(0,1); ax.set_title("Model comparison"); ax.legend(); fig.tight_layout(); fig.savefig(FIGURES/"fig4_model_comparison.png",dpi=300); plt.close(fig)

    fig, ax=plt.subplots(figsize=(6,5)); im=ax.imshow(xgb_metrics["confusion_matrix"],cmap="Blues"); ax.set_xticks([0,1],["Predicted 0","Predicted 1"]); ax.set_yticks([0,1],["Actual 0","Actual 1"])
    for (i,j),v in np.ndenumerate(xgb_metrics["confusion_matrix"]): ax.text(j,i,f"{v:,}",ha="center",va="center",color="white" if v>xgb_metrics["confusion_matrix"].max()/2 else "black")
    ax.set_title("Sliding Window XGBoost confusion matrix"); fig.colorbar(im,ax=ax); fig.tight_layout(); fig.savefig(FIGURES/"fig5_confusion_matrix.png",dpi=300); plt.close(fig)

    fi=pd.Series(xgb.feature_importances_,index=FEATURES).sort_values(); fig,ax=plt.subplots(figsize=(8,5)); fi.plot.barh(ax=ax,color="#4c9f70"); ax.set_title("XGBoost feature importance"); ax.set_xlabel("Importance"); fig.tight_layout(); fig.savefig(FIGURES/"fig6_feature_importance.png",dpi=300); plt.close(fig)
    print("\n=== FIGURES ===")
    for path in sorted(FIGURES.glob("*.png")):
        print(f"{path.name}: {path.stat().st_size:,} bytes; {plt.imread(path).shape[1]}x{plt.imread(path).shape[0]} px; 300 DPI")


def print_metrics(metrics):
    print(f"Precision: {metrics['precision']:.4f}")
    print(f"Recall: {metrics['recall']:.4f}")
    print(f"F1: {metrics['f1']:.4f}")
    print(f"Accuracy: {metrics['accuracy']:.4f}")
    print(f"ROC-AUC: {metrics['roc_auc']:.4f}")
    print(f"PR-AUC: {metrics['pr_auc']:.4f}")
    print(f"Confusion Matrix [[TN,FP],[FN,TP]]: {metrics['confusion_matrix'].tolist()}")


if __name__ == "__main__":
    main()
