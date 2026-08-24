"""
Chickpea Pubs — Room Revenue Report
Fetches confirmed eviivo bookings for a date range and produces a PDF.

Usage:
    python room_revenue_report.py                          # current month
    python room_revenue_report.py 2026-04-01 2026-04-30   # specific range
    python room_revenue_report.py 2026-04-01 2026-04-30 "The Bell & Crown"

Output: room_revenue_YYYYMMDD_YYYYMMDD.pdf  (saved in the same folder)
"""

import io
import sys
from datetime import date
from calendar import monthrange

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from eviivo_api import EviivoClient
from pub_mapping import EVIIVO_PROPERTY_MAPPINGS


# ── Brand colours ──────────────────────────────────────────────────────────────
RL_GREEN = colors.HexColor("#1C3829")
RL_LIGHT = colors.HexColor("#C8DFC8")
RL_LGREY = colors.HexColor("#F5F5F5")
RL_GREY  = colors.HexColor("#E4E4E4")
RL_WHITE = colors.white
RL_BLACK = colors.black

PAGE_W, PAGE_H = A4
MARGIN  = 1.5 * cm
INNER_W = PAGE_W - 2 * MARGIN


# ── Styles ─────────────────────────────────────────────────────────────────────

def _styles():
    S = {}
    def s(name, **kw):
        S[name] = ParagraphStyle(name, **kw)
    s("cover_title", fontName="Helvetica-Bold",  fontSize=28, textColor=RL_WHITE, alignment=TA_CENTER, leading=34)
    s("cover_sub",   fontName="Helvetica",        fontSize=12, textColor=RL_LIGHT, alignment=TA_CENTER, leading=16)
    s("cover_date",  fontName="Helvetica",        fontSize=9,  textColor=RL_LIGHT, alignment=TA_CENTER, leading=13)
    s("section",     fontName="Helvetica-Bold",   fontSize=13, textColor=RL_GREEN, leading=18, spaceBefore=4, spaceAfter=3)
    s("kpi_val",     fontName="Helvetica-Bold",   fontSize=24, textColor=RL_GREEN, alignment=TA_CENTER, leading=28)
    s("kpi_lbl",     fontName="Helvetica",        fontSize=8,  textColor=colors.HexColor("#555555"), alignment=TA_CENTER, leading=11)
    s("th",          fontName="Helvetica-Bold",   fontSize=8.5, textColor=RL_WHITE, alignment=TA_CENTER, leading=12)
    s("td",          fontName="Helvetica",        fontSize=8.5, textColor=RL_BLACK, alignment=TA_CENTER, leading=12)
    s("td_l",        fontName="Helvetica",        fontSize=8.5, textColor=RL_BLACK, alignment=TA_LEFT,   leading=12)
    s("td_r",        fontName="Helvetica",        fontSize=8.5, textColor=RL_BLACK, alignment=TA_RIGHT,  leading=12)
    return S


_BASE_TS = [
    ("BACKGROUND",    (0, 0), (-1, 0),  RL_GREEN),
    ("TEXTCOLOR",     (0, 0), (-1, 0),  RL_WHITE),
    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("FONTSIZE",      (0, 0), (-1, -1), 8.5),
    ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [RL_WHITE, RL_LGREY]),
    ("TOPPADDING",    (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING",   (0, 0), (0, -1),  6),
]


def _tbl(rows, col_fracs, extra_style=None):
    col_w = [INNER_W * f for f in col_fracs]
    ts = list(_BASE_TS) + (extra_style or [])
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle(ts))
    return t


def _section(title, S):
    return [
        Spacer(1, 0.35 * cm),
        Paragraph(title, S["section"]),
        HRFlowable(width=INNER_W, thickness=1, color=RL_LIGHT, spaceAfter=6),
    ]


def _kpi_row(items, S):
    n = len(items)
    cells = [[Paragraph(str(v), S["kpi_val"]), Paragraph(str(l), S["kpi_lbl"])] for l, v in items]
    t = Table([cells], colWidths=[INNER_W / n] * n)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), RL_LGREY),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ] + [("BOX", (i, 0), (i, 0), 0.4, RL_GREY) for i in range(n)]))
    return t


def _build_doc(buf, period_str):
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
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.7 * cm, f"Room Revenue Report  ·  {period_str}")
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.setFont("Helvetica", 6.5)
        canvas.drawString(MARGIN, 0.5 * cm, "Confidential — Chickpea Pub Group")
        canvas.drawRightString(PAGE_W - MARGIN, 0.5 * cm, f"Page {doc.page - 1}")
        canvas.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="Cover", frames=[cover_frame], onPage=_cover_bg),
        PageTemplate(id="Inner", frames=[inner_frame], onPage=_inner_pg),
    ])
    return doc


# ── PDF content ─────────────────────────────────────────────────────────────────

def generate_pdf(stays_raw, start_date, end_date, venue_filter="All Properties"):
    df = pd.DataFrame(stays_raw)
    df = df[df["status"] != "Cancelled"].copy()
    if venue_filter != "All Properties" and "venue_name" in df.columns:
        df = df[df["venue_name"] == venue_filter]

    df["total_value"]   = pd.to_numeric(df.get("total_value", 0), errors="coerce").fillna(0)
    df["checkin_dt"]    = pd.to_datetime(df["date"], errors="coerce")
    df["checkin_month"] = df["checkin_dt"].dt.to_period("M")

    total_stays   = len(df)
    total_revenue = df["total_value"].sum()

    S          = _styles()
    buf        = io.BytesIO()
    period_str = f"{start_date.strftime('%d %b %Y')} – {end_date.strftime('%d %b %Y')}"
    doc        = _build_doc(buf, period_str)
    E          = []

    # Cover
    E.append(Spacer(1, PAGE_H * 0.28))
    E += [
        Paragraph("Room Revenue Report", S["cover_title"]),
        Spacer(1, 0.35 * cm),
        Paragraph(venue_filter, S["cover_sub"]),
        Spacer(1, 0.2 * cm),
        Paragraph(period_str, S["cover_date"]),
        Spacer(1, 0.15 * cm),
        Paragraph(f"Generated {date.today().strftime('%d %b %Y')}", S["cover_date"]),
        Spacer(1, 0.15 * cm),
        Paragraph("Gross revenue including VAT  ·  Confirmed bookings only", S["cover_date"]),
    ]
    E.append(NextPageTemplate("Inner"))
    E.append(PageBreak())

    # Headline KPIs
    E += _section("Summary", S)
    E.append(_kpi_row([
        ("Confirmed Stays",           f"{total_stays:,}"),
        ("Gross Revenue (inc VAT)",   f"£{total_revenue:,.2f}" if total_revenue > 0 else "—"),
    ], S))
    E.append(Spacer(1, 0.4 * cm))

    # Revenue by property (only when showing multiple)
    if "venue_name" in df.columns and df["venue_name"].nunique() > 1:
        E += _section("Revenue by Property", S)
        by_prop = (
            df.groupby("venue_name")
            .agg(Stays=("total_value", "count"), Revenue=("total_value", "sum"))
            .reset_index()
            .sort_values("Revenue", ascending=False)
        )
        headers = ["Property", "Confirmed Stays", "Gross Revenue (inc VAT)"]
        fracs   = [0.50, 0.25, 0.25]
        rows    = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in by_prop.iterrows():
            rows.append([
                Paragraph(str(row["venue_name"]), S["td_l"]),
                Paragraph(str(int(row["Stays"])), S["td"]),
                Paragraph(f"£{row['Revenue']:,.2f}", S["td_r"]),
            ])
        rows.append([
            Paragraph("<b>TOTAL</b>", S["td_l"]),
            Paragraph(f"<b>{int(by_prop['Stays'].sum()):,}</b>", S["td"]),
            Paragraph(f"<b>£{by_prop['Revenue'].sum():,.2f}</b>", S["td_r"]),
        ])
        E.append(_tbl(rows, fracs, [
            ("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), RL_LIGHT),
            ("FONTNAME",   (0, len(rows) - 1), (-1, len(rows) - 1), "Helvetica-Bold"),
        ]))
        E.append(Spacer(1, 0.4 * cm))

    # Revenue by month
    if df["checkin_month"].nunique() > 0:
        E += _section("Revenue by Month", S)
        by_month = (
            df.groupby("checkin_month")
            .agg(Stays=("total_value", "count"), Revenue=("total_value", "sum"))
            .reset_index()
            .sort_values("checkin_month")
        )
        headers = ["Month", "Confirmed Stays", "Gross Revenue (inc VAT)"]
        fracs   = [0.50, 0.25, 0.25]
        rows    = [[Paragraph(h, S["th"]) for h in headers]]
        for _, row in by_month.iterrows():
            rows.append([
                Paragraph(row["checkin_month"].strftime("%B %Y"), S["td_l"]),
                Paragraph(str(int(row["Stays"])), S["td"]),
                Paragraph(f"£{row['Revenue']:,.2f}", S["td_r"]),
            ])
        rows.append([
            Paragraph("<b>TOTAL</b>", S["td_l"]),
            Paragraph(f"<b>{int(by_month['Stays'].sum()):,}</b>", S["td"]),
            Paragraph(f"<b>£{by_month['Revenue'].sum():,.2f}</b>", S["td_r"]),
        ])
        E.append(_tbl(rows, fracs, [
            ("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), RL_LIGHT),
            ("FONTNAME",   (0, len(rows) - 1), (-1, len(rows) - 1), "Helvetica-Bold"),
        ]))

    doc.build(E)
    return buf.getvalue()


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    today = date.today()

    # Parse args: [from_date] [to_date] [venue]
    args = sys.argv[1:]
    if len(args) >= 2:
        from_date = date.fromisoformat(args[0])
        to_date   = date.fromisoformat(args[1])
    else:
        # Default: current month
        from_date = today.replace(day=1)
        last_day  = monthrange(today.year, today.month)[1]
        to_date   = today.replace(day=last_day)

    venue_filter = args[2] if len(args) >= 3 else "All Properties"

    print(f"Fetching bookings {from_date} – {to_date}  |  {venue_filter}")

    client = EviivoClient()
    if not client.authenticate():
        print("ERROR: Could not authenticate with eviivo. Check credentials in config.py.")
        sys.exit(1)

    if venue_filter == "All Properties":
        mappings = {k: v for k, v in EVIIVO_PROPERTY_MAPPINGS.items() if v}
    else:
        prop = EVIIVO_PROPERTY_MAPPINGS.get(venue_filter)
        if not prop:
            print(f"ERROR: Unknown venue '{venue_filter}'. Valid options:")
            for k in EVIIVO_PROPERTY_MAPPINGS:
                print(f"  {k}")
            sys.exit(1)
        mappings = {venue_filter: prop}

    all_stays = []
    for vname, shortname in mappings.items():
        print(f"  {vname} ({shortname})…", end=" ", flush=True)
        stays = client.get_bookings_range(shortname, from_date, to_date)
        for s in stays:
            s["venue_name"] = vname
        all_stays.extend(stays)
        print(f"{len(stays)} bookings")

    confirmed = [s for s in all_stays if s.get("status") != "Cancelled"]
    total_rev = sum(s.get("total_value", 0) or 0 for s in confirmed)
    print(f"\n{len(confirmed)} confirmed stays  |  Total gross revenue: £{total_rev:,.2f}")

    if not confirmed:
        print("No confirmed bookings found — no PDF generated.")
        sys.exit(0)

    print("Building PDF…")
    pdf_bytes = generate_pdf(all_stays, from_date, to_date, venue_filter)

    filename = f"room_revenue_{from_date.strftime('%Y%m%d')}_{to_date.strftime('%Y%m%d')}.pdf"
    with open(filename, "wb") as f:
        f.write(pdf_bytes)
    print(f"Saved: {filename}")


if __name__ == "__main__":
    main()
