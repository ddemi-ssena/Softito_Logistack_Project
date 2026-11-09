import os
import sys
from pathlib import Path

import plotly.express as px
import requests
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import apply_global_styles, format_brl, read_df, render_date_filter, show_data_notice, show_filter_error


st.set_page_config(page_title="Customer & Delivery | RetailPulse", page_icon="👥", layout="wide")
apply_global_styles()
st.title("Customer and Delivery")
show_data_notice()
start_date, end_date = render_date_filter()
if not start_date or not end_date:
    show_filter_error()
    st.stop()

try:
    rfm = read_df(
        """
        SELECT r.customer_unique_id, r.frequency, r.monetary, r.recency_days,
               s.segment_name
        FROM gold.mart_customer_rfm AS r
        LEFT JOIN gold.mart_customer_segments AS s USING (customer_unique_id)
        ORDER BY r.monetary DESC
        """
    )
    segments = read_df(
        """
        SELECT segment_name, COUNT(*) AS customer_count,
               AVG(monetary) AS average_monetary,
               AVG(frequency) AS average_frequency,
               AVG(recency) AS average_recency
        FROM gold.mart_customer_segments
        GROUP BY segment_name
        ORDER BY customer_count DESC
        """
    )
    delivery = read_df(
        """
        SELECT customer_state,
               SUM(average_delivery_days * orders_with_delivery)
                   / NULLIF(SUM(orders_with_delivery), 0) AS average_delivery_days,
               SUM(late_delivery_rate * orders_with_delivery)
                   / NULLIF(SUM(orders_with_delivery), 0) AS late_delivery_rate,
               SUM(average_actual_vs_estimated_days * orders_with_delivery)
                   / NULLIF(SUM(orders_with_delivery), 0) AS average_actual_vs_estimated_days,
               SUM(orders_with_delivery) AS orders_with_delivery
        FROM gold.mart_delivery_performance
        WHERE order_month >= DATE_TRUNC('month', CAST(:start_date AS date))::date
          AND order_month <= DATE_TRUNC('month', CAST(:end_date AS date))::date
        GROUP BY customer_state
        ORDER BY late_delivery_rate DESC
        """,
        {"start_date": start_date, "end_date": end_date},
    )
except Exception as error:
    st.error(f"Müşteri veya teslimat verileri yüklenemedi: {error}")
    st.stop()

customer_tab, delivery_tab = st.tabs(["Müşteri Analitiği", "Teslimat & Lojistik"])

with customer_tab:
    st.subheader("Müşteri segmentasyonu")
    if segments.empty:
        st.error("Müşteri segment martı boş. Önce analytics/customer_analysis.py çalıştırın.")
    else:
        palette = {
            "Champions": "#2563EB",
            "Loyal Customers": "#0EA5E9",
            "At Risk": "#F59E0B",
            "Hibernating/Lost": "#94A3B8",
        }
        donut_col, profile_col = st.columns([1, 1.5])
        with donut_col:
            fig_segments = px.pie(
                segments,
                names="segment_name",
                values="customer_count",
                hole=0.62,
                template="plotly_white",
                color="segment_name",
                color_discrete_map=palette,
                labels={"segment_name": "Segment", "customer_count": "Müşteri sayısı"},
            )
            fig_segments.update_traces(textposition="inside", textinfo="percent+label")
            fig_segments.update_layout(margin=dict(l=10, r=10, t=20, b=10), showlegend=False)
            st.plotly_chart(fig_segments, use_container_width=True)
        with profile_col:
            spend_chart, frequency_chart = st.columns(2)
            with spend_chart:
                fig_spend = px.bar(
                    segments.sort_values("average_monetary"),
                    x="average_monetary",
                    y="segment_name",
                    orientation="h",
                    template="plotly_white",
                    color="segment_name",
                    color_discrete_map=palette,
                    labels={"average_monetary": "Ort. harcama (R$)", "segment_name": "Segment"},
                )
                fig_spend.update_layout(showlegend=False, margin=dict(l=5, r=5, t=20, b=5), xaxis_tickprefix="R$ ")
                st.plotly_chart(fig_spend, use_container_width=True)
            with frequency_chart:
                fig_frequency = px.bar(
                    segments.sort_values("average_frequency"),
                    x="average_frequency",
                    y="segment_name",
                    orientation="h",
                    template="plotly_white",
                    color="segment_name",
                    color_discrete_map=palette,
                    labels={"average_frequency": "Ort. sipariş sayısı", "segment_name": "Segment"},
                )
                fig_frequency.update_layout(showlegend=False, margin=dict(l=5, r=5, t=20, b=5))
                st.plotly_chart(fig_frequency, use_container_width=True)

        st.subheader("RFM müşteri dağılımı")
        if rfm.empty:
            st.error("RFM martı boş sonuç döndürdü.")
        else:
            fig_rfm = px.scatter(
                rfm,
                x="frequency",
                y="monetary",
                color="segment_name",
                template="plotly_white",
                color_discrete_map=palette,
                hover_data={"customer_unique_id": True, "recency_days": True},
                labels={
                    "frequency": "Sipariş sıklığı",
                    "monetary": "Toplam harcama (R$)",
                    "segment_name": "Segment",
                    "recency_days": "Recency (gün)",
                },
                opacity=0.65,
            )
            fig_rfm.update_layout(margin=dict(l=10, r=10, t=20, b=10), yaxis_tickprefix="R$ ")
            st.plotly_chart(fig_rfm, use_container_width=True)
            st.caption("RFM ve segmentler Gold martındaki sabit analitik dönem özetidir; tarih filtresinden bağımsızdır.")

    st.divider()
    st.subheader("Müşteri Churn Risk Simülatörü")
    st.caption("90 günlük tekrar sipariş tahmin modeline müşteri özelliklerini gönderin.")
    with st.form("churn_risk_simulator"):
        input_a, input_b, input_c = st.columns(3)
        with input_a:
            recency_days = st.number_input("Son siparişten geçen gün", min_value=0, max_value=1200, value=90, step=7)
            frequency = st.number_input("Sipariş sayısı", min_value=1, max_value=100, value=2, step=1)
        with input_b:
            monetary = st.number_input("Toplam harcama (R$)", min_value=0.0, max_value=100000.0, value=350.0, step=25.0)
            avg_item_price = st.number_input("Ortalama ürün fiyatı (R$)", min_value=0.0, max_value=10000.0, value=120.0, step=10.0)
        with input_c:
            avg_review_score = st.slider("Ortalama değerlendirme", min_value=1.0, max_value=5.0, value=4.0, step=0.5)
        submitted = st.form_submit_button("Churn riskini hesapla", type="primary")

    if submitted:
        api_default = "http://api:8000" if os.getenv("DB_HOST") == "postgres" else "http://localhost:8000"
        api_url = os.getenv("API_BASE_URL", api_default).rstrip("/")
        features = {
            "recency_days": recency_days,
            "frequency": frequency,
            "monetary": monetary,
            "avg_item_price": avg_item_price,
            "avg_review_score": avg_review_score,
        }
        try:
            response = requests.post(f"{api_url}/api/v1/predict/churn", json=features, timeout=20)
            response.raise_for_status()
            prediction = response.json()
        except requests.RequestException as error:
            st.error(f"Churn tahmin servisine ulaşılamadı: {error}")
        else:
            result_col, probability_col, action_col = st.columns(3)
            result_col.metric("Churn Riski", prediction["risk_level"], f"Tahmin olasılığı %{prediction['churn_probability'] * 100:.1f}")
            probability_col.metric("Tekrar Sipariş Vermeme", "Evet" if prediction["churn_prediction"] else "Hayır")
            action_col.info(f"Önerilen aksiyon: **{prediction['action_recommendation']}**")
            if prediction["risk_level"] == "Yüksek":
                st.error("Yüksek risk: müşteriyi geri kazanmak için hızlı aksiyon önerilir.")
            elif prediction["risk_level"] == "Orta":
                st.warning("Orta risk: hedefli bir sadakat iletişimi değerlendirin.")
            else:
                st.success("Düşük risk: mevcut etkileşimi sürdürün.")

with delivery_tab:
    st.subheader("Eyalet bazında teslimat performansı")
    if delivery.empty:
        st.error(f"Seçili dönem için teslimat verisi bulunamadı ({start_date} — {end_date}).")
    else:
        delivery["late_percent"] = delivery["late_delivery_rate"] * 100
        fig_late = px.bar(
            delivery.sort_values("late_percent"),
            x="late_percent",
            y="customer_state",
            orientation="h",
            template="plotly_white",
            labels={"late_percent": "Geç teslimat oranı (%)", "customer_state": "Eyalet"},
            hover_data={"orders_with_delivery": True, "average_delivery_days": ":.1f"},
            text_auto=".1f",
            color_discrete_sequence=["#2563EB"],
        )
        fig_late.update_traces(marker_cornerradius=7)
        fig_late.update_layout(margin=dict(l=10, r=10, t=20, b=10), xaxis_ticksuffix="%")
        st.plotly_chart(fig_late, use_container_width=True)

        fig_days = px.scatter(
            delivery,
            template="plotly_white",
            x="average_delivery_days",
            y="average_actual_vs_estimated_days",
            size="orders_with_delivery",
            hover_name="customer_state",
            labels={
                "average_delivery_days": "Ort. teslimat süresi (gün)",
                "average_actual_vs_estimated_days": "Gerçek - tahmin (gün)",
                "orders_with_delivery": "Teslim edilen sipariş",
            },
        )
        st.plotly_chart(fig_days, use_container_width=True)
