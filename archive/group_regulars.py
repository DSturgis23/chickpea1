"""
SevenRooms Frequent Guests Export
Fetches all guests who have visited more than 5 times in the last 3 months,
across all venues, and exports to PDF.

Usage:
    python group_regulars.py

Output:
    frequent_guests_YYYY-MM-DD.pdf in the current directory
"""

import requests
import sys
import os
from collections import defaultdict
from datetime import datetime, timedelta

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_LEFT

# --- Credentials ---
CLIENT_ID     = "dcc8dabbbd8de6f13b9831b31535eac35f0792ba6caec7cd2418fb72d1cc90acac580700da9861dfa64f17988b3dcbdd651e3e5fcd626aeb1e70689a37daa962"
CLIENT_SECRET = "40590241a64c8988a36341b5245c04eaaac175d3742ab8e09bea7b7fd46cdf56dda467c75934b5a2c557725a4411efad473a0d54747a2aa6291e6a21c7d21d51"
API_BASE_URL  = "https://api.sevenrooms.com/2_4"

MIN_VISITS    = 3          # more than this many visits
LOOKBACK_DAYS = 180        # last 6 months

CHICKPEA_GREEN = colors.HexColor("#2E7D32")
LIGHT_GREEN    = colors.HexColor("#E8F5E9")
MID_GREEN      = colors.HexColor("#A5D6A7")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def authenticate():
    print("Authenticating...")
    resp = requests.post(f"{API_BASE_URL}/auth",
                         data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
                         timeout=30)
    resp.raise_for_status()
    token = (resp.json().get("data", {}).get("token")
             or resp.json().get("token")
             or resp.json().get("access_token"))
    if not token:
        print("ERROR: no token in response:", resp.json())
        sys.exit(1)
    print("  OK")
    return token


def h(token):
    return {"Authorization": token, "Content-Type": "application/json"}


def get_venues(token):
    """Return {venue_id: venue_name} for all venues."""
    venues = {}
    cursor = None
    while True:
        params = {"cursor": cursor} if cursor else {}
        resp = requests.get(f"{API_BASE_URL}/venues", headers=h(token),
                            params=params or None, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for v in data.get("data", {}).get("results", []):
            venues[v["id"]] = v.get("name", v["id"])
        cursor = data.get("data", {}).get("cursor")
        if not cursor:
            break
    print(f"  Found {len(venues)} venue(s): {list(venues.values())}")
    return venues


def fetch_reservations(token, venue_id, from_date, to_date):
    """Fetch all reservations for a venue in the date range."""
    results, cursor = [], None
    while True:
        params = {
            "venue_id":  venue_id,
            "from_date": from_date,
            "to_date":   to_date,
            "limit":     400,
        }
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{API_BASE_URL}/reservations", headers=h(token),
                            params=params, timeout=60)
        if resp.status_code != 200:
            print(f"  Warning: {resp.status_code} fetching reservations for {venue_id}")
            break
        data = resp.json()
        page = data.get("data", {}).get("results", [])
        results.extend(page)
        cursor = data.get("data", {}).get("cursor")
        if not cursor:
            break
    return results


def fetch_client(token, client_id):
    """Fetch a single client profile by ID."""
    resp = requests.get(f"{API_BASE_URL}/clients/{client_id}",
                        headers=h(token), timeout=30)
    if resp.status_code == 200:
        return resp.json().get("data", resp.json())
    return None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def find_frequent_guests(token, venue_map):
    """
    Pull all reservations for the last 3 months across all venues.
    Count visits per client_id. Return those with more than MIN_VISITS.
    Also track which venues each guest visited.
    """
    from_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    to_date   = datetime.now().strftime("%Y-%m-%d")

    # client_id -> {visit_count, venues, last_visit, name}
    visit_counts  = defaultdict(int)
    client_venues = defaultdict(set)
    client_meta   = {}  # client_id -> basic info from reservation

    for venue_id, venue_name in venue_map.items():
        print(f"  Fetching reservations: {venue_name}...")
        reservations = fetch_reservations(token, venue_id, from_date, to_date)
        print(f"    {len(reservations)} reservation(s)")

        for r in reservations:
            # Only count completed/attended visits, not cancellations
            status = r.get("status", "").upper()
            if status in ("CANCELED", "CANCELLED", "NO_SHOW"):
                continue

            cid = r.get("client_id")
            if not cid:
                continue

            visit_counts[cid] += 1
            client_venues[cid].add(venue_name)

            # Keep the most recent reservation's metadata
            res_date = r.get("date", "")
            existing = client_meta.get(cid, {})
            if not existing or res_date > existing.get("last_visit", ""):
                client_meta[cid] = {
                    "first_name":  r.get("first_name", ""),
                    "last_name":   r.get("last_name", ""),
                    "email":       r.get("email", ""),
                    "phone":       r.get("phone_number", ""),
                    "last_visit":  res_date,
                }

    # Filter to guests with more than MIN_VISITS
    frequent = {
        cid: count
        for cid, count in visit_counts.items()
        if count > MIN_VISITS
    }
    print(f"\n  {len(frequent)} guest(s) with more than {MIN_VISITS} visits in the last {LOOKBACK_DAYS} days.")
    return frequent, client_venues, client_meta


def enrich_with_profiles(token, client_ids):
    """
    Fetch full client profiles for a list of client IDs.
    Returns {client_id: profile_dict}.
    """
    print(f"\nFetching full profiles for {len(client_ids)} guest(s)...")
    profiles = {}
    for i, cid in enumerate(client_ids, 1):
        profile = fetch_client(token, cid)
        if profile:
            profiles[cid] = profile
        if i % 10 == 0:
            print(f"  ...{i}/{len(client_ids)}")
    print(f"  Done — {len(profiles)} profile(s) retrieved.")
    return profiles


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def build_pdf(frequent, client_venues, client_meta, profiles, filename):
    from reportlab.lib.pagesizes import landscape
    doc = SimpleDocTemplate(filename, pagesize=landscape(A4),
                            leftMargin=20*mm, rightMargin=20*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("t", parent=styles["Heading1"],
                                 textColor=CHICKPEA_GREEN, fontSize=20,
                                 spaceAfter=4, alignment=TA_LEFT)
    sub_style   = ParagraphStyle("s", parent=styles["Normal"],
                                 textColor=colors.HexColor("#555555"),
                                 fontSize=10, spaceAfter=12)
    header_style = ParagraphStyle("h", parent=styles["Normal"],
                                  textColor=colors.white,
                                  fontName="Helvetica-Bold", fontSize=10)
    cell_style  = ParagraphStyle("c", parent=styles["Normal"],
                                 fontSize=10, leading=13)

    from_date_str = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%d %B %Y")
    to_date_str   = datetime.now().strftime("%d %B %Y")

    story = []
    story.append(Paragraph("Chickpea — Frequent Guests", title_style))
    story.append(Paragraph(
        f"Generated {datetime.now().strftime('%d %B %Y, %H:%M')}  |  "
        f"More than {MIN_VISITS} visits between {from_date_str} and {to_date_str}  |  "
        f"{len(frequent)} guest(s)",
        sub_style))
    story.append(Spacer(1, 4*mm))

    # Landscape A4 usable width = 257mm
    col_headers = [
        Paragraph("Guest Name",       header_style),
        Paragraph("Email",            header_style),
        Paragraph("Visits (6 months)", header_style),
        Paragraph("Pubs Visited",     header_style),
    ]
    col_widths = [55*mm, 75*mm, 35*mm, 92*mm]

    table_data = [col_headers]

    for cid, visit_count in sorted(frequent.items(), key=lambda x: x[1], reverse=True):
        meta    = client_meta.get(cid, {})
        profile = profiles.get(cid, {})

        first = profile.get("first_name") or meta.get("first_name", "")
        last  = profile.get("last_name")  or meta.get("last_name", "")
        email = profile.get("email")      or meta.get("email", "")
        phone = profile.get("phone_number") or meta.get("phone", "")
        name  = f"{first} {last}".strip()

        # Skip guests with no email and no phone
        if not email.strip() and not phone.strip():
            continue

        venues_str = ", ".join(sorted(client_venues.get(cid, set())))

        row = [
            Paragraph(name,             cell_style),
            Paragraph(email,            cell_style),
            Paragraph(str(visit_count), cell_style),
            Paragraph(venues_str,       cell_style),
        ]
        table_data.append(row)

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), CHICKPEA_GREEN),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, LIGHT_GREEN]),
        ("GRID",          (0, 0), (-1, -1), 0.5, MID_GREEN),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    doc.build(story)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

def build_excel(frequent, client_venues, client_meta, profiles, filename):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Frequent Guests"

    header_fill   = PatternFill("solid", fgColor="2E7D32")
    alt_fill      = PatternFill("solid", fgColor="E8F5E9")
    header_font   = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    cell_font     = Font(name="Calibri", size=11)
    thin_border   = Border(
        left=Side(style="thin", color="A5D6A7"),
        right=Side(style="thin", color="A5D6A7"),
        top=Side(style="thin", color="A5D6A7"),
        bottom=Side(style="thin", color="A5D6A7"),
    )
    center_align  = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align    = Alignment(horizontal="left",   vertical="center", wrap_text=True)

    headers = ["Guest Name", "Email", "Visits (6 months)", "Pubs Visited"]
    col_widths = [30, 40, 20, 60]

    for col, (header, width) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font      = header_font
        cell.fill      = header_fill
        cell.alignment = center_align
        cell.border    = thin_border
        ws.column_dimensions[cell.column_letter].width = width

    ws.row_dimensions[1].height = 20

    for row_idx, (cid, visit_count) in enumerate(
        sorted(frequent.items(), key=lambda x: x[1], reverse=True), start=2
    ):
        meta    = client_meta.get(cid, {})
        profile = profiles.get(cid, {})

        first = profile.get("first_name") or meta.get("first_name", "")
        last  = profile.get("last_name")  or meta.get("last_name", "")
        email = profile.get("email")      or meta.get("email", "")
        phone = profile.get("phone_number") or meta.get("phone", "")
        name  = f"{first} {last}".strip()

        if not email.strip() and not phone.strip():
            continue

        venues_str = ", ".join(sorted(client_venues.get(cid, set())))
        fill = alt_fill if row_idx % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")

        for col, value in enumerate([name, email, visit_count, venues_str], 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.font      = cell_font
            cell.fill      = fill
            cell.border    = thin_border
            cell.alignment = center_align if col == 3 else left_align

    # Freeze header row
    ws.freeze_panes = "A2"

    wb.save(filename)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    token = authenticate()

    print("\nFetching venues...")
    venue_map = get_venues(token)
    if not venue_map:
        print("No venues found.")
        sys.exit(1)

    print(f"\nCounting visits per guest over the last {LOOKBACK_DAYS} days...")
    frequent, client_venues, client_meta = find_frequent_guests(token, venue_map)

    if not frequent:
        print("No guests found with more than 5 visits in the last 3 months.")
        sys.exit(0)

    profiles = enrich_with_profiles(token, list(frequent.keys()))

    datestamp = datetime.now().strftime('%Y-%m-%d')

    pdf_file = f"frequent_guests_{datestamp}.pdf"
    print(f"\nBuilding PDF...")
    build_pdf(frequent, client_venues, client_meta, profiles, pdf_file)
    print(f"  Saved to: {os.path.abspath(pdf_file)}")

    xlsx_file = f"frequent_guests_{datestamp}.xlsx"
    print(f"Building Excel spreadsheet...")
    build_excel(frequent, client_venues, client_meta, profiles, xlsx_file)
    print(f"  Saved to: {os.path.abspath(xlsx_file)}")


if __name__ == "__main__":
    main()
