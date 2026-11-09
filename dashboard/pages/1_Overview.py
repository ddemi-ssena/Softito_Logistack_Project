import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import apply_global_styles, format_brl, read_df, render_date_filter, show_data_notice, show_filter_error


st.set_page_config(page_title="Overview | RetailPulse", page_icon="📈", layout="wide")
apply_global_styles()
st.title("Overview")
show_data_notice()
start_date, end_date = render_date_filter()
if not start_date or not end_date:
    show_filter_error()
    st.stop()

params = {"start_date": start_date, "end_date": end_date}
try:
    kpis = read_df(
        """
        SELECT COALESCE(SUM(approved_revenue), 0) AS sales,
               COALESCE(SUM(order_count), 0) AS orders,
               SUM(approved_revenue) / NULLIF(SUM(order_count), 0) AS aov
        FROM gold.mart_sales_daily
        WHERE sales_date BETWEEN :start_date AND :end_date
        """,
        params,
    ).iloc[0]
    delivery = read_df(
        """
        SELECT AVG(delivery_days) AS avg_delivery_days
        FROM gold.fact_orders
        WHERE order_status = 'delivered'
          AND order_purchase_timestamp::date BETWEEN :start_date AND :end_date
        """,
        params,
    ).iloc[0]["avg_delivery_days"]
    trend_mode = st.radio("Satış trendi", ["Günlük", "Aylık"], horizontal=True)
    if trend_mode == "Günlük":
        trend = read_df(
            """
            SELECT sales_date AS period, approved_revenue, order_count
            FROM gold.mart_sales_daily
            WHERE sales_date BETWEEN :start_date AND :end_date
            ORDER BY sales_date
            """,
            params,
        )
    else:
        trend = read_df(
            """
            SELECT DATE_TRUNC('month', sales_date)::date AS period,
                   SUM(approved_revenue) AS approved_revenue,
                   SUM(order_count) AS order_count
            FROM gold.mart_sales_daily
            WHERE sales_date BETWEEN :start_date AND :end_date
            GROUP BY DATE_TRUNC('month', sales_date)::date
            ORDER BY period
            """,
            params,
        )
    categories = read_df(
        """
        SELECT COALESCE(NULLIF(BTRIM(p.product_category_name), ''), '(unknown)') AS category,
               SUM(i.price) AS revenue
        FROM gold.fact_order_items i
        JOIN gold.fact_orders o ON o.order_id = i.order_id
        LEFT JOIN gold.dim_products p ON p.product_id = i.product_id
        WHERE o.order_status IN ('approved', 'delivered')
          AND o.order_purchase_timestamp::date BETWEEN :start_date AND :end_date
        GROUP BY 1
        ORDER BY revenue DESC
        LIMIT 10
        """,
        params,
    )
except Exception as error:
    st.error(f"Overview verileri yüklenemedi: {error}")
    st.stop()

if trend.empty:
    show_filter_error()
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Toplam satış", format_brl(kpis["sales"]))
col2.metric("Toplam sipariş", f"{int(kpis['orders']):,}".replace(",", "."))
col3.metric("Ortalama sepet (AOV)", format_brl(kpis["aov"]))
col4.metric("Ort. teslimat süresi", f"{float(delivery):.1f} gün" if pd.notna(delivery) else "—")

st.subheader("Satış performansı")
fig_trend = px.line(
    trend,
    x="period",
    y="approved_revenue",
    markers=True,
    template="plotly_white",
    labels={"period": "Tarih", "approved_revenue": "Onaylı ciro (R$)"},
)
fig_trend.update_traces(
    line=dict(color="#2563EB", width=2.5),
    fill="tozeroy",
    fillcolor="rgba(37, 99, 235, 0.12)",
)
fig_trend.update_layout(
    margin=dict(l=10, r=10, t=20, b=10),
    yaxis_tickprefix="R$ ",
    paper_bgcolor="white",
    plot_bgcolor="white",
)
st.plotly_chart(fig_trend, use_container_width=True)

st.subheader("Ciroya göre ilk 10 kategori")
if categories.empty:
    st.error(f"Seçili tarih aralığında kategori satışı bulunamadı ({start_date} — {end_date}).")
else:
    categories["category"] = categories["category"].str.replace("_", " ", regex=False).str.title()
    fig_categories = px.bar(
        categories.sort_values("revenue"),
        x="revenue",
        y="category",
        orientation="h",
        template="plotly_white",
        labels={"revenue": "Ciro (R$)", "category": "Kategori"},
        text_auto=".2s",
        color_discrete_sequence=["#2563EB"],
    )
    fig_categories.update_traces(marker_cornerradius=8)
    fig_categories.update_layout(
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis_tickprefix="R$ ",
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    st.plotly_chart(fig_categories, use_container_width=True)
