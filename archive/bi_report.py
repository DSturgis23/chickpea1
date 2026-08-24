"""
Chickpea Pubs – Business Intelligence Report
Jan 1 to present, with year-on-year comparison.
Covers: table reservations (SevenRooms/Tevalis), room occupancy (Eviivo),
guest reviews, booking patterns, and competitor intelligence.
"""

import re
import time
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from bs4 import BeautifulSoup

# ── DATE CONSTANTS ────────────────────────────────────────────────────────────
REPORT_START = date(2026, 1, 1)
REPORT_END = date.today()
YOY_START = date(2025, 1, 1)
YOY_END = date(2025, REPORT_END.month, REPORT_END.day)

# 7 properties with rooms (from pub_mapping.py)
ROOM_PROPERTY_COUNT = 7

COLOURS = {
    "green": "#2E7D32",
    "green_mid": "#66BB6A",
    "green_light": "#A5D6A7",
    "amber": "#FB8C00",
    "amber_light": "#FFCC80",
    "red": "#EF5350",
}

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ── COMPETITORS ───────────────────────────────────────────────────────────────
COMPETITORS = {
    "Beckford Group": "beckford group pub restaurant reviews",
    "Public House Group": "public house group restaurant UK reviews",
    "The Pig Hotels": "the pig hotel UK reviews rating",
}

# ── DATA LOADING (cached) ─────────────────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def _load_reservations(_client, from_date, to_date, label=""):
    if not _client._ensure_authenticated():
        return []
    resp = _client.get_reservations(from_date=str(from_date), to_date=str(to_date))
    results = resp.get("data", {}).get("results", []) if resp else []
    print(f"BI [{label}]: {len(results)} reservations")
    return results


@st.cache_data(ttl=1800, show_spinner=False)
def _load_eviivo(_eviivo_client, from_date, to_date, label=""):
    from pub_mapping import get_all_eviivo_properties
    if not _eviivo_client._ensure_authenticated():
        return []
    mappings = get_all_eviivo_properties()
    bookings = _eviivo_client.get_all_historical_bookings(
        mappings, checkin_from=str(from_date), checkin_to=str(to_date)
    )
    print(f"BI Eviivo [{label}]: {len(bookings)} bookings")
    return bookings


@st.cache_data(ttl=1800, show_spinner=False)
def _load_feedback(_client, from_date, to_date):
    if not hasattr(_client, "get_feedback"):
        return []
    try:
        resp = _client.get_feedback(from_date=str(from_date), to_date=str(to_date))
        return resp.get("data", {}).get("results", []) if resp else []
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner=False)
def _scrape_competitors():
    """Scrape publicly available Google search ratings for competitors. Cached 24 h."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    results = {}
    for name, query in COMPETITORS.items():
        data = {"name": name, "google_rating": None, "review_count": None}
        try:
            url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
            resp = requests.get(url, headers=headers, timeout=12)
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(" ", strip=True)

            # Match patterns like "4.5 stars", "4.5 out of 5", "Rated 4.5"
            for pat in [
                r"(\d\.\d)\s*(?:stars?|out of 5|★)",
                r"Rating[:\s]+(\d\.\d)",
                r"(\d\.\d)\s*\([\d,]+\s*(?:reviews?|ratings?)\)",
            ]:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    data["google_rating"] = float(m.group(1))
                    break

            # Review count
            m2 = re.search(r"([\d,]+)\s*(?:Google\s+)?reviews?", text, re.IGNORECASE)
            if m2:
                data["review_count"] = int(m2.group(1).replace(",", ""))
        except Exception:
            pass

        results[name] = data
        time.sleep(1.2)

    return results


# ── DATA PROCESSING ───────────────────────────────────────────────────────────

def _process_reservations(raw, venue_map):
    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)

    # Dates
    if "date" in df.columns:
        dt = pd.to_datetime(df["date"], errors="coerce")
        df["reservation_date"] = dt.dt.date
        df["week"] = dt.dt.to_period("W").dt.start_time
        df["month"] = dt.dt.to_period("M").dt.start_time
        df["day_of_week"] = dt.dt.day_name()

    # Covers / party size
    df["covers"] = pd.to_numeric(
        df.get("max_guests", df.get("covers", 0)), errors="coerce"
    ).fillna(0).astype(int)

    # Venue
    if "venue_id" in df.columns:
        df["venue_name"] = df["venue_id"].map(venue_map).fillna("Unknown")

    # Status
    if "status_display" in df.columns:
        df["status"] = df["status_display"].fillna("Unknown")
    elif "status" not in df.columns:
        df["status"] = "Unknown"

    # Spend (Tevalis via SevenRooms POS integration)
    spend_found = False
    for col in ["spend", "total_spend", "spend_amount", "check_amount"]:
        if col in df.columns:
            df["total_spend"] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            spend_found = True
            break
    if not spend_found:
        df["total_spend"] = 0

    for col in ["spend_per_cover", "avg_spend_per_cover", "spend_per_cover_avg", "check_per_cover"]:
        if col in df.columns:
            df["spend_per_cover"] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            break
    else:
        df["spend_per_cover"] = 0

    # Meal period
    if "shift_category" in df.columns:
        def _period(row):
            shift = str(row.get("shift_category", "")).upper()
            if shift == "BREAKFAST":
                return "Breakfast"
            if shift == "LUNCH":
                return "Lunch"
            if shift == "DINNER":
                return "Dinner"
            if shift == "DAY":
                try:
                    hour = int(str(row.get("time_slot_iso", "")).split("T")[1][:2])
                    return "Lunch" if hour < 15 else "Dinner"
                except Exception:
                    return "Lunch"
            return "Other"

        df["meal_period"] = df.apply(_period, axis=1)

    # Booking lead time
    if "created" in df.columns and "reservation_date" in df.columns:
        created_dates = pd.to_datetime(df["created"], errors="coerce").dt.date
        df["lead_days"] = [
            (rd - cd).days if rd and cd else None
            for rd, cd in zip(df["reservation_date"], created_dates)
        ]

    # Hour from time_slot_iso
    if "time_slot_iso" in df.columns:
        df["hour"] = pd.to_datetime(df["time_slot_iso"], errors="coerce").dt.hour

    return df


def _confirmed_only(df):
    """Filter to confirmed/completed bookings, exclude no-shows and cancellations."""
    if df.empty or "status" not in df.columns:
        return df
    exclude = ["canceled", "cancelled", "no show", "no-show", "noshow"]
    mask = ~df["status"].str.lower().str.contains("|".join(exclude), na=False)
    return df[mask]


def _process_eviivo(raw):
    if not raw:
        return pd.DataFrame()

    df = pd.DataFrame(raw)

    if "date" in df.columns:
        df["checkin_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    if "checkout_date" in df.columns:
        df["checkout_date_dt"] = pd.to_datetime(df["checkout_date"], errors="coerce").dt.date

    if "checkin_date" in df.columns and "checkout_date_dt" in df.columns:
        df["nights"] = [
            max((co - ci).days, 1) if ci and co and co > ci else 1
            for ci, co in zip(df["checkin_date"], df["checkout_date_dt"])
        ]
    else:
        df["nights"] = 1

    df["revenue"] = pd.to_numeric(df.get("total_value", 0), errors="coerce").fillna(0)

    # Remove cancelled
    if "status" in df.columns:
        df = df[~df["status"].str.lower().isin(["cancelled", "canceled"])]

    if "checkin_date" in df.columns:
        dt = pd.to_datetime(df["checkin_date"], errors="coerce")
        df["month"] = dt.dt.to_period("M").dt.start_time
        df["day_of_week"] = dt.dt.day_name()

    return df


# ── SECTION RENDERERS ─────────────────────────────────────────────────────────

def _kpis(df_cur, df_yoy, df_rooms_cur, df_rooms_yoy):
    st.subheader("At a Glance")
    days_cur = (REPORT_END - REPORT_START).days + 1
    days_yoy = (YOY_END - YOY_START).days + 1

    # Table bookings
    covers_cur = int(df_cur["covers"].sum()) if "covers" in df_cur.columns else 0
    covers_yoy = int(df_yoy["covers"].sum()) if "covers" in df_yoy.columns else 0
    bookings_cur = len(df_cur)
    bookings_yoy = len(df_yoy)

    # No-show rate
    if "status" in df_cur.columns:
        noshow_mask = df_cur["status"].str.contains(r"no.?show", case=False, na=False)
        noshow_rate = len(df_cur[noshow_mask]) / max(bookings_cur, 1) * 100
    else:
        noshow_rate = 0

    # Spend
    total_spend = df_cur["total_spend"].sum() if "total_spend" in df_cur.columns else 0
    avg_spc = (
        df_cur.loc[df_cur["spend_per_cover"] > 0, "spend_per_cover"].mean()
        if "spend_per_cover" in df_cur.columns and (df_cur["spend_per_cover"] > 0).any()
        else None
    )

    # Rooms
    nights_cur = int(df_rooms_cur["nights"].sum()) if "nights" in df_rooms_cur.columns else 0
    nights_yoy = int(df_rooms_yoy["nights"].sum()) if "nights" in df_rooms_yoy.columns else 0
    avail_cur = ROOM_PROPERTY_COUNT * days_cur
    avail_yoy = ROOM_PROPERTY_COUNT * days_yoy
    occ_cur = nights_cur / avail_cur * 100 if avail_cur else 0
    occ_yoy = nights_yoy / avail_yoy * 100 if avail_yoy else 0
    rev_cur = df_rooms_cur["revenue"].sum() if "revenue" in df_rooms_cur.columns else 0
    rev_yoy = df_rooms_yoy["revenue"].sum() if "revenue" in df_rooms_yoy.columns else 0
    adr = rev_cur / nights_cur if nights_cur else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric("Total Covers", f"{covers_cur:,}", delta=f"{covers_cur - covers_yoy:+,} vs 2025")
    with c2:
        st.metric("Table Bookings", f"{bookings_cur:,}", delta=f"{bookings_cur - bookings_yoy:+,} vs 2025")
    with c3:
        avg_cov = df_cur["covers"].mean() if "covers" in df_cur.columns and len(df_cur) else 0
        st.metric("Avg Party Size", f"{avg_cov:.1f}")
    with c4:
        st.metric("No-show Rate", f"{noshow_rate:.1f}%")
    with c5:
        st.metric(
            "Room Occupancy",
            f"{occ_cur:.1f}%",
            delta=f"{occ_cur - occ_yoy:+.1f}pp vs 2025",
        )
    with c6:
        if total_spend > 0:
            st.metric("F&B Revenue (Tevalis)", f"£{total_spend:,.0f}")
        elif adr > 0:
            st.metric("Room ADR", f"£{adr:,.0f}", delta=f"£{rev_cur - rev_yoy:+,.0f} room rev vs 2025")
        else:
            st.metric("Room Nights Sold", f"{nights_cur:,}", delta=f"{nights_cur - nights_yoy:+,} vs 2025")


def _reservations_section(df_cur, df_yoy):
    st.subheader("Table Reservations")

    t_yoy, t_venue, t_shift, t_spend = st.tabs(
        ["Year on Year", "By Pub", "By Shift / Day", "Spend (Tevalis)"]
    )

    with t_yoy:
        _chart_yoy(df_cur, df_yoy)
    with t_venue:
        _chart_venue(df_cur, df_yoy)
    with t_shift:
        _chart_shift(df_cur)
    with t_spend:
        _chart_spend(df_cur)


def _chart_yoy(df_cur, df_yoy):
    """Weekly covers: 2026 vs 2025."""
    if df_cur.empty:
        st.info("No 2026 reservation data loaded.")
        return

    def weekly(df, label):
        if "week" not in df.columns or "covers" not in df.columns:
            return pd.DataFrame()
        g = df.groupby("week", as_index=False)["covers"].sum()
        g["year"] = label
        return g

    combined = pd.concat([weekly(df_yoy, "2025"), weekly(df_cur, "2026")], ignore_index=True)
    if combined.empty:
        st.info("Insufficient data for year-on-year chart.")
        return

    fig = px.line(
        combined,
        x="week",
        y="covers",
        color="year",
        title="Weekly Covers: 2026 vs 2025",
        labels={"week": "Week", "covers": "Covers", "year": "Year"},
        color_discrete_map={"2026": COLOURS["green"], "2025": COLOURS["amber"]},
        markers=True,
    )
    fig.update_layout(height=380, legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, use_container_width=True)

    # Summary delta table by month
    if "month" in df_cur.columns:
        m26 = df_cur.groupby("month", as_index=False).agg(covers_26=("covers", "sum"), bookings_26=("covers", "count"))
        m25 = df_yoy.groupby("month", as_index=False).agg(covers_25=("covers", "sum")).rename(columns={"month": "month"})
        merged = m26.merge(m25, on="month", how="left").fillna(0)
        merged["change"] = (merged["covers_26"] - merged["covers_25"]).astype(int)
        merged["change_%"] = (merged["change"] / merged["covers_25"].replace(0, 1) * 100).round(1)
        merged["month"] = merged["month"].dt.strftime("%b %Y")
        merged = merged.rename(columns={
            "month": "Month", "covers_26": "Covers 2026", "bookings_26": "Bookings 2026",
            "covers_25": "Covers 2025", "change": "Change", "change_%": "Change %"
        })
        st.dataframe(merged, use_container_width=True, hide_index=True)


def _chart_venue(df_cur, df_yoy):
    if df_cur.empty or "venue_name" not in df_cur.columns:
        st.info("No venue data available.")
        return

    def venue_agg(df, label):
        g = df.groupby("venue_name", as_index=False).agg(
            covers=("covers", "sum"),
            bookings=("covers", "count"),
        )
        g["year"] = label
        return g

    v26 = venue_agg(df_cur, "2026")
    v25 = venue_agg(df_yoy, "2025")
    order = v26.sort_values("covers", ascending=False)["venue_name"].tolist()
    combined = pd.concat([v25, v26], ignore_index=True)

    fig = px.bar(
        combined,
        x="venue_name",
        y="covers",
        color="year",
        barmode="group",
        title="Covers by Pub (2025 vs 2026)",
        color_discrete_map={"2026": COLOURS["green"], "2025": COLOURS["amber"]},
        category_orders={"venue_name": order},
    )
    fig.update_layout(height=420, xaxis_tickangle=-30, legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, use_container_width=True)

    # Summary table
    summary = v26[["venue_name", "covers", "bookings"]].copy()
    if not v25.empty:
        yoy_map = v25.set_index("venue_name")["covers"]
        summary["covers_2025"] = summary["venue_name"].map(yoy_map).fillna(0).astype(int)
        summary["change"] = summary["covers"] - summary["covers_2025"]
        summary["change_%"] = (summary["change"] / summary["covers_2025"].replace(0, 1) * 100).round(1)
    summary = summary.sort_values("covers", ascending=False).rename(columns={
        "venue_name": "Pub", "covers": "Covers 2026", "bookings": "Bookings 2026",
        "covers_2025": "Covers 2025", "change": "Change", "change_%": "Change %",
    })
    st.dataframe(summary, use_container_width=True, hide_index=True)


def _chart_shift(df):
    if df.empty:
        return

    c1, c2 = st.columns(2)

    with c1:
        if "meal_period" in df.columns:
            shift_data = df.groupby("meal_period", as_index=False)["covers"].sum()
            fig = px.pie(
                shift_data,
                values="covers",
                names="meal_period",
                title="Covers by Meal Period",
                color_discrete_sequence=[COLOURS["green"], COLOURS["green_mid"], COLOURS["green_light"]],
            )
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        if "day_of_week" in df.columns:
            day_data = df.groupby("day_of_week", as_index=False)["covers"].sum()
            day_data["day_of_week"] = pd.Categorical(
                day_data["day_of_week"], categories=DAY_ORDER, ordered=True
            )
            day_data = day_data.sort_values("day_of_week")
            fig = px.bar(
                day_data,
                x="day_of_week",
                y="covers",
                title="Covers by Day of Week",
                color_discrete_sequence=[COLOURS["green"]],
            )
            fig.update_layout(xaxis_title="", height=350)
            st.plotly_chart(fig, use_container_width=True)

    # Demand heatmap
    if "day_of_week" in df.columns and "hour" in df.columns:
        heat_df = df.dropna(subset=["hour"]).copy()
        heat_df["hour"] = heat_df["hour"].astype(int)
        if not heat_df.empty:
            heat = heat_df.groupby(["day_of_week", "hour"])["covers"].sum().reset_index()
            heat_pivot = heat.pivot(index="day_of_week", columns="hour", values="covers").fillna(0)
            heat_pivot = heat_pivot.reindex([d for d in DAY_ORDER if d in heat_pivot.index])
            fig = go.Figure(
                data=go.Heatmap(
                    z=heat_pivot.values,
                    x=[f"{int(h):02d}:00" for h in heat_pivot.columns],
                    y=heat_pivot.index.tolist(),
                    colorscale=[[0, "#ffffff"], [0.5, "#A5D6A7"], [1, "#1B5E20"]],
                    showscale=True,
                )
            )
            fig.update_layout(
                title="Booking Demand Heatmap (Day × Hour)",
                height=320,
                xaxis_title="Sitting Time",
            )
            st.plotly_chart(fig, use_container_width=True)


def _chart_spend(df):
    has_spend = "total_spend" in df.columns and df["total_spend"].sum() > 0
    has_spc = "spend_per_cover" in df.columns and (df["spend_per_cover"] > 0).any()

    if not has_spend and not has_spc:
        st.info(
            "No spend data found for this period. This data flows from Tevalis via the "
            "SevenRooms POS integration — if you're expecting figures here, confirm the "
            "integration is active in your SevenRooms account settings."
        )
        return

    c1, c2 = st.columns(2)

    if has_spend and "venue_name" in df.columns:
        with c1:
            v_spend = df.groupby("venue_name", as_index=False)["total_spend"].sum().sort_values(
                "total_spend", ascending=False
            )
            fig = px.bar(
                v_spend,
                x="venue_name",
                y="total_spend",
                title="Total F&B Spend by Pub",
                color_discrete_sequence=[COLOURS["green"]],
            )
            fig.update_layout(xaxis_tickangle=-30, height=380, yaxis_title="£")
            st.plotly_chart(fig, use_container_width=True)

    if has_spc and "venue_name" in df.columns:
        with c2:
            spc = (
                df[df["spend_per_cover"] > 0]
                .groupby("venue_name", as_index=False)["spend_per_cover"]
                .mean()
                .sort_values("spend_per_cover", ascending=False)
            )
            fig = px.bar(
                spc,
                x="venue_name",
                y="spend_per_cover",
                title="Avg Spend per Cover by Pub",
                color_discrete_sequence=[COLOURS["green_mid"]],
            )
            fig.update_layout(xaxis_tickangle=-30, height=380, yaxis_title="£")
            st.plotly_chart(fig, use_container_width=True)


def _rooms_section(df_cur, df_yoy):
    st.subheader("Room Occupancy (Eviivo)")

    if df_cur.empty:
        st.info("No Eviivo room booking data returned for this period.")
        return

    days_cur = (REPORT_END - REPORT_START).days + 1
    days_yoy = (YOY_END - YOY_START).days + 1
    avail_cur = ROOM_PROPERTY_COUNT * days_cur
    avail_yoy = ROOM_PROPERTY_COUNT * days_yoy

    nights_cur = int(df_cur["nights"].sum())
    nights_yoy = int(df_yoy["nights"].sum()) if not df_yoy.empty and "nights" in df_yoy.columns else 0
    rev_cur = df_cur["revenue"].sum()
    rev_yoy = df_yoy["revenue"].sum() if not df_yoy.empty and "revenue" in df_yoy.columns else 0
    occ_cur = nights_cur / avail_cur * 100 if avail_cur else 0
    occ_yoy = nights_yoy / avail_yoy * 100 if avail_yoy else 0
    adr = rev_cur / nights_cur if nights_cur else 0
    revpar_cur = rev_cur / avail_cur if avail_cur else 0
    revpar_yoy = rev_yoy / avail_yoy if avail_yoy else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Occupancy Rate", f"{occ_cur:.1f}%", delta=f"{occ_cur - occ_yoy:+.1f}pp vs 2025")
    with c2:
        st.metric("Room Nights Sold", f"{nights_cur:,}", delta=f"{nights_cur - nights_yoy:+,} vs 2025")
    with c3:
        st.metric("ADR", f"£{adr:,.0f}")
    with c4:
        st.metric("RevPAR", f"£{revpar_cur:,.2f}", delta=f"£{revpar_cur - revpar_yoy:+.2f} vs 2025")

    st.caption(
        f"Occupancy across {ROOM_PROPERTY_COUNT} properties × {days_cur} days = "
        f"{avail_cur:,} available room nights."
    )

    t_trend, t_prop = st.tabs(["Monthly Trend", "By Property"])

    with t_trend:
        def monthly(df, label):
            if df.empty or "month" not in df.columns:
                return pd.DataFrame()
            g = df.groupby("month", as_index=False).agg(nights=("nights", "sum"), revenue=("revenue", "sum"))
            g["year"] = label
            return g

        combined = pd.concat([monthly(df_yoy, "2025"), monthly(df_cur, "2026")], ignore_index=True)
        if not combined.empty:
            fig = px.bar(
                combined,
                x="month",
                y="nights",
                color="year",
                barmode="group",
                title="Room Nights Sold per Month (2025 vs 2026)",
                color_discrete_map={"2026": COLOURS["green"], "2025": COLOURS["amber"]},
            )
            fig.update_layout(height=360, legend=dict(orientation="h", y=1.08))
            st.plotly_chart(fig, use_container_width=True)

    with t_prop:
        if "venue_name" in df_cur.columns:
            agg = (
                df_cur.groupby("venue_name", as_index=False)
                .agg(nights=("nights", "sum"), revenue=("revenue", "sum"), bookings=("revenue", "count"))
                .sort_values("nights", ascending=False)
            )
            fig = px.bar(
                agg,
                x="venue_name",
                y="nights",
                title="Room Nights Sold by Property (2026)",
                color_discrete_sequence=[COLOURS["green"]],
                text="nights",
            )
            fig.update_layout(height=380, xaxis_tickangle=-30)
            st.plotly_chart(fig, use_container_width=True)

            agg["ADR"] = (agg["revenue"] / agg["nights"].replace(0, 1)).round(2)
            agg = agg.rename(columns={
                "venue_name": "Property",
                "nights": "Nights Sold",
                "revenue": "Revenue",
                "bookings": "Bookings",
            })
            agg["Revenue"] = agg["Revenue"].apply(lambda x: f"£{x:,.0f}")
            agg["ADR"] = agg["ADR"].apply(lambda x: f"£{x:.2f}")
            st.dataframe(agg, use_container_width=True, hide_index=True)
        else:
            st.info("No property breakdown available — venue name not present in Eviivo data.")


def _patterns_section(df):
    st.subheader("Booking Patterns & Insights")

    if df.empty:
        st.info("No data available for pattern analysis.")
        return

    c1, c2 = st.columns(2)

    with c1:
        # No-show rate by venue
        if "venue_name" in df.columns and "status" in df.columns:
            totals = df.groupby("venue_name").size().rename("total")
            noshows = (
                df[df["status"].str.contains(r"no.?show", case=False, na=False)]
                .groupby("venue_name")
                .size()
                .rename("noshows")
            )
            ns_df = pd.concat([totals, noshows], axis=1).fillna(0).reset_index()
            ns_df["rate_%"] = (ns_df["noshows"] / ns_df["total"] * 100).round(1)
            ns_df = ns_df.sort_values("rate_%", ascending=False)
            fig = px.bar(
                ns_df,
                x="venue_name",
                y="rate_%",
                title="No-show Rate by Pub (%)",
                color="rate_%",
                color_continuous_scale=[[0, COLOURS["green_light"]], [1, COLOURS["red"]]],
            )
            fig.update_layout(height=360, xaxis_tickangle=-30, coloraxis_showscale=False, xaxis_title="")
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        # Booking lead time
        if "lead_days" in df.columns:
            lead = df["lead_days"].dropna()
            lead = lead[(lead >= 0) & (lead <= 180)]
            if not lead.empty:
                fig = px.histogram(
                    lead,
                    nbins=36,
                    title="Booking Lead Time (days in advance)",
                    labels={"value": "Days in Advance"},
                    color_discrete_sequence=[COLOURS["green"]],
                )
                fig.update_layout(height=360)
                st.plotly_chart(fig, use_container_width=True)

                median_lead = lead.median()
                pct_same_day = (lead == 0).mean() * 100
                st.caption(
                    f"Median lead time: **{int(median_lead)} days** · "
                    f"Same-day bookings: **{pct_same_day:.1f}%**"
                )
        else:
            st.info("Lead time data not available (requires 'created' field from SevenRooms).")

    # Monthly booking trend per pub — spot seasonal patterns
    if "month" in df.columns and "venue_name" in df.columns:
        st.markdown("**Monthly Covers per Pub**")
        monthly_venue = df.groupby(["month", "venue_name"], as_index=False)["covers"].sum()
        fig = px.line(
            monthly_venue,
            x="month",
            y="covers",
            color="venue_name",
            title="Monthly Covers by Pub (2026)",
            markers=True,
        )
        fig.update_layout(height=400, legend=dict(orientation="h", y=1.08))
        st.plotly_chart(fig, use_container_width=True)


def _feedback_section(feedback, venue_map):
    st.subheader("Guest Reviews (SevenRooms Feedback)")

    if not feedback:
        st.info("No SevenRooms feedback data returned for this period.")
        return

    df_fb = pd.DataFrame(feedback)
    rating_col = next(
        (c for c in ["overall", "overall_rating", "rating", "stars", "score"] if c in df_fb.columns),
        None,
    )

    if not rating_col:
        st.info("No rating field found in feedback data.")
        return

    df_fb["rating"] = pd.to_numeric(df_fb[rating_col], errors="coerce")
    df_fb = df_fb.dropna(subset=["rating"])

    if df_fb.empty:
        st.info("No valid ratings in feedback data.")
        return

    avg = df_fb["rating"].mean()
    total = len(df_fb)
    low = len(df_fb[df_fb["rating"] <= 2])
    five_star = len(df_fb[df_fb["rating"] == 5])

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Avg Rating", f"{avg:.2f} / 5")
    with c2:
        st.metric("Total Reviews", total)
    with c3:
        st.metric("5-Star Reviews", five_star)
    with c4:
        st.metric("Low Ratings (≤2★)", low)

    chart_c1, chart_c2 = st.columns(2)

    with chart_c1:
        dist = df_fb["rating"].value_counts().sort_index().reset_index()
        dist.columns = ["stars", "count"]
        fig = px.bar(
            dist,
            x="stars",
            y="count",
            title="Rating Distribution",
            color_discrete_sequence=[COLOURS["green"]],
        )
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)

    with chart_c2:
        if "venue_id" in df_fb.columns:
            df_fb["venue_name"] = df_fb["venue_id"].map(venue_map).fillna("Unknown")
            v_ratings = (
                df_fb.groupby("venue_name")["rating"]
                .agg(["mean", "count"])
                .reset_index()
                .rename(columns={"mean": "Avg Rating", "count": "Reviews", "venue_name": "Pub"})
                .sort_values("Avg Rating", ascending=False)
            )
            fig = px.bar(
                v_ratings,
                x="Pub",
                y="Avg Rating",
                title="Avg Rating by Pub",
                color="Avg Rating",
                color_continuous_scale=[[0, COLOURS["red"]], [0.5, "#FFF176"], [1, COLOURS["green_mid"]]],
                range_color=[1, 5],
                text="Reviews",
            )
            fig.update_layout(height=320, xaxis_tickangle=-30, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    # Rating trend over time
    date_col = next((c for c in ["reservation_date", "date", "created"] if c in df_fb.columns), None)
    if date_col:
        df_fb["fb_month"] = pd.to_datetime(df_fb[date_col], errors="coerce").dt.to_period("M").dt.start_time
        monthly_ratings = df_fb.groupby("fb_month", as_index=False)["rating"].mean().dropna()
        if not monthly_ratings.empty:
            fig = px.line(
                monthly_ratings,
                x="fb_month",
                y="rating",
                title="Avg Rating Trend (monthly)",
                markers=True,
                color_discrete_sequence=[COLOURS["green"]],
            )
            fig.update_layout(height=280, yaxis_range=[1, 5])
            st.plotly_chart(fig, use_container_width=True)

    # Low-rating comments
    low_df = df_fb[df_fb["rating"] <= 2].copy()
    if not low_df.empty:
        st.markdown("**Low-rating Feedback (≤ 2★)**")
        comment_col = next(
            (c for c in ["notes", "comment", "comments", "feedback", "additional_notes"] if c in low_df.columns),
            None,
        )
        disp = ["venue_name", "rating"] + ([comment_col] if comment_col else [])
        disp = [c for c in disp if c in low_df.columns]
        st.dataframe(low_df[disp].sort_values("rating"), use_container_width=True, hide_index=True)


def _competitors_section():
    st.subheader("Competitor Intelligence")
    st.caption(
        "Publicly available data from competitor web presence. "
        "Competitor revenue, occupancy, or volumes are not publicly accessible — "
        "for deep benchmarking consider STR or Coffer Peach data services."
    )

    with st.spinner("Checking competitor ratings..."):
        comp = _scrape_competitors()

    rows = [
        {
            "Competitor": name,
            "Google Rating": f"{d['google_rating']:.1f} ★" if d.get("google_rating") else "—",
            "Review Count": f"{d['review_count']:,}" if d.get("review_count") else "—",
            "Status": "✓ Data found" if d.get("google_rating") else "✗ Not extracted",
        }
        for name, d in comp.items()
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    chart_data = [
        {"Group": n, "Rating": d["google_rating"]}
        for n, d in comp.items()
        if d.get("google_rating")
    ]
    if chart_data:
        fig = px.bar(
            pd.DataFrame(chart_data),
            x="Group",
            y="Rating",
            title="Competitor Google Ratings",
            color_discrete_sequence=[COLOURS["amber"]],
            range_y=[3, 5],
            text="Rating",
        )
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("What can we realistically benchmark?"):
        st.markdown(
            """
**Available from public sources**
- Google / TripAdvisor review scores and review volume
- Publicly listed menu pricing
- Room rates and availability windows (where booking widgets are public)

**Not available without data partnerships**
- Competitor revenue or occupancy figures
- No-show rates, average party size, lead times

**Recommended data services for hospitality benchmarking**
- [Coffer Peach Business Tracker](https://www.cofferpeach.com) — UK hospitality sector benchmarks
- [STR Global](https://str.com) — Hotel/accommodation benchmarking (RevPAR, ADR, Occ)
"""
        )


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

def render(tab, sr_client, eviivo_client, venue_map):
    """Render the BI report inside the given Streamlit tab."""

    with tab:
        st.header("Business Intelligence Report")
        st.caption(
            f"**Period:** 1 Jan 2026 – {REPORT_END.strftime('%d %b %Y')}  |  "
            f"**YoY comparison:** 1 Jan 2025 – {YOY_END.strftime('%d %b %Y')}"
        )

        col_btn, col_note = st.columns([1, 4])
        with col_btn:
            load = st.button("Generate Report", type="primary", key="bi_load_btn")
        with col_note:
            st.caption(
                "Pulls live data from SevenRooms (reservations, Tevalis spend, reviews) "
                "and Eviivo (room bookings). Allow ~30 seconds on first load."
            )

        if load:
            with st.spinner("Fetching reservations, room bookings, and feedback..."):
                raw_cur = _load_reservations(sr_client, REPORT_START, REPORT_END, "2026")
                raw_yoy = _load_reservations(sr_client, YOY_START, YOY_END, "2025")
                raw_rooms_cur = _load_eviivo(eviivo_client, REPORT_START, REPORT_END, "2026")
                raw_rooms_yoy = _load_eviivo(eviivo_client, YOY_START, YOY_END, "2025")
                fb = _load_feedback(sr_client, REPORT_START, REPORT_END)

            st.session_state["bi_df_cur"] = _process_reservations(raw_cur, venue_map)
            st.session_state["bi_df_yoy"] = _process_reservations(raw_yoy, venue_map)
            st.session_state["bi_rooms_cur"] = _process_eviivo(raw_rooms_cur)
            st.session_state["bi_rooms_yoy"] = _process_eviivo(raw_rooms_yoy)
            st.session_state["bi_feedback"] = fb
            st.session_state["bi_ready"] = True

        if not st.session_state.get("bi_ready"):
            st.info("Click **Generate Report** to load data and build the report.")
            return

        df_cur = st.session_state.get("bi_df_cur", pd.DataFrame())
        df_yoy = st.session_state.get("bi_df_yoy", pd.DataFrame())
        df_rooms_cur = st.session_state.get("bi_rooms_cur", pd.DataFrame())
        df_rooms_yoy = st.session_state.get("bi_rooms_yoy", pd.DataFrame())
        feedback = st.session_state.get("bi_feedback", [])

        if df_cur.empty:
            st.warning("No reservation data returned. Check that SevenRooms is authenticated and the date range has data.")
            return

        df_conf_cur = _confirmed_only(df_cur)
        df_conf_yoy = _confirmed_only(df_yoy)

        _kpis(df_conf_cur, df_conf_yoy, df_rooms_cur, df_rooms_yoy)
        st.divider()
        _reservations_section(df_conf_cur, df_conf_yoy)
        st.divider()
        _rooms_section(df_rooms_cur, df_rooms_yoy)
        st.divider()
        _patterns_section(df_conf_cur)
        st.divider()
        _feedback_section(feedback, venue_map)
        st.divider()
        _competitors_section()
