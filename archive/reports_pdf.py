"""
Chickpea Pubs – Summary Report PDF
Generates a branded PDF from the Reports tab's weekly/monthly summary data.
"""

import io
import os
from datetime import date

import pandas as pd

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether,
    NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

# ── BRAND ──────────────────────────────────────────────────────────────────────

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
    s("cover_title", fontName="Helvetica-Bold",  fontSize=28, textColor=RL_WHITE, alignment=TA_CENTER, leading=34)
    s("cover_sub",   fontName="Helvetica",         fontSize=12, textColor=RL_LIGHT, alignment=TA_CENTER, leading=17)
    s("cover_date",  fontName="Helvetica",          fontSize=9,  textColor=RL_LIGHT, alignment=TA_CENTER, leading=13)
    s("section",     fontName="Helvetica-Bold",    fontSize=14, textColor=RL_GREEN, leading=18, spaceBefore=4, spaceAfter=3)
    s("subsection",  fontName="Helvetica-Bold",    fontSize=10, textColor=RL_GREEN, leading=14, spaceBefore=4, spaceAfter=2)
    s("body",        fontName="Helvetica",          fontSize=8.5, textColor=RL_BLACK, leading=13, spaceAfter=3)
    s("note",        fontName="Helvetica-Oblique",  fontSize=7.5, textColor=colors.HexColor("#777777"), leading=11, spaceAfter=3)
    s("kpi_val",     fontName="Helvetica-Bold",    fontSize=20, textColor=RL_GREEN, alignment=TA_CENTER, leading=24)
    s("kpi_lbl",     fontName="Helvetica",          fontSize=7.5, textColor=colors.HexColor("#555555"), alignment=TA_CENTER, leading=10)
    s("kpi_delta_pos", fontName="Helvetica-Bold",  fontSize=8, textColor=RL_MID, alignment=TA_CENTER, leading=11)
    s("kpi_delta_neg", fontName="Helvetica-Bold",  fontSize=8, textColor=RL_RED, alignment=TA_CENTER, leading=11)
    s("th",          fontName="Helvetica-Bold",    fontSize=7.5, textColor=RL_WHITE, alignment=TA_CENTER, leading=10)
    s("td",          fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_CENTER, leading=10)
    s("td_l",        fontName="Helvetica",          fontSize=7.5, textColor=RL_BLACK, alignment=TA_LEFT,   leading=10)
    return S


# ── HELPERS ────────────────────────────────────────────────────────────────────

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
    """items = [(label, value, delta_str, positive?), ...]  — delta is optional (pass None)"""
    n = len(items)
    cells = []
    for item in items:
        label, val = item[0], item[1]
        delta = item[2] if len(item) > 2 else None
        pos   = item[3] if len(item) > 3 else True
        content = [Paragraph(str(val), S["kpi_val"]), Paragraph(str(label), S["kpi_lbl"])]
        if delta:
            content.append(Paragraph(str(delta), S["kpi_delta_pos"] if pos else S["kpi_delta_neg"]))
        cells.append(content)
    t = Table([cells], colWidths=[INNER_W / n] * n)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), RL_LGREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ] + [("BOX", (i, 0), (i, 0), 0.4, RL_GREY) for i in range(n)]))
    return t


def _build_doc(buf, report_title):
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

    def _inner_pg(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(RL_GREEN)
        canvas.rect(0, PAGE_H - 1.05 * cm, PAGE_W, 1.05 * cm, fill=1, stroke=0)
        canvas.setFillColor(RL_WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(MARGIN, PAGE_H - 0.7 * cm, "chickpea.")
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.7 * cm, report_title)
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


# ── MAIN ───────────────────────────────────────────────────────────────────────

def generate_summary_pdf(
    report_title: str,
    period_label: str,
    prev_label: str,
    # Restaurant
    cur_res: int = 0,
    cur_covers: int = 0,
    prev_res: int = 0,
    prev_covers: int = 0,
    by_pub_df=None,        # DataFrame with Pub, Reservations, Covers (+ optional prev/change cols)
    top_pub: str = "",
    bottom_pub: str = "",
    # Rooms
    room_stays: int = 0,
    room_stays_prev: int = 0,
    room_guests: int = 0,
    room_guests_prev: int = 0,
    room_nights: int = 0,
    room_revenue: float = 0,
    rooms_by_prop_df=None,  # DataFrame with Property, Stays, Guests, Revenue
    # Feedback
    avg_rating: float = None,
    five_star: int = 0,
    low_ratings: int = 0,
    # Upcoming
    covers_28: int = 0,
    functions_df=None,      # DataFrame with Date, Pub, Guest, Party Size
) -> bytes:
    """
    Build a branded summary (weekly/monthly) PDF from already-computed dashboard data.
    """
    S   = _styles()
    buf = io.BytesIO()
    doc = _build_doc(buf, report_title)
    E   = []

    # ── Cover ──
    E.append(Spacer(1, PAGE_H * 0.22))
    if os.path.exists(LOGO_PATH):
        logo = Image(LOGO_PATH, width=5 * cm, height=5 * cm, kind="proportional")
        logo.hAlign = "CENTER"
        E.append(logo)
        E.append(Spacer(1, 0.6 * cm))
    E += [
        Paragraph(report_title, S["cover_title"]),
        Spacer(1, 0.3 * cm),
        Paragraph(period_label, S["cover_sub"]),
        Spacer(1, 0.2 * cm),
        Paragraph(f"Generated {date.today().strftime('%d %b %Y')}", S["cover_date"]),
    ]
    E.append(NextPageTemplate("Inner"))
    E.append(PageBreak())

    # ── Restaurant Performance ──
    E += _section("Restaurant Performance", S)

    res_delta = cur_res - prev_res
    cov_delta = cur_covers - prev_covers
    E.append(_kpi_row([
        ("Reservations", f"{cur_res:,}",
         f"{res_delta:+,} vs {prev_label}", res_delta >= 0),
        ("Covers", f"{cur_covers:,}",
         f"{cov_delta:+,} vs {prev_label}", cov_delta >= 0),
        (f"{prev_label} Reservations", f"{prev_res:,}"),
        (f"{prev_label} Covers",       f"{prev_covers:,}"),
    ], S))

    if by_pub_df is not None and len(by_pub_df) > 0:
        E.append(Spacer(1, 0.2 * cm))
        E.append(Paragraph("By pub", S["subsection"]))
        cols   = list(by_pub_df.columns)
        n_cols = len(cols)
        frac_pub  = 0.28
        frac_rest = (1 - frac_pub) / (n_cols - 1)
        fracs     = [frac_pub] + [frac_rest] * (n_cols - 1)
        rows  = [[Paragraph(c, S["th"]) for c in cols]]
        for _, row in by_pub_df.iterrows():
            rows.append([Paragraph(str(row[cols[0]]), S["td_l"])]
                        + [Paragraph(str(row[c]), S["td"]) for c in cols[1:]])
        E.append(KeepTogether([_tbl(rows, fracs)]))
        if top_pub:
            E.append(Spacer(1, 0.1 * cm))
            E.append(Paragraph(
                f"Top performer: <b>{top_pub}</b>   ·   Needs attention: <b>{bottom_pub}</b>",
                S["note"],
            ))
    E.append(Spacer(1, 0.3 * cm))

    # ── Rooms Performance ──
    E += _section("Rooms Performance", S)
    E.append(_kpi_row([
        ("Stays",        f"{room_stays:,}",
         f"{room_stays - room_stays_prev:+,} vs {prev_label}", room_stays >= room_stays_prev),
        ("Guests",       f"{room_guests:,}",
         f"{room_guests - room_guests_prev:+,} vs {prev_label}", room_guests >= room_guests_prev),
        ("Nights Sold",  f"{room_nights:,}"),
        ("Room Revenue", f"£{room_revenue:,.0f}" if room_revenue > 0 else "—"),
    ], S))

    if rooms_by_prop_df is not None and len(rooms_by_prop_df) > 0:
        E.append(Spacer(1, 0.2 * cm))
        E.append(Paragraph("By property", S["subsection"]))
        cols  = list(rooms_by_prop_df.columns)
        n_c   = len(cols)
        fracs = [0.35] + [(0.65 / (n_c - 1))] * (n_c - 1)
        rows  = [[Paragraph(c, S["th"]) for c in cols]]
        for _, row in rooms_by_prop_df.iterrows():
            rows.append([Paragraph(str(row[cols[0]]), S["td_l"])]
                        + [Paragraph(str(row[c]), S["td"]) for c in cols[1:]])
        E.append(KeepTogether([_tbl(rows, fracs)]))
    E.append(Spacer(1, 0.3 * cm))

    # ── Guest Feedback ──
    E += _section("Guest Feedback", S)
    if avg_rating is not None:
        E.append(_kpi_row([
            ("Avg Rating",        f"{avg_rating:.2f} / 5"),
            ("5-Star Reviews",    f"{five_star:,}"),
            ("Low Ratings (<3★)", f"{low_ratings:,}"),
        ], S))
    else:
        E.append(Paragraph("No feedback data loaded for this period.", S["body"]))
    E.append(Spacer(1, 0.3 * cm))

    # ── Upcoming Highlights ──
    E += _section("Upcoming Highlights", S)
    E.append(Paragraph(
        f"Covers booked in the next 28 days: <b>{covers_28:,}</b>",
        S["body"],
    ))
    if functions_df is not None and len(functions_df) > 0:
        E.append(Spacer(1, 0.15 * cm))
        E.append(Paragraph(f"Functions (16+ covers) in the next 14 days: {len(functions_df)}", S["subsection"]))
        cols  = list(functions_df.columns)
        n_c   = len(cols)
        fracs = [1 / n_c] * n_c
        rows  = [[Paragraph(c, S["th"]) for c in cols]]
        for _, row in functions_df.iterrows():
            rows.append([Paragraph(str(row[cols[0]]), S["td_l"])]
                        + [Paragraph(str(row[c]), S["td"]) for c in cols[1:]])
        E.append(KeepTogether([_tbl(rows, fracs)]))

    doc.build(E)
    return buf.getvalue()
