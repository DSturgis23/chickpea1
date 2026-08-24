"""
Chickpea Pubs – Performance Report Generator
Run: streamlit run report_app.py
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

st.set_page_config(
    page_title="Chickpea Performance Report",
    page_icon="📊",
    layout="centered",
)

LOGO_PATH = (
    r"C:\Users\Delilah Sturgis\Chickpea Dropbox\Chickpea\Chickpea"
    r"\Branding\Logos (2023 onwards)\Chickpea Group\Chickpea 2026 Logo.png"
)

# Header
col_logo, col_title = st.columns([1, 4])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=90)
with col_title:
    st.title("Performance Report")
    st.caption("Pulls live data from SevenRooms and Eviivo and generates a branded PDF.")

st.divider()

# Date range
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "Report from",
        value=date(date.today().year, 1, 1),
        format="DD/MM/YYYY",
    )
with col2:
    end_date = st.date_input(
        "Report to",
        value=date.today(),
        format="DD/MM/YYYY",
    )

if start_date >= end_date:
    st.error("Start date must be before end date.")
    st.stop()

yoy_start = date(start_date.year - 1, start_date.month, start_date.day)
yoy_end   = date(end_date.year - 1, end_date.month, end_date.day)
st.caption(
    f"Year-on-year comparison will use: "
    f"**{yoy_start.strftime('%d %b %Y')} – {yoy_end.strftime('%d %b %Y')}**"
)

st.divider()

# What's included
with st.expander("What's included in this report"):
    st.markdown("""
- **Executive Summary** — key KPIs at a glance with year-on-year deltas
- **Table Reservations** — weekly covers (YoY chart), by pub breakdown, meal period and day-of-week analysis
- **F&B Revenue** — spend per cover from Tevalis (if POS integration is active in SevenRooms)
- **Room Occupancy** — occupancy %, ADR, RevPAR, room nights by month and property (Eviivo)
- **Booking Patterns** — no-show rates, lead time, monthly trends by pub
- **Guest Reviews** — SevenRooms feedback scores, rating distribution, low-rating comments
""")

st.markdown("### Generate")

generate_btn = st.button("Generate PDF Report", type="primary", use_container_width=True)

if generate_btn:
    progress_bar = st.progress(0)
    status_text = st.empty()

    def _on_progress(frac, msg):
        progress_bar.progress(frac)
        status_text.text(msg)

    try:
        from report_generator import generate_pdf
        pdf_bytes = generate_pdf(start_date, end_date, progress_callback=_on_progress)

        progress_bar.progress(1.0)
        status_text.text("Report ready.")

        filename = (
            f"chickpea_report_"
            f"{start_date.strftime('%b%Y').lower()}_"
            f"{end_date.strftime('%b%Y').lower()}.pdf"
        )

        st.success("Your report is ready to download.")
        st.download_button(
            label="Download PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            use_container_width=True,
            type="primary",
        )

    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Report generation failed: {e}")
        st.exception(e)
