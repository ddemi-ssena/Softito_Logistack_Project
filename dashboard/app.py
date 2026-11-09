import streamlit as st

from db import apply_global_styles, render_date_filter, show_data_notice


st.set_page_config(page_title="RetailPulse | Analytics", page_icon="📈", layout="wide")
apply_global_styles()

st.title("RetailPulse")
st.subheader("E-commerce Analytics & Business Intelligence")
show_data_notice()

start_date, end_date = render_date_filter()
if start_date and end_date:
    st.caption(f"Seçili analiz dönemi: {start_date:%d %b %Y} — {end_date:%d %b %Y}")

st.markdown(
    """
    RetailPulse, Olist siparişlerini PostgreSQL Bronze, Silver ve Gold katmanlarında
    analize hazırlar. Sol menüden **Overview**, **Customer and Delivery** veya
    **Streaming Monitor** sayfasına geçerek satış, müşteri, teslimat ve replay
    olaylarını inceleyebilirsiniz.
    """
)

st.divider()
st.markdown("**Başlangıç:** Sol menüden bir analiz sayfası seçin. Tarih filtresi satış ve teslimat görünümlerinde kullanılır.")
