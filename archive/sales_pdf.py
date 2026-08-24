"""
Chickpea Pubs – Sales & Food PDF Report
Generates a branded, shareable PDF from Tevalis POS ticket data.
"""

import io
import os
from datetime import date

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
C_CREAM = "#F9F5EF"
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

DRINK_KEYWORDS = [
    'beer', 'lager', 'ale', 'stout', 'cider', 'wine', 'prosecco', 'champagne',
    'gin', 'vodka', 'rum', 'whisky', 'whiskey', 'spirit', 'cocktail', 'shots',
    'pint', 'half', 'soft drink', 'cola', 'juice', 'water', 'coffee', 'tea',
    'americano', 'latte', 'cappuccino', 'espresso', 'hot chocolate',
    'thatchers', 'peroni', 'estrella', 'corona', 'guinness', 'fosters',
    'carlsberg', 'heineken', 'mahou', 'proper job', 'tribute', 'korev',
]


# ── STYLES ─────────────────────────────────────────────────────────────────────

def _styles():
    S = {}

    def s(name, **kw):
        S[name] = ParagraphStyle(name, **kw)

    s("cover_title",   fontName="Helvetica-Bold",  fontSize=30, textColor=RL_WHITE, alignment=TA_CENTER, leading=36)
    s("cover_sub",     fontName="Helvetica",         fontSize=13, textColor=RL_LIGHT, alignment=TA_CENTER, leading=18)
    s("cover_date",    fontName="Helvetica",          fontSize=9,  textColor=RL_LIGHT, alignment=TA_CENTER, leading=13)
    s("section",       fontName="Helvetica-Bold",    fontSize=14, textColor=RL_GREEN, leading=18, spaceBefore=4, spaceAfter=3)
    s("subsection",    fontName="Helvetica-Bold",    fontSize=10, textColor=RL_GREEN, leading=14, spaceBefore=4, spaceAfter=2)
    s("body",          fontName="Helvetica",          fontSize=8.5, textColor=RL_BLACK, leading=13, spaceAfter=3)
    s("note",          fontName="Helvetica-Oblique",  fontSize=7.5, textColor=colors.HexColor("#777777"), leading=11, spaceAfter=3)
    s("kpi_val",       fontName="Helvetica-Bold",    fontSize=20, textColor=RL_GREEN, alignment=TA_CENTER, leading=24)
    s("kpi_lbl",       fontName="Helvetica",          fontSize=7.5, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, leading=10)
    s("th",            fontName="Helvetica-Bold",    fontSize=7.5, textColor=RL_WHITE, alignment=TA_CENTER, leading=10)
    s("td",            fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_CENTER, leading=10)
    s("td_l",          fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_LEFT,   leading=10)
    s("td_r",          fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_RIGHT,  leading=10)
    return S


# ── TABLE HELPER ───────────────────────────────────────────────────────────────

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
    cells = []
    for label, val in items:
        cells.append([
            Paragraph(str(val), S["kpi_val"]),
            Paragraph(str(label), S["kpi_lbl"]),
        ])
    t = Table([cells], colWidths=[INNER_W / n] * n)
    box_rules = [("BOX", (i, 0), (i, 0), 0.4, RL_GREY) for i in range(n)]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), RL_LGREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ] + box_rules))
    return t


# ── CHART HELPERS ──────────────────────────────────────────────────────────────

def _fig_img(fig, width_pts, height_pts):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close(fig)
    return Image(buf, width=width_pts, height=height_pts)


def _ax_style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)


def _chart_daily_revenue(df_tickets, w, h=160):
    daily = (
        df_tickets.groupby("date")["subtotal"]
        .sum()
        .reset_index()
        .sort_values("date")
    )
    if len(daily) < 2:
        return None
    fig, ax = plt.subplots(figsize=(w / 72, h / 72), facecolor="white")
    ax.bar(range(len(daily)), daily["subtotal"], color=C_GREEN, width=0.7)
    ax.set_xticks(range(len(daily)))
    labels = pd.to_datetime(daily["date"], errors="coerce").dt.strftime("%d %b")
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=6)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"£{x:,.0f}"))
    ax.set_ylabel("Revenue (£)", fontsize=7)
    _ax_style(ax)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def _chart_pub_revenue(df_tickets, w, h=170):
    if "venue" not in df_tickets.columns:
        return None
    data = df_tickets.groupby("venue")["subtotal"].sum().sort_values(ascending=True)
    if data.empty:
        return None
    fig, ax = plt.subplots(figsize=(w / 72, h / 72), facecolor="white")
    bars = ax.barh([v.replace("The ", "") for v in data.index], data.values, color=C_GREEN)
    ax.bar_label(bars, fmt="£%.0f", padding=4, fontsize=6.5)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"£{x:,.0f}"))
    ax.set_xlabel("Revenue (£)", fontsize=7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=7)
    fig.tight_layout(pad=0.5)
    return _fig_img(fig, w, h)


def _chart_food_drink_split(df_items, w, h=150):
    if df_items.empty:
        return None
    df_items = df_items.copy()
    df_items["category"] = df_items["item"].apply(
        lambda x: "Drinks" if any(k in str(x).lower() for k in DRINK_KEYWORDS) else "Food"
    )
    split = df_items.groupby("category")["revenue"].sum()
    if split.empty or split.sum() == 0:
        return None
    fig, ax = plt.subplots(figsize=(w / 72, h / 72), facecolor="white")
    clrs = {"Food": C_GREEN, "Drinks": C_AMBER}
    wedge_clrs = [clrs.get(c, C_MID) for c in split.index]
    wedges, texts, autos = ax.pie(
        split.values, labels=split.index, autopct="%1.1f%%",
        colors=wedge_clrs,
        wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
        textprops={"fontsize": 8},
    )
    for at in autos:
        at.set_fontsize(8)
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
                        leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0)

    def _cover_bg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(RL_GREEN)
        canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
        canvas.restoreState()

    inner_frame = Frame(
        MARGIN, MARGIN + 0.75 * cm,
        INNER_W, PAGE_H - 2 * MARGIN - 1.6 * cm,
        id="inner",
    )
    period_str = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"

    def _inner_pg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(RL_GREEN)
        canvas.rect(0, PAGE_H - 1.05 * cm, PAGE_W, 1.05 * cm, fill=1, stroke=0)
        canvas.setFillColor(RL_WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(MARGIN, PAGE_H - 0.7 * cm, "chickpea.")
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.7 * cm,
                               f"Sales & Food Report  ·  {period_str}")
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


# ── COVER PAGE ─────────────────────────────────────────────────────────────────

def _cover_page(start_date, end_date, venue_name, S):
    period_str = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"
    elems = [Spacer(1, PAGE_H * 0.22)]

    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=5 * cm, height=5 * cm, kind="proportional")
        logo.hAlign = "CENTER"
        elems.append(logo)
        elems.append(Spacer(1, 0.6 * cm))

    elems += [
        Paragraph("Sales &amp; Food Report", S["cover_title"]),
        Spacer(1, 0.3 * cm),
        Paragraph(venue_name if venue_name != "All Pubs" else "All Venues", S["cover_sub"]),
        Spacer(1, 0.2 * cm),
        Paragraph(period_str, S["cover_date"]),
        Spacer(1, 0.15 * cm),
        Paragraph(f"Generated {date.today().strftime('%d %b %Y')}", S["cover_date"]),
    ]
    return elems


# ── MAIN GENERATOR ─────────────────────────────────────────────────────────────

def generate_sales_pdf(tickets: list, items: list, start_date, end_date, venue_name: str = "All Pubs") -> bytes:
    """
    Build a branded Sales & Food PDF.

    Parameters
    ----------
    tickets  : list of dicts (already extracted from Tevalis POS tickets in the dashboard)
    items    : list of dicts (line items from POS tickets)
    start_date, end_date : date objects
    venue_name : display name for the report ("All Pubs" or specific pub)

    Returns
    -------
    bytes  PDF content ready for st.download_button
    """
    if not tickets:
        raise ValueError("No Tevalis ticket data found for this period.")

    df = pd.DataFrame(tickets)
    df_items = pd.DataFrame(items) if items else pd.DataFrame()

    S = _styles()
    buf = io.BytesIO()
    doc = _build_doc(buf, start_date, end_date)

    E = []

    # ── Cover ──
    E += _cover_page(start_date, end_date, venue_name, S)
    E.append(NextPageTemplate("Inner"))
    E.append(PageBreak())

    # ── KPI Summary ──
    total_rev    = df["subtotal"].sum()
    total_tax    = df["tax"].sum()
    total_sc     = df["service_charge"].sum()
    total_covers = df["covers"].sum()
    avg_sph      = total_rev / total_covers if total_covers else 0
    n_tickets    = len(df)

    E += _section("Executive Summary", S)
    E.append(_kpi_row([
        ("Total Revenue (ex. tax)", f"£{total_rev:,.0f}"),
        ("Covers", f"{total_covers:,}"),
        ("Avg Spend / Head", f"£{avg_sph:.2f}"),
        ("Tickets", f"{n_tickets:,}"),
    ], S))
    E.append(Spacer(1, 0.2 * cm))
    E.append(_kpi_row([
        ("Tax Collected", f"£{total_tax:,.0f}"),
        ("Service Charge", f"£{total_sc:,.0f}"),
        ("Total inc. Tax & SC", f"£{total_rev + total_tax + total_sc:,.0f}"),
    ], S))
    E.append(Spacer(1, 0.3 * cm))

    # ── Daily Revenue Chart ──
    if len(df["date"].unique()) > 1:
        E += _section("Daily Revenue", S)
        chart = _chart_daily_revenue(df, INNER_W, 160)
        if chart:
            E.append(chart)
        E.append(Spacer(1, 0.3 * cm))

    # ── Revenue by Pub ──
    if venue_name == "All Pubs" and "venue" in df.columns:
        E += _section("Revenue by Pub", S)
        pub_chart = _chart_pub_revenue(df, INNER_W, 180)
        if pub_chart:
            E.append(pub_chart)
            E.append(Spacer(1, 0.2 * cm))

        pub_grp = df.groupby("venue").agg(
            Tickets=("ticket_id", "count"),
            Covers=("covers", "sum"),
            Revenue=("subtotal", "sum"),
            Avg_per_Head=("spend_per_head", "mean"),
            Service_Charge=("service_charge", "sum"),
        ).reset_index().sort_values("Revenue", ascending=False)

        headers = ["Pub", "Tickets", "Covers", "Revenue (£)", "Avg/Head (£)", "SC (£)"]
        fracs   = [0.30, 0.12, 0.12, 0.16, 0.15, 0.15]
        rows    = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in pub_grp.iterrows():
            rows.append([
                Paragraph(row["venue"], S["td_l"]),
                Paragraph(f"{int(row['Tickets']):,}", S["td"]),
                Paragraph(f"{int(row['Covers']):,}", S["td"]),
                Paragraph(f"£{row['Revenue']:,.2f}", S["td"]),
                Paragraph(f"£{row['Avg_per_Head']:.2f}", S["td"]),
                Paragraph(f"£{row['Service_Charge']:,.2f}", S["td"]),
            ])
        # Totals row
        rows.append([
            Paragraph("<b>TOTAL</b>", S["td_l"]),
            Paragraph(f"<b>{int(pub_grp['Tickets'].sum()):,}</b>", S["td"]),
            Paragraph(f"<b>{int(pub_grp['Covers'].sum()):,}</b>", S["td"]),
            Paragraph(f"<b>£{pub_grp['Revenue'].sum():,.2f}</b>", S["td"]),
            Paragraph(f"<b>£{pub_grp['Avg_per_Head'].mean():.2f}</b>", S["td"]),
            Paragraph(f"<b>£{pub_grp['Service_Charge'].sum():,.2f}</b>", S["td"]),
        ])
        total_row_style = [("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), RL_LIGHT)]
        E.append(KeepTogether([_tbl(rows, fracs, total_row_style)]))
        E.append(Spacer(1, 0.3 * cm))

    # ── Revenue by Service ──
    if "shift" in df.columns:
        known = df[df["shift"] != "Unknown"]
        if not known.empty:
            E += _section("Revenue by Service", S)
            shift_grp = known.groupby("shift").agg(
                Tickets=("ticket_id", "count"),
                Covers=("covers", "sum"),
                Revenue=("subtotal", "sum"),
                Avg_per_Head=("spend_per_head", "mean"),
            ).reset_index().sort_values("Revenue", ascending=False)

            shift_grp["Pct"] = (shift_grp["Revenue"] / shift_grp["Revenue"].sum() * 100).round(1)

            headers = ["Service", "Tickets", "Covers", "Revenue (£)", "Avg/Head (£)", "% of Revenue"]
            fracs   = [0.22, 0.13, 0.13, 0.18, 0.18, 0.16]
            rows    = [[Paragraph(h, S["th"]) for h in headers]]
            for _, row in shift_grp.iterrows():
                rows.append([
                    Paragraph(str(row["shift"]), S["td_l"]),
                    Paragraph(f"{int(row['Tickets']):,}", S["td"]),
                    Paragraph(f"{int(row['Covers']):,}", S["td"]),
                    Paragraph(f"£{row['Revenue']:,.2f}", S["td"]),
                    Paragraph(f"£{row['Avg_per_Head']:.2f}", S["td"]),
                    Paragraph(f"{row['Pct']:.1f}%", S["td"]),
                ])
            E.append(KeepTogether([_tbl(rows, fracs)]))
            E.append(Spacer(1, 0.3 * cm))

    # ── Food vs Drinks Split ──
    if not df_items.empty:
        E += _section("Food vs Drinks Split", S)
        df_items_cat = df_items.copy()
        df_items_cat["category"] = df_items_cat["item"].apply(
            lambda x: "Drinks" if any(k in str(x).lower() for k in DRINK_KEYWORDS) else "Food"
        )

        split_chart = _chart_food_drink_split(df_items, INNER_W * 0.4, 150)

        split_grp = df_items_cat.groupby("category")["revenue"].sum().reset_index()
        total_split = split_grp["revenue"].sum()
        split_grp["Pct"] = (split_grp["revenue"] / total_split * 100).round(1)
        split_grp = split_grp.sort_values("revenue", ascending=False)

        headers = ["Category", "Revenue (£)", "% of Revenue"]
        fracs   = [0.40, 0.30, 0.30]
        split_rows = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in split_grp.iterrows():
            split_rows.append([
                Paragraph(str(row["category"]), S["td_l"]),
                Paragraph(f"£{row['revenue']:,.2f}", S["td"]),
                Paragraph(f"{row['Pct']:.1f}%", S["td"]),
            ])

        split_tbl = _tbl(split_rows, fracs)

        if split_chart:
            # Chart on left, table on right
            tbl_w = INNER_W * 0.55 - 0.3 * cm
            t = Table([[split_chart, split_tbl]],
                      colWidths=[INNER_W * 0.40, tbl_w])
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            E.append(t)
        else:
            E.append(split_tbl)

        E.append(Spacer(1, 0.2 * cm))

        # Per-pub food/drink split (if All Pubs)
        if venue_name == "All Pubs" and "venue" in df_items_cat.columns:
            pub_split = (
                df_items_cat.groupby(["venue", "category"])["revenue"]
                .sum()
                .unstack(fill_value=0)
                .reset_index()
            )
            if "Food" not in pub_split.columns:
                pub_split["Food"] = 0.0
            if "Drinks" not in pub_split.columns:
                pub_split["Drinks"] = 0.0
            pub_split["Total"] = pub_split["Food"] + pub_split["Drinks"]
            pub_split = pub_split[pub_split["Total"] > 0].copy()
            pub_split["Food %"]   = (pub_split["Food"]   / pub_split["Total"] * 100).round(1)
            pub_split["Drinks %"] = (pub_split["Drinks"] / pub_split["Total"] * 100).round(1)
            pub_split = pub_split.sort_values("Drinks %", ascending=False)

            E.append(Paragraph("Food vs Drinks by Pub", S["subsection"]))
            headers = ["Pub", "Food (£)", "Food %", "Drinks (£)", "Drinks %"]
            fracs   = [0.30, 0.175, 0.125, 0.175, 0.125]
            rows = [[Paragraph(h, S["th"]) for h in headers]]
            for _, row in pub_split.iterrows():
                rows.append([
                    Paragraph(row["venue"], S["td_l"]),
                    Paragraph(f"£{row['Food']:,.2f}", S["td"]),
                    Paragraph(f"{row['Food %']:.1f}%", S["td"]),
                    Paragraph(f"£{row['Drinks']:,.2f}", S["td"]),
                    Paragraph(f"{row['Drinks %']:.1f}%", S["td"]),
                ])
            E.append(KeepTogether([_tbl(rows, fracs)]))
            E.append(Spacer(1, 0.3 * cm))

    # ── Top Dishes ──
    if not df_items.empty:
        E += _section("Most Popular Items", S)

        def _top_items(df_src, n=20):
            grp = (
                df_src.groupby("item")
                .agg(Qty=("quantity", "sum"), Revenue=("revenue", "sum"))
                .reset_index()
                .sort_values("Qty", ascending=False)
                .head(n)
            )
            headers = ["Item", "Times Ordered", "Revenue (£)"]
            fracs   = [0.55, 0.22, 0.23]
            rows    = [[Paragraph(h, S["th"]) for h in headers]]
            for _, row in grp.iterrows():
                rows.append([
                    Paragraph(str(row["item"]), S["td_l"]),
                    Paragraph(f"{int(row['Qty']):,}", S["td"]),
                    Paragraph(f"£{row['Revenue']:,.2f}", S["td"]),
                ])
            return _tbl(rows, fracs)

        if venue_name == "All Pubs":
            E.append(Paragraph("Top 20 items across all pubs (by times ordered)", S["body"]))
            E.append(KeepTogether([_top_items(df_items)]))
        else:
            E.append(Paragraph(f"Top 20 items — {venue_name} (by times ordered)", S["body"]))
            E.append(KeepTogether([_top_items(df_items)]))
        E.append(Spacer(1, 0.3 * cm))

    # ── Dwell Time ──
    dwell = df[df["dwell_mins"].notna() & (df["dwell_mins"] > 0)].copy() if "dwell_mins" in df.columns else pd.DataFrame()
    if not dwell.empty:
        E += _section("Table Dwell Time", S)
        avg_d = dwell["dwell_mins"].mean()
        max_d = dwell["dwell_mins"].max()
        min_d = dwell["dwell_mins"].min()
        E.append(_kpi_row([
            ("Avg Time at Table", f"{int(avg_d)} mins"),
            ("Longest Sitting",   f"{int(max_d)} mins"),
            ("Shortest Sitting",  f"{int(min_d)} mins"),
        ], S))

        long_sit = dwell[dwell["dwell_mins"] > 120].sort_values("dwell_mins", ascending=False)
        if not long_sit.empty:
            E.append(Spacer(1, 0.2 * cm))
            E.append(Paragraph(f"Tables over 2 hours ({len(long_sit)} tickets)", S["subsection"]))
            cols = [c for c in ["date", "venue", "guest", "covers", "dwell_mins", "subtotal"] if c in long_sit.columns]
            headers = {"date": "Date", "venue": "Pub", "guest": "Guest",
                       "covers": "Covers", "dwell_mins": "Mins", "subtotal": "Revenue (£)"}
            fracs_map = {"date": 0.13, "venue": 0.25, "guest": 0.25,
                         "covers": 0.10, "dwell_mins": 0.12, "subtotal": 0.15}
            fracs = [fracs_map[c] for c in cols]
            rows = [[Paragraph(headers[c], S["th"]) for c in cols]]
            for _, row in long_sit.head(30).iterrows():
                rows.append([
                    Paragraph(str(row.get(c, "")), S["td"] if c != cols[0] else S["td_l"])
                    for c in cols
                ])
            E.append(KeepTogether([_tbl(rows, fracs)]))

    # ── Build PDF ──
    doc.build(E)
    return buf.getvalue()
