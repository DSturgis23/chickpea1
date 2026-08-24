"""
Chickpea Pubs – PDF Report Generator
Sophisticated business intelligence: SevenRooms reservations + Tevalis spend +
Eviivo room occupancy. Generates a branded, insight-driven PDF.
"""

import io
import os
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

sys.path.insert(0, str(Path(__file__).parent))
from sevenrooms_api import SevenRoomsClient
from eviivo_api import EviivoClient
from pub_mapping import get_all_eviivo_properties

warnings.filterwarnings("ignore")

# ── CONSTANTS ─────────────────────────────────────────────────────────────────

LOGO_PATH = (
    r"C:\Users\Delilah Sturgis\Chickpea Dropbox\Chickpea\Chickpea"
    r"\Branding\Logos (2023 onwards)\Chickpea Group\Chickpea 2026 Logo.png"
)

ROOM_COUNTS = {
    "The Bell & Crown":   6,
    "The Dog & Gun":      6,
    "The Fleur de Lys":   9,
    "The Grosvenor Arms": 9,
    "The Manor House Inn":9,
    "The Pembroke Arms":  9,
    "The Queen's Head":   4,
}
TOTAL_ROOMS = sum(ROOM_COUNTS.values())  # 52

# Brand palette
C_GREEN  = "#1C3829"
C_MID    = "#2E7D32"
C_LIGHT  = "#C8DFC8"
C_CREAM  = "#F9F5EF"
C_AMBER  = "#C8882A"
C_RED    = "#B71C1C"
C_BLUE   = "#1565C0"
C_TEXT   = "#1A1A1A"
C_GREY   = "#E4E4E4"
C_LGREY  = "#F5F5F5"

RL_GREEN  = colors.HexColor(C_GREEN)
RL_MID    = colors.HexColor(C_MID)
RL_LIGHT  = colors.HexColor(C_LIGHT)
RL_CREAM  = colors.HexColor(C_CREAM)
RL_AMBER  = colors.HexColor(C_AMBER)
RL_RED    = colors.HexColor(C_RED)
RL_GREY   = colors.HexColor(C_GREY)
RL_LGREY  = colors.HexColor(C_LGREY)
RL_WHITE  = colors.white
RL_BLACK  = colors.black

PAGE_W, PAGE_H = A4
MARGIN   = 1.5 * cm
INNER_W  = PAGE_W - 2 * MARGIN

DAY_ORDER = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]

CONFIRMED_STATUSES = {
    "seated", "completed", "confirmed", "reserved", "arrived", "checked in"
}
NOSHOW_PATTERN   = r"no.?show"
CANCEL_PATTERN   = r"cancel"

# ── STYLES ────────────────────────────────────────────────────────────────────

def _styles():
    S = {}
    def s(name, **kw):
        S[name] = ParagraphStyle(name, **kw)

    s("cover_title",  fontName="Helvetica-Bold",   fontSize=30, textColor=RL_WHITE,  alignment=TA_CENTER, leading=36)
    s("cover_sub",    fontName="Helvetica",          fontSize=13, textColor=RL_LIGHT,  alignment=TA_CENTER, leading=18)
    s("cover_date",   fontName="Helvetica",          fontSize=9,  textColor=RL_LIGHT,  alignment=TA_CENTER, leading=13)
    s("section",      fontName="Helvetica-Bold",     fontSize=14, textColor=RL_GREEN,  leading=18, spaceBefore=4, spaceAfter=3)
    s("subsection",   fontName="Helvetica-Bold",     fontSize=10, textColor=RL_GREEN,  leading=14, spaceBefore=4, spaceAfter=2)
    s("body",         fontName="Helvetica",          fontSize=8.5,textColor=RL_BLACK,  leading=13, spaceAfter=3)
    s("body_bold",    fontName="Helvetica-Bold",     fontSize=8.5,textColor=RL_BLACK,  leading=13)
    s("insight",      fontName="Helvetica",          fontSize=8.5,textColor=colors.HexColor("#1A3829"), leading=13, spaceAfter=2)
    s("note",         fontName="Helvetica-Oblique",  fontSize=7.5,textColor=colors.HexColor("#777777"), leading=11, spaceAfter=3)
    s("small",        fontName="Helvetica",          fontSize=7.5,textColor=colors.HexColor("#555555"), leading=11)
    s("kpi_val",      fontName="Helvetica-Bold",     fontSize=20, textColor=RL_GREEN,  alignment=TA_CENTER, leading=24)
    s("kpi_lbl",      fontName="Helvetica",          fontSize=7.5,textColor=colors.HexColor("#555555"), alignment=TA_CENTER, leading=10)
    s("kpi_delta_pos",fontName="Helvetica-Bold",     fontSize=8,  textColor=RL_MID,    alignment=TA_CENTER, leading=11)
    s("kpi_delta_neg",fontName="Helvetica-Bold",     fontSize=8,  textColor=RL_RED,    alignment=TA_CENTER, leading=11)
    s("th",           fontName="Helvetica-Bold",     fontSize=7.5,textColor=RL_WHITE,  alignment=TA_CENTER, leading=10)
    s("td",           fontName="Helvetica",          fontSize=7.5,textColor=RL_BLACK,  alignment=TA_CENTER, leading=10)
    s("td_l",         fontName="Helvetica",          fontSize=7.5,textColor=RL_BLACK,  alignment=TA_LEFT,   leading=10)
    s("td_r",         fontName="Helvetica",          fontSize=7.5,textColor=RL_BLACK,  alignment=TA_RIGHT,  leading=10)
    return S


# ── DATA FETCHING ─────────────────────────────────────────────────────────────

def _fetch_in_monthly_chunks(sr_client, start_date, end_date):
    """
    Fetch reservations month-by-month to avoid the SevenRooms 4400-record
    per-request cap, then deduplicate by reservation id.
    """
    from calendar import monthrange
    all_records = {}   # id -> record (deduplicates across chunk boundaries)

    cur = date(start_date.year, start_date.month, 1)
    while cur <= end_date:
        last_day = monthrange(cur.year, cur.month)[1]
        chunk_end = min(date(cur.year, cur.month, last_day), end_date)
        r = sr_client.get_reservations(from_date=str(cur), to_date=str(chunk_end))
        records = r.get("data", {}).get("results", []) if r else []
        for rec in records:
            rid = rec.get("id") or rec.get("reservation_id") or id(rec)
            all_records[rid] = rec
        print(f"    {cur} → {chunk_end}: {len(records)} records (total so far: {len(all_records)})")
        # advance to first day of next month
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)

    return list(all_records.values())


def _fetch_data(start_date, end_date, progress=None):
    def _p(f, m):
        print(f"[{int(f*100):3d}%] {m}")
        if progress: progress(f, m)

    yoy_start = date(start_date.year - 1, start_date.month, start_date.day)
    yoy_end   = date(end_date.year - 1,   end_date.month,   end_date.day)

    result = dict(
        reservations_cur=[], reservations_yoy=[],
        rooms_cur=[], rooms_yoy=[],
        feedback=[], venues=[], errors=[],
        yoy_start=yoy_start, yoy_end=yoy_end,
    )

    # ── SevenRooms ────────────────────────────────────────────────────────────
    _p(0.05, "Connecting to SevenRooms…")
    try:
        sr = SevenRoomsClient()
        if not sr.authenticate():
            result["errors"].append("SevenRooms: authentication failed — check credentials.")
        else:
            _p(0.08, "Fetching venue list…")
            vr = sr.get_venues()
            result["venues"] = vr.get("data", {}).get("results", []) if vr else []

            _p(0.12, f"Fetching reservations {start_date} → {end_date}…")
            result["reservations_cur"] = _fetch_in_monthly_chunks(sr, start_date, end_date)
            print(f"  Current period: {len(result['reservations_cur'])} reservations")

            _p(0.20, f"Fetching prior-year reservations {yoy_start} → {yoy_end}…")
            result["reservations_yoy"] = _fetch_in_monthly_chunks(sr, yoy_start, yoy_end)
            print(f"  Prior year: {len(result['reservations_yoy'])} reservations")

            _p(0.28, "Fetching guest feedback / reviews…")
            try:
                fb = sr.get_feedback(from_date=str(start_date), to_date=str(end_date))
                result["feedback"] = fb.get("data", {}).get("results", []) if fb else []
                print(f"  Feedback: {len(result['feedback'])} records")
            except Exception as e:
                result["errors"].append(f"Feedback fetch error: {e}")

    except Exception as e:
        result["errors"].append(f"SevenRooms error: {e}")

    # ── Eviivo ────────────────────────────────────────────────────────────────
    _p(0.35, "Connecting to Eviivo…")
    try:
        ev = EviivoClient()
        if not ev.authenticate():
            result["errors"].append("Eviivo: authentication failed — check credentials.")
        else:
            mappings = get_all_eviivo_properties()

            _p(0.40, f"Fetching room bookings {start_date} → {end_date}…")
            result["rooms_cur"] = ev.get_all_historical_bookings(
                mappings, checkin_from=str(start_date), checkin_to=str(end_date)
            )
            print(f"  Current rooms: {len(result['rooms_cur'])} bookings")

            _p(0.48, f"Fetching prior-year room bookings {yoy_start} → {yoy_end}…")
            result["rooms_yoy"] = ev.get_all_historical_bookings(
                mappings, checkin_from=str(yoy_start), checkin_to=str(yoy_end)
            )
            print(f"  Prior year rooms: {len(result['rooms_yoy'])} bookings")

    except Exception as e:
        result["errors"].append(f"Eviivo error: {e}")

    return result


# ── DATA PROCESSING ───────────────────────────────────────────────────────────

def _process_reservations(raw, venue_map):
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)

    # ── Dates ──
    if "date" in df.columns:
        dt = pd.to_datetime(df["date"], errors="coerce")
        df["reservation_date"] = dt.dt.date
        df["week"]        = dt.dt.to_period("W").dt.start_time
        df["month"]       = dt.dt.to_period("M").dt.start_time
        df["month_str"]   = dt.dt.strftime("%b %Y")
        df["day_of_week"] = dt.dt.day_name()
        df["is_weekend"]  = dt.dt.dayofweek >= 4   # Fri/Sat/Sun
        df["year"]        = dt.dt.year

    # ── Covers ──
    df["covers"] = pd.to_numeric(
        df.get("max_guests", df.get("covers", 0)), errors="coerce"
    ).fillna(0).astype(int)

    # ── Venue ──
    if "venue_id" in df.columns:
        df["venue_name"] = df["venue_id"].map(venue_map).fillna("Unknown")

    # ── Status normalised ──
    raw_status = df.get("status_display", df.get("status", pd.Series(["Unknown"] * len(df))))
    df["status"] = raw_status.fillna("Unknown").astype(str)
    df["status_lc"] = df["status"].str.lower().str.strip()
    df["is_confirmed"] = df["status_lc"].isin(CONFIRMED_STATUSES)
    df["is_noshow"]    = df["status_lc"].str.contains(NOSHOW_PATTERN, regex=True, na=False)
    df["is_cancelled"] = df["status_lc"].str.contains(CANCEL_PATTERN, regex=True, na=False)

    # ── Spend / Tevalis ──
    # SevenRooms fields when Tevalis POS is connected
    spend_candidates = ["spend", "total_spend", "spend_amount", "check_amount",
                        "actual_spend", "actual_revenue"]
    df["total_spend"] = 0.0
    for col in spend_candidates:
        if col in df.columns:
            val = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if val.sum() > 0:
                df["total_spend"] = val
                break

    spc_candidates = ["spend_per_cover", "avg_spend_per_cover", "check_per_cover",
                      "actual_spend_per_cover", "revenue_per_cover"]
    df["spend_per_cover"] = 0.0
    for col in spc_candidates:
        if col in df.columns:
            val = pd.to_numeric(df[col], errors="coerce").fillna(0)
            if val.sum() > 0:
                df["spend_per_cover"] = val
                break

    # Derive spend_per_cover from total / covers where direct field is zero
    derived = (df["spend_per_cover"] == 0) & (df["total_spend"] > 0) & (df["covers"] > 0)
    df.loc[derived, "spend_per_cover"] = df.loc[derived, "total_spend"] / df.loc[derived, "covers"]

    df["has_spend"] = df["total_spend"] > 0

    # ── Meal period ──
    def _period(row):
        s = str(row.get("shift_category", "")).upper()
        if s == "BREAKFAST": return "Breakfast"
        if s == "LUNCH":     return "Lunch"
        if s == "DINNER":    return "Dinner"
        if s == "DAY":
            try:
                h = int(str(row.get("time_slot_iso","")).split("T")[1][:2])
                return "Lunch" if h < 15 else "Dinner"
            except Exception: return "Lunch"
        return "Unknown"
    if "shift_category" in df.columns:
        df["meal_period"] = df.apply(_period, axis=1)

    # ── Booking channel ──
    for col in ["booked_by", "booked_via", "source", "booking_source"]:
        if col in df.columns and df[col].notna().any():
            df["channel"] = df[col].fillna("Unknown")
            break

    # ── Booking lead time ──
    if "created" in df.columns and "reservation_date" in df.columns:
        created = pd.to_datetime(df["created"], errors="coerce").dt.date
        df["lead_days"] = [
            (rd - cd).days if rd and cd else None
            for rd, cd in zip(df["reservation_date"], created)
        ]
        df["lead_bucket"] = pd.cut(
            df["lead_days"].clip(0, 365),
            bins=[-1, 0, 3, 7, 14, 30, 60, 365],
            labels=["Same day", "1–3 days", "4–7 days", "8–14 days",
                    "15–30 days", "31–60 days", "60+ days"],
        )

    # ── Party size buckets ──
    df["party_bucket"] = pd.cut(
        df["covers"],
        bins=[0, 2, 4, 6, 10, 100],
        labels=["1–2", "3–4", "5–6", "7–10", "10+"],
    )

    # ── Occasion / reservation type ──
    for col in ["reservation_type", "occasion", "type"]:
        if col in df.columns and df[col].notna().any():
            df["occasion"] = df[col].fillna("").astype(str).str.strip()
            break

    # ── Hour ──
    if "time_slot_iso" in df.columns:
        df["hour"] = pd.to_datetime(df["time_slot_iso"], errors="coerce").dt.hour

    # ── Guest loyalty — new vs returning ──
    # SevenRooms includes visit_count (cumulative visits by this guest)
    visit_col = next((c for c in ["visit_count", "client_visit_count", "total_visits", "visits"]
                      if c in df.columns), None)
    if visit_col:
        df["visit_count"] = pd.to_numeric(df[visit_col], errors="coerce").fillna(1)
        df["is_returning"] = df["visit_count"] > 1
        df["guest_tier"] = pd.cut(
            df["visit_count"],
            bins=[0, 1, 3, 7, 9999],
            labels=["First visit", "2–3 visits", "4–7 visits", "8+ visits"],
        )
    else:
        # Fall back: use email/client_id to identify guests seen more than once
        # within the dataset itself (undercount vs true history, but still useful)
        id_col = next((c for c in ["client_id", "guest_id", "email"] if c in df.columns), None)
        if id_col:
            seen = df[id_col].value_counts()
            df["visit_count"] = df[id_col].map(seen).fillna(1)
            df["is_returning"] = df["visit_count"] > 1
        else:
            df["is_returning"] = False

    # ── Booking source / channel ──
    channel_col = next((c for c in ["booked_by", "booked_via", "booking_source",
                                     "source", "shift_booking_source", "channel"]
                        if c in df.columns and df[c].notna().any()), None)
    if channel_col:
        raw_ch = df[channel_col].fillna("Unknown").astype(str).str.strip()
        def _norm_channel(v):
            vl = v.lower()
            if any(x in vl for x in ("walk", "walkin", "walk-in")):       return "Walk-in"
            if any(x in vl for x in ("phone", "telephone", "call")):      return "Phone"
            if any(x in vl for x in ("online", "web", "website", "internet", "direct")): return "Online Direct"
            if any(x in vl for x in ("opentable", "resy", "quandoo", "bookatable",
                                      "design my night", "designmynight")):return "Third Party Platform"
            if any(x in vl for x in ("email", "mail")):                    return "Email"
            if v in ("", "none", "unknown", "Unknown"):                    return "Unknown"
            return v.title()
        df["booking_channel"] = raw_ch.apply(_norm_channel)

    return df


def _process_rooms(raw):
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw)

    if "date" in df.columns:
        df["checkin_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    if "checkout_date" in df.columns:
        df["checkout_dt"] = pd.to_datetime(df["checkout_date"], errors="coerce").dt.date

    if "checkin_date" in df.columns and "checkout_dt" in df.columns:
        df["nights"] = [
            max((co - ci).days, 1) if ci and co and co > ci else 1
            for ci, co in zip(df["checkin_date"], df["checkout_dt"])
        ]
    else:
        df["nights"] = 1

    df["revenue"] = pd.to_numeric(df.get("total_value", 0), errors="coerce").fillna(0)

    if "status" in df.columns:
        df["is_cancelled"] = df["status"].str.lower().isin(["cancelled", "canceled"])
        df = df[~df["is_cancelled"]]

    if "checkin_date" in df.columns:
        dt = pd.to_datetime(df["checkin_date"], errors="coerce")
        df["month"]       = dt.dt.to_period("M").dt.start_time
        df["month_str"]   = dt.dt.strftime("%b %Y")
        df["day_of_week"] = dt.dt.day_name()
        df["is_weekend"]  = dt.dt.dayofweek >= 4
        df["year"]        = dt.dt.year

    df["los_bucket"] = pd.cut(
        df["nights"],
        bins=[0, 1, 2, 3, 5, 100],
        labels=["1 night", "2 nights", "3 nights", "4–5 nights", "6+ nights"],
    )

    if "party_size" in df.columns:
        df["party_size"] = pd.to_numeric(df["party_size"], errors="coerce").fillna(1)

    # ── Booking channel (OTA vs Direct) ──
    # Populated by updated eviivo_api._normalize_booking
    if "booking_channel" not in df.columns:
        df["booking_channel"] = "Unknown"
    df["is_direct"] = df["booking_channel"].str.lower().isin(["direct"])
    df["is_ota"]    = df["booking_channel"].str.lower().isin(["ota"])

    # OTA commission estimate (industry standard ~15%)
    OTA_COMMISSION = 0.15
    df["ota_commission_cost"] = df.apply(
        lambda r: r["revenue"] * OTA_COMMISSION if r["is_ota"] else 0, axis=1
    )
    df["net_revenue"] = df["revenue"] - df["ota_commission_cost"]

    return df


# ── AUTO-INSIGHT ENGINE ───────────────────────────────────────────────────────

def _insights_reservations(df, df_yoy, has_spend):
    """Generate a list of data-driven insight strings."""
    ins = []
    if df.empty:
        return ins

    # YoY overall
    covers_cur = int(df["covers"].sum())
    covers_yoy = int(df_yoy["covers"].sum()) if not df_yoy.empty and "covers" in df_yoy.columns else 0
    if covers_yoy > 0:
        pct = (covers_cur - covers_yoy) / covers_yoy * 100
        direction = "up" if pct > 0 else "down"
        ins.append(
            f"Total covers are <b>{direction} {abs(pct):.1f}%</b> year-on-year "
            f"({covers_cur:,} vs {covers_yoy:,})."
        )

    # Best and worst performing pub
    if "venue_name" in df.columns and "venue_name" in df_yoy.columns and not df_yoy.empty:
        v26 = df.groupby("venue_name")["covers"].sum()
        v25 = df_yoy.groupby("venue_name")["covers"].sum()
        growth = ((v26 - v25) / v25.replace(0, 1) * 100).dropna().sort_values(ascending=False)
        if not growth.empty:
            best  = growth.index[0]
            worst = growth.index[-1]
            ins.append(
                f"<b>{best.replace('The ','')}</b> is the strongest performer, "
                f"covers <b>{'up' if growth.iloc[0] > 0 else 'down'} {abs(growth.iloc[0]):.1f}%</b> YoY."
            )
            if growth.iloc[-1] < -5:
                ins.append(
                    f"<b>{worst.replace('The ','')}</b> needs attention — covers "
                    f"<b>down {abs(growth.iloc[-1]):.1f}%</b> on prior year."
                )

    # Busiest day
    if "day_of_week" in df.columns:
        day_covers = df.groupby("day_of_week")["covers"].sum()
        busiest = day_covers.idxmax()
        quietest = day_covers.idxmin()
        ins.append(
            f"<b>{busiest}</b> is your busiest day "
            f"({int(day_covers[busiest]):,} covers); "
            f"<b>{quietest}</b> is your quietest "
            f"({int(day_covers[quietest]):,} covers)."
        )

    # Weekend vs weekday
    if "is_weekend" in df.columns:
        wk  = df[df["is_weekend"]]["covers"].sum()
        mf  = df[~df["is_weekend"]]["covers"].sum()
        total = wk + mf
        if total > 0:
            ins.append(
                f"Weekend (Fri–Sun) accounts for <b>{wk/total*100:.0f}%</b> of total covers."
            )

    # Meal period
    if "meal_period" in df.columns:
        mp = df.groupby("meal_period")["covers"].sum()
        if "Dinner" in mp and "Lunch" in mp:
            ratio = mp["Dinner"] / max(mp["Lunch"], 1)
            ins.append(
                f"Dinner drives <b>{ratio:.1f}×</b> more covers than Lunch."
                if ratio > 1 else
                f"Lunch drives <b>{(1/ratio):.1f}×</b> more covers than Dinner."
            )

    # No-show
    noshow_rate = df["is_noshow"].mean() * 100
    cancel_rate = df["is_cancelled"].mean() * 100
    if noshow_rate > 0:
        ins.append(
            f"No-show rate: <b>{noshow_rate:.1f}%</b> · Cancellation rate: <b>{cancel_rate:.1f}%</b>."
        )

    # Spend
    if has_spend and "total_spend" in df.columns:
        total_spend = df["total_spend"].sum()
        avg_spc = df.loc[df["spend_per_cover"] > 0, "spend_per_cover"].mean()
        if "meal_period" in df.columns:
            spc_mp = df[df["spend_per_cover"] > 0].groupby("meal_period")["spend_per_cover"].mean()
            if "Dinner" in spc_mp and "Lunch" in spc_mp:
                ins.append(
                    f"Average spend per cover: Dinner <b>£{spc_mp['Dinner']:.2f}</b> "
                    f"vs Lunch <b>£{spc_mp['Lunch']:.2f}</b>."
                )
        if "venue_name" in df.columns:
            top_spc = df[df["spend_per_cover"] > 0].groupby("venue_name")["spend_per_cover"].mean().sort_values(ascending=False)
            if not top_spc.empty:
                ins.append(
                    f"Highest spend per cover: <b>{top_spc.index[0].replace('The ','')}</b> "
                    f"at <b>£{top_spc.iloc[0]:.2f}</b> per head."
                )

    # Lead time
    if "lead_days" in df.columns:
        valid = df["lead_days"].dropna()
        valid = valid[valid >= 0]
        if len(valid) > 10:
            median_l = valid.median()
            same_day = (valid == 0).mean() * 100
            ins.append(
                f"Median booking lead time is <b>{int(median_l)} days</b> in advance; "
                f"<b>{same_day:.1f}%</b> of bookings are made on the day."
            )

    return ins


def _insights_rooms(df, df_yoy, days_cur, days_yoy):
    ins = []
    if df.empty:
        return ins

    avail_cur = TOTAL_ROOMS * days_cur
    avail_yoy = TOTAL_ROOMS * days_yoy
    occ_cur   = df["nights"].sum() / avail_cur * 100 if avail_cur else 0
    occ_yoy   = df_yoy["nights"].sum() / avail_yoy * 100 if not df_yoy.empty and avail_yoy else 0
    rev_cur   = df["revenue"].sum()
    nights    = df["nights"].sum()
    adr       = rev_cur / nights if nights else 0

    direction = "up" if occ_cur > occ_yoy else "down"
    ins.append(
        f"Overall occupancy is <b>{occ_cur:.1f}%</b>, "
        f"<b>{direction} {abs(occ_cur - occ_yoy):.1f}pp</b> year-on-year."
    )

    if "venue_name" in df.columns:
        v_occ = {}
        for vn, room_c in ROOM_COUNTS.items():
            sub = df[df["venue_name"] == vn]
            avail = room_c * days_cur
            occ = sub["nights"].sum() / avail * 100 if avail else 0
            v_occ[vn] = occ
        best  = max(v_occ, key=v_occ.get)
        worst = min(v_occ, key=v_occ.get)
        ins.append(
            f"<b>{best.replace('The ','')}</b> has the highest occupancy at "
            f"<b>{v_occ[best]:.1f}%</b>; "
            f"<b>{worst.replace('The ','')}</b> the lowest at <b>{v_occ[worst]:.1f}%</b>."
        )

    if "is_weekend" in df.columns:
        wk  = df[df["is_weekend"]]["nights"].sum()
        mf  = df[~df["is_weekend"]]["nights"].sum()
        total = wk + mf
        if total > 0:
            ins.append(
                f"Weekend room nights account for <b>{wk/total*100:.0f}%</b> of all nights sold."
            )

    if "nights" in df.columns:
        los = df["nights"].mean()
        ins.append(f"Average length of stay: <b>{los:.1f} nights</b>.")

    return ins


# ── CHART FACTORY ─────────────────────────────────────────────────────────────

def _fig_img(fig, width_pts, height_pts):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return Image(buf, width=width_pts, height=height_pts)


def _ax_style(ax):
    ax.spines[["top","right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)


def chart_yoy_weekly(df_cur, df_yoy, w, h=180):
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")

    def _plot(df, label, col, lw=1.8):
        if df.empty or "week" not in df.columns: return
        g = df.groupby("week")["covers"].sum()
        ax.plot(g.index, g.values, marker="o", markersize=3.5,
                linewidth=lw, color=col, label=label)

    _plot(df_yoy, "Prior year", C_AMBER)
    _plot(df_cur,  "Current year", C_GREEN, lw=2.2)
    ax.set_xlabel("Week", fontsize=7); ax.set_ylabel("Covers", fontsize=7)
    ax.legend(fontsize=7); _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_venue_grouped(df_cur, df_yoy, w, h=190):
    if df_cur.empty or "venue_name" not in df_cur.columns: return None
    v26 = df_cur.groupby("venue_name")["covers"].sum()
    v25 = df_yoy.groupby("venue_name")["covers"].sum() if not df_yoy.empty and "venue_name" in df_yoy.columns else pd.Series(dtype=float)
    venues = v26.sort_values(ascending=False).index.tolist()
    x, bw = np.arange(len(venues)), 0.38
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    ax.bar(x,      [v26.get(v,0) for v in venues], bw, label="Current year",  color=C_GREEN)
    ax.bar(x+bw,   [v25.get(v,0) for v in venues], bw, label="Prior year",    color=C_AMBER, alpha=0.85)
    ax.set_xticks(x + bw/2)
    ax.set_xticklabels([v.replace("The ","") for v in venues], rotation=28, ha="right", fontsize=6.5)
    ax.set_ylabel("Covers", fontsize=7); ax.legend(fontsize=7); _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_spend_per_cover_venue(df, w, h=175):
    if df.empty or "venue_name" not in df.columns: return None
    sub = df[df["spend_per_cover"] > 0]
    if sub.empty: return None
    data = sub.groupby("venue_name")["spend_per_cover"].mean().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    bars = ax.barh([v.replace("The ","") for v in data.index], data.values, color=C_GREEN)
    ax.bar_label(bars, fmt="£%.2f", padding=4, fontsize=7)
    ax.set_xlabel("Avg Spend per Cover (£)", fontsize=7)
    ax.spines[["top","right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_spend_per_cover_shift(df, w, h=155):
    if df.empty or "meal_period" not in df.columns: return None
    sub = df[(df["spend_per_cover"] > 0) & (df["meal_period"] != "Unknown")]
    if sub.empty: return None
    data = sub.groupby("meal_period")["spend_per_cover"].mean().sort_values(ascending=False)
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    clrs = [C_GREEN, C_MID, C_LIGHT]
    bars = ax.bar(data.index, data.values, color=clrs[:len(data)])
    ax.bar_label(bars, fmt="£%.2f", padding=3, fontsize=7.5)
    ax.set_ylabel("Avg Spend per Cover (£)", fontsize=7)
    _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_spend_trend(df, w, h=160):
    if df.empty or "month" not in df.columns: return None
    sub = df[df["has_spend"]]
    if sub.empty: return None
    monthly = sub.groupby("month").agg(
        total_spend=("total_spend","sum"),
        covers=("covers","sum"),
    )
    monthly["spc"] = monthly["total_spend"] / monthly["covers"].replace(0,1)
    fig, ax1 = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    ax2 = ax1.twinx()
    ax1.bar(monthly.index, monthly["total_spend"], width=18, color=C_LIGHT, label="Revenue")
    ax2.plot(monthly.index, monthly["spc"], color=C_GREEN, marker="o",
             markersize=4, linewidth=1.8, label="Spend/cover")
    ax1.set_ylabel("F&B Revenue (£)", fontsize=7)
    ax2.set_ylabel("Spend per Cover (£)", fontsize=7)
    ax1.tick_params(labelsize=7); ax2.tick_params(labelsize=7)
    ax1.spines[["top","right"]].set_visible(False)
    ax2.spines[["top","left"]].set_visible(False)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1+lines2, labels1+labels2, fontsize=7, loc="upper left")
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_noshow_venue(df, w, h=165):
    if df.empty or "venue_name" not in df.columns: return None
    agg = df.groupby("venue_name").agg(
        total=("is_noshow","count"),
        noshows=("is_noshow","sum"),
        cancels=("is_cancelled","sum"),
    ).reset_index()
    agg["ns_pct"] = agg["noshows"] / agg["total"] * 100
    agg["cn_pct"] = agg["cancels"] / agg["total"] * 100
    agg = agg.sort_values("ns_pct", ascending=True)
    x = np.arange(len(agg))
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    ax.barh(x,       agg["ns_pct"], label="No-show",    color=C_RED,   alpha=0.85)
    ax.barh(x, agg["cn_pct"], left=agg["ns_pct"], label="Cancellation", color=C_AMBER, alpha=0.75)
    ax.set_yticks(x)
    ax.set_yticklabels([v.replace("The ","") for v in agg["venue_name"]], fontsize=7)
    ax.set_xlabel("% of Bookings", fontsize=7)
    ax.legend(fontsize=7); ax.spines[["top","right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_lead_time(df, w, h=155):
    if df.empty or "lead_days" not in df.columns: return None
    valid = df["lead_days"].dropna()
    valid = valid[(valid >= 0) & (valid <= 180)]
    if len(valid) < 5: return None
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    ax.hist(valid, bins=36, color=C_GREEN, edgecolor="white", linewidth=0.4)
    ax.axvline(valid.median(), color=C_AMBER, linewidth=1.5, linestyle="--",
               label=f"Median: {int(valid.median())}d")
    ax.set_xlabel("Days in advance", fontsize=7)
    ax.set_ylabel("Bookings", fontsize=7)
    ax.legend(fontsize=7); _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_day_of_week(df, w, h=150):
    if df.empty or "day_of_week" not in df.columns: return None
    data = df.groupby("day_of_week")["covers"].sum()
    data = data.reindex([d for d in DAY_ORDER if d in data.index])
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    clrs = [C_RED if d in ("Friday","Saturday","Sunday") else C_GREEN for d in data.index]
    bars = ax.bar([d[:3] for d in data.index], data.values, color=clrs)
    ax.bar_label(bars, fontsize=6.5, padding=2)
    ax.set_ylabel("Covers", fontsize=7); _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_heatmap(df, w, h=190):
    if df.empty or "day_of_week" not in df.columns or "hour" not in df.columns: return None
    df2 = df.dropna(subset=["hour"]).copy()
    df2["hour"] = df2["hour"].astype(int)
    heat = df2.groupby(["day_of_week","hour"])["covers"].sum().reset_index()
    piv  = heat.pivot(index="day_of_week", columns="hour", values="covers").fillna(0)
    piv  = piv.reindex([d for d in DAY_ORDER if d in piv.index])
    if piv.empty: return None
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    im = ax.imshow(piv.values, aspect="auto",
                   cmap=plt.colormaps["Greens"], vmin=0)
    ax.set_xticks(range(len(piv.columns)))
    ax.set_xticklabels([f"{int(h):02d}:00" for h in piv.columns], fontsize=6, rotation=45)
    ax.set_yticks(range(len(piv.index)))
    ax.set_yticklabels(piv.index.tolist(), fontsize=7)
    plt.colorbar(im, ax=ax, label="Covers", fraction=0.03)
    ax.set_title("Covers by Day & Hour", fontsize=8, pad=4)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_room_monthly(df_cur, df_yoy, w, h=170):
    if df_cur.empty: return None
    def _m(df):
        return df.groupby("month")["nights"].sum() if "month" in df.columns else pd.Series(dtype=float)
    mc, my = _m(df_cur), _m(df_yoy)
    months = sorted(set(mc.index) | set(my.index))
    x, bw = np.arange(len(months)), 0.38
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    ax.bar(x,      [mc.get(m,0) for m in months], bw, label="Current year", color=C_GREEN)
    ax.bar(x+bw,   [my.get(m,0) for m in months], bw, label="Prior year",   color=C_AMBER, alpha=0.85)
    ax.set_xticks(x + bw/2)
    ax.set_xticklabels([m.strftime("%b") for m in months], fontsize=7)
    ax.set_ylabel("Nights Sold", fontsize=7); ax.legend(fontsize=7); _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_room_occupancy_property(df_cur, days_cur, w, h=170):
    if df_cur.empty or "venue_name" not in df_cur.columns: return None
    rows = []
    for vn, rc in ROOM_COUNTS.items():
        sub  = df_cur[df_cur["venue_name"] == vn]
        occ  = sub["nights"].sum() / (rc * days_cur) * 100 if rc * days_cur else 0
        rows.append({"venue": vn.replace("The ",""), "occ": occ})
    data = pd.DataFrame(rows).sort_values("occ")
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    clrs = [C_RED if v < 40 else (C_AMBER if v < 65 else C_GREEN) for v in data["occ"]]
    bars = ax.barh(data["venue"], data["occ"], color=clrs)
    ax.bar_label(bars, fmt="%.1f%%", padding=4, fontsize=7)
    ax.set_xlim(0, 110)
    ax.axvline(data["occ"].mean(), color="#555555", linewidth=1, linestyle="--",
               label=f"Avg {data['occ'].mean():.1f}%")
    ax.set_xlabel("Occupancy %", fontsize=7)
    ax.legend(fontsize=7); ax.spines[["top","right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_los_distribution(df, w, h=145):
    if df.empty or "los_bucket" not in df.columns: return None
    data = df["los_bucket"].value_counts().sort_index()
    if data.empty: return None
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    bars = ax.bar(data.index.astype(str), data.values, color=C_GREEN)
    ax.bar_label(bars, fontsize=7, padding=2)
    ax.set_ylabel("Bookings", fontsize=7); _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_weekend_weekday_rooms(df, days_cur, w, h=145):
    if df.empty or "is_weekend" not in df.columns: return None
    fig, axes = plt.subplots(1, 2, figsize=(w/72, h/72), facecolor="white")
    for ax, col, label in [
        (axes[0], "nights", "Room Nights"),
        (axes[1], "revenue", "Revenue (£)"),
    ]:
        wk = df[df["is_weekend"]][col].sum()
        wd = df[~df["is_weekend"]][col].sum()
        ax.pie([wk, wd], labels=["Weekend", "Weekday"],
               colors=[C_GREEN, C_AMBER], autopct="%1.0f%%",
               textprops={"fontsize":7}, startangle=140)
        ax.set_title(label, fontsize=7.5)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_rating_dist(df_fb, w, h=140):
    if df_fb.empty or "rating" not in df_fb.columns: return None
    data = df_fb["rating"].value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    clr_map = {1: C_RED, 2: "#E57373", 3: C_AMBER, 4: C_MID, 5: C_GREEN}
    bars = ax.bar(data.index.astype(str), data.values,
                  color=[clr_map.get(int(i), C_MID) for i in data.index])
    ax.bar_label(bars, fontsize=7, padding=2)
    ax.set_xlabel("Stars", fontsize=7); ax.set_ylabel("Reviews", fontsize=7)
    _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_rating_venue(df_fb, w, h=140):
    if df_fb.empty or "venue_name" not in df_fb.columns or "rating" not in df_fb.columns:
        return None
    data = df_fb.groupby("venue_name")["rating"].mean().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    norm = plt.Normalize(1, 5)
    cmap = plt.colormaps["RdYlGn"]
    clrs = [cmap(norm(v)) for v in data.values]
    bars = ax.barh([v.replace("The ","") for v in data.index], data.values, color=clrs)
    ax.bar_label(bars, fmt="%.2f", padding=4, fontsize=7)
    ax.set_xlim(0, 5.5); ax.set_xlabel("Avg Rating", fontsize=7)
    ax.spines[["top","right"]].set_visible(False); ax.tick_params(labelsize=7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_rating_trend(df_fb, w, h=140):
    if df_fb.empty or "rating" not in df_fb.columns: return None
    date_col = next((c for c in ["reservation_date","date","created"] if c in df_fb.columns), None)
    if not date_col: return None
    df_fb = df_fb.copy()
    df_fb["fb_month"] = pd.to_datetime(df_fb[date_col], errors="coerce").dt.to_period("M").dt.start_time
    monthly = df_fb.groupby("fb_month").agg(avg=("rating","mean"), n=("rating","count")).reset_index()
    monthly = monthly[monthly["n"] >= 2]
    if monthly.empty: return None
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    ax.plot(monthly["fb_month"], monthly["avg"], marker="o", markersize=4,
            linewidth=1.8, color=C_GREEN)
    ax.fill_between(monthly["fb_month"], monthly["avg"], alpha=0.12, color=C_GREEN)
    ax.axhline(4.0, color=C_AMBER, linewidth=0.8, linestyle="--", label="4.0 target")
    ax.set_ylim(1, 5.2); ax.set_ylabel("Avg Rating", fontsize=7)
    ax.legend(fontsize=7); _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


# ── GUEST LOYALTY & CHANNEL CHARTS ───────────────────────────────────────────

def chart_new_vs_returning(df, w, h=155):
    """Donut: new vs returning guests by covers and bookings."""
    if df.empty or "is_returning" not in df.columns:
        return None
    ret = df[df["is_returning"]]
    new = df[~df["is_returning"]]
    bookings = [len(new), len(ret)]
    covers   = [int(new["covers"].sum()), int(ret["covers"].sum())]
    labels   = ["New guests", "Returning guests"]
    fig, axes = plt.subplots(1, 2, figsize=(w/72, h/72), facecolor="white")
    for ax, vals, title in [(axes[0], bookings, "By Bookings"), (axes[1], covers, "By Covers")]:
        if sum(vals) == 0:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", fontsize=8)
            ax.axis("off")
            continue
        wedges, texts, autotexts = ax.pie(
            vals, labels=labels, autopct="%1.0f%%",
            colors=[C_AMBER, C_GREEN], startangle=140,
            wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
            textprops={"fontsize": 7},
        )
        for at in autotexts:
            at.set_fontsize(7)
        ax.set_title(title, fontsize=8, pad=4)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_guest_tiers(df, w, h=155):
    """Bar: visit frequency tiers — how loyal is your customer base."""
    if df.empty or "guest_tier" not in df.columns:
        return None
    data = df.groupby("guest_tier", observed=True).agg(
        bookings=("covers", "count"),
        covers=("covers", "sum"),
    )
    if data.empty:
        return None
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    x = np.arange(len(data))
    bars = ax.bar(data.index.astype(str), data["covers"].values,
                  color=[C_AMBER, C_MID, C_GREEN, "#0D2B1F"])
    ax.bar_label(bars, fontsize=7, padding=2)
    ax.set_ylabel("Covers", fontsize=7)
    ax.set_xlabel("Visit Frequency", fontsize=7)
    _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_booking_source(df, w, h=155):
    """Horizontal bar: bookings and covers by channel."""
    if df.empty or "booking_channel" not in df.columns:
        return None
    data = df.groupby("booking_channel").agg(
        bookings=("covers", "count"),
        covers=("covers", "sum"),
    ).sort_values("bookings", ascending=True)
    if data.empty or len(data) <= 1:
        return None
    fig, ax = plt.subplots(figsize=(w/72, h/72), facecolor="white")
    bars = ax.barh(data.index.astype(str), data["bookings"].values, color=C_GREEN)
    ax.bar_label(bars, padding=4, fontsize=7)
    ax.set_xlabel("Bookings", fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def chart_room_channel_mix(df, w, h=165):
    """Stacked analysis: OTA vs Direct room bookings, revenue, and commission cost."""
    if df.empty or "booking_channel" not in df.columns:
        return None
    ch = df.groupby("booking_channel").agg(
        bookings=("revenue", "count"),
        nights=("nights", "sum"),
        gross_rev=("revenue", "sum"),
        commission=("ota_commission_cost", "sum"),
        net_rev=("net_revenue", "sum"),
    ).sort_values("gross_rev", ascending=False)
    if ch.empty or len(ch) <= 1:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(w/72, h/72), facecolor="white")

    # Left: bookings by channel (pie)
    ax1 = axes[0]
    clrs = [C_GREEN if "direct" in str(c).lower() else
            (C_RED if "ota" in str(c).lower() else C_AMBER)
            for c in ch.index]
    wedges, texts, autos = ax1.pie(
        ch["bookings"].values, labels=ch.index.astype(str),
        autopct="%1.0f%%", colors=clrs,
        wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
        textprops={"fontsize": 6.5},
    )
    for at in autos: at.set_fontsize(6.5)
    ax1.set_title("Bookings by Channel", fontsize=8, pad=4)

    # Right: gross revenue vs net revenue (OTA commission impact) — bar
    ax2 = axes[1]
    x = np.arange(len(ch))
    ax2.bar(x, ch["gross_rev"].values, label="Gross Revenue", color=C_LIGHT, width=0.5)
    ax2.bar(x, ch["net_rev"].values,   label="Net of Commission", color=C_GREEN, width=0.5, alpha=0.85)
    ax2.set_xticks(x)
    ax2.set_xticklabels(ch.index.astype(str), fontsize=6.5, rotation=20, ha="right")
    ax2.set_ylabel("Revenue (£)", fontsize=7)
    ax2.legend(fontsize=6.5)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.tick_params(labelsize=7)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"£{x:,.0f}"))
    ax2.set_title("Revenue Gross vs Net of OTA Commission", fontsize=7, pad=4)

    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


# ── TABLE BUILDERS ────────────────────────────────────────────────────────────

_BASE_TS = [
    ("BACKGROUND",    (0,0),(-1,0),  RL_GREEN),
    ("TEXTCOLOR",     (0,0),(-1,0),  RL_WHITE),
    ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
    ("FONTSIZE",      (0,0),(-1,-1), 7.5),
    ("GRID",          (0,0),(-1,-1), 0.3, colors.HexColor("#CCCCCC")),
    ("ROWBACKGROUNDS",(0,1),(-1,-1), [RL_WHITE, RL_LGREY]),
    ("ALIGN",         (1,1),(-1,-1), "CENTER"),
    ("TOPPADDING",    (0,0),(-1,-1), 3.5),
    ("BOTTOMPADDING", (0,0),(-1,-1), 3.5),
    ("LEFTPADDING",   (0,0),(0,-1),  5),
]


def _tbl(rows, col_fracs, extra_style=None):
    col_w = [INNER_W * f for f in col_fracs]
    ts = list(_BASE_TS) + (extra_style or [])
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle(ts))
    return t


def tbl_venue_reservations(df_cur, df_yoy, has_spend, S):
    if df_cur.empty or "venue_name" not in df_cur.columns: return None
    v26 = df_cur.groupby("venue_name").agg(
        covers=("covers","sum"), bookings=("covers","count"),
        noshows=("is_noshow","sum"), cancels=("is_cancelled","sum"),
        spend=("total_spend","sum"), spc=("spend_per_cover","mean"),
    )
    v25 = df_yoy.groupby("venue_name").agg(covers=("covers","sum")) \
        if not df_yoy.empty and "venue_name" in df_yoy.columns else pd.DataFrame()

    headers = ["Pub","Covers","Bookings","No-shows","Cancels","YoY Covers"]
    fracs   = [0.26, 0.12, 0.12, 0.12, 0.12, 0.14]
    if has_spend:
        headers += ["F&B Revenue","Spend/Cover"]
        fracs    = [0.22,0.10,0.10,0.09,0.09,0.12,0.14,0.14]

    rows = [[Paragraph(h, S["th"]) for h in headers]]
    for vn in v26.sort_values("covers", ascending=False).index:
        c26 = int(v26.loc[vn,"covers"])
        c25 = int(v25.loc[vn,"covers"]) if not v25.empty and vn in v25.index else 0
        delta = c26 - c25
        delta_s = f"+{delta}" if delta > 0 else str(delta)
        delta_col = C_MID if delta >= 0 else C_RED
        row = [
            Paragraph(vn.replace("The ",""), S["td_l"]),
            Paragraph(f"{c26:,}", S["td"]),
            Paragraph(f"{int(v26.loc[vn,'bookings']):,}", S["td"]),
            Paragraph(f"{int(v26.loc[vn,'noshows']):,}", S["td"]),
            Paragraph(f"{int(v26.loc[vn,'cancels']):,}", S["td"]),
            Paragraph(f'<font color="{delta_col}">{delta_s}</font>', S["td"]),
        ]
        if has_spend:
            row += [
                Paragraph(f"£{v26.loc[vn,'spend']:,.0f}", S["td"]),
                Paragraph(f"£{v26.loc[vn,'spc']:.2f}", S["td"]),
            ]
        rows.append(row)

    return _tbl(rows, fracs)


def tbl_rooms_property(df_cur, df_yoy, days_cur, days_yoy, S):
    if df_cur.empty or "venue_name" not in df_cur.columns: return None
    v_cur = df_cur.groupby("venue_name").agg(nights=("nights","sum"), revenue=("revenue","sum"))
    v_yoy = df_yoy.groupby("venue_name").agg(nights=("nights","sum")) \
        if not df_yoy.empty and "venue_name" in df_yoy.columns else pd.DataFrame()

    headers = ["Property","Rooms","Avail Nights","Nights Sold","Occ %","YoY Occ","Revenue","ADR","RevPAR"]
    fracs   = [0.20,0.07,0.10,0.10,0.08,0.09,0.13,0.10,0.13]
    rows    = [[Paragraph(h, S["th"]) for h in headers]]
    totals  = dict(avail=0, nights=0, rev=0, avail_y=0, nights_y=0)

    for vn, rc in sorted(ROOM_COUNTS.items()):
        avail = rc * days_cur
        avail_y = rc * days_yoy
        n  = int(v_cur.loc[vn,"nights"])  if vn in v_cur.index else 0
        ny = int(v_yoy.loc[vn,"nights"]) if not v_yoy.empty and vn in v_yoy.index else 0
        r  = v_cur.loc[vn,"revenue"] if vn in v_cur.index else 0
        occ  = n  / avail   * 100 if avail   else 0
        occ_y= ny / avail_y * 100 if avail_y else 0
        adr  = r  / n       if n       else 0
        revpar = r / avail  if avail   else 0
        occ_delta = occ - occ_y
        dclr = C_MID if occ_delta >= 0 else C_RED
        totals["avail"] += avail; totals["nights"] += n; totals["rev"] += r
        totals["avail_y"] += avail_y; totals["nights_y"] += ny
        rows.append([
            Paragraph(vn.replace("The ",""), S["td_l"]),
            Paragraph(str(rc), S["td"]),
            Paragraph(f"{avail:,}", S["td"]),
            Paragraph(f"{n:,}", S["td"]),
            Paragraph(f"{occ:.1f}%", S["td"]),
            Paragraph(f'<font color="{dclr}">{occ_delta:+.1f}pp</font>', S["td"]),
            Paragraph(f"£{r:,.0f}", S["td"]),
            Paragraph(f"£{adr:,.0f}", S["td"]),
            Paragraph(f"£{revpar:.2f}", S["td"]),
        ])

    # Totals row
    t_occ  = totals["nights"]   / totals["avail"]   * 100 if totals["avail"]   else 0
    t_occ_y= totals["nights_y"] / totals["avail_y"] * 100 if totals["avail_y"] else 0
    t_adr  = totals["rev"] / totals["nights"] if totals["nights"] else 0
    t_revpar = totals["rev"] / totals["avail"] if totals["avail"] else 0
    dclr = C_MID if t_occ >= t_occ_y else C_RED
    rows.append([
        Paragraph("<b>Total / Avg</b>", S["td_l"]),
        Paragraph(f"<b>{TOTAL_ROOMS}</b>", S["td"]),
        Paragraph(f"<b>{totals['avail']:,}</b>", S["td"]),
        Paragraph(f"<b>{totals['nights']:,}</b>", S["td"]),
        Paragraph(f"<b>{t_occ:.1f}%</b>", S["td"]),
        Paragraph(f'<b><font color="{dclr}">{t_occ - t_occ_y:+.1f}pp</font></b>', S["td"]),
        Paragraph(f"<b>£{totals['rev']:,.0f}</b>", S["td"]),
        Paragraph(f"<b>£{t_adr:,.0f}</b>", S["td"]),
        Paragraph(f"<b>£{t_revpar:.2f}</b>", S["td"]),
    ])
    extra = [
        ("BACKGROUND", (0, len(rows)-1), (-1, len(rows)-1), colors.HexColor("#D7EDD7")),
        ("FONTNAME",   (0, len(rows)-1), (-1, len(rows)-1), "Helvetica-Bold"),
    ]
    return _tbl(rows, fracs, extra)


def tbl_feedback(df_fb, S):
    if df_fb.empty or "venue_name" not in df_fb.columns: return None
    agg = df_fb.groupby("venue_name").agg(
        avg=("rating","mean"), n=("rating","count"),
        five=("rating", lambda x: (x==5).sum()),
        low=("rating",  lambda x: (x<=2).sum()),
    ).sort_values("avg", ascending=False)
    rows = [[Paragraph(h, S["th"]) for h in ["Pub","Reviews","Avg Rating","5★","≤2★","Score"]]]
    for vn, row in agg.iterrows():
        score = int(row["avg"] / 5 * 100)
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        rows.append([
            Paragraph(vn.replace("The ",""), S["td_l"]),
            Paragraph(str(int(row["n"])), S["td"]),
            Paragraph(f"{row['avg']:.2f}", S["td"]),
            Paragraph(str(int(row["five"])), S["td"]),
            Paragraph(str(int(row["low"])), S["td"]),
            Paragraph(f"<font face='Courier'>{bar}</font> {score}%", S["td_l"]),
        ])
    return _tbl(rows, [0.28,0.10,0.12,0.08,0.08,0.34])


# ── LAYOUT HELPERS ────────────────────────────────────────────────────────────

def _insight_box(text_lines, S):
    """Dark green callout box with key insights."""
    if not text_lines:
        return []
    items = "".join(f"<br/>• {t}" for t in text_lines)
    cell_para = Paragraph(f"<b>Key Findings</b>{items}", S["insight"])
    t = Table([[cell_para]], colWidths=[INNER_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#EEF5EE")),
        ("BOX",           (0,0),(-1,-1), 0.8, RL_MID),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
    ]))
    return [t, Spacer(1, 0.2*cm)]


def _kpi_row(items, S):
    """items = [(label, value, delta, positive?), ...]"""
    n = len(items)
    cells = []
    for label, val, delta, pos in items:
        delta_style = S["kpi_delta_pos"] if pos else S["kpi_delta_neg"]
        content = [
            Paragraph(str(val), S["kpi_val"]),
            Paragraph(str(label), S["kpi_lbl"]),
        ]
        if delta is not None:
            content.append(Paragraph(str(delta), delta_style))
        cells.append(content)
    t = Table([cells], colWidths=[INNER_W / n] * n)
    box_rules = [("BOX", (i,0),(i,0), 0.4, RL_GREY) for i in range(n)]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), RL_LGREY),
        ("TOPPADDING",    (0,0),(-1,-1), 7),
        ("BOTTOMPADDING", (0,0),(-1,-1), 7),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ] + box_rules))
    return t


def _section(title, S):
    return [
        Spacer(1, 0.25*cm),
        Paragraph(title, S["section"]),
        HRFlowable(width=INNER_W, thickness=1, color=RL_LIGHT, spaceAfter=4),
    ]


def _subsection(title, S):
    return Paragraph(title, S["subsection"])


def _side_by_side(left, right, ratio=0.5):
    """Place two flowables side-by-side."""
    if left is None and right is None:
        return None
    if left is None:
        return right
    if right is None:
        return left
    w_l = INNER_W * ratio
    w_r = INNER_W * (1 - ratio) - 4
    t = Table([[left, right]], colWidths=[w_l, w_r])
    t.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP")]))
    return t


# ── PAGE TEMPLATES ────────────────────────────────────────────────────────────

def _build_doc(buf, start_date, end_date):
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 0.5*cm,
    )

    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, id="cover",
                        leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0)

    def _cover_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(RL_GREEN)
        canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        canvas.restoreState()

    inner_frame = Frame(
        MARGIN, MARGIN + 0.75*cm,
        INNER_W, PAGE_H - 2*MARGIN - 1.6*cm,
        id="inner",
    )
    period_str = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"

    def _inner_pg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(RL_GREEN)
        canvas.rect(0, PAGE_H - 1.05*cm, PAGE_W, 1.05*cm, fill=1, stroke=0)
        canvas.setFillColor(RL_WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(MARGIN, PAGE_H - 0.7*cm, "chickpea.")
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.7*cm,
                               f"Performance Report  ·  {period_str}")
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(MARGIN, 0.5*cm, "Confidential — Chickpea Pub Group")
        canvas.drawRightString(PAGE_W - MARGIN, 0.5*cm, f"Page {doc.page - 1}")
        canvas.setStrokeColor(RL_LIGHT)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - 1.1*cm, PAGE_W - MARGIN, PAGE_H - 1.1*cm)
        canvas.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame], onPage=_cover_bg),
        PageTemplate(id="Inner", frames=[inner_frame], onPage=_inner_pg),
    ])
    return doc


# ── RECOMMENDATION ENGINE ────────────────────────────────────────────────────

def _build_recommendations(
    venue, v_conf, v_all, v_yoy, v_fb, v_rm,
    p_covers, p_covers_yoy, covers_pct, p_bookings,
    p_noshow, p_cancel, p_spc, p_rating, p_return,
    p_occ, p_occ_yoy, grp_noshow, grp_spc, grp_rating,
    grp_return, grp_occ, avg_spc, has_spend, has_rooms, days_cur,
):
    """
    Return a list of (priority, category, headline, detail) recommendation tuples
    for a single venue, based on its data vs group averages.
    Priority: 'urgent' | 'important' | 'opportunity'
    """
    recs = []
    vname = venue.replace("The ", "")

    # ── COVERS / REVENUE GROWTH ───────────────────────────────────────────────

    if p_covers_yoy > 0 and covers_pct < -10:
        lost = p_covers_yoy - p_covers
        recs.append(("urgent", "Sales", "Covers are declining",
            f"Covers are down {abs(covers_pct):.1f}% year-on-year ({lost:,} fewer covers). "
            f"Prioritise a targeted local marketing push — email past guests, promote on social, "
            f"and review whether pricing or menu changes may be driving the drop."))

    elif p_covers_yoy > 0 and covers_pct < -5:
        recs.append(("important", "Sales", "Covers softening vs prior year",
            f"Down {abs(covers_pct):.1f}% YoY. Consider a midweek offer or event series "
            f"to recover volume without discounting peak sessions."))

    # Quiet day identification
    if not v_conf.empty and "day_of_week" in v_conf.columns:
        dow = v_conf.groupby("day_of_week")["covers"].sum()
        if len(dow) >= 3:
            quietest = dow.idxmin()
            busiest  = dow.idxmax()
            quiet_n  = int(dow.min())
            busy_n   = int(dow.max())
            if busy_n > 0 and quiet_n / busy_n < 0.40:
                recs.append(("opportunity", "Marketing",
                    f"Drive {quietest} trade",
                    f"{quietest} averages just {quiet_n} covers vs {busy_n} on {busiest} — "
                    f"a {quietest} set menu, quiz night, or 'locals' offer would improve "
                    f"table utilisation on your quietest day."))

    # Dinner/lunch imbalance
    if not v_conf.empty and "meal_period" in v_conf.columns:
        mp = v_conf.groupby("meal_period")["covers"].sum()
        lunch  = int(mp.get("Lunch",   0))
        dinner = int(mp.get("Dinner",  0))
        if lunch > 0 and dinner > 0:
            if dinner / lunch < 0.5:
                recs.append(("important", "Marketing",
                    "Dinner trade is underdeveloped",
                    f"Lunch generates {lunch:,} covers vs only {dinner:,} at dinner — a ratio of "
                    f"{dinner/lunch:.1f}×. A dedicated dinner campaign (social ads, email, "
                    f"tasting menus, or pre-theatre set menu) could significantly lift evening revenue."))
            elif lunch / dinner < 0.4:
                recs.append(("opportunity", "Marketing",
                    "Lunch trade has room to grow",
                    f"Dinner leads strongly. A targeted lunch promotion "
                    f"(working lunch menu, loyalty card for regulars) could unlock "
                    f"incremental weekday revenue."))

    # Large party / private dining
    if not v_conf.empty and "covers" in v_conf.columns:
        large = v_conf[v_conf["covers"] >= 8]
        large_pct = len(large) / max(len(v_conf), 1) * 100
        if large_pct < 5 and p_bookings > 20:
            recs.append(("opportunity", "Sales",
                "Private dining / large party opportunity",
                f"Only {large_pct:.1f}% of bookings are parties of 8+. "
                f"A dedicated private dining package (set menu, drinks package, exclusive area) "
                f"would attract corporate and celebration bookings with higher average spend."))

    # ── NO-SHOWS & CANCELLATIONS ──────────────────────────────────────────────

    if p_noshow > grp_noshow * 1.5 and p_noshow > 4:
        est_lost = 0
        if has_spend and avg_spc > 0 and not v_all.empty:
            ns_covers = int(v_all[v_all["is_noshow"]]["covers"].sum())
            est_lost  = ns_covers * avg_spc
        detail = (
            f"No-show rate of {p_noshow:.1f}% is significantly above the group average of "
            f"{grp_noshow:.1f}%. "
        )
        if est_lost > 0:
            detail += f"Estimated revenue lost to no-shows: £{est_lost:,.0f}. "
        detail += (
            "Introduce a card-on-file or £10/head deposit for parties of 4+, "
            "and send automated SMS/email reminders 24 hours before."
        )
        recs.append(("urgent" if p_noshow > grp_noshow * 2 else "important",
                      "Operations", "High no-show rate — introduce deposit policy", detail))

    elif p_noshow > grp_noshow * 1.2 and p_noshow > 3:
        recs.append(("important", "Operations",
            "No-show rate above group average",
            f"At {p_noshow:.1f}% vs group avg {grp_noshow:.1f}%. "
            f"Automated day-before reminders via SevenRooms should be activated "
            f"for all future bookings."))

    if p_cancel > 15:
        recs.append(("important", "Operations",
            "Cancellation rate needs attention",
            f"Cancellation rate of {p_cancel:.1f}%. Introduce a 48-hour cancellation policy "
            f"with automated reminders at 72 and 24 hours. Consider a short waitlist "
            f"to backfill cancellations on busy sessions."))

    # ── SPEND / UPSELLING ─────────────────────────────────────────────────────

    if has_spend and grp_spc > 0 and p_spc > 0:
        if p_spc < grp_spc * 0.85:
            gap    = grp_spc - p_spc
            uplift = gap * p_covers
            recs.append(("important", "Revenue",
                "Spend per cover below group average — upsell opportunity",
                f"Average spend of £{p_spc:.2f}/cover is £{gap:.2f} below the group average "
                f"of £{grp_spc:.2f}. Closing that gap would generate an estimated "
                f"£{uplift:,.0f} additional revenue over this period. "
                f"Focus on drinks upselling, pre-dessert prompts, and staff training on "
                f"suggestive selling."))

        elif p_spc > grp_spc * 1.15:
            recs.append(("opportunity", "Revenue",
                "Strong spend per cover — protect and grow",
                f"At £{p_spc:.2f}/cover, {vname} leads the group (avg £{grp_spc:.2f}). "
                f"Analyse what's driving this — menu mix, portion pricing, or upsell culture — "
                f"and share learnings with lower-performing venues."))

    # ── GUEST REVIEWS / RATING ────────────────────────────────────────────────

    if p_rating is not None:
        if p_rating < 3.5:
            low_comments = []
            if not v_fb.empty and "rating" in v_fb.columns:
                comment_col = next((c for c in ["notes","comment","comments","feedback"]
                                    if c in v_fb.columns), None)
                low_fb = v_fb[v_fb["rating"] <= 2]
                if comment_col and not low_fb.empty:
                    sample = low_fb[comment_col].dropna().head(2).tolist()
                    low_comments = [str(s)[:120] for s in sample if str(s).strip()]
            detail = (
                f"Average rating of {p_rating:.2f}★ is below acceptable threshold. "
                f"This needs immediate attention — review low-rating comments, speak to the "
                f"management team, and conduct a service audit."
            )
            if low_comments:
                detail += " Recent feedback: " + " / ".join(f'"{c}"' for c in low_comments)
            recs.append(("urgent", "Guest Experience", "Rating critically low", detail))

        elif p_rating < 4.0:
            recs.append(("important", "Guest Experience",
                "Rating below 4.0 — service focus required",
                f"Average rating of {p_rating:.2f}★ is below the 4.0 benchmark. "
                f"Review the most recent low-rating feedback, introduce a post-visit "
                f"follow-up email via SevenRooms, and brief front-of-house on common complaint themes."))

        elif grp_rating and p_rating < grp_rating - 0.2:
            recs.append(("important", "Guest Experience",
                "Rating below group average",
                f"{p_rating:.2f}★ vs group average {grp_rating:.2f}★. "
                f"Proactively solicit feedback during service to catch dissatisfied guests "
                f"before they leave a public review."))

        elif p_rating >= 4.5:
            recs.append(("opportunity", "Marketing",
                "Excellent rating — leverage for marketing",
                f"A {p_rating:.2f}★ average is exceptional. "
                f"Use this in local press, social media, and targeted Google Ads. "
                f"Ask happy guests to leave a Google review — it directly drives organic bookings."))

    # ── GUEST LOYALTY / RETENTION ─────────────────────────────────────────────

    if p_return is not None:
        if p_return < 15:
            recs.append(("urgent" if p_return < 10 else "important",
                "Marketing", "Low returning guest rate — retention campaign needed",
                f"Only {p_return:.0f}% of bookings are from returning guests — "
                f"well below the group average{f' of {grp_return:.0f}%' if grp_return else ''}. "
                f"Launch a re-engagement email campaign targeting guests who visited 3–12 months ago "
                f"but haven't returned. A 'welcome back' offer (free drink, fixed-price menu) "
                f"typically converts 8–15% of lapsed guests."))

        elif grp_return and p_return < grp_return - 10:
            recs.append(("important", "Marketing",
                "Returning guest rate below group average",
                f"{p_return:.0f}% vs group average {grp_return:.0f}%. "
                f"Review post-visit comms — ensure all guests receive a thank-you email "
                f"within 24 hours and are added to the newsletter list in SevenRooms."))

    # Booking channel — check if capturing source
    if not v_conf.empty and "booking_channel" in v_conf.columns:
        unknown_ch = (v_conf["booking_channel"] == "Unknown").mean() * 100
        if unknown_ch > 30:
            recs.append(("important", "Operations",
                "Booking channel not being recorded",
                f"{unknown_ch:.0f}% of bookings have no channel recorded. "
                f"Brief the reservations team to select booking source in SevenRooms for every booking — "
                f"this data is essential for understanding where marketing investment is working."))

    # ── ROOMS ─────────────────────────────────────────────────────────────────

    if has_rooms:
        if p_occ < grp_occ - 10 and p_occ < 60:
            recs.append(("urgent" if p_occ < 40 else "important",
                "Rooms", f"Room occupancy below group average",
                f"Occupancy of {p_occ:.1f}% is {grp_occ - p_occ:.1f}pp below the group average "
                f"of {grp_occ:.1f}%. Consider: a 'stay and dine' package with the restaurant, "
                f"last-minute rate promotions via Eviivo for 7-day out availability, and "
                f"reviewing your Booking.com listing quality (photos, description, review response)."))

        elif p_occ_yoy > 0 and p_occ < p_occ_yoy - 8:
            recs.append(("important", "Rooms",
                "Room occupancy declined year-on-year",
                f"Occupancy is down {p_occ_yoy - p_occ:.1f}pp vs prior year. "
                f"Review whether a rate increase may have suppressed demand, "
                f"and check Eviivo for any distribution gaps (missing OTA channels, "
                f"outdated availability calendars)."))

        if not v_rm.empty and "booking_channel" in v_rm.columns:
            ota_pct_v = v_rm[v_rm["is_ota"]]["revenue"].sum() / max(v_rm["revenue"].sum(), 1) * 100
            if ota_pct_v > 50:
                comm_v = v_rm["ota_commission_cost"].sum()
                recs.append(("important", "Rooms",
                    "High OTA dependency — drive direct bookings",
                    f"{ota_pct_v:.0f}% of room revenue comes via OTA channels "
                    f"(est. £{comm_v:,.0f} in commission this period). "
                    f"Add a 'book direct for best rate' message to all guest comms, "
                    f"create a direct-only rate or perk in Eviivo, and promote direct "
                    f"booking via the website and email list."))

        if not v_rm.empty:
            avg_los = v_rm["nights"].mean()
            if avg_los < 1.3:
                recs.append(("opportunity", "Rooms",
                    "Short length of stay — promote multi-night packages",
                    f"Average length of stay is {avg_los:.1f} nights. "
                    f"A 2-night 'escape' package (dinner, breakfast, late checkout) "
                    f"would increase revenue per booking and reduce changeover costs."))

    # ── SOCIAL / OCCASIONS ────────────────────────────────────────────────────

    if not v_conf.empty and "occasion" in v_conf.columns:
        occ_data = v_conf[v_conf["occasion"].str.len() > 0]["occasion"].value_counts()
        if not occ_data.empty:
            top_occ = occ_data.index[0]
            top_n   = int(occ_data.iloc[0])
            if top_n >= 3:
                recs.append(("opportunity", "Marketing",
                    f"Capitalise on '{top_occ}' bookings",
                    f"{top_n} '{top_occ}' bookings in this period. "
                    f"Create a targeted offer or package for this occasion "
                    f"(e.g. a birthday/anniversary menu, complimentary cake, or "
                    f"dedicated social media content) to attract more of the same."))

    # Sort: urgent first, then important, then opportunity
    order = {"urgent": 0, "important": 1, "opportunity": 2}
    recs.sort(key=lambda r: order.get(r[0], 3))
    return recs


# ── MAIN GENERATOR ────────────────────────────────────────────────────────────

def generate_pdf(start_date, end_date, progress_callback=None):
    def _p(f, m):
        print(f"[{int(f*100):3d}%] {m}")
        if progress_callback: progress_callback(f, m)

    # ── FETCH ─────────────────────────────────────────────────────────────────
    raw = _fetch_data(start_date, end_date, progress=_p)

    _p(0.55, "Processing data…")
    venue_map   = {v["id"]: v["name"].strip() for v in raw["venues"]}
    df_all      = _process_reservations(raw["reservations_cur"], venue_map)
    df_all_yoy  = _process_reservations(raw["reservations_yoy"], venue_map)
    df_conf     = df_all[df_all["is_confirmed"]]    if not df_all.empty     else df_all
    df_conf_yoy = df_all_yoy[df_all_yoy["is_confirmed"]] if not df_all_yoy.empty else df_all_yoy
    df_rooms    = _process_rooms(raw["rooms_cur"])
    df_rooms_yoy= _process_rooms(raw["rooms_yoy"])

    df_fb = pd.DataFrame(raw["feedback"]) if raw["feedback"] else pd.DataFrame()
    rating_col = next((c for c in ["overall","overall_rating","rating","stars","score"]
                       if c in df_fb.columns), None)
    if rating_col and not df_fb.empty:
        df_fb["rating"] = pd.to_numeric(df_fb[rating_col], errors="coerce")
        df_fb = df_fb.dropna(subset=["rating"])
        if "venue_id" in df_fb.columns:
            df_fb["venue_name"] = df_fb["venue_id"].map(venue_map).fillna("Unknown")

    # ── KPIs ──────────────────────────────────────────────────────────────────
    days_cur = (end_date - start_date).days + 1
    days_yoy = days_cur
    yoy_start = raw["yoy_start"]
    yoy_end   = raw["yoy_end"]

    covers_cur  = int(df_conf["covers"].sum())     if not df_conf.empty     else 0
    covers_yoy  = int(df_conf_yoy["covers"].sum()) if not df_conf_yoy.empty else 0
    bookings_cur = len(df_conf)
    bookings_yoy = len(df_conf_yoy)
    avg_party    = df_conf["covers"].mean() if not df_conf.empty and len(df_conf) else 0

    ns_rate  = df_all["is_noshow"].mean()    * 100 if not df_all.empty else 0
    can_rate = df_all["is_cancelled"].mean() * 100 if not df_all.empty else 0

    has_spend     = not df_conf.empty and "total_spend" in df_conf.columns and df_conf["total_spend"].sum() > 0
    total_spend   = df_conf["total_spend"].sum() if has_spend else 0
    avg_spc       = df_conf.loc[df_conf["spend_per_cover"] > 0, "spend_per_cover"].mean() if has_spend else 0
    spend_yoy     = df_conf_yoy["total_spend"].sum() if not df_conf_yoy.empty and "total_spend" in df_conf_yoy.columns else 0

    nights_cur  = int(df_rooms["nights"].sum())     if not df_rooms.empty     else 0
    nights_yoy  = int(df_rooms_yoy["nights"].sum()) if not df_rooms_yoy.empty else 0
    avail_cur   = TOTAL_ROOMS * days_cur
    avail_yoy   = TOTAL_ROOMS * days_yoy
    occ_cur     = nights_cur  / avail_cur  * 100 if avail_cur  else 0
    occ_yoy     = nights_yoy  / avail_yoy  * 100 if avail_yoy  else 0
    rev_cur     = df_rooms["revenue"].sum()     if not df_rooms.empty     else 0
    rev_yoy     = df_rooms_yoy["revenue"].sum() if not df_rooms_yoy.empty else 0
    adr         = rev_cur / nights_cur  if nights_cur  else 0
    adr_yoy     = rev_yoy / nights_yoy  if nights_yoy  else 0
    revpar      = rev_cur / avail_cur   if avail_cur   else 0
    revpar_yoy  = rev_yoy / avail_yoy   if avail_yoy   else 0

    avg_rating    = df_fb["rating"].mean()  if not df_fb.empty and "rating" in df_fb.columns else None
    total_reviews = len(df_fb)

    # Estimated lost revenue from no-shows
    lost_rev = 0
    if has_spend and avg_spc > 0 and not df_all.empty:
        ns_bookings = df_all[df_all["is_noshow"]]["covers"].sum()
        lost_rev = ns_bookings * avg_spc

    _p(0.65, "Building charts…")
    S = _styles()

    # ── INSIGHTS ──────────────────────────────────────────────────────────────
    ins_res  = _insights_reservations(df_conf, df_conf_yoy, has_spend)
    ins_rooms = _insights_rooms(df_rooms, df_rooms_yoy, days_cur, days_yoy)

    # ── ALL CHARTS ────────────────────────────────────────────────────────────
    _p(0.70, "Rendering charts…")
    ch_yoy      = chart_yoy_weekly(df_conf, df_conf_yoy, INNER_W)
    ch_venue    = chart_venue_grouped(df_conf, df_conf_yoy, INNER_W)
    ch_spc_v    = chart_spend_per_cover_venue(df_conf, INNER_W * 0.48)
    ch_spc_s    = chart_spend_per_cover_shift(df_conf, INNER_W * 0.48)
    ch_spc_t    = chart_spend_trend(df_conf, INNER_W)
    ch_ns       = chart_noshow_venue(df_all, INNER_W * 0.48)
    ch_lead     = chart_lead_time(df_conf, INNER_W * 0.48)
    ch_dow      = chart_day_of_week(df_conf, INNER_W * 0.48)
    ch_heat     = chart_heatmap(df_conf, INNER_W)
    ch_rm_mo    = chart_room_monthly(df_rooms, df_rooms_yoy, INNER_W)
    ch_rm_occ   = chart_room_occupancy_property(df_rooms, days_cur, INNER_W * 0.48)
    ch_rm_los   = chart_los_distribution(df_rooms, INNER_W * 0.48)
    ch_rm_wknd  = chart_weekend_weekday_rooms(df_rooms, days_cur, INNER_W * 0.48)
    ch_rt_dist  = chart_rating_dist(df_fb, INNER_W * 0.48)
    ch_rt_ven   = chart_rating_venue(df_fb, INNER_W * 0.48)
    ch_rt_trend = chart_rating_trend(df_fb, INNER_W)

    _p(0.82, "Assembling PDF…")

    # ── BUILD ELEMENTS ────────────────────────────────────────────────────────
    E = []   # elements list

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 1 — COVER
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(Spacer(1, 3.5*cm))
    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=5*cm, height=5*cm, kind="proportional")
        logo.hAlign = "CENTER"
        E.append(logo)
        E.append(Spacer(1, 1.0*cm))
    E.append(Paragraph("Performance Report", S["cover_title"]))
    E.append(Spacer(1, 0.35*cm))
    E.append(Paragraph(
        f"{start_date.strftime('%d %B %Y')} – {end_date.strftime('%d %B %Y')}",
        S["cover_sub"],
    ))
    E.append(Spacer(1, 0.25*cm))
    E.append(Paragraph(
        f"Year-on-year comparison: {yoy_start.strftime('%d %b %Y')} – {yoy_end.strftime('%d %b %Y')}",
        S["cover_date"],
    ))
    E.append(Spacer(1, 5.5*cm))
    E.append(Paragraph(
        f"Generated {date.today().strftime('%d %B %Y')}  ·  Strictly Confidential",
        S["cover_date"],
    ))
    E.append(NextPageTemplate("Inner"))
    E.append(PageBreak())

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 2 — EXECUTIVE SUMMARY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E += _section("Executive Summary", S)
    E.append(Paragraph(
        f"<b>Reporting period:</b> {start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}  ({days_cur} days)  ·  "
        f"<b>Prior year:</b> {yoy_start.strftime('%d %b %Y')} to {yoy_end.strftime('%d %b %Y')}",
        S["body"],
    ))
    E.append(Spacer(1, 0.2*cm))

    E.append(_kpi_row([
        ("Total Covers",      f"{covers_cur:,}",    f"{covers_cur - covers_yoy:+,} vs prior year", covers_cur >= covers_yoy),
        ("Table Bookings",    f"{bookings_cur:,}",   f"{bookings_cur - bookings_yoy:+,} vs prior year", bookings_cur >= bookings_yoy),
        ("Avg Party Size",    f"{avg_party:.1f}",    None, True),
        ("No-show Rate",      f"{ns_rate:.1f}%",     None, ns_rate < 5),
        ("Cancellation Rate", f"{can_rate:.1f}%",    None, can_rate < 10),
    ], S))
    E.append(Spacer(1, 0.2*cm))
    E.append(_kpi_row([
        ("Room Occupancy",   f"{occ_cur:.1f}%",     f"{occ_cur - occ_yoy:+.1f}pp vs prior year", occ_cur >= occ_yoy),
        ("ADR",              f"£{adr:,.0f}",          f"£{adr - adr_yoy:+.0f} vs prior year", adr >= adr_yoy),
        ("RevPAR",           f"£{revpar:.2f}",        f"£{revpar - revpar_yoy:+.2f} vs prior year", revpar >= revpar_yoy),
        ("Room Nights Sold", f"{nights_cur:,}",      f"{nights_cur - nights_yoy:+,} vs prior year", nights_cur >= nights_yoy),
        ("Avg Guest Rating", f"{avg_rating:.2f}★" if avg_rating else "—", f"{total_reviews} reviews", (avg_rating or 0) >= 4.0),
    ], S))

    if has_spend:
        E.append(Spacer(1, 0.2*cm))
        E.append(_kpi_row([
            ("Total F&B Revenue",         f"£{total_spend:,.0f}",      f"£{total_spend - spend_yoy:+,.0f} vs prior year", total_spend >= spend_yoy),
            ("Avg Spend per Cover",        f"£{avg_spc:.2f}",           None, True),
            ("Est. Lost Revenue (no-shows)", f"£{lost_rev:,.0f}",      "Based on avg spend/cover", False),
            ("Room Revenue",               f"£{rev_cur:,.0f}",          f"£{rev_cur - rev_yoy:+,.0f} vs prior year", rev_cur >= rev_yoy),
            ("Combined Revenue",           f"£{total_spend + rev_cur:,.0f}", None, True),
        ], S))

    if raw["errors"]:
        E.append(Spacer(1, 0.15*cm))
        for err in raw["errors"]:
            E.append(Paragraph(f"⚠ {err}", S["note"]))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 3 — TABLE RESERVATIONS + F&B SPEND
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section("Table Reservations", S)
    E += _insight_box(ins_res, S)

    E.append(_subsection("Weekly Covers — Current Year vs Prior Year", S))
    E.append(Spacer(1, 0.1*cm))
    if ch_yoy: E.append(ch_yoy)
    E.append(Spacer(1, 0.2*cm))

    E.append(_subsection("Covers by Pub", S))
    E.append(Spacer(1, 0.1*cm))
    if ch_venue: E.append(ch_venue)
    E.append(Spacer(1, 0.15*cm))

    tbl_v = tbl_venue_reservations(df_all, df_all_yoy, has_spend, S)
    if tbl_v:
        E.append(tbl_v)
        E.append(Paragraph(
            "Table includes all booking statuses. No-shows and cancellations shown separately.",
            S["note"],
        ))

    # F&B spend — folded in, no page break
    if has_spend:
        E.append(Spacer(1, 0.25*cm))
        E += _section("F&B Revenue (Tevalis via SevenRooms)", S)

        spend_ins = []
        if avg_spc > 0:
            spend_ins.append(f"Group average spend per cover: <b>£{avg_spc:.2f}</b>.")
        if lost_rev > 0:
            spend_ins.append(
                f"Estimated revenue lost to no-shows: <b>£{lost_rev:,.0f}</b> "
                f"({int(df_all['is_noshow'].sum())} no-shows × avg £{avg_spc:.2f}/cover)."
            )
        E += _insight_box(spend_ins, S)

        side_spc = _side_by_side(ch_spc_v, ch_spc_s)
        if side_spc:
            E.append(_subsection("Spend per Cover — by Pub & by Shift", S))
            E.append(Spacer(1, 0.1*cm))
            E.append(side_spc)
        if ch_spc_t:
            E.append(Spacer(1, 0.15*cm))
            E.append(_subsection("Monthly F&B Revenue & Spend per Cover Trend", S))
            E.append(Spacer(1, 0.1*cm))
            E.append(ch_spc_t)
    else:
        E.append(Spacer(1, 0.15*cm))
        E.append(Paragraph(
            "F&B revenue data not returned by SevenRooms for this period. "
            "Confirm in SevenRooms Settings → Integrations that Tevalis spend sync is enabled.",
            S["note"],
        ))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 4 — BOOKING PATTERNS · GUEST LOYALTY · BOOKING SOURCES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section("Booking Patterns & Guest Intelligence", S)

    # No-show/cancellation + day-of-week (side by side)
    E.append(_subsection("No-show & Cancellation Rates by Pub", S))
    E.append(Spacer(1, 0.1*cm))
    side_ns = _side_by_side(ch_ns, ch_dow)
    if side_ns:
        E.append(side_ns)
    elif ch_ns:
        E.append(ch_ns)
    E.append(Spacer(1, 0.15*cm))

    # Lead time — mention median in text only; no table
    if not df_conf.empty and "lead_days" in df_conf.columns:
        med_lead = df_conf["lead_days"].median()
        same_day = (df_conf["lead_days"] == 0).sum()
        same_day_pct = same_day / max(len(df_conf), 1) * 100
        E.append(Paragraph(
            f"<b>Booking lead time:</b> median <b>{med_lead:.0f} days</b> in advance. "
            f"{same_day_pct:.0f}% of bookings are made same-day.",
            S["body"],
        ))
        E.append(Spacer(1, 0.1*cm))

    # Guest loyalty
    has_loyalty = not df_conf.empty and "is_returning" in df_conf.columns
    has_channel = not df_conf.empty and "booking_channel" in df_conf.columns

    E.append(_subsection("Guest Loyalty — New vs Returning", S))
    if has_loyalty:
        ret_count  = int(df_conf["is_returning"].sum())
        new_count  = int((~df_conf["is_returning"]).sum())
        ret_pct    = ret_count / max(len(df_conf), 1) * 100
        ret_covers = int(df_conf[df_conf["is_returning"]]["covers"].sum())
        new_covers = int(df_conf[~df_conf["is_returning"]]["covers"].sum())

        loyalty_ins = [
            f"<b>{ret_pct:.0f}%</b> of bookings are from returning guests "
            f"({ret_count:,} bookings, {ret_covers:,} covers)."
        ]
        if ret_pct < 30:
            loyalty_ins.append(
                "Return rate below 30% — prioritise retention through follow-up comms "
                "and personalised service."
            )
        elif ret_pct > 50:
            loyalty_ins.append("Return rate above 50% — strong loyal base. Focus on converting new guests to regulars.")
        if has_spend and "spend_per_cover" in df_conf.columns:
            ret_spc = df_conf[(df_conf["is_returning"]) & (df_conf["spend_per_cover"] > 0)]["spend_per_cover"].mean()
            new_spc = df_conf[(~df_conf["is_returning"]) & (df_conf["spend_per_cover"] > 0)]["spend_per_cover"].mean()
            if ret_spc > 0 and new_spc > 0:
                loyalty_ins.append(
                    f"Returning guests spend <b>£{ret_spc:.2f}/cover</b> vs "
                    f"<b>£{new_spc:.2f}/cover</b> for new guests."
                )
        E += _insight_box(loyalty_ins, S)

        E.append(_kpi_row([
            ("Returning Guests", f"{ret_pct:.0f}%",         f"{ret_count:,} bookings", ret_pct >= 30),
            ("New Guests",       f"{100 - ret_pct:.0f}%",   f"{new_count:,} bookings", True),
            ("Returning Covers", f"{ret_covers:,}",         None, True),
            ("New Guest Covers", f"{new_covers:,}",         None, True),
        ], S))
        E.append(Spacer(1, 0.15*cm))

        ch_loyalty = chart_new_vs_returning(df_conf, INNER_W * 0.48)
        ch_tiers   = chart_guest_tiers(df_conf, INNER_W * 0.48)
        side_loy   = _side_by_side(ch_loyalty, ch_tiers)
        if side_loy:
            E.append(side_loy)

        # Compact per-pub return rate table
        if "venue_name" in df_conf.columns:
            E.append(Spacer(1, 0.15*cm))
            v_loyalty = df_conf.groupby("venue_name").agg(
                total=("is_returning", "count"),
                returning=("is_returning", "sum"),
            ).reset_index()
            v_loyalty["ret_pct"] = (v_loyalty["returning"] / v_loyalty["total"] * 100).round(1)
            v_loyalty = v_loyalty.sort_values("ret_pct", ascending=False)
            loy_rows = [[Paragraph(h, S["th"]) for h in
                         ["Pub", "Bookings", "Returning", "New", "Return Rate"]]]
            for _, r in v_loyalty.iterrows():
                rate_col = C_GREEN if r["ret_pct"] >= 30 else C_AMBER if r["ret_pct"] >= 15 else C_RED
                loy_rows.append([
                    Paragraph(str(r["venue_name"]).replace("The ", ""), S["td_l"]),
                    Paragraph(f"{int(r['total']):,}", S["td"]),
                    Paragraph(f"{int(r['returning']):,}", S["td"]),
                    Paragraph(f"{int(r['total'] - r['returning']):,}", S["td"]),
                    Paragraph(f'<font color="{rate_col}"><b>{r["ret_pct"]:.1f}%</b></font>', S["td"]),
                ])
            E.append(_tbl(loy_rows, [0.30, 0.17, 0.17, 0.17, 0.19]))
    else:
        E.append(Paragraph(
            "Guest loyalty data not available — visit_count not present in SevenRooms records.",
            S["note"],
        ))

    # Booking source breakdown
    E.append(Spacer(1, 0.2*cm))
    E.append(_subsection("Table Booking Source Breakdown", S))
    if has_channel:
        ch_data = df_conf.groupby("booking_channel").agg(
            bookings=("covers", "count"),
            covers=("covers", "sum"),
        ).sort_values("bookings", ascending=False)

        channel_ins = []
        if not ch_data.empty:
            top_ch  = ch_data.index[0]
            top_pct = ch_data.iloc[0]["bookings"] / len(df_conf) * 100
            channel_ins.append(
                f"<b>{top_ch}</b> is the leading booking channel "
                f"(<b>{top_pct:.0f}%</b> of table bookings)."
            )
            unknown_pct = ch_data.loc["Unknown", "bookings"] / len(df_conf) * 100 \
                if "Unknown" in ch_data.index else 0
            if unknown_pct > 20:
                channel_ins.append(
                    f"<b>{unknown_pct:.0f}%</b> of bookings have no channel recorded — "
                    "ensure staff select source at time of booking in SevenRooms."
                )
        E += _insight_box(channel_ins, S)

        ch_src = chart_booking_source(df_conf, INNER_W * 0.45)
        src_rows = [[Paragraph(h, S["th"]) for h in
                     ["Channel", "Bookings", "%", "Covers", "%"]]]
        for ch_name, row in ch_data.iterrows():
            src_rows.append([
                Paragraph(str(ch_name), S["td_l"]),
                Paragraph(f"{int(row['bookings']):,}", S["td"]),
                Paragraph(f"{row['bookings']/len(df_conf)*100:.0f}%", S["td"]),
                Paragraph(f"{int(row['covers']):,}", S["td"]),
                Paragraph(f"{row['covers']/df_conf['covers'].sum()*100:.0f}%", S["td"]),
            ])
        src_tbl = _tbl(src_rows, [0.36, 0.16, 0.16, 0.16, 0.16])
        side_src = _side_by_side(ch_src, src_tbl, ratio=0.40) if ch_src else None
        if side_src:
            E.append(side_src)
        else:
            E.append(src_tbl)
    else:
        E.append(Paragraph(
            "Booking channel data not available — ensure 'Booking Source' is captured in SevenRooms.",
            S["note"],
        ))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 5 — ROOM OCCUPANCY + CHANNEL MIX
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section("Room Occupancy & Channel Mix (Eviivo)", S)
    E.append(Paragraph(
        f"7 properties · <b>{TOTAL_ROOMS} rooms</b> total · "
        f"{avail_cur:,} available room nights in period.",
        S["body"],
    ))
    E += _insight_box(ins_rooms, S)

    if df_rooms.empty:
        E.append(Paragraph(
            "No Eviivo room data returned. Check credentials and property short names.",
            S["note"],
        ))
    else:
        E.append(_subsection("Room Nights Sold per Month — Current Year vs Prior Year", S))
        E.append(Spacer(1, 0.1*cm))
        if ch_rm_mo: E.append(ch_rm_mo)
        E.append(Spacer(1, 0.15*cm))

        side_rm = _side_by_side(ch_rm_occ, ch_rm_los)
        if side_rm:
            E.append(_subsection("Occupancy % by Property & Length of Stay", S))
            E.append(Spacer(1, 0.1*cm))
            E.append(side_rm)
        E.append(Spacer(1, 0.15*cm))

        tbl_r = tbl_rooms_property(df_rooms, df_rooms_yoy, days_cur, days_yoy, S)
        if tbl_r:
            E.append(tbl_r)
            E.append(Paragraph(
                "YoY Occ = occupancy % change vs same period prior year (pp). "
                "ADR = Average Daily Rate. RevPAR = Revenue per Available Room Night.",
                S["note"],
            ))

        # OTA vs Direct — inline KPIs + compact table (no bar chart)
        E.append(Spacer(1, 0.2*cm))
        E.append(_subsection("OTA vs Direct Channel Mix", S))

        ch_room_data = df_rooms.groupby("booking_channel").agg(
            bookings=("revenue", "count"),
            nights=("nights", "sum"),
            gross_rev=("revenue", "sum"),
            commission=("ota_commission_cost", "sum"),
            net_rev=("net_revenue", "sum"),
        ).sort_values("gross_rev", ascending=False)

        total_gross = df_rooms["revenue"].sum()
        total_comm  = df_rooms["ota_commission_cost"].sum()
        total_net   = df_rooms["net_revenue"].sum()
        ota_rev     = df_rooms[df_rooms["is_ota"]]["revenue"].sum()
        direct_rev  = df_rooms[df_rooms["is_direct"]]["revenue"].sum()
        ota_pct     = ota_rev / total_gross * 100 if total_gross else 0

        room_ch_ins = []
        if total_comm > 0:
            room_ch_ins.append(
                f"Estimated OTA commission cost: <b>£{total_comm:,.0f}</b> "
                f"(~15% on £{ota_rev:,.0f} OTA revenue). "
                f"Net room revenue: <b>£{total_net:,.0f}</b>."
            )
        if ota_pct > 40:
            room_ch_ins.append(
                f"<b>{ota_pct:.0f}%</b> of room revenue is OTA — direct booking incentives "
                "would materially improve margins."
            )
        elif ota_pct > 0:
            room_ch_ins.append(
                f"OTA: <b>{ota_pct:.0f}%</b> of room revenue. "
                f"Direct: <b>{direct_rev/total_gross*100:.0f}%</b>."
            )
        else:
            room_ch_ins.append(
                "Booking channel not populated in Eviivo — commission estimates unavailable."
            )
        E += _insight_box(room_ch_ins, S)

        E.append(_kpi_row([
            ("Gross Room Revenue",  f"£{total_gross:,.0f}", None, True),
            ("Est. OTA Commission", f"£{total_comm:,.0f}",  "~15% on OTA bookings", False),
            ("Net Room Revenue",    f"£{total_net:,.0f}",   "After est. commission", True),
            ("OTA Revenue Share",   f"{ota_pct:.0f}%",      None, ota_pct < 40),
        ], S))

        if not ch_room_data.empty:
            E.append(Spacer(1, 0.15*cm))
            rm_ch_rows = [[Paragraph(h, S["th"]) for h in
                           ["Channel", "Bookings", "Nights", "Gross Rev",
                            "Est. Commission", "Net Rev", "ADR (Net)"]]]
            for ch_name, row in ch_room_data.iterrows():
                adr_net = row["net_rev"] / max(row["nights"], 1)
                rm_ch_rows.append([
                    Paragraph(str(ch_name), S["td_l"]),
                    Paragraph(f"{int(row['bookings']):,}", S["td"]),
                    Paragraph(f"{int(row['nights']):,}", S["td"]),
                    Paragraph(f"£{row['gross_rev']:,.0f}", S["td"]),
                    Paragraph(f"£{row['commission']:,.0f}", S["td"]),
                    Paragraph(f"£{row['net_rev']:,.0f}", S["td"]),
                    Paragraph(f"£{adr_net:,.0f}", S["td"]),
                ])
            E.append(_tbl(rm_ch_rows, [0.18, 0.12, 0.11, 0.15, 0.16, 0.15, 0.13]))
            E.append(Paragraph(
                "Commission estimated at 15% on OTA bookings. Verify against your OTA contracts.",
                S["note"],
            ))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 6 — GUEST REVIEWS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section("Guest Reviews", S)

    if df_fb.empty or "rating" not in df_fb.columns or len(df_fb) == 0:
        E.append(Paragraph("No SevenRooms feedback data returned for this period.", S["note"]))
    else:
        five_star = int((df_fb["rating"] == 5).sum())
        low_star  = int((df_fb["rating"] <= 2).sum())

        review_ins = []
        if avg_rating:
            benchmark = "above" if avg_rating >= 4.5 else ("meeting" if avg_rating >= 4.0 else "below")
            review_ins.append(
                f"Overall average rating: <b>{avg_rating:.2f}/5</b> across {total_reviews} reviews — "
                f"<b>{benchmark}</b> the 4.0 hospitality benchmark."
            )
        if low_star > 0:
            review_ins.append(
                f"<b>{low_star}</b> low rating(s) ≤2★ require follow-up — see comments below."
            )
        E += _insight_box(review_ins, S)

        E.append(_kpi_row([
            ("Avg Rating",      f"{avg_rating:.2f}★" if avg_rating else "—",
             f"{total_reviews} reviews", (avg_rating or 0) >= 4.0),
            ("5-Star Reviews",  str(five_star),
             f"{five_star/total_reviews*100:.0f}% of total", True),
            ("Low Ratings ≤2★", str(low_star),
             f"{low_star/total_reviews*100:.0f}% of total", low_star == 0),
        ], S))
        E.append(Spacer(1, 0.15*cm))

        side_rt = _side_by_side(ch_rt_dist, ch_rt_ven)
        if side_rt:
            E.append(_subsection("Rating Distribution & Average by Pub", S))
            E.append(Spacer(1, 0.1*cm))
            E.append(side_rt)
        E.append(Spacer(1, 0.15*cm))

        fb_tbl = tbl_feedback(df_fb, S)
        if fb_tbl:
            E.append(_subsection("Feedback Summary by Pub", S))
            E.append(Spacer(1, 0.1*cm))
            E.append(fb_tbl)

        low_df = df_fb[df_fb["rating"] <= 2].copy()
        if not low_df.empty:
            E.append(Spacer(1, 0.2*cm))
            E.append(_subsection("Low-rating Feedback (≤2★) — Action Required", S))
            E.append(Spacer(1, 0.1*cm))
            comment_col = next((c for c in ["notes","comment","comments","feedback","additional_notes"]
                                if c in low_df.columns), None)
            date_col    = next((c for c in ["reservation_date","date","created"] if c in low_df.columns), None)
            lr_rows = [[Paragraph(h, S["th"]) for h in ["Pub","Rating","Date","Comment"]]]
            for _, r in low_df.sort_values("rating").iterrows():
                comment = ""
                if comment_col and str(r.get(comment_col,"")) not in ("","nan"):
                    comment = str(r[comment_col])[:200] + ("…" if len(str(r[comment_col])) > 200 else "")
                dt_str = str(r.get(date_col,"—"))[:10] if date_col else "—"
                lr_rows.append([
                    Paragraph(str(r.get("venue_name","—")).replace("The ",""), S["td_l"]),
                    Paragraph(f"{r['rating']:.0f}★", S["td"]),
                    Paragraph(dt_str, S["td"]),
                    Paragraph(comment or "—", S["td_l"]),
                ])
            E.append(_tbl(lr_rows, [0.20, 0.09, 0.12, 0.59]))

    # Methodology footnote (replaces standalone page)
    E.append(Spacer(1, 0.3*cm))
    E.append(Paragraph(
        f"<i>Data sources: SevenRooms API v2.4 (reservations, spend, reviews) · "
        f"Eviivo PMS API (rooms). Room counts: "
        + ", ".join(f"{k.replace('The ','')} ({v})" for k,v in ROOM_COUNTS.items())
        + f". OTA commission estimated at 15%. "
        f"YoY = {yoy_start.strftime('%d %b %Y')} – {yoy_end.strftime('%d %b %Y')}. "
        f"Generated {datetime.now().strftime('%d %b %Y at %H:%M')}.</i>",
        S["note"],
    ))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 7+ — PER-PUB RECOMMENDATIONS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    E.append(PageBreak())
    E += _section("Recommendations by Pub", S)
    E.append(Paragraph(
        "Data-driven marketing and sales recommendations benchmarked against group averages. "
        "Priority: 🔴 Urgent · 🟡 Important · 🟢 Opportunity.",
        S["body"],
    ))
    E.append(Spacer(1, 0.2*cm))

    venue_names = sorted([v for v in df_conf["venue_name"].unique()
                          if v and v != "Unknown"]) if not df_conf.empty else []
    if not venue_names:
        E.append(Paragraph("No venue data available for recommendations.", S["note"]))
    else:
        def _safe_mean(series):
            v = pd.to_numeric(series, errors="coerce").dropna()
            return float(v.mean()) if len(v) else 0.0

        grp_noshow_rate = df_all["is_noshow"].mean() * 100    if not df_all.empty else 0
        grp_cancel_rate = df_all["is_cancelled"].mean() * 100 if not df_all.empty else 0
        grp_avg_party   = _safe_mean(df_conf["covers"])        if not df_conf.empty else 0
        grp_spc         = _safe_mean(df_conf.loc[df_conf.get("spend_per_cover", pd.Series([0])) > 0, "spend_per_cover"]) if has_spend else 0
        grp_return_rate = df_conf["is_returning"].mean() * 100 if not df_conf.empty and "is_returning" in df_conf.columns else None
        grp_avg_rating  = df_fb["rating"].mean()               if not df_fb.empty and "rating" in df_fb.columns else None
        grp_occ         = nights_cur / avail_cur * 100          if avail_cur else 0

        for venue in venue_names:
            E.append(Spacer(1, 0.15*cm))

            hdr = Table(
                [[Paragraph(venue, ParagraphStyle("vhdr", fontName="Helvetica-Bold",
                             fontSize=11, textColor=RL_WHITE, leading=15))]],
                colWidths=[INNER_W],
            )
            hdr.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,-1), RL_GREEN),
                ("TOPPADDING",    (0,0),(-1,-1), 6),
                ("BOTTOMPADDING", (0,0),(-1,-1), 6),
                ("LEFTPADDING",   (0,0),(-1,-1), 8),
            ]))
            E.append(hdr)
            E.append(Spacer(1, 0.1*cm))

            v_all  = df_all[df_all["venue_name"] == venue]   if not df_all.empty  else pd.DataFrame()
            v_conf = df_conf[df_conf["venue_name"] == venue]  if not df_conf.empty else pd.DataFrame()
            v_yoy  = df_conf_yoy[df_conf_yoy["venue_name"] == venue] if not df_conf_yoy.empty else pd.DataFrame()
            v_fb   = df_fb[df_fb["venue_name"] == venue]     if not df_fb.empty and "venue_name" in df_fb.columns else pd.DataFrame()
            v_rm   = df_rooms[df_rooms["venue_name"] == venue] if not df_rooms.empty and "venue_name" in df_rooms.columns else pd.DataFrame()
            has_rooms = venue in ROOM_COUNTS

            p_covers     = int(v_conf["covers"].sum()) if not v_conf.empty else 0
            p_covers_yoy = int(v_yoy["covers"].sum())  if not v_yoy.empty  else 0
            p_bookings   = len(v_conf)
            p_noshow     = v_all["is_noshow"].mean()    * 100 if not v_all.empty else 0
            p_cancel     = v_all["is_cancelled"].mean() * 100 if not v_all.empty else 0
            p_spc        = _safe_mean(v_conf.loc[v_conf.get("spend_per_cover", pd.Series([0])) > 0, "spend_per_cover"]) if has_spend else 0
            p_rating     = v_fb["rating"].mean()  if not v_fb.empty and "rating" in v_fb.columns else None
            p_return     = v_conf["is_returning"].mean() * 100 if not v_conf.empty and "is_returning" in v_conf.columns else None

            p_occ = 0
            p_occ_yoy = 0
            if has_rooms and not v_rm.empty:
                p_avail  = ROOM_COUNTS[venue] * days_cur
                p_occ    = v_rm["nights"].sum() / p_avail * 100 if p_avail else 0
                v_rm_yoy = df_rooms_yoy[df_rooms_yoy["venue_name"] == venue] if not df_rooms_yoy.empty and "venue_name" in df_rooms_yoy.columns else pd.DataFrame()
                p_avail_yoy = ROOM_COUNTS[venue] * days_yoy
                p_occ_yoy   = v_rm_yoy["nights"].sum() / p_avail_yoy * 100 if not v_rm_yoy.empty and p_avail_yoy else 0

            covers_pct = (p_covers - p_covers_yoy) / p_covers_yoy * 100 if p_covers_yoy else 0

            snap_items = [
                ("Covers (YTD)",  f"{p_covers:,}",
                 f"{covers_pct:+.1f}% YoY", covers_pct >= 0),
                ("No-show Rate",  f"{p_noshow:.1f}%",
                 f"Group avg {grp_noshow_rate:.1f}%", p_noshow <= grp_noshow_rate),
                ("Avg Rating",    f"{p_rating:.2f}★" if p_rating else "—",
                 f"Group avg {grp_avg_rating:.2f}★" if grp_avg_rating else None,
                 (p_rating or 0) >= (grp_avg_rating or 4.0)),
            ]
            if has_spend and p_spc > 0:
                snap_items.append(("Spend/Cover", f"£{p_spc:.2f}",
                                   f"Group avg £{grp_spc:.2f}", p_spc >= grp_spc))
            if has_rooms:
                snap_items.append(("Room Occupancy", f"{p_occ:.1f}%",
                                   f"Group avg {grp_occ:.1f}%", p_occ >= grp_occ))
            if p_return is not None:
                snap_items.append(("Return Rate", f"{p_return:.0f}%",
                                   f"Group avg {grp_return_rate:.0f}%" if grp_return_rate else None,
                                   p_return >= (grp_return_rate or 30)))
            E.append(_kpi_row(snap_items, S))
            E.append(Spacer(1, 0.15*cm))

            recs = _build_recommendations(
                venue=venue,
                v_conf=v_conf, v_all=v_all, v_yoy=v_yoy, v_fb=v_fb, v_rm=v_rm,
                p_covers=p_covers, p_covers_yoy=p_covers_yoy, covers_pct=covers_pct,
                p_bookings=p_bookings,
                p_noshow=p_noshow, p_cancel=p_cancel,
                p_spc=p_spc, p_rating=p_rating, p_return=p_return,
                p_occ=p_occ, p_occ_yoy=p_occ_yoy,
                grp_noshow=grp_noshow_rate, grp_spc=grp_spc,
                grp_rating=grp_avg_rating, grp_return=grp_return_rate, grp_occ=grp_occ,
                avg_spc=avg_spc, has_spend=has_spend, has_rooms=has_rooms,
                days_cur=days_cur,
            )

            if not recs:
                E.append(Paragraph(
                    "No specific recommendations — performance at or above group average across all metrics.",
                    S["body"],
                ))
            else:
                rec_rows = []
                for priority, category, headline, detail in recs:
                    icon    = "🔴" if priority == "urgent" else ("🟡" if priority == "important" else "🟢")
                    cat_col = C_RED if priority == "urgent" else (C_AMBER if priority == "important" else C_MID)
                    rec_rows.append([
                        Paragraph(f"{icon} <b>{category}</b>",
                                  ParagraphStyle("cat", fontName="Helvetica-Bold", fontSize=8,
                                                 textColor=colors.HexColor(cat_col), leading=11)),
                        Paragraph(f"<b>{headline}</b><br/><font size=7.5>{detail}</font>",
                                  S["body"]),
                    ])
                rec_tbl = Table(rec_rows, colWidths=[INNER_W * 0.20, INNER_W * 0.80])
                rec_tbl.setStyle(TableStyle([
                    ("VALIGN",         (0,0),(-1,-1), "TOP"),
                    ("TOPPADDING",     (0,0),(-1,-1), 5),
                    ("BOTTOMPADDING",  (0,0),(-1,-1), 5),
                    ("LEFTPADDING",    (0,0),(0,-1),  4),
                    ("ROWBACKGROUNDS", (0,0),(-1,-1), [RL_WHITE, RL_LGREY]),
                    ("GRID",           (0,0),(-1,-1), 0.3, RL_GREY),
                ]))
                E.append(rec_tbl)

            E.append(Spacer(1, 0.2*cm))

    _p(0.95, "Writing PDF to disk…")
    buf = io.BytesIO()
    doc = _build_doc(buf, start_date, end_date)
    doc.build(E)
    buf.seek(0)
    _p(1.00, "Done.")
    return buf.read()
