"""Log-transform and cluster Gold RFM customers into named segments."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl"))
from extract import connection_settings  # noqa: E402


N_CLUSTERS = 4
RANDOM_STATE = 42
SILHOUETTE_SAMPLE_SIZE = 5_000
SEGMENT_NAMES = {
    "champions": "Champions",
    "loyal": "Loyal Customers",
    "at_risk": "At Risk",
    "lost": "Hibernating/Lost",
}


def _scaled_profile(series: pd.Series) -> pd.Series:
    spread = series.max() - series.min()
    if not spread:
        return pd.Series(0.5, index=series.index)
    return (series - series.min()) / spread


def name_clusters(frame: pd.DataFrame) -> dict[int, str]:
    """Map arbitrary K-Means labels to business names using mean RFM profiles."""
    profiles = frame.groupby("cluster_id")[
        ["recency_days", "frequency", "monetary"]
    ].mean()
    recency_good = 1 - _scaled_profile(profiles["recency_days"])
    frequency_good = _scaled_profile(profiles["frequency"])
    monetary_good = _scaled_profile(profiles["monetary"])

    champions_id = (recency_good + frequency_good + monetary_good).idxmax()
    remaining = profiles.index.difference([champions_id])
    at_risk_score = (
        (1 - recency_good.loc[remaining])
        + frequency_good.loc[remaining]
        + monetary_good.loc[remaining]
    )
    at_risk_id = at_risk_score.idxmax()
    remaining = remaining.difference([at_risk_id])
    lost_score = (
        (1 - recency_good.loc[remaining])
        + (1 - frequency_good.loc[remaining])
        + (1 - monetary_good.loc[remaining])
    )
    lost_id = lost_score.idxmax()
    loyal_id = profiles.index.difference([champions_id, at_risk_id, lost_id])[0]

    return {
        int(champions_id): SEGMENT_NAMES["champions"],
        int(loyal_id): SEGMENT_NAMES["loyal"],
        int(at_risk_id): SEGMENT_NAMES["at_risk"],
        int(lost_id): SEGMENT_NAMES["lost"],
    }


def load_rfm(connection) -> pd.DataFrame:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT customer_unique_id, recency_days, frequency, monetary
            FROM gold.mart_customer_rfm
            WHERE customer_unique_id IS NOT NULL
              AND recency_days >= 0 AND frequency >= 0 AND monetary >= 0
            ORDER BY customer_unique_id
            """
        )
        rows = cursor.fetchall()
    if not rows:
        raise RuntimeError("gold.mart_customer_rfm contains no valid customers")
    return pd.DataFrame(rows, columns=["customer_unique_id", "recency_days", "frequency", "monetary"])


def main() -> None:
    with psycopg.connect(**connection_settings()) as connection:
        rfm = load_rfm(connection)
        raw_features = rfm[["recency_days", "frequency", "monetary"]].astype(float)
        if not np.isfinite(raw_features.to_numpy()).all():
            raise ValueError("RFM contains non-finite feature values")
# data preprocessing
        log_features = np.log1p(raw_features) #OUTLİER I ENGELLEMEK İÇİN LOG ALIYORUZ
        scaled_features = StandardScaler().fit_transform(log_features) #3 FEAUTURE I DA ORTALAMSI 0 STANDART SAPMASI 1 OLACAK ŞEKİLDE AYNI ÖLÇEĞE GETİRİR
        if len(rfm) <= N_CLUSTERS:
            raise ValueError(f"Need more than {N_CLUSTERS} RFM rows, got {len(rfm)}")

        model = KMeans(n_clusters=N_CLUSTERS, n_init=10, random_state=RANDOM_STATE) #93K MÜŞTERİYİ 4 KÜMEYE AYIRIR.
        rfm["cluster_id"] = model.fit_predict(scaled_features)
        sample_size = min(SILHOUETTE_SAMPLE_SIZE, len(rfm))
        score = silhouette_score( #bir müşteririn hangi kümeye ait olduğunu ve kümeler arası benzerliği ölçer. 1 e yakınsa iyi bir kümeleme demektir.
            scaled_features,
            rfm["cluster_id"],
            sample_size=sample_size,
            random_state=RANDOM_STATE,
        )
        cluster_names = name_clusters(rfm) #4 kümeye isim veriyoruz. (champions, loyal, at_risk, lost)
        rfm["segment_name"] = rfm["cluster_id"].map(cluster_names)

        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE gold.mart_customer_segments")
            copy_sql = """
                COPY gold.mart_customer_segments (
                    customer_unique_id, recency, frequency, monetary, cluster_id, segment_name
                ) FROM STDIN
            """
            with cursor.copy(copy_sql) as copy:
                for row in rfm.itertuples(index=False):
                    copy.write_row((
                        row.customer_unique_id,
                        int(row.recency_days),
                        int(row.frequency),
                        row.monetary,
                        int(row.cluster_id),
                        row.segment_name,
                    ))

            cursor.execute("SELECT COUNT(*) FROM gold.mart_customer_segments")
            total = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT segment_name, COUNT(*) AS customer_count,
                       ROUND(AVG(monetary), 2) AS average_monetary,
                       ROUND(AVG(frequency), 2) AS average_frequency,
                       ROUND(AVG(recency), 2) AS average_recency
                FROM gold.mart_customer_segments
                GROUP BY segment_name
                ORDER BY segment_name
                """
            )
            distribution = cursor.fetchall()

    print(f"K-Means: k={N_CLUSTERS}; silhouette(sample={sample_size:,})={score:.4f}")
    print(f"gold.mart_customer_segments rows: {total:,}")
    for name, count, monetary, frequency, recency in distribution:
        print(
            f"{name}: customers={count:,}, average_monetary=R${monetary:,.2f}, "
            f"average_frequency={frequency}, average_recency_days={recency}"
        )


if __name__ == "__main__":
    main()
