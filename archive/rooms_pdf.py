"""
Chickpea Pubs – Rooms Intelligence PDF Report
Generates a branded, shareable PDF from eviivo room booking data.
"""

import io
import os
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether,
    NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

# ── BRAND CONSTANTS ────────────────────────────────────────────────────────────

LOGO_PATH = (
    r"C:\Users\Delilah Sturgis\Chickpea Dropbox\Chickpea\Chickpea"
    r"\Branding\Logos (2023 onwards)\Chickpea Group\Chickpea 2026 Logo.png"
)

C_GREEN = "#1C3829"
C_MID   = "#2E7D32"
C_LIGHT = "#C8DFC8"
C_AMBER = "#C8882A"
C_RED   = "#B71C1C"

RL_GREEN = colors.HexColor(C_GREEN)
RL_MID   = colors.HexColor(C_MID)
RL_LIGHT = colors.HexColor(C_LIGHT)
RL_AMBER = colors.HexColor(C_AMBER)
RL_RED   = colors.HexColor(C_RED)
RL_GREY  = colors.HexColor("#E4E4E4")
RL_LGREY = colors.HexColor("#F5F5F5")
RL_WHITE = colors.white
RL_BLACK = colors.black

PAGE_W, PAGE_H = A4
MARGIN  = 1.5 * cm
INNER_W = PAGE_W - 2 * MARGIN


# ── STYLES ─────────────────────────────────────────────────────────────────────

def _styles():
    S = {}

    def s(name, **kw):
        S[name] = ParagraphStyle(name, **kw)

    s("cover_title", fontName="Helvetica-Bold",  fontSize=30, textColor=RL_WHITE, alignment=TA_CENTER, leading=36)
    s("cover_sub",   fontName="Helvetica",         fontSize=13, textColor=RL_LIGHT, alignment=TA_CENTER, leading=18)
    s("cover_date",  fontName="Helvetica",          fontSize=9,  textColor=RL_LIGHT, alignment=TA_CENTER, leading=13)
    s("section",     fontName="Helvetica-Bold",    fontSize=14, textColor=RL_GREEN, leading=18, spaceBefore=4, spaceAfter=3)
    s("subsection",  fontName="Helvetica-Bold",    fontSize=10, textColor=RL_GREEN, leading=14, spaceBefore=4, spaceAfter=2)
    s("body",        fontName="Helvetica",          fontSize=8.5, textColor=RL_BLACK, leading=13, spaceAfter=3)
    s("note",        fontName="Helvetica-Oblique",  fontSize=7.5, textColor=colors.HexColor("#777777"), leading=11, spaceAfter=3)
    s("kpi_val",     fontName="Helvetica-Bold",    fontSize=20, textColor=RL_GREEN, alignment=TA_CENTER, leading=24)
    s("kpi_lbl",     fontName="Helvetica",          fontSize=7.5, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, leading=10)
    s("th",          fontName="Helvetica-Bold",    fontSize=7.5, textColor=RL_WHITE, alignment=TA_CENTER, leading=10)
    s("td",          fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_CENTER, leading=10)
    s("td_l",        fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_LEFT,   leading=10)
    s("td_r",        fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_RIGHT,  leading=10)
    return S


# ── TABLE / KPI HELPERS ────────────────────────────────────────────────────────

_BASE_TS = [
    ("BACKGROUND",    (0, 0), (-1, 0),  RL_GREEN),
    ("TEXTCOLOR",     (0, 0), (-1, 0),  RL_WHITE),
    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
    ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [RL_WHITE, RL_LGREY]),
    ("ALIGN",         (1, 1), (-1, -1), "CENTER"),
    ("TOPPADDING",    (0, 0), (-1, -1), 3.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ("LEFTPADDING",   (0, 0), (0, -1),  5),
]


def _tbl(rows, col_fracs, extra_style=None):
    col_w = [INNER_W * f for f in col_fracs]
    ts = list(_BASE_TS) + (extra_style or [])
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle(ts))
    return t


def _section(title, S):
    return [
        Spacer(1, 0.25 * cm),
        Paragraph(title, S["section"]),
        HRFlowable(width=INNER_W, thickness=1, color=RL_LIGHT, spaceAfter=4),
    ]


def _kpi_row(items, S):
    n = len(items)
    cells = [[Paragraph(str(v), S["kpi_val"]), Paragraph(str(l), S["kpi_lbl"])] for l, v in items]
    t = Table([cells], colWidths=[INNER_W / n] * n)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), RL_LGREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ] + [("BOX", (i, 0), (i, 0), 0.4, RL_GREY) for i in range(n)]))
    return t


# ── CHARTS ─────────────────────────────────────────────────────────────────────

def _fig_img(fig, w, h):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return Image(buf, width=w, height=h)


def _ax_style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)


def _chart_channel_pie(df_ri, w, h=160):
    counts = df_ri.groupby("channel").size()
    if counts.empty:
        return None
    clr_map = {"Booking.com": C_AMBER, "Expedia": C_RED, "Airbnb": "#FF5A5F",
               "Hotels.com": C_MID, "Direct / Unknown": C_GREEN}
    clrs = [clr_map.get(c, C_LIGHT) for c in counts.index]
    fig, ax = plt.subplots(figsize=(w / 72, h / 72), facecolor="white")
    wedges, texts, autos = ax.pie(
        counts.values, labels=counts.index, autopct="%1.0f%%",
        colors=clrs, wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
        textprops={"fontsize": 7},
    )
    for at in autos:
        at.set_fontsize(7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def _chart_revenue_by_venue(df_confirmed, w, h=170):
    if "venue_name" not in df_confirmed.columns or df_confirmed["total_value"].sum() == 0:
        return None
    data = df_confirmed.groupby("venue_name")["total_value"].sum().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(w / 72, h / 72), facecolor="white")
    bars = ax.barh([v.replace("The ", "") for v in data.index], data.values, color=C_GREEN)
    ax.bar_label(bars, fmt="£%.0f", padding=4, fontsize=6.5)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"£{x:,.0f}"))
    ax.set_xlabel("Revenue (£)", fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def _chart_los_dist(df_confirmed, w, h=145):
    los = df_confirmed["nights"].value_counts().sort_index()
    if los.empty:
        return None
    fig, ax = plt.subplots(figsize=(w / 72, h / 72), facecolor="white")
    bars = ax.bar(los.index.astype(str), los.values, color=C_GREEN)
    ax.bar_label(bars, fontsize=7, padding=2)
    ax.set_xlabel("Nights", fontsize=7)
    ax.set_ylabel("Stays", fontsize=7)
    _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


# ── PAGE TEMPLATES ─────────────────────────────────────────────────────────────

def _build_doc(buf, start_date, end_date):
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN + 0.5 * cm,
    )
    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, id="cover",
                        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    def _cover_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(RL_GREEN)
        canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        canvas.restoreState()

    inner_frame = Frame(MARGIN, MARGIN + 0.75 * cm, INNER_W, PAGE_H - 2 * MARGIN - 1.6 * cm, id="inner")
    period_str = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"

    def _inner_pg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(RL_GREEN)
        canvas.rect(0, PAGE_H - 1.05 * cm, PAGE_W, 1.05 * cm, fill=1, stroke=0)
        canvas.setFillColor(RL_WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(MARGIN, PAGE_H - 0.7 * cm, "chickpea.")
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.7 * cm, f"Rooms Intelligence  ·  {period_str}")
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(MARGIN, 0.5 * cm, "Confidential — Chickpea Pub Group")
        canvas.drawRightString(PAGE_W - MARGIN, 0.5 * cm, f"Page {doc.page - 1}")
        canvas.setStrokeColor(RL_LIGHT)
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, PAGE_H - 1.1 * cm, PAGE_W - MARGIN, PAGE_H - 1.1 * cm)
        canvas.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame], onPage=_cover_bg),
        PageTemplate(id="Inner", frames=[inner_frame], onPage=_inner_pg),
    ])
    return doc


# ── MAIN GENERATOR ─────────────────────────────────────────────────────────────

def generate_rooms_pdf(stays_raw: list, start_date, end_date, venue_name: str = "All Properties") -> bytes:
    """
    Build a branded Rooms Intelligence PDF.

    Parameters
    ----------
    stays_raw   : list of dicts (raw eviivo booking records)
    start_date, end_date : date objects
    venue_name  : "All Properties" or specific property name

    Returns
    -------
    bytes  PDF content
    """
    if not stays_raw:
        raise ValueError("No room booking data found for this period.")

    df_ri = pd.DataFrame(stays_raw)

    # ── Data prep (mirrors the dashboard tab) ──
    df_ri["checkin_dt"]  = pd.to_datetime(df_ri["date"], errors="coerce")
    df_ri["checkout_dt"] = pd.to_datetime(df_ri["checkout_date"], errors="coerce")
    df_ri["nights"]      = (df_ri["checkout_dt"] - df_ri["checkin_dt"]).dt.days.clip(lower=0)
    df_ri["party_size"]  = pd.to_numeric(df_ri.get("party_size", 1), errors="coerce").fillna(1).astype(int)
    df_ri["total_value"] = pd.to_numeric(df_ri.get("total_value", 0), errors="coerce").fillna(0)
    df_ri["notes_lower"] = df_ri["notes"].fillna("").str.lower()
    df_ri["checkin_dow"] = df_ri["checkin_dt"].dt.day_name()
    df_ri["checkin_week"]= df_ri["checkin_dt"].dt.to_period("W")

    if venue_name != "All Properties" and "venue_name" in df_ri.columns:
        df_ri = df_ri[df_ri["venue_name"] == venue_name]

    def detect_channel(n):
        if any(k in n for k in ["booking.com", "non-smoking", "genius booker", "payment_on_booking", "breakfast is included"]):
            return "Booking.com"
        if "expedia" in n: return "Expedia"
        if "airbnb"  in n: return "Airbnb"
        if "hotels.com" in n: return "Hotels.com"
        return "Direct / Unknown"

    df_ri["channel"] = df_ri["notes_lower"].apply(detect_channel)

    today_dt     = pd.Timestamp(date.today())
    df_confirmed = df_ri[df_ri["status"] != "Cancelled"].copy()
    df_cancelled = df_ri[df_ri["status"] == "Cancelled"].copy()
    df_future    = df_confirmed[df_confirmed["checkin_dt"] >= today_dt]

    total_stays       = len(df_confirmed)
    avg_nights        = df_confirmed["nights"].mean() if total_stays else 0
    total_revenue     = df_confirmed["total_value"].sum()
    total_nights_sold = df_confirmed["nights"].sum()
    avg_rate          = total_revenue / total_nights_sold if total_nights_sold > 0 else 0
    cancel_count      = len(df_cancelled)
    cancel_rate       = cancel_count / max(len(df_ri), 1) * 100
    upcoming_count    = len(df_future)

    S   = _styles()
    buf = io.BytesIO()
    doc = _build_doc(buf, start_date, end_date)
    E   = []

    # ── Cover ──
    period_str = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"
    E.append(Spacer(1, PAGE_H * 0.22))
    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=5 * cm, height=5 * cm, kind="proportional")
        logo.hAlign = "CENTER"
        E.append(logo)
        E.append(Spacer(1, 0.6 * cm))
    E += [
        Paragraph("Rooms Intelligence", S["cover_title"]),
        Spacer(1, 0.3 * cm),
        Paragraph(venue_name, S["cover_sub"]),
        Spacer(1, 0.2 * cm),
        Paragraph(period_str, S["cover_date"]),
        Spacer(1, 0.15 * cm),
        Paragraph(f"Generated {date.today().strftime('%d %b %Y')}", S["cover_date"]),
    ]
    E.append(NextPageTemplate("Inner"))
    E.append(PageBreak())

    # ── Headline KPIs ──
    E += _section("Summary", S)
    E.append(_kpi_row([
        ("Confirmed Stays",   f"{total_stays:,}"),
        ("Avg Length of Stay",f"{avg_nights:.1f} nights"),
        ("Upcoming Bookings", f"{upcoming_count:,}"),
        ("Cancellation Rate", f"{cancel_rate:.1f}%"),
    ], S))
    E.append(Spacer(1, 0.15 * cm))
    E.append(_kpi_row([
        ("Room Revenue",      f"£{total_revenue:,.0f}" if total_revenue > 0 else "—"),
        ("Nights Sold",       f"{int(total_nights_sold):,}"),
        ("Avg Rate / Night",  f"£{avg_rate:.0f}" if avg_rate > 0 else "—"),
    ], S))
    E.append(Spacer(1, 0.3 * cm))

    # ── Booking Channels ──
    E += _section("Booking Channels", S)
    E.append(Paragraph(
        "Channel inferred from booking notes. 'Direct / Unknown' = no OTA markers detected.",
        S["note"],
    ))
    channel_chart = _chart_channel_pie(df_ri, INNER_W * 0.38, 160)
    channel_grp = df_ri.groupby("channel").agg(
        Total=("channel", "count"),
        Confirmed=("status", lambda x: (x != "Cancelled").sum()),
        Cancelled=("status", lambda x: (x == "Cancelled").sum()),
    ).reset_index()
    if "total_value" in df_confirmed.columns:
        ch_rev = df_confirmed.groupby("channel")["total_value"].sum().reset_index()
        ch_rev.columns = ["channel", "rev"]
        channel_grp = channel_grp.merge(ch_rev, on="channel", how="left").fillna(0)
    else:
        channel_grp["rev"] = 0
    channel_grp["pct"] = (channel_grp["Total"] / channel_grp["Total"].sum() * 100).round(1)
    channel_grp = channel_grp.sort_values("Total", ascending=False)

    headers = ["Channel", "Total", "Confirmed", "Cancelled", "% of Total", "Revenue (£)"]
    fracs   = [0.32, 0.12, 0.13, 0.13, 0.13, 0.17]
    ch_rows = [[Paragraph(h, S["th"]) for h in headers]]
    for _, row in channel_grp.iterrows():
        ch_rows.append([
            Paragraph(str(row["channel"]), S["td_l"]),
            Paragraph(str(int(row["Total"])), S["td"]),
            Paragraph(str(int(row["Confirmed"])), S["td"]),
            Paragraph(str(int(row["Cancelled"])), S["td"]),
            Paragraph(f"{row['pct']:.1f}%", S["td"]),
            Paragraph(f"£{row['rev']:,.0f}" if row["rev"] > 0 else "—", S["td"]),
        ])
    ch_tbl = _tbl(ch_rows, fracs)

    if channel_chart:
        tbl_w = INNER_W * 0.57 - 0.3 * cm
        side = Table([[channel_chart, ch_tbl]], colWidths=[INNER_W * 0.38, tbl_w])
        side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        E.append(side)
    else:
        E.append(ch_tbl)
    E.append(Spacer(1, 0.3 * cm))

    # ── Revenue by Property ──
    if total_revenue > 0 and "venue_name" in df_confirmed.columns:
        E += _section("Revenue & Rate by Property", S)
        rev_chart = _chart_revenue_by_venue(df_confirmed, INNER_W, 170)
        if rev_chart:
            E.append(rev_chart)
            E.append(Spacer(1, 0.2 * cm))

        rev_grp = df_confirmed.groupby("venue_name").agg(
            Stays=("total_value", "count"),
            Revenue=("total_value", "sum"),
            Nights=("nights", "sum"),
            Guests=("party_size", "sum"),
        ).reset_index()
        rev_grp["ADR"] = (rev_grp["Revenue"] / rev_grp["Nights"].replace(0, 1)).round(0)
        rev_grp = rev_grp.sort_values("Revenue", ascending=False)

        headers = ["Property", "Stays", "Nights Sold", "Guests", "Revenue (£)", "ADR (£)"]
        fracs   = [0.28, 0.12, 0.14, 0.12, 0.18, 0.16]
        rows    = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in rev_grp.iterrows():
            rows.append([
                Paragraph(str(row["venue_name"]), S["td_l"]),
                Paragraph(str(int(row["Stays"])), S["td"]),
                Paragraph(str(int(row["Nights"])), S["td"]),
                Paragraph(str(int(row["Guests"])), S["td"]),
                Paragraph(f"£{row['Revenue']:,.0f}", S["td"]),
                Paragraph(f"£{row['ADR']:.0f}", S["td"]),
            ])
        # Totals
        rows.append([
            Paragraph("<b>TOTAL</b>", S["td_l"]),
            Paragraph(f"<b>{int(rev_grp['Stays'].sum()):,}</b>", S["td"]),
            Paragraph(f"<b>{int(rev_grp['Nights'].sum()):,}</b>", S["td"]),
            Paragraph(f"<b>{int(rev_grp['Guests'].sum()):,}</b>", S["td"]),
            Paragraph(f"<b>£{rev_grp['Revenue'].sum():,.0f}</b>", S["td"]),
            Paragraph(f"<b>£{rev_grp['Revenue'].sum() / max(rev_grp['Nights'].sum(), 1):.0f}</b>", S["td"]),
        ])
        E.append(KeepTogether([_tbl(rows, fracs, [("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), RL_LIGHT)])]))
        E.append(Spacer(1, 0.3 * cm))

    # ── Cancellations ──
    E += _section("Cancellations", S)
    E.append(Paragraph(
        f"{cancel_count} cancellation{'s' if cancel_count != 1 else ''} — {cancel_rate:.1f}% of all bookings in the period.",
        S["body"],
    ))
    if cancel_count > 0 and "venue_name" in df_cancelled.columns:
        canc_grp = df_cancelled.groupby("venue_name").size().reset_index(name="Cancellations")
        total_by = df_ri.groupby("venue_name").size().reset_index(name="Total")
        canc_grp = canc_grp.merge(total_by, on="venue_name", how="left")
        canc_grp["Rate"] = (canc_grp["Cancellations"] / canc_grp["Total"] * 100).round(1)
        canc_grp = canc_grp.sort_values("Cancellations", ascending=False)
        headers = ["Property", "Cancellations", "Total Bookings", "Cancel Rate"]
        fracs   = [0.35, 0.22, 0.22, 0.21]
        rows    = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in canc_grp.iterrows():
            rows.append([
                Paragraph(str(row["venue_name"]), S["td_l"]),
                Paragraph(str(int(row["Cancellations"])), S["td"]),
                Paragraph(str(int(row["Total"])), S["td"]),
                Paragraph(f"{row['Rate']:.1f}%", S["td"]),
            ])
        E.append(KeepTogether([_tbl(rows, fracs)]))
    else:
        E.append(Paragraph("No cancellations in this period.", S["body"]))
    E.append(Spacer(1, 0.3 * cm))

    # ── Length of Stay ──
    E += _section("Length of Stay", S)
    los_chart = _chart_los_dist(df_confirmed, INNER_W * 0.45, 145)

    los = df_confirmed["nights"].value_counts().sort_index().reset_index()
    los.columns = ["Nights", "Stays"]
    los["% of Total"] = (los["Stays"] / los["Stays"].sum() * 100).round(1)
    headers = ["Nights", "Stays", "% of Total"]
    fracs   = [0.33, 0.33, 0.34]
    los_rows = [[Paragraph(h, S["th"]) for h in headers]]
    for _, row in los.iterrows():
        los_rows.append([
            Paragraph(str(int(row["Nights"])), S["td"]),
            Paragraph(str(int(row["Stays"])), S["td"]),
            Paragraph(f"{row['% of Total']:.1f}%", S["td"]),
        ])
    los_tbl = _tbl(los_rows, fracs)

    if los_chart:
        tbl_w = INNER_W * 0.50 - 0.3 * cm
        side = Table([[los_chart, los_tbl]], colWidths=[INNER_W * 0.45, tbl_w])
        side.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        E.append(side)
    else:
        E.append(los_tbl)

    if "venue_name" in df_confirmed.columns:
        E.append(Spacer(1, 0.2 * cm))
        E.append(Paragraph("Average nights by property", S["subsection"]))
        los_venue = df_confirmed.groupby("venue_name")["nights"].mean().round(1).reset_index()
        los_venue.columns = ["Property", "Avg Nights"]
        los_venue = los_venue.sort_values("Avg Nights", ascending=False)
        headers = ["Property", "Avg Nights"]
        fracs   = [0.65, 0.35]
        rows    = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in los_venue.iterrows():
            rows.append([
                Paragraph(str(row["Property"]), S["td_l"]),
                Paragraph(str(row["Avg Nights"]), S["td"]),
            ])
        E.append(KeepTogether([_tbl(rows, fracs)]))
    E.append(Spacer(1, 0.3 * cm))

    # ── Weekend Occupancy ──
    all_weeks = sorted(df_confirmed["checkin_week"].dropna().unique())
    if all_weeks:
        E += _section("Weekend Occupancy by Week", S)
        E.append(Paragraph("Friday, Saturday and Sunday check-ins.", S["note"]))
        week_data = []
        for week in all_weeks:
            wdf = df_confirmed[df_confirmed["checkin_week"] == week]
            ws  = week.start_time.date()
            week_data.append({
                "Week":           f"w/c {ws.strftime('%d/%m/%y')}",
                "Fri":            len(wdf[wdf["checkin_dow"] == "Friday"]),
                "Sat":            len(wdf[wdf["checkin_dow"] == "Saturday"]),
                "Sun":            len(wdf[wdf["checkin_dow"] == "Sunday"]),
                "Weekend Total":  len(wdf[wdf["checkin_dow"].isin(["Friday", "Saturday", "Sunday"])]),
                "Weekday":        len(wdf[~wdf["checkin_dow"].isin(["Friday", "Saturday", "Sunday"])]),
                "Period":         "Upcoming" if ws >= date.today() else "Past",
            })
        df_wk = pd.DataFrame(week_data)
        headers = ["Week", "Fri", "Sat", "Sun", "Weekend Total", "Weekday", "Period"]
        fracs   = [0.19, 0.08, 0.08, 0.08, 0.16, 0.14, 0.13]
        # Adjust fracs to sum to 1
        fracs   = [0.20, 0.09, 0.09, 0.09, 0.17, 0.14, 0.14]
        rows    = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in df_wk.iterrows():
            is_future = row["Period"] == "Upcoming"
            low_wknd  = is_future and row["Weekend Total"] < 3
            row_style = colors.HexColor("#FFF3CD") if low_wknd else (RL_LGREY if not is_future else RL_WHITE)
            rows.append([
                Paragraph(str(row["Week"]), S["td_l"]),
                Paragraph(str(int(row["Fri"])), S["td"]),
                Paragraph(str(int(row["Sat"])), S["td"]),
                Paragraph(str(int(row["Sun"])), S["td"]),
                Paragraph(str(int(row["Weekend Total"])), S["td"]),
                Paragraph(str(int(row["Weekday"])), S["td"]),
                Paragraph(str(row["Period"]), S["td"]),
            ])
        E.append(KeepTogether([_tbl(rows, fracs)]))
        quiet = df_wk[(df_wk["Period"] == "Upcoming") & (df_wk["Weekend Total"] < 3)]
        if not quiet.empty:
            E.append(Spacer(1, 0.1 * cm))
            E.append(Paragraph(
                f"⚠ {len(quiet)} upcoming weekend{'s' if len(quiet) != 1 else ''} with fewer than 3 check-ins: "
                + ", ".join(quiet["Week"].tolist()),
                S["body"],
            ))
        E.append(Spacer(1, 0.3 * cm))

    # ── Forward Occupancy ──
    if len(df_future) > 0 and "venue_name" in df_future.columns:
        E += _section("Forward Occupancy — Next 8 Weeks", S)
        today_mon   = date.today() - timedelta(days=date.today().weekday())
        week_starts = [today_mon + timedelta(weeks=i) for i in range(8)]
        fwd_data = []
        for pub in sorted(df_future["venue_name"].unique()):
            row = {"Property": pub}
            pub_f = df_future[df_future["venue_name"] == pub]
            for ws in week_starts:
                we    = ws + timedelta(days=6)
                ws_ts = pd.Timestamp(ws)
                we_ts = pd.Timestamp(we)
                count = len(pub_f[(pub_f["checkin_dt"] >= ws_ts) & (pub_f["checkin_dt"] <= we_ts)])
                row[ws.strftime("%d/%m")] = str(count) if count > 0 else ""
            fwd_data.append(row)

        if fwd_data:
            df_fwd   = pd.DataFrame(fwd_data)
            wk_cols  = [ws.strftime("%d/%m") for ws in week_starts]
            headers  = ["Property"] + wk_cols
            n_wk     = len(wk_cols)
            prop_frac= 0.28
            wk_frac  = (1 - prop_frac) / n_wk
            fracs    = [prop_frac] + [wk_frac] * n_wk
            rows     = [[Paragraph(h, S["th"]) for h in headers]]
            for _, row in df_fwd.iterrows():
                rows.append(
                    [Paragraph(str(row["Property"]), S["td_l"])]
                    + [Paragraph(str(row.get(c, "")), S["td"]) for c in wk_cols]
                )
            E.append(KeepTogether([_tbl(rows, fracs)]))
            pipeline = df_future["total_value"].sum()
            if pipeline > 0:
                E.append(Spacer(1, 0.1 * cm))
                E.append(Paragraph(f"Revenue in pipeline (upcoming confirmed): £{pipeline:,.0f}", S["body"]))
        E.append(Spacer(1, 0.3 * cm))

    # ── Party Size ──
    E += _section("Party Size", S)
    ps = df_confirmed["party_size"].value_counts().sort_index().reset_index()
    ps.columns = ["Party Size", "Stays"]
    ps["% of Total"] = (ps["Stays"] / ps["Stays"].sum() * 100).round(1)
    avg_ps  = df_confirmed["party_size"].mean()
    solo    = int((df_confirmed["party_size"] == 1).sum())
    couples = int((df_confirmed["party_size"] == 2).sum())
    groups  = int((df_confirmed["party_size"] >= 3).sum())
    n       = max(len(df_confirmed), 1)
    E.append(Paragraph(
        f"Average party size: <b>{avg_ps:.1f} guests</b>. "
        f"Solo travellers: <b>{solo}</b> ({solo/n*100:.0f}%),  "
        f"Couples: <b>{couples}</b> ({couples/n*100:.0f}%),  "
        f"Groups (3+): <b>{groups}</b> ({groups/n*100:.0f}%).",
        S["body"],
    ))
    headers = ["Party Size", "Stays", "% of Total"]
    fracs   = [0.33, 0.33, 0.34]
    rows    = [[Paragraph(h, S["th"]) for h in headers]]
    for _, row in ps.iterrows():
        rows.append([
            Paragraph(str(int(row["Party Size"])), S["td"]),
            Paragraph(str(int(row["Stays"])), S["td"]),
            Paragraph(f"{row['% of Total']:.1f}%", S["td"]),
        ])
    E.append(KeepTogether([_tbl(rows, fracs)]))

    doc.build(E)
    return buf.getvalue()
