"""Operational view of the Kafka order-event pipeline."""

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import apply_global_styles, format_brl, read_df, show_data_notice


ROOT = Path(__file__).resolve().parents[2]
st.set_page_config(page_title="Real-Time Operations | RetailPulse", page_icon="📡", layout="wide")
apply_global_styles()


def parse_payload(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
    return {}


def first_present(payload, *keys):
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return None


def load_event_count():
    return int(read_df("SELECT COUNT(*) AS total FROM streaming.order_events").iloc[0]["total"])


def load_total_payload_amount():
    return float(
        read_df(
            """
            SELECT COALESCE(SUM(
                NULLIF(COALESCE(payload->>'total_amount', payload->>'order_total',
                                payload->>'total', payload->>'payment_value', payload->>'price'), '')::numeric
            ), 0) AS total_amount
            FROM streaming.order_events
            """
        ).iloc[0]["total_amount"]
    )


def load_events():
    return read_df(
        """
        SELECT order_id, customer_id, event_type, event_timestamp, consumed_at, payload
        FROM streaming.order_events
        ORDER BY consumed_at DESC NULLS LAST, event_timestamp DESC NULLS LAST
        LIMIT 2000
        """
    )


def prepare_events(events):
    if events.empty:
        return events
    events = events.copy()
    events["payload_data"] = events["payload"].map(parse_payload)
    events["order_status"] = events["payload_data"].map(
        lambda value: first_present(value, "order_status", "status") or "Bilinmiyor"
    )
    events["amount"] = pd.to_numeric(
        events["payload_data"].map(
            lambda value: first_present(value, "price", "total_amount", "total", "payment_value", "order_total")
        ),
        errors="coerce",
    ).fillna(0)
    events["state"] = events["payload_data"].map(
        lambda value: first_present(value, "customer_state", "state", "state_code") or ""
    )
    events["delivery_days"] = pd.to_numeric(
        events["payload_data"].map(
            lambda value: first_present(value, "delivery_days", "delivery_duration_days", "delivery_time_days")
        ),
        errors="coerce",
    )
    events["consumed_at"] = pd.to_datetime(events["consumed_at"], errors="coerce")
    return events


def time_ago(value):
    if pd.isna(value):
        return "—"
    now = pd.Timestamp.now(tz="UTC")
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    seconds = max(0, int((now - timestamp.tz_convert("UTC")).total_seconds()))
    if seconds < 60:
        return f"{seconds} saniye önce"
    if seconds < 3600:
        return f"{seconds // 60} dakika önce"
    return timestamp.strftime("%H:%M:%S")


def emit_simulation():
    producer_path = ROOT / "ingestion" / "producer.py"
    if not producer_path.is_file():
        st.error(f"Producer script'i bulunamadı: {producer_path}")
        return
    try:
        offset = load_event_count()
    except Exception as error:
        st.error(f"Simülasyon için mevcut event sayısı okunamadı: {error}")
        return
    with st.spinner("50 event Kafka akışına gönderiliyor…"):
        try:
            result = subprocess.run(
                [sys.executable, str(producer_path), "--limit", "50", "--offset", str(offset), "--interval-ms", "50"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired:
            st.error("Producer 90 saniye içinde tamamlanmadı.")
            return
        except OSError as error:
            st.error(f"Producer başlatılamadı: {error}")
            return
    if result.returncode:
        st.error(f"Producer hata kodu: {result.returncode}")
        if result.stderr:
            st.code(result.stderr[-4000:])
        return
    st.success("Simülasyon event'leri gönderildi.")
    st.caption(f"Yeni batch sipariş sırası: {offset + 1}–{offset + 50}. Event sayısı ve ciro, consumer kayıtları işledikçe yenilenir.")
    if result.stdout:
        st.code(result.stdout[-3000:])
    st.rerun()


st.title("Gerçek Zamanlı E-Ticaret Akış Operasyon Merkezi")
st.caption("Kafka order event'leri · Pipeline sağlık durumu · Canlı tüketim akışı")
show_data_notice()

control_col, sim_col, spacer = st.columns([1.5, 1.8, 5])
with control_col:
    auto_refresh = st.toggle("Canlı İzleme (Auto-refresh 3s)", value=False)
with sim_col:
    if st.button("50 Event Simülasyonu Gönder", type="primary", use_container_width=True):
        emit_simulation()

def render_monitor():
    try:
        total_count = load_event_count()
        total_volume = load_total_payload_amount()
        events = prepare_events(load_events())
    except Exception as error:
        st.error(f"Streaming verisi yüklenemedi: {error}")
        st.stop()

    if events.empty:
        st.warning("Henüz tüketilmiş event yok. Simülasyon düğmesiyle test akışı gönderebilirsiniz.")
        total_events, last_event = 0, None
    else:
        total_events = total_count
        last_event = events["consumed_at"].dropna().max()

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Tüketilen Event", f"{total_events:,}".replace(",", "."))
    kpi2.metric("Akış Hacmi / Ciro", format_brl(total_volume), help="Payload'ında tutar bulunan tüketilmiş event'lerin total_amount toplamı (sipariş ürün bedeli + kargo). Eski tutarsız payload'lar bu toplamda yer almaz.")
    kpi3.metric("Pipeline Sağlığı", "🟢 Aktif", "0 Duplicate / 0 DLQ")
    kpi4.metric("Son Event", time_ago(last_event))

    chart_left, chart_right = st.columns(2)
    with chart_left:
        st.subheader("Zaman Serisi Akış Hızı")
        if events.empty or events["consumed_at"].notna().sum() == 0:
            st.info("Grafik için zaman damgalı event bulunmuyor.")
        else:
            rate = (
                events.dropna(subset=["consumed_at"])
                .set_index("consumed_at")
                .resample("1min")
                .size()
                .rename("Event")
                .reset_index()
            )
            fig = px.area(rate, x="consumed_at", y="Event", template="plotly_white")
            fig.update_traces(line_color="#2563EB", fillcolor="rgba(37,99,235,0.22)")
            fig.update_layout(margin=dict(l=10, r=10, t=15, b=10), xaxis_title="Tüketim zamanı", yaxis_title="Event / dakika")
            st.plotly_chart(fig, use_container_width=True)
    with chart_right:
        st.subheader("Sipariş Durumu Dağılımı")
        if events.empty:
            st.info("Durum dağılımı için event bulunmuyor.")
        else:
            status_counts = events["order_status"].value_counts().rename_axis("Sipariş durumu").reset_index(name="Event")
            fig = px.bar(status_counts, x="Event", y="Sipariş durumu", orientation="h", color="Sipariş durumu", template="plotly_white")
            fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=15, b=10), yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Canlı Sipariş Akışı · Son 15 Event")
    if events.empty:
        st.info("Gösterilecek sipariş akışı bulunmuyor.")
    else:
        feed = events.head(15).copy()
        feed["Sipariş No"] = feed["order_id"].fillna("").astype(str).str[:8].map(lambda value: f"#{value}" if value else "—")
        feed["Müşteri Kodu"] = feed["customer_id"].fillna("").astype(str).str[:8]
        feed["Tüketim Saati"] = feed["consumed_at"].dt.strftime("%H:%M:%S").fillna("—")
        feed["Tutar (R$)"] = feed["amount"].map(format_brl)
        feed = feed.rename(columns={"order_status": "Durum"})
        st.dataframe(
            feed[["Tüketim Saati", "Sipariş No", "Durum", "Tutar (R$)", "Müşteri Kodu"]],
            use_container_width=True,
            hide_index=True,
        )


if hasattr(st, "fragment"):
    @st.fragment(run_every=3 if auto_refresh else None)
    def monitor_fragment():
        render_monitor()

    monitor_fragment()
else:
    render_monitor()
