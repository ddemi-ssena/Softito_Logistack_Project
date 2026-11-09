"""Shared database and date-filter helpers for the Streamlit pages."""

from pathlib import Path
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)


def apply_global_styles():
    css_path = ROOT / "dashboard" / "assets" / "style.css"
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


@st.cache_resource
def get_engine():
    required = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
    import os

    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing .env settings: {', '.join(missing)}")
    print(
        "RetailPulse PostgreSQL connection: "
        f"host={os.environ['DB_HOST']} port={os.environ['DB_PORT']} "
        f"database={os.environ['DB_NAME']}"
    )
    url = URL.create(
        "postgresql+psycopg",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)


def read_df(query: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as connection:
        return pd.read_sql_query(text(query), connection, params=params or {})


def render_date_filter():
    """Render a shared Olist date filter, clamped to the supported analytic period."""
    min_date = date(2017, 1, 1)
    max_date = date(2018, 8, 31)
    default_range = (min_date, max_date)
    state_key = "retailpulse_date_range"
    saved_range = st.session_state.get(state_key)
    if isinstance(saved_range, (tuple, list)) and len(saved_range) == 2:
        try:
            saved_start, saved_end = (pd.to_datetime(value).date() for value in saved_range)
            if saved_start < min_date or saved_end > max_date:
                st.session_state[state_key] = default_range
        except (TypeError, ValueError):
            st.session_state[state_key] = default_range
    elif saved_range is not None and not isinstance(saved_range, (tuple, list)):
        st.session_state[state_key] = default_range

    try:
        # Touch the DB here so a broken connection is surfaced before page queries.
        get_engine().connect().close()
        st.sidebar.header("Genel filtre")
        selected = st.sidebar.date_input(
            "Sipariş tarihi aralığı",
            value=default_range,
            min_value=min_date,
            max_value=max_date,
            key=state_key,
        )
        if isinstance(selected, (tuple, list)) and len(selected) == 2:
            return selected[0], selected[1]
        return None, None
    except Exception as error:
        st.error(f"Veritabanına bağlanılamadı: {error}")
        return None, None


def show_data_notice():
    st.info(
        "Bu panel Olist'in tarihsel 2016–2018 e-ticaret kayıtlarını kullanır. "
        "Streaming Monitor'daki Kafka olayları gerçek canlı trafik değil, "
        "geçmiş siparişlerden oluşturulan kontrollü bir replay simülasyonudur."
    )


def show_filter_error():
    st.error("Veri alınamadı veya seçilen aralık için sonuç bulunamadı. PostgreSQL'in çalıştığını, .env ayarlarını ve tarih filtresini kontrol edin.")


def format_brl(value):
    if value is None or pd.isna(value):
        value = 0
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
