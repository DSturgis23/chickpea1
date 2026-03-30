"""
Chickpea Pubs - Table Reservations Dashboard
Displays reservation data from SevenRooms across 12 pubs
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
import os

st.set_page_config(
    page_title="Chickpea Reservations",
    page_icon="🍺",
    layout="wide"
)

# === PASSWORD PROTECTION ===
def check_password():
    """Returns True if the user has entered the correct password."""
    correct_password = os.environ.get("DASHBOARD_PASSWORD")
    if not correct_password:
        try:
            correct_password = st.secrets.get("password")
        except:
            pass
    if not correct_password:
        correct_password = "chickpea2024"

    if "password_ok" not in st.session_state:
        st.session_state.password_ok = False

    if st.session_state.password_ok:
        return True

    st.title("Chickpea Reservations")
    st.markdown("Please enter the password to access the dashboard.")
    password = st.text_input("Password", type="password", key="password_input")

    if st.button("Login", type="primary"):
        if password == correct_password:
            st.session_state.password_ok = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False

if not check_password():
    st.stop()

# === MAIN DASHBOARD ===
from sevenrooms_api import SevenRoomsClient
from eviivo_api import EviivoClient
from pub_mapping import get_all_eviivo_properties

st.title("Chickpea Pubs - Reservations Dashboard")

# Create tabs
tab_operations, tab_analytics, tab_marketing, tab_sales, tab_rooms = st.tabs(["📅 Operations", "📊 Analytics", "📣 Marketing", "🍽️ Sales & Food", "🛏️ Rooms Intelligence"])

# Initialize clients
@st.cache_resource
def get_sevenrooms_client():
    return SevenRoomsClient()

@st.cache_resource
def get_eviivo_client():
    return EviivoClient()

client = get_sevenrooms_client()
eviivo_client = get_eviivo_client()

# === DATA LOADING FUNCTIONS ===

def load_data():
    """Load venues and reservations from SevenRooms (fresh, no cache for Operations)"""
    if not client.authenticate():
        return None, None, None, None, None, []

    venues_resp = client.get_venues()
    venues = venues_resp.get("data", {}).get("results", []) if venues_resp else []

    # Fetch reservations from today through 90 days out
    from_date = datetime.now()
    to_date = datetime.now() + timedelta(days=90)
    res_resp = client.get_reservations(from_date=from_date, to_date=to_date)
    reservations = res_resp.get("data", {}).get("results", []) if res_resp else []

    # Fetch historical data — 400 days to cover last year's equivalent dates for YoY comparison
    hist_from = datetime.now() - timedelta(days=400)
    hist_to = datetime.now() - timedelta(days=1)
    hist_resp = client.get_reservations(from_date=hist_from, to_date=hist_to)
    historical = hist_resp.get("data", {}).get("results", []) if hist_resp else []

    # Fetch eviivo room bookings for today + historical stays (last 365 days)
    eviivo_bookings = []
    eviivo_historical = []
    try:
        if eviivo_client.authenticate():
            property_mappings = get_all_eviivo_properties()
            eviivo_bookings = eviivo_client.get_all_bookings(property_mappings, date.today())
            eviivo_historical = eviivo_client.get_all_historical_bookings(
                property_mappings,
                checkin_from=datetime.now() - timedelta(days=365),
                checkin_to=datetime.now() - timedelta(days=1),
            )
            print(f"eviivo: {len(eviivo_bookings)} tonight, {len(eviivo_historical)} historical stays")
    except Exception as e:
        print(f"eviivo error: {e}")

    # Fetch historical feedback for guest matching (last 180 days)
    feedback_for_alerts = []
    try:
        feedback_resp = client.get_feedback(
            from_date=datetime.now() - timedelta(days=180),
            to_date=datetime.now()
        )
        feedback_for_alerts = feedback_resp.get("data", {}).get("results", []) if feedback_resp else []
    except Exception as e:
        print(f"Feedback fetch error: {e}")

    return venues, reservations, historical, eviivo_bookings, eviivo_historical, feedback_for_alerts

# Cached functions for Analytics (historical data doesn't change)
@st.cache_data(ttl=600, show_spinner=False)  # Cache for 10 minutes
def load_analytics_reservations(_client, from_date_str, to_date_str):
    """Load historical reservations with caching"""
    if not _client._ensure_authenticated():
        return []
    resp = _client.get_reservations(from_date=from_date_str, to_date=to_date_str)
    return resp.get("data", {}).get("results", []) if resp else []

@st.cache_data(ttl=600, show_spinner=False)  # Cache for 10 minutes
def load_analytics_feedback(_client, from_date_str, to_date_str):
    """Load feedback with caching"""
    if not hasattr(_client, 'get_feedback'):
        return [], None
    try:
        resp = _client.get_feedback(from_date=from_date_str, to_date=to_date_str)
        results = resp.get("data", {}).get("results", []) if resp else []
        endpoint = resp.get("endpoint_used") if resp else None
        return results, endpoint
    except Exception:
        return [], None


# === LOW-RATING GUEST ALERT HELPERS ===

def normalize_phone(phone):
    """Normalize phone number for matching."""
    if not phone:
        return ''
    return ''.join(c for c in str(phone) if c.isdigit())[-10:]  # Last 10 digits


def normalize_name(first, last):
    """Normalize name for matching."""
    full = f"{first or ''} {last or ''}".lower().strip()
    return ' '.join(full.split())  # Collapse whitespace


def build_low_rating_lookup(feedback_list):
    """
    Build a lookup of guests who left ratings < 3 stars.
    Returns dict keyed by (type, value) with feedback details.
    """
    low_ratings = {}

    if not feedback_list:
        return low_ratings

    # Find rating column - SevenRooms uses 'overall'
    rating_col = None
    for col in ['overall', 'overall_rating', 'overallRating', 'rating', 'stars', 'score']:
        if feedback_list and col in feedback_list[0]:
            rating_col = col
            break

    if not rating_col:
        return low_ratings

    for fb in feedback_list:
        try:
            raw_rating = fb.get(rating_col, 5)
            if raw_rating is None or str(raw_rating).strip() == '':
                continue
            rating = float(raw_rating)
            if rating <= 3:
                # Extract identifiers (enriched by _enrich_feedback_with_guest_data)
                email = str(fb.get('email', fb.get('guest_email', ''))).lower().strip()
                phone = normalize_phone(fb.get('phone_number', fb.get('phone', fb.get('telephone', ''))))
                first_name = fb.get('first_name', fb.get('firstName', ''))
                last_name = fb.get('last_name', fb.get('lastName', fb.get('surname', '')))
                name = normalize_name(first_name, last_name)

                # Find comment - SevenRooms uses 'notes'
                comment = ''
                for c in ['notes', 'comment', 'comments', 'feedback', 'text', 'review', 'additional_notes']:
                    if fb.get(c):
                        comment = str(fb[c])
                        break

                # Find venue
                venue_id = fb.get('venue_id', fb.get('venueId', ''))

                # Store by each identifier that exists
                entry = {
                    'rating': rating,
                    'comment': comment,
                    'venue_id': venue_id,
                    'date': fb.get('reservation_date', fb.get('date', fb.get('created', '')))
                }

                if email:
                    low_ratings[('email', email)] = entry
                if phone:
                    low_ratings[('phone', phone)] = entry
                if name:
                    low_ratings[('name', name)] = entry
        except (ValueError, TypeError):
            continue

    return low_ratings


def find_low_rating_match(reservation, low_rating_lookup, venue_map):
    """Check if a reservation guest has left a low rating."""
    email = str(reservation.get('email', '')).lower().strip()
    phone = normalize_phone(reservation.get('phone_number', reservation.get('phone', '')))
    name = normalize_name(reservation.get('first_name', ''), reservation.get('last_name', ''))

    # Check each identifier
    for key in [('email', email), ('phone', phone), ('name', name)]:
        if key[1] and key in low_rating_lookup:
            match = low_rating_lookup[key]
            venue_name = venue_map.get(match.get('venue_id', ''), 'Unknown')
            return {
                'rating': match['rating'],
                'comment': match['comment'],
                'venue': venue_name,
                'date': match['date']
            }
    return None


# Sidebar - global controls only
st.sidebar.header("Settings")

# Load/Refresh button
if st.sidebar.button("Refresh Data", type="primary") or 'venues' not in st.session_state:
    with st.spinner("Loading from SevenRooms and eviivo..."):
        venues, reservations, historical, eviivo_bookings, eviivo_historical, feedback_for_alerts = load_data()
        if venues is not None:
            st.session_state['venues'] = venues
            st.session_state['reservations'] = reservations
            st.session_state['historical'] = historical
            st.session_state['eviivo_bookings'] = eviivo_bookings or []
            st.session_state['eviivo_historical'] = eviivo_historical or []
            # Build low-rating lookup for alerts
            st.session_state['low_rating_lookup'] = build_low_rating_lookup(feedback_for_alerts)
            eviivo_msg = f", {len(eviivo_bookings)} room stays" if eviivo_bookings else ""
            st.sidebar.success(f"Loaded {len(venues)} pubs, {len(reservations)} future + {len(historical)} historical reservations{eviivo_msg}")
        else:
            st.sidebar.error("Failed to connect - check credentials")

# Logout button
st.sidebar.markdown("---")
if st.sidebar.button("Logout"):
    st.session_state.password_ok = False
    st.session_state.pop('venues', None)
    st.session_state.pop('reservations', None)
    st.rerun()
st.sidebar.caption("Chickpea Pub Group")

# Get data from session state
venues = st.session_state.get('venues', [])
reservations = st.session_state.get('reservations', [])
historical = st.session_state.get('historical', [])
eviivo_bookings = st.session_state.get('eviivo_bookings', [])

if not reservations:
    st.info("Click **Refresh Data** in the sidebar to fetch reservations from SevenRooms.")
    st.stop()

# Build DataFrame
df = pd.DataFrame(reservations)

# Map SevenRooms fields
if 'first_name' in df.columns:
    df['guest_name'] = (df['first_name'].fillna('') + ' ' + df['last_name'].fillna('')).str.strip()
if 'max_guests' in df.columns:
    df['party_size'] = pd.to_numeric(df['max_guests'], errors='coerce').fillna(0).astype(int)
if 'table_numbers' in df.columns:
    df['table'] = df['table_numbers'].apply(lambda x: ', '.join(x) if isinstance(x, list) and len(x) > 0 else '-')
if 'time_slot_iso' in df.columns:
    df['time'] = pd.to_datetime(df['time_slot_iso'], errors='coerce').dt.strftime('%H:%M')
if 'phone_number' in df.columns:
    df['phone'] = df['phone_number']
if 'venue_seating_area_name' in df.columns:
    df['seating_area'] = df['venue_seating_area_name'].fillna('-')
if 'reservation_type' in df.columns:
    df['occasion'] = df['reservation_type'].fillna('')
if 'status_display' in df.columns:
    df['status'] = df['status_display'].fillna('Unknown')
if 'shift_category' in df.columns:
    def map_meal_period(row):
        shift = str(row.get('shift_category', '')).upper()
        if shift == 'BREAKFAST':
            return 'Breakfast'
        elif shift == 'LUNCH':
            return 'Lunch'
        elif shift == 'DINNER':
            return 'Dinner'
        else:
            # For 'DAY' or anything else, determine from the parsed HH:MM time
            time_str = str(row.get('time', '') or '')
            if not time_str or time_str == 'nan':
                # Fall back to parsing time_slot_iso directly
                iso = str(row.get('time_slot_iso', '') or '')
                try:
                    time_str = pd.to_datetime(iso).strftime('%H:%M')
                except Exception:
                    time_str = ''
            if time_str and len(time_str) >= 2:
                try:
                    hour = int(time_str[:2])
                    return 'Lunch' if hour < 15 else 'Dinner'
                except Exception:
                    pass
            return 'Other'
    df['meal_period'] = df.apply(map_meal_period, axis=1)

# Combine notes
df['all_notes'] = df.apply(lambda r: ' | '.join(filter(None, [str(r.get('notes') or ''), str(r.get('client_requests') or '')])), axis=1)

# Parse date
if 'date' in df.columns:
    df['reservation_date'] = pd.to_datetime(df['date'], errors='coerce').dt.date

# Map venue names
venue_map = {v['id']: v['name'].strip() for v in venues}
if 'venue_id' in df.columns:
    df['venue_name'] = df['venue_id'].map(venue_map).fillna('Unknown')

# === PROCESS HISTORICAL DATA ===
df_hist = pd.DataFrame(historical) if historical else pd.DataFrame()

if len(df_hist) > 0:
    # Apply same transformations as main df
    if 'max_guests' in df_hist.columns:
        df_hist['party_size'] = pd.to_numeric(df_hist['max_guests'], errors='coerce').fillna(0).astype(int)
    if 'date' in df_hist.columns:
        df_hist['reservation_date'] = pd.to_datetime(df_hist['date'], errors='coerce').dt.date
    if 'venue_id' in df_hist.columns:
        df_hist['venue_name'] = df_hist['venue_id'].map(venue_map).fillna('Unknown')
    if 'status_display' in df_hist.columns:
        df_hist['status'] = df_hist['status_display'].fillna('Unknown')
    if 'shift_category' in df_hist.columns:
        if 'time_slot_iso' in df_hist.columns:
            df_hist['time'] = pd.to_datetime(df_hist['time_slot_iso'], errors='coerce').dt.strftime('%H:%M')
        def map_meal_period_hist(row):
            shift = str(row.get('shift_category', '')).upper()
            if shift == 'BREAKFAST':
                return 'Breakfast'
            elif shift == 'LUNCH':
                return 'Lunch'
            elif shift == 'DINNER':
                return 'Dinner'
            else:
                time_str = str(row.get('time', '') or '')
                if not time_str or time_str == 'nan':
                    iso = str(row.get('time_slot_iso', '') or '')
                    try:
                        time_str = pd.to_datetime(iso).strftime('%H:%M')
                    except Exception:
                        time_str = ''
                if time_str and len(time_str) >= 2:
                    try:
                        hour = int(time_str[:2])
                        return 'Lunch' if hour < 15 else 'Dinner'
                    except Exception:
                        pass
                return 'Other'
        df_hist['meal_period'] = df_hist.apply(map_meal_period_hist, axis=1)

# Helper function for formatting differences
def format_diff(current, last_week):
    """Format a value with difference from last week in brackets"""
    if last_week == '-':
        return str(current)
    diff = current - last_week
    if diff > 0:
        return f"{current} (+{diff})"
    elif diff < 0:
        return f"{current} ({diff})"
    else:
        return f"{current} (=)"

# === OPERATIONS TAB ===
with tab_operations:
    # Filters at top of Operations tab
    filter_col1, filter_col2, filter_col3, filter_col4, filter_col5 = st.columns([2, 2, 2, 2, 1])

    # Venue filter - exclude group-level entries
    venue_names = ["All Pubs"] + sorted([v['name'].strip() for v in venues if 'chickpea' not in v['name'].lower()])
    with filter_col1:
        selected_venue = st.selectbox("Pub", venue_names, key="ops_venue")

    # Date filter - future dates only
    today = date.today()
    future_dates = []
    if 'reservation_date' in df.columns:
        future_dates = [d for d in df['reservation_date'].dropna().unique() if d >= today]
        future_dates = sorted(future_dates)

    with filter_col2:
        if future_dates:
            max_date = max(future_dates)
            default_date = today if today in future_dates else future_dates[0]
            selected_date = st.date_input(
                "Date",
                value=default_date,
                min_value=today,
                max_value=max_date,
                format="DD/MM/YYYY",
                key="ops_date"
            )
        else:
            selected_date = today
            st.warning("No future reservations found")

    with filter_col3:
        source_options = ["All", "Reservations", "Room Stays"]
        selected_source = st.radio("Show", source_options, horizontal=True, key="ops_source")

    with filter_col4:
        hide_cancelled = st.checkbox("Hide cancelled", value=True, key="ops_hide_cancelled")

    with filter_col5:
        st.caption(f"{len(df)} res + {len(eviivo_bookings)} rooms")

    st.markdown("---")

    # === FETCH EVIIVO BOOKINGS FOR SELECTED DATE ===
    # Fetch eviivo bookings for the selected date (if different from today)
    eviivo_for_date = []
    if selected_date == today:
        eviivo_for_date = eviivo_bookings
    else:
        # Fetch eviivo bookings for the selected date
        try:
            if eviivo_client._ensure_authenticated():
                property_mappings = get_all_eviivo_properties()
                eviivo_for_date = eviivo_client.get_all_bookings(property_mappings, selected_date)
        except Exception as e:
            print(f"eviivo fetch error for {selected_date}: {e}")

    # === APPLY FILTERS ===
    df_filtered = df.copy()

    # Filter out cancelled bookings if checkbox is checked
    if hide_cancelled and 'status' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['status'] != 'Canceled']

    # Filter to future dates only
    if 'reservation_date' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['reservation_date'] >= today]

    # Filter by venue
    if selected_venue != "All Pubs" and 'venue_name' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['venue_name'] == selected_venue]

    # Filter by date - ensure types match
    if 'reservation_date' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['reservation_date'] == selected_date]

    # Add source/type columns for SevenRooms reservations
    df_filtered['source'] = 'sevenrooms'
    df_filtered['type'] = 'reservation'
    df_filtered['detail'] = df_filtered.get('table', '-')

    # === CREATE EVIIVO DATAFRAME ===
    df_eviivo = pd.DataFrame()
    if eviivo_for_date:
        df_eviivo = pd.DataFrame(eviivo_for_date)
        # Only show guests actually staying tonight (checkout must be after selected date)
        if 'checkout_date' in df_eviivo.columns:
            df_eviivo = df_eviivo[pd.to_datetime(df_eviivo['checkout_date'], errors='coerce') > pd.Timestamp(selected_date)]
        # Filter by venue if selected
        if selected_venue != "All Pubs" and 'venue_name' in df_eviivo.columns:
            df_eviivo = df_eviivo[df_eviivo['venue_name'] == selected_venue]
        # Filter by status if hide_cancelled
        if hide_cancelled and 'status' in df_eviivo.columns:
            df_eviivo = df_eviivo[~df_eviivo['status'].str.lower().isin(['cancelled', 'canceled'])]

    # Apply source filter
    if selected_source == "Reservations":
        df_eviivo = pd.DataFrame()  # Clear eviivo data
    elif selected_source == "Room Stays":
        df_filtered = pd.DataFrame()  # Clear SevenRooms data

    # Calculate comparison dates
    last_week_date = selected_date - timedelta(days=7)
    last_year_date = selected_date - timedelta(weeks=52)  # Same weekday last year

    def _filter_hist(target_date):
        if len(df_hist) == 0 or 'reservation_date' not in df_hist.columns:
            return pd.DataFrame()
        df_out = df_hist[df_hist['reservation_date'] == target_date].copy()
        if hide_cancelled and 'status' in df_out.columns:
            df_out = df_out[df_out['status'] != 'Canceled']
        if selected_venue != "All Pubs" and 'venue_name' in df_out.columns:
            df_out = df_out[df_out['venue_name'] == selected_venue]
        return df_out

    df_last_week = _filter_hist(last_week_date)
    df_last_year = _filter_hist(last_year_date)

    # Calculate meal period breakdown
    total_res = len(df_filtered)
    total_covers = int(df_filtered['party_size'].sum()) if 'party_size' in df_filtered.columns else 0

    # Eviivo stats
    total_rooms = len(df_eviivo)
    total_room_guests = int(df_eviivo['party_size'].sum()) if len(df_eviivo) > 0 and 'party_size' in df_eviivo.columns else 0

    # Last week totals
    lw_total_res = len(df_last_week) if len(df_last_week) > 0 else 0
    lw_total_covers = int(df_last_week['party_size'].sum()) if len(df_last_week) > 0 and 'party_size' in df_last_week.columns else 0

    st.subheader(f"Overview - {selected_date.strftime('%A %d/%m/%Y')}")
    if selected_venue != "All Pubs":
        st.caption(f"Showing: {selected_venue}")

    # Dual summary cards for restaurant and accommodation
    if selected_source == "All":
        summary_col1, summary_col2 = st.columns(2)
        with summary_col1:
            st.markdown("**RESTAURANT**")
            st.metric("Reservations", total_res)
            st.metric("Covers", total_covers)
        with summary_col2:
            st.markdown("**ACCOMMODATION**")
            st.metric("Room Stays", total_rooms)
            st.metric("Guests", total_room_guests)
        st.markdown("---")

    if 'meal_period' in df_filtered.columns:
        meal_stats = []
        for period in ['Breakfast', 'Lunch', 'Dinner']:
            period_df = df_filtered[df_filtered['meal_period'] == period]
            current_res = len(period_df)
            current_covers = int(period_df['party_size'].sum()) if 'party_size' in period_df.columns else 0

            if len(df_last_week) > 0 and 'meal_period' in df_last_week.columns:
                lw_pf = df_last_week[df_last_week['meal_period'] == period]
                lw_res = len(lw_pf)
                lw_covers = int(lw_pf['party_size'].sum()) if 'party_size' in lw_pf.columns else 0
            else:
                lw_res = '-'
                lw_covers = '-'

            meal_stats.append({
                'Period': period,
                'Res': current_res,
                'Covers': current_covers,
                f'LW Res ({last_week_date.strftime("%d/%m")})': lw_res,
                f'LW Covers': lw_covers,
            })

        total_row = {
            'Period': 'TOTAL',
            'Res': total_res,
            'Covers': total_covers,
            f'LW Res ({last_week_date.strftime("%d/%m")})': lw_total_res if lw_total_res > 0 else '-',
            f'LW Covers': lw_total_covers if lw_total_covers > 0 else '-',
        }
        meal_stats.insert(0, total_row)

        meal_df = pd.DataFrame(meal_stats)
        st.dataframe(meal_df, use_container_width=True, hide_index=True)
        st.caption(f"LW = {last_week_date.strftime('%A %d/%m/%Y')}")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Reservations", total_res)
        with col2:
            st.metric("Covers", total_covers)
        with col3:
            st.metric(f"LW Res ({last_week_date.strftime('%d/%m')})", lw_total_res if lw_total_res > 0 else '-')
        with col4:
            st.metric(f"LW Covers ({last_week_date.strftime('%d/%m')})", lw_total_covers if lw_total_covers > 0 else '-')

    # Notes count
    if 'all_notes' in df_filtered.columns:
        with_notes = len(df_filtered[df_filtered['all_notes'].str.len() > 0])
        if with_notes > 0:
            st.caption(f"{with_notes} booking(s) with notes")

    # === HELPER FUNCTIONS FOR DISPLAY SECTIONS ===
    def show_reservations_table():
        st.subheader("Combined Activity" if selected_source == "All" else ("Reservations" if selected_source == "Reservations" else "Room Stays"))

        # Build combined dataframe
        combined_rows = []

        # Add SevenRooms reservations
        if len(df_filtered) > 0:
            for _, row in df_filtered.iterrows():
                combined_rows.append({
                    'Type': 'R',
                    'Pub': row.get('venue_name', '-'),
                    'Time': row.get('time', '-'),
                    'Guest': row.get('guest_name', '-'),
                    'Size': row.get('party_size', 0),
                    'Detail': row.get('table', '-'),
                    'Notes': row.get('all_notes', ''),
                    'Phone': row.get('phone', '-'),
                    'source': 'sevenrooms'
                })

        # Add eviivo room stays
        if len(df_eviivo) > 0:
            for _, row in df_eviivo.iterrows():
                combined_rows.append({
                    'Type': 'A',
                    'Pub': row.get('venue_name', '-'),
                    'Time': row.get('time', '14:00'),
                    'Guest': row.get('guest_name', '-'),
                    'Size': row.get('party_size', 0),
                    'Detail': row.get('detail', 'Room'),
                    'Notes': row.get('notes', ''),
                    'Phone': row.get('phone', '-'),
                    'source': 'eviivo'
                })

        if combined_rows:
            df_combined = pd.DataFrame(combined_rows)
            # Sort by time
            df_combined = df_combined.sort_values('Time')

            # Display columns (hide source column from display)
            display_cols = ['Type', 'Pub', 'Time', 'Guest', 'Size', 'Detail', 'Notes', 'Phone']
            st.dataframe(df_combined[display_cols], use_container_width=True, hide_index=True)

            csv = df_combined[display_cols].to_csv(index=False)
            filename = f"activity_{selected_date}.csv" if selected_source == "All" else f"{'reservations' if selected_source == 'Reservations' else 'rooms'}_{selected_date}.csv"
            st.download_button("Download CSV", csv, filename, "text/csv")

            # Legend
            if selected_source == "All":
                st.caption("Type: R = Reservation, A = Accommodation")
        else:
            st.info("No bookings for the selected filters.")

    def show_alerts():
        st.subheader("Alerts")
        alert_col1, alert_col2, alert_col3, alert_col4 = st.columns(4)

        with alert_col1:
            st.markdown("**Potential Clashes**")
            if 'table' in df_filtered.columns and 'time' in df_filtered.columns and len(df_filtered) > 0:
                clash_df = df_filtered[df_filtered['table'] != '-'].copy()
                if len(clash_df) > 0:
                    # Calculate end times using duration (default 90 mins if not available)
                    if 'duration' in clash_df.columns:
                        clash_df['duration_mins'] = pd.to_numeric(clash_df['duration'], errors='coerce').fillna(90)
                    else:
                        clash_df['duration_mins'] = 90

                    # Parse start time to minutes since midnight for easier comparison
                    clash_df['start_mins'] = clash_df['time'].apply(
                        lambda t: int(t.split(':')[0]) * 60 + int(t.split(':')[1]) if pd.notna(t) and ':' in str(t) else 0
                    )
                    clash_df['end_mins'] = clash_df['start_mins'] + clash_df['duration_mins']

                    # Find overlapping bookings on same table at same venue
                    clashes_found = []
                    venue_col = 'venue_name' if 'venue_name' in clash_df.columns else None

                    for table in clash_df['table'].unique():
                        table_df = clash_df[clash_df['table'] == table]
                        if venue_col:
                            for venue in table_df[venue_col].unique():
                                venue_table_df = table_df[table_df[venue_col] == venue].sort_values('start_mins')
                                # Check consecutive bookings for overlap
                                for i in range(len(venue_table_df) - 1):
                                    curr = venue_table_df.iloc[i]
                                    next_row = venue_table_df.iloc[i + 1]
                                    if curr['end_mins'] > next_row['start_mins']:
                                        clashes_found.append({
                                            'venue': venue,
                                            'table': table,
                                            'booking1': f"{curr['time']} ({curr.get('guest_name', 'Guest')})",
                                            'booking2': f"{next_row['time']} ({next_row.get('guest_name', 'Guest')})"
                                        })

                    if clashes_found:
                        st.error(f"Found {len(clashes_found)} potential double-bookings!")
                        clash_table = pd.DataFrame([
                            {
                                '#': i + 1,
                                'Pub': c['venue'],
                                'Table': c['table'],
                                'Booking 1': c['booking1'],
                                'Booking 2': c['booking2']
                            }
                            for i, c in enumerate(clashes_found)
                        ])
                        st.dataframe(clash_table, use_container_width=True, hide_index=True)
                    else:
                        st.success("No clashes detected")
                else:
                    st.success("No clashes detected")
            else:
                st.info("No table data for clash detection")

        with alert_col2:
            st.markdown("**Bookings with Notes**")
            if 'all_notes' in df_filtered.columns:
                noted = df_filtered[df_filtered['all_notes'].str.len() > 0]
                if len(noted) > 0:
                    for _, row in noted.head(5).iterrows():
                        guest = row.get('guest_name', 'Guest')
                        venue = row.get('venue_name', '')
                        time = row.get('time', '')
                        note = str(row['all_notes'])[:80] + ('...' if len(str(row['all_notes'])) > 80 else '')
                        st.warning(f"**{guest}** ({venue} @ {time}): {note}")
                    if len(noted) > 5:
                        st.caption(f"...and {len(noted) - 5} more")
                else:
                    st.success("No special notes to review")
            else:
                st.info("No notes data")

        with alert_col3:
            st.markdown("**Special Occasions**")
            if 'occasion' in df_filtered.columns:
                occasions = df_filtered[df_filtered['occasion'].str.len() > 0]
                if len(occasions) > 0:
                    for _, row in occasions.head(5).iterrows():
                        guest = row.get('guest_name', 'Guest')
                        venue = row.get('venue_name', '')
                        time = row.get('time', '')
                        occasion = row.get('occasion', '')
                        st.info(f"**{occasion}**: {guest} ({venue} @ {time})")
                    if len(occasions) > 5:
                        st.caption(f"...and {len(occasions) - 5} more")
                else:
                    st.success("No special occasions")
            else:
                st.info("No occasion data")

        with alert_col4:
            st.markdown("**VIP & Loyalty**")
            vip_df = df_filtered[df_filtered.get('is_vip', pd.Series(False, index=df_filtered.index)) == True] if 'is_vip' in df_filtered.columns else pd.DataFrame()
            loyalty_df = df_filtered[df_filtered['loyalty_tier'].notna() & (df_filtered['loyalty_tier'] != '')] if 'loyalty_tier' in df_filtered.columns else pd.DataFrame()
            if len(vip_df) > 0 or len(loyalty_df) > 0:
                for _, row in pd.concat([vip_df, loyalty_df]).drop_duplicates().iterrows():
                    tier = row.get('loyalty_tier', 'VIP')
                    st.info(f"**{row.get('guest_name', 'Guest')}** ({row.get('venue_name', '')} @ {row.get('time', '')}) — {tier}")
            else:
                st.success("No VIP or loyalty guests today")

        # --- PREVIOUSLY UNHAPPY GUESTS (full width) ---
        low_rating_lookup = st.session_state.get('low_rating_lookup', {})
        if low_rating_lookup and len(df_filtered) > 0:
            flagged_guests = []
            for _, row in df_filtered.iterrows():
                match = find_low_rating_match(row, low_rating_lookup, venue_map)
                if match:
                    flagged_guests.append({
                        'guest': row.get('guest_name', 'Guest'),
                        'venue': row.get('venue_name', ''),
                        'time': row.get('time', ''),
                        'party_size': row.get('party_size', ''),
                        'rating': match['rating'],
                        'comment': match['comment'],
                        'prev_venue': match['venue'],
                        'prev_date': match['date'],
                    })
            if flagged_guests:
                st.markdown("---")
                st.markdown(f"### ⚠️ Previously Unhappy Guests ({len(flagged_guests)})")
                st.caption("These guests have previously left a review of 3★ or lower. Please ensure they receive exceptional service today.")
                for fg in flagged_guests:
                    comment_str = f' — *"{fg["comment"][:120]}{"..." if len(fg["comment"]) > 120 else ""}"*' if fg['comment'] else ''
                    prev_date_str = f" on {fg['prev_date']}" if fg['prev_date'] else ''
                    st.error(
                        f"**{fg['guest']}** · {fg['venue']} · {fg['time']} · party of {fg['party_size']}  \n"
                        f"Rated **{fg['rating']}/5** at {fg['prev_venue']}{prev_date_str}{comment_str}"
                    )

    def show_service_briefing():
        """Daily service briefing paragraph for manager to read to staff."""
        st.subheader(f"📋 Today's Briefing — {selected_venue}")
        st.caption(selected_date.strftime('%A %d %B %Y'))

        if total_res == 0 and total_rooms == 0:
            st.info("No bookings for this date.")
            st.markdown("---")
            return

        dietary_keywords = ['allerg', 'intoleran', 'gluten', 'vegan', 'vegetarian', 'dairy', 'nut', 'celiac', 'halal', 'kosher', 'pescatarian']
        vc_col = next((c for c in ['visit_count', 'total_visits', 'visits'] if c in df_filtered.columns), None)

        # Build guest -> last visit lookup from historical data (excluding today)
        guest_last_visit = {}
        if len(df_hist) > 0:
            hist_past = df_hist.copy()
            if 'first_name' in hist_past.columns:
                hist_past['_name'] = (hist_past['first_name'].fillna('') + ' ' + hist_past['last_name'].fillna('')).str.strip().str.lower()
            if 'reservation_date' in hist_past.columns and '_name' in hist_past.columns:
                hist_past = hist_past[hist_past['_name'].str.len() > 0]
                for name, grp in hist_past.groupby('_name'):
                    last = grp['reservation_date'].max()
                    if last < date.today():
                        guest_last_visit[name] = last

        # 1. OPENING PARAGRAPH
        sentences = []

        # Reservations + last week comparison
        lw_covers = int(df_last_week['party_size'].sum()) if len(df_last_week) > 0 and 'party_size' in df_last_week.columns else None
        if lw_covers is not None:
            diff = total_covers - lw_covers
            diff_str = f", up {diff} on last week" if diff > 0 else (f", down {abs(diff)} on last week" if diff < 0 else ", same as last week")
        else:
            diff_str = ""
        sentences.append(f"You have {total_res} reservation{'s' if total_res != 1 else ''} today for {total_covers} covers{diff_str}.")

        # Busiest service + peaking time
        if 'meal_period' in df_filtered.columns and 'party_size' in df_filtered.columns and 'time' in df_filtered.columns:
            period_stats = {}
            for period in ['Breakfast', 'Lunch', 'Dinner']:
                p_df = df_filtered[df_filtered['meal_period'] == period]
                if len(p_df) > 0:
                    covers = int(p_df['party_size'].sum())
                    # Find peak 30-min slot
                    peak_time = p_df.groupby('time')['party_size'].sum().idxmax() if len(p_df) > 0 else None
                    period_stats[period] = (len(p_df), covers, peak_time)

            if period_stats:
                busiest = max(period_stats, key=lambda p: period_stats[p][1])
                b_count, b_covers, b_peak = period_stats[busiest]
                peak_str = f", peaking around {b_peak}" if b_peak else ""
                sentences.append(f"{busiest} is your busiest service with {b_covers} covers across {b_count} bookings{peak_str}.")
                for period, (count, covers, _) in period_stats.items():
                    if period != busiest:
                        sentences.append(f"{period} has {covers} covers across {count} bookings.")

        opening = " ".join(sentences)
        st.markdown(f"**Service Briefing - {selected_venue}, {selected_date.strftime('%A %d/%m/%Y')}**")
        st.markdown(opening)

        # 2. SPECIAL OCCASIONS — all reservation_type values, as flowing sentence
        if 'occasion' in df_filtered.columns:
            occ_df = df_filtered[df_filtered['occasion'].str.len() > 0].sort_values('time')
            if len(occ_df) > 0:
                occ_parts = []
                for _, row in occ_df.iterrows():
                    occ_parts.append(f"{row.get('occasion', '')} for the {row.get('guest_name', 'Guest')} party at {row.get('time', '?')}.")
                st.markdown(f"**Special occasions:** {' '.join(occ_parts)}")

        # 3. ALLERGIES & DIETARY REQUIREMENTS
        allergy_parts = []
        for _, row in df_filtered.sort_values('time').iterrows():
            notes_text = str(row.get('all_notes', '') or '').lower()
            occasion_text = str(row.get('occasion', '') or '').lower()
            if any(k in notes_text for k in dietary_keywords) or any(k in occasion_text for k in dietary_keywords):
                name = row.get('guest_name', 'Guest')
                time = row.get('time', '?')
                size = row.get('party_size', '?')
                # Use whichever field has the dietary info
                detail = str(row.get('all_notes', '') or row.get('occasion', '') or '')
                # Strip boilerplate prefixes
                import re
                detail = re.sub(r'^Booking Notes:\s*', '', detail, flags=re.IGNORECASE).strip()
                detail = re.sub(r'^Custom question response:\s*', '', detail, flags=re.IGNORECASE).strip()
                allergy_parts.append(f"{name} ({time}, party of {size}) — {detail}")
        if allergy_parts:
            st.markdown(f"**Allergies & dietary requirements** (please brief the kitchen): {'; '.join(allergy_parts)}.")

        # 4. WELCOME BACK — guests not seen in 90+ days
        if guest_last_visit:
            welcome_parts = []
            for _, row in df_filtered.sort_values('time').iterrows():
                name_key = str(row.get('guest_name', '')).strip().lower()
                if name_key and name_key in guest_last_visit:
                    last = guest_last_visit[name_key]
                    days_away = (date.today() - last).days
                    if days_away >= 90:
                        welcome_parts.append(f"{row.get('guest_name', 'Guest')} ({row.get('time', '?')}) is back after {days_away} days.")
            if welcome_parts:
                st.markdown(f"**Welcome back:** {' '.join(welcome_parts)} Great to see them again!")

        # 5. LOYAL MEMBERS
        loyal_parts = []
        if 'loyalty_tier' in df_filtered.columns:
            for _, row in df_filtered[df_filtered['loyalty_tier'].notna() & (df_filtered['loyalty_tier'] != '')].sort_values('time').iterrows():
                loyal_parts.append(f"{row.get('guest_name', 'Guest')} ({row.get('time', '?')}, {row.get('loyalty_tier', '')})")
        elif vc_col:
            for _, row in df_filtered[pd.to_numeric(df_filtered[vc_col], errors='coerce').fillna(0) >= 5].sort_values('time').iterrows():
                visits = int(pd.to_numeric(row.get(vc_col, 0), errors='coerce') or 0)
                loyal_parts.append(f"{row.get('guest_name', 'Guest')} ({row.get('time', '?')}, {visits} visits)")
        if loyal_parts:
            st.markdown(f"**Loyal members:** {', '.join(loyal_parts)}. Please give these guests a particularly warm welcome.")

        st.markdown("---")

    def show_room_guests():
        if len(df_eviivo) == 0:
            return

        import re

        def clean_eviivo_note(note):
            """Strip Booking.com boilerplate from eviivo notes."""
            if not note:
                return ''
            boilerplate = [
                r'Non-Smoking.*', r'Breakfast is included.*', r'Children and Extra Bed.*',
                r'Deposit Policy.*', r'Cancellation Policy.*', r'payment_on_Booking.*',
                r'Booking\.com has provided.*', r'Genius Booker.*', r'Group: \d+ x Adult.*',
                r'BED PREFERENCE.*',
            ]
            for pattern in boilerplate:
                note = re.split(pattern, note, flags=re.IGNORECASE | re.DOTALL)[0]
            return note.strip().strip('\n')

        eviivo_hist = st.session_state.get('eviivo_historical', [])
        df_eviivo_hist = pd.DataFrame(eviivo_hist) if eviivo_hist else pd.DataFrame()

        def count_visits(guest_email, guest_phone, guest_name):
            total = 0
            norm_email = guest_email.lower().strip() if guest_email else ''
            norm_phone = re.sub(r'\D', '', guest_phone) if guest_phone else ''
            norm_name = guest_name.lower().strip() if guest_name else ''

            def matches_row(row_email, row_phone, row_name):
                if norm_email and str(row_email).lower().strip() == norm_email:
                    return True
                if norm_phone and re.sub(r'\D', '', str(row_phone)) == norm_phone:
                    return True
                if norm_name and str(row_name).lower().strip() == norm_name:
                    return True
                return False

            if len(df_hist) > 0:
                for _, r in df_hist.iterrows():
                    if matches_row(r.get('email',''), r.get('phone_number',''), r.get('guest_name','')):
                        total += 1
            if len(df_eviivo_hist) > 0:
                for _, r in df_eviivo_hist.iterrows():
                    if matches_row(r.get('email',''), r.get('phone',''), r.get('guest_name','')):
                        total += 1
            return total if total > 0 else None

        def find_table_booking(guest_email, guest_phone, guest_name):
            if len(df_filtered) == 0:
                return None
            for _, row in df_filtered.iterrows():
                res_email = str(row.get('email', '') or '').lower().strip()
                res_phone = re.sub(r'\D', '', str(row.get('phone_number', '') or ''))
                res_name = str(row.get('guest_name', '') or '').lower().strip()
                if guest_email and res_email and guest_email.lower().strip() == res_email:
                    return row
                if guest_phone and res_phone:
                    norm = re.sub(r'\D', '', guest_phone)
                    if norm and norm == res_phone:
                        return row
                if guest_name and res_name and guest_name.lower().strip() == res_name:
                    return row
            return None

        st.subheader("🛏️ Room Guests")

        # Build enriched list of all room guests
        enriched = []
        for _, room in df_eviivo.sort_values(['venue_name', 'detail']).iterrows():
            email = room.get('email', '') or ''
            phone = room.get('phone', '') or ''
            guest_name = room.get('guest_name', 'Guest')
            clean_note = clean_eviivo_note(room.get('notes', '') or '')
            has_note = bool(clean_note) and len(clean_note) > 3
            visits = count_visits(email, phone, guest_name)
            table_match = find_table_booking(email, phone, guest_name)

            checkin = str(room.get('date', ''))
            checkout = str(room.get('checkout_date', ''))
            # Format dates as DD/MM if possible
            try:
                from datetime import date as _date
                checkin_fmt = datetime.strptime(checkin, '%Y-%m-%d').strftime('%d/%m') if checkin else '—'
                checkout_fmt = datetime.strptime(checkout, '%Y-%m-%d').strftime('%d/%m') if checkout else '—'
            except Exception:
                checkin_fmt = checkin or '—'
                checkout_fmt = checkout or '—'

            flags = []
            if has_note:
                flags.append('📝')
            if table_match is not None:
                flags.append('🍽️')
            if visits:
                flags.append('⭐')

            enriched.append({
                'venue_name': room.get('venue_name', ''),
                'detail': room.get('detail', ''),
                'guest_name': guest_name,
                'party_size': room.get('party_size', 1),
                'checkin': checkin,
                'checkout': checkout,
                'checkin_fmt': checkin_fmt,
                'checkout_fmt': checkout_fmt,
                'visits': visits,
                'table_match': table_match,
                'clean_note': clean_note,
                'has_note': has_note,
                'flags': ' '.join(flags) if flags else '',
            })

        if not enriched:
            st.caption("No room guests today.")
            st.markdown("---")
            return

        # Group by venue for All Pubs, or show flat list for individual pub
        venues_to_show = []
        if selected_venue == "All Pubs":
            venues_to_show = sorted(set(e['venue_name'] for e in enriched))
        else:
            venues_to_show = [selected_venue]

        for venue in venues_to_show:
            venue_guests = [e for e in enriched if e['venue_name'] == venue] if selected_venue == "All Pubs" else enriched

            if not venue_guests:
                continue

            if selected_venue == "All Pubs":
                st.markdown(f"**{venue}**")

            # Summary table
            table_rows = []
            for e in venue_guests:
                table_row = {
                    'Room': e['detail'].replace('Room ', ''),
                    'Guest': e['guest_name'],
                    'Party': e['party_size'],
                    'Check-in': e['checkin_fmt'],
                    'Check-out': e['checkout_fmt'],
                    'Prev. Visits': e['visits'] if e['visits'] else '—',
                    'Table Today': f"{e['table_match'].get('time','?')} (party of {e['table_match'].get('party_size','?')})" if e['table_match'] is not None else '—',
                    'Flags': e['flags'],
                }
                table_rows.append(table_row)

            st.dataframe(
                pd.DataFrame(table_rows),
                use_container_width=True,
                hide_index=True,
            )

            # Notes / flag details — only show if there's something to highlight
            flagged = [e for e in venue_guests if e['has_note'] or e['table_match'] is not None or e['visits']]
            if flagged:
                for e in flagged:
                    parts = []
                    if e['visits']:
                        parts.append(f"⭐ **{e['visits']} previous visit{'s' if e['visits'] != 1 else ''}**")
                    if e['table_match'] is not None:
                        tm = e['table_match']
                        parts.append(f"🍽️ Table booked at **{tm.get('time','?')}**, party of {tm.get('party_size','?')}")
                    if e['has_note']:
                        parts.append(f"📝 {e['clean_note']}")

                    room_label = e['detail'].replace('Room ', 'Room ')
                    st.warning(f"**{e['guest_name']}** ({room_label}) — " + " · ".join(parts))

            if selected_venue == "All Pubs":
                st.markdown("")  # spacing between venues

        st.markdown("---")

    # === DISPLAY SECTIONS ===
    if selected_venue == "All Pubs":
        # All Pubs view: Bookings by Pub -> Alerts -> Reservations
        has_reservations = 'venue_name' in df_filtered.columns and len(df_filtered) > 0
        has_rooms = len(df_eviivo) > 0 and 'venue_name' in df_eviivo.columns

        if has_reservations or has_rooms:
            st.subheader("Bookings by Pub")

            # Build comprehensive stats by pub with meal period breakdown
            pub_list = []
            # Get all venues from reservations, rooms, and last week
            all_venues = set()
            if has_reservations:
                all_venues.update(df_filtered['venue_name'].unique())
            if has_rooms:
                all_venues.update(df_eviivo['venue_name'].unique())
            if len(df_last_week) > 0 and 'venue_name' in df_last_week.columns:
                all_venues.update(df_last_week['venue_name'].unique())

            for venue in all_venues:
                row = {'Pub': venue}

                # Current reservation totals
                if has_reservations:
                    venue_df = df_filtered[df_filtered['venue_name'] == venue]
                    current_res = len(venue_df)
                    current_covers = int(venue_df['party_size'].sum()) if 'party_size' in venue_df.columns else 0
                else:
                    venue_df = pd.DataFrame()
                    current_res = 0
                    current_covers = 0

                # Room stay totals for this venue
                if has_rooms:
                    venue_rooms = df_eviivo[df_eviivo['venue_name'] == venue]
                    room_count = len(venue_rooms)
                    room_guests = int(venue_rooms['party_size'].sum()) if 'party_size' in venue_rooms.columns else 0
                else:
                    room_count = 0
                    room_guests = 0

                # Last week totals for this venue
                if len(df_last_week) > 0 and 'venue_name' in df_last_week.columns:
                    lw_venue_df = df_last_week[df_last_week['venue_name'] == venue]
                    lw_res = len(lw_venue_df)
                    lw_covers = int(lw_venue_df['party_size'].sum()) if 'party_size' in lw_venue_df.columns else 0
                else:
                    lw_res = '-'
                    lw_covers = '-'

                row['Res'] = current_res
                row['Covers'] = current_covers
                row['Rooms'] = room_count
                row['Room Guests'] = room_guests
                row[f'LW Res ({last_week_date.strftime("%d/%m")})'] = lw_res
                row[f'LW Covers'] = lw_covers

                # By meal period (only for reservations)
                if has_reservations and 'meal_period' in venue_df.columns:
                    for period in ['Breakfast', 'Lunch', 'Dinner']:
                        period_df = venue_df[venue_df['meal_period'] == period]
                        row[f'{period} Res'] = len(period_df)
                        row[f'{period} Covers'] = int(period_df['party_size'].sum()) if 'party_size' in period_df.columns else 0

                pub_list.append(row)

            pub_stats = pd.DataFrame(pub_list).sort_values('Covers', ascending=False)

            lw_col = f'LW Res ({last_week_date.strftime("%d/%m")})'
            col_order = ['Pub', 'Res', 'Covers', 'Rooms', 'Room Guests', lw_col, 'LW Covers']
            if has_reservations and 'meal_period' in df_filtered.columns:
                col_order += ['Breakfast Res', 'Breakfast Covers', 'Lunch Res', 'Lunch Covers', 'Dinner Res', 'Dinner Covers']
            pub_stats = pub_stats[[c for c in col_order if c in pub_stats.columns]]

            st.dataframe(pub_stats, use_container_width=True, hide_index=True)
            st.caption(f"LW = {last_week_date.strftime('%A %d/%m')}")

        show_alerts()
        show_reservations_table()
        show_room_guests()
    else:
        # Individual pub view: Service Briefing -> Reservations -> Alerts
        show_service_briefing()
        show_reservations_table()
        show_alerts()
        show_room_guests()

# === ANALYTICS TAB ===
with tab_analytics:
    st.subheader("Historical Analytics")
    st.caption("View past reservation data and customer feedback")

    # Date range picker
    analytics_col1, analytics_col2, analytics_col3 = st.columns([1, 1, 2])
    with analytics_col1:
        analytics_from = st.date_input(
            "From date",
            value=date.today() - timedelta(days=30),
            max_value=date.today() - timedelta(days=1),
            key="analytics_from",
            format="DD/MM/YYYY"
        )
    with analytics_col2:
        analytics_to = st.date_input(
            "To date",
            value=date.today() - timedelta(days=1),
            max_value=date.today() - timedelta(days=1),
            key="analytics_to",
            format="DD/MM/YYYY"
        )
    with analytics_col3:
        analytics_venue = st.selectbox(
            "Pub",
            ["All Pubs"] + sorted([v['name'].strip() for v in venues if 'chickpea' not in v['name'].lower()]),
            key="analytics_venue"
        )

    # Load analytics data button
    if st.button("Load Analytics Data", type="primary", key="load_analytics"):
        with st.spinner("Fetching historical data (cached for 10 mins)..."):
            # Convert dates to strings for cache key
            from_str = analytics_from.strftime("%Y-%m-%d")
            to_str = analytics_to.strftime("%Y-%m-%d")

            # Fetch using cached functions
            analytics_reservations = load_analytics_reservations(client, from_str, to_str)
            analytics_feedback, feedback_endpoint = load_analytics_feedback(client, from_str, to_str)

            st.session_state['analytics_reservations'] = analytics_reservations
            st.session_state['analytics_feedback'] = analytics_feedback
            st.session_state['analytics_date_range'] = (analytics_from, analytics_to)
            st.session_state['feedback_endpoint'] = feedback_endpoint

            feedback_msg = f" (from {feedback_endpoint})" if feedback_endpoint else ""
            st.success(f"Loaded {len(analytics_reservations)} reservations and {len(analytics_feedback)} feedback entries{feedback_msg}")

    # Display analytics if data loaded
    if 'analytics_reservations' in st.session_state:
        analytics_res = st.session_state['analytics_reservations']
        analytics_fb = st.session_state.get('analytics_feedback', [])
        date_range = st.session_state.get('analytics_date_range', (None, None))

        if analytics_res:
            # Process analytics reservations
            df_analytics = pd.DataFrame(analytics_res)

            # Apply same transformations
            if 'max_guests' in df_analytics.columns:
                df_analytics['party_size'] = pd.to_numeric(df_analytics['max_guests'], errors='coerce').fillna(0).astype(int)
            if 'date' in df_analytics.columns:
                df_analytics['reservation_date'] = pd.to_datetime(df_analytics['date'], errors='coerce').dt.date
            if 'venue_id' in df_analytics.columns:
                df_analytics['venue_name'] = df_analytics['venue_id'].map(venue_map).fillna('Unknown')
            if 'status_display' in df_analytics.columns:
                df_analytics['status'] = df_analytics['status_display'].fillna('Unknown')

            # Filter by venue if selected
            if analytics_venue != "All Pubs" and 'venue_name' in df_analytics.columns:
                df_analytics = df_analytics[df_analytics['venue_name'] == analytics_venue]

            # Exclude cancelled
            if 'status' in df_analytics.columns:
                df_analytics = df_analytics[df_analytics['status'] != 'Canceled']

            # === RESERVATIONS SUMMARY ===
            st.markdown("---")
            st.subheader("Reservations Summary")

            total_res = len(df_analytics)
            total_covers = int(df_analytics['party_size'].sum()) if 'party_size' in df_analytics.columns else 0
            num_days = (analytics_to - analytics_from).days + 1

            summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
            with summary_col1:
                st.metric("Total Reservations", total_res)
            with summary_col2:
                st.metric("Total Covers", total_covers)
            with summary_col3:
                st.metric("Avg Reservations/Day", round(total_res / num_days, 1) if num_days > 0 else 0)
            with summary_col4:
                st.metric("Avg Covers/Day", round(total_covers / num_days, 1) if num_days > 0 else 0)

            # By pub breakdown
            if analytics_venue == "All Pubs" and 'venue_name' in df_analytics.columns:
                st.markdown("**By Pub**")
                pub_summary = df_analytics.groupby('venue_name').agg(
                    Reservations=('venue_name', 'count'),
                    Covers=('party_size', 'sum')
                ).reset_index()
                pub_summary.columns = ['Pub', 'Reservations', 'Covers']
                pub_summary = pub_summary.sort_values('Covers', ascending=False)
                st.dataframe(pub_summary, use_container_width=True, hide_index=True)

            # Daily trend - show line for each pub
            if 'reservation_date' in df_analytics.columns:
                st.markdown("**Daily Covers**")

                # Pivot to get covers by date and venue
                if 'venue_name' in df_analytics.columns and analytics_venue == "All Pubs":
                    # Create pivot table: dates as rows, venues as columns
                    daily_by_pub = df_analytics.pivot_table(
                        index='reservation_date',
                        columns='venue_name',
                        values='party_size',
                        aggfunc='sum',
                        fill_value=0
                    )
                    # Sort columns alphabetically
                    daily_by_pub = daily_by_pub[sorted(daily_by_pub.columns)]
                    st.line_chart(daily_by_pub)
                else:
                    # Single venue or no venue data - just show that venue
                    daily = df_analytics.groupby('reservation_date').agg(
                        Covers=('party_size', 'sum')
                    ).reset_index()
                    daily.columns = ['Date', 'Covers']
                    st.line_chart(daily.set_index('Date')['Covers'])

        # === FEEDBACK SECTION ===
        st.markdown("---")
        st.subheader("Customer Feedback")

        if analytics_fb:
            df_feedback = pd.DataFrame(analytics_fb)

            # Debug: show available columns
            with st.expander("Debug: Feedback data structure"):
                st.write(f"Columns: {list(df_feedback.columns)}")
                if len(df_feedback) > 0:
                    st.write("Sample record:")
                    st.json(analytics_fb[0] if analytics_fb else {})

            # Map venue names - try different possible field names
            venue_id_col = None
            for col in ['venue_id', 'venueId', 'venue']:
                if col in df_feedback.columns:
                    venue_id_col = col
                    break
            if venue_id_col:
                df_feedback['venue_name'] = df_feedback[venue_id_col].map(venue_map).fillna('Unknown')

            # Filter by venue if selected
            if analytics_venue != "All Pubs" and 'venue_name' in df_feedback.columns:
                df_feedback = df_feedback[df_feedback['venue_name'] == analytics_venue]

            if len(df_feedback) > 0:
                # Find the rating column - try different possible names
                rating_col = None
                for col in ['overall_rating', 'overallRating', 'rating', 'stars', 'score']:
                    if col in df_feedback.columns:
                        rating_col = col
                        break

                if rating_col:
                    df_feedback[rating_col] = pd.to_numeric(df_feedback[rating_col], errors='coerce')
                    avg_rating = df_feedback[rating_col].mean()

                    # Rating distribution
                    st.markdown("**Rating Summary**")
                    fb_col1, fb_col2, fb_col3, fb_col4 = st.columns(4)
                    with fb_col1:
                        st.metric("Average Rating", f"{avg_rating:.2f}/5" if pd.notna(avg_rating) else "N/A")
                    with fb_col2:
                        st.metric("Total Reviews", len(df_feedback))
                    with fb_col3:
                        # Calculate % 5-star
                        five_star = len(df_feedback[df_feedback[rating_col] == 5])
                        pct_five = (five_star / len(df_feedback) * 100) if len(df_feedback) > 0 else 0
                        st.metric("5-Star", f"{pct_five:.0f}%")
                    with fb_col4:
                        # Calculate % positive (4-5 stars)
                        positive = len(df_feedback[df_feedback[rating_col] >= 4])
                        pct_positive = (positive / len(df_feedback) * 100) if len(df_feedback) > 0 else 0
                        st.metric("4-5 Star", f"{pct_positive:.0f}%")

                    # Star distribution breakdown
                    st.markdown("**Rating Distribution**")
                    rating_dist = df_feedback[rating_col].value_counts().sort_index(ascending=False)
                    dist_data = []
                    for stars in [5, 4, 3, 2, 1]:
                        count = rating_dist.get(stars, 0)
                        pct = (count / len(df_feedback) * 100) if len(df_feedback) > 0 else 0
                        dist_data.append({'Stars': f"{stars} star", 'Count': count, '%': f"{pct:.0f}%"})
                    st.dataframe(pd.DataFrame(dist_data), use_container_width=True, hide_index=True)

                # Low ratings breakdown
                low_reviews = df_feedback[df_feedback[rating_col] <= 3].sort_values(rating_col)
                if len(low_reviews) > 0:
                    st.markdown(f"**🔴 Reviews 3★ and under — {len(low_reviews)} review{'s' if len(low_reviews) != 1 else ''}**")
                    comment_col_lr = next((c for c in ['notes', 'comment', 'comments', 'feedback', 'text', 'review', 'additional_notes'] if c in low_reviews.columns), None)
                    for _, row in low_reviews.iterrows():
                        stars = int(row[rating_col]) if pd.notna(row[rating_col]) else '?'
                        venue = row.get('venue_name', '')
                        rev_date = row.get('reservation_date', row.get('date', row.get('created', '')))
                        comment = str(row[comment_col_lr])[:300] if comment_col_lr and pd.notna(row.get(comment_col_lr)) else ''
                        date_str = f" · {rev_date}" if rev_date else ''
                        comment_str = f'\n> {comment}' if comment else ''
                        st.error(f"**{stars}/5** · {venue}{date_str}{comment_str}")

                # Category scores if available - try different naming patterns
                category_patterns = ['_rating', '_score', 'Rating', 'Score']
                category_cols = []
                skip_cols = [rating_col] if rating_col else []
                for col in df_feedback.columns:
                    for pattern in category_patterns:
                        if pattern in col and col not in skip_cols:
                            category_cols.append(col)
                            break

                if category_cols:
                    st.markdown("**Category Scores**")
                    cat_scores = []
                    for col in category_cols:
                        # Clean up category name
                        cat_name = col
                        for pattern in category_patterns:
                            cat_name = cat_name.replace(pattern, '')
                        cat_name = cat_name.replace('_', ' ').strip().title()
                        cat_avg = pd.to_numeric(df_feedback[col], errors='coerce').mean()
                        if pd.notna(cat_avg):
                            cat_scores.append({'Category': cat_name, 'Average': f"{cat_avg:.2f}/5"})
                    if cat_scores:
                        st.dataframe(pd.DataFrame(cat_scores), use_container_width=True, hide_index=True)

                # By pub breakdown
                if analytics_venue == "All Pubs" and 'venue_name' in df_feedback.columns and rating_col:
                    st.markdown("**Ratings by Pub**")
                    pub_ratings = df_feedback.groupby('venue_name').agg(
                        Reviews=('venue_name', 'count'),
                        Avg_Rating=(rating_col, 'mean')
                    ).reset_index()
                    pub_ratings.columns = ['Pub', 'Reviews', 'Avg Rating']
                    pub_ratings['Avg Rating'] = pub_ratings['Avg Rating'].round(2)
                    pub_ratings = pub_ratings.sort_values('Avg Rating', ascending=False)
                    st.dataframe(pub_ratings, use_container_width=True, hide_index=True)

                # Recent comments - try different possible field names
                comment_col = None
                for col in ['comment', 'comments', 'feedback', 'text', 'review', 'notes', 'additional_notes']:
                    if col in df_feedback.columns:
                        comment_col = col
                        break

                if comment_col:
                    comments_df = df_feedback[df_feedback[comment_col].notna() & (df_feedback[comment_col].astype(str).str.len() > 0)]
                    if len(comments_df) > 0:
                        st.markdown("**Sample Comments**")
                        # Sort by rating if available to show mix of positive and negative
                        if rating_col:
                            comments_df = comments_df.sort_values(rating_col, ascending=True)
                        for _, row in comments_df.head(10).iterrows():
                            venue = row.get('venue_name', '')
                            rating = row.get(rating_col, '') if rating_col else ''
                            comment = str(row[comment_col])[:300] + ('...' if len(str(row[comment_col])) > 300 else '')
                            rating_str = f" ({rating}/5)" if rating and pd.notna(rating) else ""
                            st.info(f"**{venue}**{rating_str}: {comment}")
                        if len(comments_df) > 10:
                            st.caption(f"...and {len(comments_df) - 10} more comments")
                else:
                    st.caption("No comment field found in feedback data")
            else:
                st.info("No feedback found for the selected filters.")
        else:
            st.info("No feedback data loaded. Click 'Load Analytics Data' to fetch feedback.")
    else:
        st.info("Select a date range and click 'Load Analytics Data' to view historical statistics and feedback.")

# === MARKETING TAB ===
with tab_marketing:
    st.subheader("Marketing & Guest Intelligence")

    mkt_col1, mkt_col2, mkt_col3 = st.columns([1, 1, 2])
    with mkt_col1:
        mkt_from = st.date_input("From", value=date.today() - timedelta(days=30), key="mkt_from", format="DD/MM/YYYY")
    with mkt_col2:
        mkt_to = st.date_input("To", value=date.today() - timedelta(days=1), key="mkt_to", format="DD/MM/YYYY")
    with mkt_col3:
        mkt_venue = st.selectbox("Pub", ["All Pubs"] + sorted([v['name'].strip() for v in venues if 'chickpea' not in v['name'].lower()]), key="mkt_venue")

    if st.button("Load Marketing Data", type="primary", key="load_mkt"):
        with st.spinner("Fetching guest data..."):
            from_str = mkt_from.strftime("%Y-%m-%d")
            to_str = mkt_to.strftime("%Y-%m-%d")
            mkt_reservations = load_analytics_reservations(client, from_str, to_str)
            mkt_feedback, _ = load_analytics_feedback(client, from_str, to_str)
            st.session_state['mkt_reservations'] = mkt_reservations
            st.session_state['mkt_feedback'] = mkt_feedback
            st.success(f"Loaded {len(mkt_reservations)} reservations and {len(mkt_feedback)} feedback entries")

    if 'mkt_feedback' in st.session_state:
        mkt_fb = st.session_state['mkt_feedback']
        mkt_res = st.session_state.get('mkt_reservations', [])

        # === FEEDBACK SUMMARY ===
        st.markdown("---")
        st.markdown("### Guest Feedback Summary")

        if mkt_fb:
            df_mkt_fb = pd.DataFrame(mkt_fb)

            venue_id_col = next((c for c in ['venue_id', 'venueId', 'venue'] if c in df_mkt_fb.columns), None)
            if venue_id_col:
                df_mkt_fb['venue_name'] = df_mkt_fb[venue_id_col].map(venue_map).fillna('Unknown')

            if mkt_venue != "All Pubs" and 'venue_name' in df_mkt_fb.columns:
                df_mkt_fb = df_mkt_fb[df_mkt_fb['venue_name'] == mkt_venue]

            rating_col = next((c for c in ['overall', 'overall_rating', 'overallRating', 'rating', 'stars', 'score'] if c in df_mkt_fb.columns), None)

            if rating_col and len(df_mkt_fb) > 0:
                df_mkt_fb[rating_col] = pd.to_numeric(df_mkt_fb[rating_col], errors='coerce')
                avg = df_mkt_fb[rating_col].mean()

                fb_c1, fb_c2, fb_c3, fb_c4 = st.columns(4)
                with fb_c1:
                    st.metric("Average Rating", f"{avg:.2f}/5" if pd.notna(avg) else "N/A")
                with fb_c2:
                    st.metric("Total Reviews", len(df_mkt_fb))
                with fb_c3:
                    five_star = int((df_mkt_fb[rating_col] == 5).sum())
                    pct5 = five_star / len(df_mkt_fb) * 100
                    st.metric("5-Star Reviews", f"{five_star} ({pct5:.0f}%)")
                with fb_c4:
                    low = int((df_mkt_fb[rating_col] < 3).sum())
                    st.metric("Low Ratings (<3★)", low)

                if mkt_venue == "All Pubs" and 'venue_name' in df_mkt_fb.columns:
                    st.markdown("**Ratings by Pub**")
                    pub_fb = df_mkt_fb.groupby('venue_name').agg(
                        Reviews=(rating_col, 'count'),
                        Avg_Rating=(rating_col, 'mean'),
                        Low_Ratings=(rating_col, lambda x: int((x < 3).sum()))
                    ).reset_index()
                    pub_fb.columns = ['Pub', 'Reviews', 'Avg Rating', 'Low Ratings']
                    pub_fb['Avg Rating'] = pub_fb['Avg Rating'].round(2)
                    pub_fb = pub_fb.sort_values('Avg Rating', ascending=False)
                    st.dataframe(pub_fb, use_container_width=True, hide_index=True)

                cat_cols = [c for c in df_mkt_fb.columns if any(p in c for p in ['_rating', '_score', 'Rating', 'Score']) and c != rating_col]
                if cat_cols:
                    st.markdown("**Category Scores**")
                    cat_data = []
                    for col in cat_cols:
                        name = col.replace('_rating', '').replace('_score', '').replace('Rating', '').replace('Score', '').replace('_', ' ').strip().title()
                        avg_cat = pd.to_numeric(df_mkt_fb[col], errors='coerce').mean()
                        if pd.notna(avg_cat):
                            cat_data.append({'Category': name, 'Avg Score': f"{avg_cat:.2f}/5"})
                    if cat_data:
                        st.dataframe(pd.DataFrame(cat_data), use_container_width=True, hide_index=True)

                comment_col = next((c for c in ['notes', 'comment', 'comments', 'feedback', 'text', 'review', 'additional_notes'] if c in df_mkt_fb.columns), None)
                if comment_col:
                    st.markdown("**Recent Comments**")
                    tab_pos, tab_neg = st.tabs(["Positive (4-5★)", "Needs Attention (1-2★)"])
                    with tab_pos:
                        pos = df_mkt_fb[(df_mkt_fb[rating_col] >= 4) & df_mkt_fb[comment_col].notna() & (df_mkt_fb[comment_col].astype(str).str.len() > 5)]
                        if len(pos) > 0:
                            for _, row in pos.head(8).iterrows():
                                venue = row.get('venue_name', '')
                                rating = row.get(rating_col, '')
                                comment = str(row[comment_col])[:300]
                                st.success(f"**{venue}** ({rating}/5): {comment}")
                        else:
                            st.info("No positive comments found.")
                    with tab_neg:
                        neg = df_mkt_fb[(df_mkt_fb[rating_col] < 3) & df_mkt_fb[comment_col].notna() & (df_mkt_fb[comment_col].astype(str).str.len() > 5)]
                        if len(neg) > 0:
                            for _, row in neg.head(8).iterrows():
                                venue = row.get('venue_name', '')
                                rating = row.get(rating_col, '')
                                comment = str(row[comment_col])[:300]
                                st.error(f"**{venue}** ({rating}/5): {comment}")
                        else:
                            st.success("No negative comments found.")
            else:
                st.info("No feedback data with ratings found.")
        else:
            st.info("No feedback data loaded.")

        # === LOYAL GUESTS ===
        st.markdown("---")
        st.markdown("### Loyal Guests")

        if mkt_res:
            df_mkt_res = pd.DataFrame(mkt_res)

            if 'first_name' in df_mkt_res.columns:
                df_mkt_res['guest_name'] = (df_mkt_res['first_name'].fillna('') + ' ' + df_mkt_res['last_name'].fillna('')).str.strip()
            if 'venue_id' in df_mkt_res.columns:
                df_mkt_res['venue_name'] = df_mkt_res['venue_id'].map(venue_map).fillna('Unknown')
            if 'max_guests' in df_mkt_res.columns:
                df_mkt_res['party_size'] = pd.to_numeric(df_mkt_res['max_guests'], errors='coerce').fillna(0).astype(int)
            if 'status_display' in df_mkt_res.columns:
                df_mkt_res = df_mkt_res[df_mkt_res['status_display'] != 'Canceled']

            if mkt_venue != "All Pubs" and 'venue_name' in df_mkt_res.columns:
                df_mkt_res = df_mkt_res[df_mkt_res['venue_name'] == mkt_venue]

            vc_col = next((c for c in ['visit_count', 'total_visits', 'visits'] if c in df_mkt_res.columns), None)

            if vc_col:
                df_mkt_res[vc_col] = pd.to_numeric(df_mkt_res[vc_col], errors='coerce').fillna(0)
                loyal = df_mkt_res[df_mkt_res[vc_col] >= 3][['guest_name', 'venue_name', vc_col]].drop_duplicates('guest_name')
                loyal = loyal.sort_values(vc_col, ascending=False)
                loyal.columns = ['Guest', 'Last Seen At', 'Total Lifetime Visits']
                if len(loyal) > 0:
                    st.caption(f"Guests with 3+ lifetime visits: {len(loyal)}")
                    st.dataframe(loyal.head(50), use_container_width=True, hide_index=True)
                else:
                    st.info("No guests with 3+ lifetime visits found.")
            elif 'guest_name' in df_mkt_res.columns:
                guest_counts = df_mkt_res.groupby('guest_name').agg(
                    Visits=('guest_name', 'count'),
                    Total_Covers=('party_size', 'sum'),
                    Pubs=('venue_name', lambda x: ', '.join(sorted(x.dropna().unique())))
                ).reset_index()
                guest_counts.columns = ['Guest', 'Visits (Period)', 'Total Covers', 'Pubs Visited']
                guest_counts = guest_counts[guest_counts['Visits (Period)'] >= 2].sort_values('Visits (Period)', ascending=False)
                if len(guest_counts) > 0:
                    st.caption(f"Guests with 2+ visits in selected period: {len(guest_counts)}")
                    st.dataframe(guest_counts.head(50), use_container_width=True, hide_index=True)
                else:
                    st.info("No repeat guests found in this period. Try a longer date range.")
            else:
                st.info("No guest name data available.")

            # === GUEST INSIGHTS ===
            st.markdown("---")
            st.markdown("### Guest Insights")

            insight_col1, insight_col2 = st.columns(2)

            with insight_col1:
                st.markdown("**Special Occasions**")
                if 'reservation_type' in df_mkt_res.columns:
                    occ = df_mkt_res[df_mkt_res['reservation_type'].notna() & (df_mkt_res['reservation_type'].astype(str).str.len() > 0)]
                    if len(occ) > 0:
                        occ_counts = occ['reservation_type'].value_counts().head(10).reset_index()
                        occ_counts.columns = ['Occasion', 'Count']
                        st.dataframe(occ_counts, use_container_width=True, hide_index=True)
                    else:
                        st.info("No occasion data.")
                else:
                    st.info("No occasion data.")

            with insight_col2:
                st.markdown("**Party Size Distribution**")
                if 'party_size' in df_mkt_res.columns:
                    ps = df_mkt_res['party_size'].value_counts().sort_index().reset_index()
                    ps.columns = ['Party Size', 'Bookings']
                    st.dataframe(ps, use_container_width=True, hide_index=True)
        else:
            st.info("No reservation data loaded.")
    else:
        st.info("Click **Load Marketing Data** to fetch guest intelligence.")

# === SALES & FOOD TAB ===
with tab_sales:
    st.subheader("Sales & Food — Tevalis POS Data")

    sf_col1, sf_col2, sf_col3 = st.columns([1, 1, 2])
    with sf_col1:
        sf_from = st.date_input("From", value=date.today() - timedelta(days=7), key="sf_from", format="DD/MM/YYYY")
    with sf_col2:
        sf_to = st.date_input("To", value=date.today(), key="sf_to", format="DD/MM/YYYY")
    with sf_col3:
        sf_venue_options = ["All Pubs"] + sorted([v['name'].strip() for v in venues])
        sf_venue = st.selectbox("Pub", sf_venue_options, key="sf_venue")

    if st.button("Load Sales Data", type="primary", key="load_sf"):
        with st.spinner("Fetching POS data from SevenRooms..."):
            sf_resp = client.get_reservations(
                from_date=sf_from.strftime("%Y-%m-%d"),
                to_date=sf_to.strftime("%Y-%m-%d")
            )
            sf_reservations = sf_resp.get("data", {}).get("results", []) if sf_resp else []
            st.session_state['sf_reservations'] = sf_reservations
            ticket_count = sum(1 for r in sf_reservations if r.get('pos_tickets'))
            st.success(f"Loaded {len(sf_reservations)} reservations, {ticket_count} with POS data")

    if 'sf_reservations' in st.session_state:
        sf_res = st.session_state['sf_reservations']

        # Filter by venue
        if sf_venue != "All Pubs":
            target_ids = [v['id'] for v in venues if v['name'] == sf_venue]
            sf_res = [r for r in sf_res if r.get('venue_id') in target_ids]

        # Extract all POS tickets
        tickets = []
        items_all = []
        for res in sf_res:
            pos = res.get('pos_tickets') or []
            guest = f"{res.get('first_name', '')} {res.get('last_name', '')}".strip() or 'Unknown'
            res_venue = venue_map.get(res.get('venue_id'), 'Unknown')
            res_date = res.get('date', '')
            covers = res.get('max_guests') or res.get('arrived_guests') or 1
            shift = res.get('shift_category', '') or ''
            for t in pos:
                if t.get('source') == 'TEVALIS':
                    subtotal = t.get('subtotal') or 0
                    tax = t.get('tax') or 0
                    service_charge = t.get('service_charge') or 0
                    total = t.get('total') or subtotal
                    # Dwell time
                    try:
                        t_start = datetime.fromisoformat(t['start_time'])
                        t_end = datetime.fromisoformat(t['end_time'])
                        dwell_mins = round((t_end - t_start).total_seconds() / 60)
                    except Exception:
                        dwell_mins = None
                    tickets.append({
                        'date': res_date,
                        'venue': res_venue,
                        'guest': guest,
                        'covers': covers,
                        'subtotal': subtotal,
                        'tax': tax,
                        'service_charge': service_charge,
                        'total': total,
                        'spend_per_head': round(subtotal / covers, 2) if covers else 0,
                        'ticket_id': t.get('ticket_id', ''),
                        'status': t.get('status', ''),
                        'shift': shift.title() if shift else 'Unknown',
                        'dwell_mins': dwell_mins,
                    })
                    for item in (t.get('items') or []):
                        items_all.append({
                            'date': res_date,
                            'venue': res_venue,
                            'item': item.get('name', 'Unknown'),
                            'price': item.get('price') or 0,
                            'quantity': item.get('quantity') or 1,
                            'revenue': (item.get('price') or 0) * (item.get('quantity') or 1),
                        })

        if not tickets:
            st.info("No Tevalis POS data found for this period. Tickets are linked to reservations when guests are checked in and the till is connected.")
        else:
            df_tickets = pd.DataFrame(tickets)
            df_items = pd.DataFrame(items_all) if items_all else pd.DataFrame()

            # --- SUMMARY METRICS ---
            total_revenue = df_tickets['subtotal'].sum()
            total_tax = df_tickets['tax'].sum()
            total_sc = df_tickets['service_charge'].sum()
            total_covers_sf = df_tickets['covers'].sum()
            avg_spend = total_revenue / total_covers_sf if total_covers_sf else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Revenue (ex. tax)", f"£{total_revenue:,.2f}")
            m2.metric("Tax Collected", f"£{total_tax:,.2f}")
            m3.metric("Service Charge", f"£{total_sc:,.2f}")
            m4.metric("Avg Spend per Head", f"£{avg_spend:,.2f}")

            st.markdown("---")

            # --- PER PUB BREAKDOWN ---
            if sf_venue == "All Pubs":
                st.markdown("### Revenue by Pub")
                pub_summary = df_tickets.groupby('venue').agg(
                    Tickets=('ticket_id', 'count'),
                    Covers=('covers', 'sum'),
                    Revenue=('subtotal', 'sum'),
                    Avg_per_Head=('spend_per_head', 'mean'),
                    Service_Charge=('service_charge', 'sum'),
                ).reset_index()
                pub_summary.columns = ['Pub', 'Tickets', 'Covers', 'Revenue (£)', 'Avg/Head (£)', 'Service Charge (£)']
                pub_summary['Revenue (£)'] = pub_summary['Revenue (£)'].round(2)
                pub_summary['Avg/Head (£)'] = pub_summary['Avg/Head (£)'].round(2)
                pub_summary['Service Charge (£)'] = pub_summary['Service Charge (£)'].round(2)
                pub_summary = pub_summary.sort_values('Revenue (£)', ascending=False)
                st.dataframe(pub_summary, use_container_width=True, hide_index=True)
                st.markdown("---")

            # --- REVENUE BY SERVICE ---
            st.markdown("### Revenue by Service")
            known_shifts = [s for s in df_tickets['shift'].unique() if s != 'Unknown']
            if known_shifts:
                shift_summary = df_tickets.groupby('shift').agg(
                    Tickets=('ticket_id', 'count'),
                    Covers=('covers', 'sum'),
                    Revenue=('subtotal', 'sum'),
                    Avg_per_Head=('spend_per_head', 'mean'),
                ).reset_index()
                shift_summary.columns = ['Service', 'Tickets', 'Covers', 'Revenue (£)', 'Avg/Head (£)']
                shift_summary['Revenue (£)'] = shift_summary['Revenue (£)'].round(2)
                shift_summary['Avg/Head (£)'] = shift_summary['Avg/Head (£)'].round(2)
                shift_summary['% of Revenue'] = (shift_summary['Revenue (£)'] / shift_summary['Revenue (£)'].sum() * 100).round(1).astype(str) + '%'
                shift_summary = shift_summary.sort_values('Revenue (£)', ascending=False)
                st.dataframe(shift_summary, use_container_width=True, hide_index=True)
            else:
                st.caption("Service period data not available for this selection.")
            st.markdown("---")

            # --- FOOD VS DRINKS SPLIT ---
            if not df_items.empty:
                st.markdown("### Food vs Drinks Split")
                drink_keywords = ['beer', 'lager', 'ale', 'stout', 'cider', 'wine', 'prosecco', 'champagne',
                                  'gin', 'vodka', 'rum', 'whisky', 'whiskey', 'spirit', 'cocktail', 'shots',
                                  'pint', 'half', 'soft drink', 'cola', 'juice', 'water', 'coffee', 'tea',
                                  'americano', 'latte', 'cappuccino', 'espresso', 'hot chocolate',
                                  'thatchers', 'peroni', 'estrella', 'corona', 'guinness', 'fosters',
                                  'carlsberg', 'heineken', 'mahou', 'proper job', 'tribute', 'korev']
                df_items['category'] = df_items['item'].apply(
                    lambda x: 'Drinks' if any(k in x.lower() for k in drink_keywords) else 'Food'
                )
                if sf_venue == "All Pubs":
                    # Overall split
                    split = df_items.groupby('category')['revenue'].sum().reset_index()
                    total_split = split['revenue'].sum()
                    split['% of Revenue'] = (split['revenue'] / total_split * 100).round(1).astype(str) + '%'
                    split['Revenue (£)'] = split['revenue'].round(2)
                    split = split[['category', 'Revenue (£)', '% of Revenue']].rename(columns={'category': 'Category'})
                    st.dataframe(split, use_container_width=True, hide_index=True)

                    # Per pub split
                    st.markdown("**By pub**")
                    pub_split = df_items.groupby(['venue', 'category'])['revenue'].sum().unstack(fill_value=0).reset_index()
                    if 'Food' not in pub_split.columns:
                        pub_split['Food'] = 0.0
                    if 'Drinks' not in pub_split.columns:
                        pub_split['Drinks'] = 0.0
                    pub_split['Total'] = pub_split['Food'] + pub_split['Drinks']
                    pub_split['Food %'] = (pub_split['Food'] / pub_split['Total'] * 100).round(1).astype(str) + '%'
                    pub_split['Drinks %'] = (pub_split['Drinks'] / pub_split['Total'] * 100).round(1).astype(str) + '%'
                    pub_split['Food (£)'] = pub_split['Food'].round(2)
                    pub_split['Drinks (£)'] = pub_split['Drinks'].round(2)
                    pub_split = pub_split[['venue', 'Food (£)', 'Food %', 'Drinks (£)', 'Drinks %']].rename(columns={'venue': 'Pub'})
                    pub_split = pub_split.sort_values('Drinks %', ascending=False)
                    st.dataframe(pub_split, use_container_width=True, hide_index=True)
                else:
                    split = df_items.groupby('category')['revenue'].sum().reset_index()
                    total_split = split['revenue'].sum()
                    split['% of Revenue'] = (split['revenue'] / total_split * 100).round(1).astype(str) + '%'
                    split['Revenue (£)'] = split['revenue'].round(2)
                    split = split[['category', 'Revenue (£)', '% of Revenue']].rename(columns={'category': 'Category'})
                    st.dataframe(split, use_container_width=True, hide_index=True)
                st.markdown("---")

            # --- TABLE DWELL TIME ---
            dwell_df = df_tickets[df_tickets['dwell_mins'].notna() & (df_tickets['dwell_mins'] > 0)].copy()
            if not dwell_df.empty:
                st.markdown("### Table Dwell Time")
                avg_dwell = dwell_df['dwell_mins'].mean()
                max_dwell = dwell_df['dwell_mins'].max()
                min_dwell = dwell_df['dwell_mins'].min()

                d1, d2, d3 = st.columns(3)
                d1.metric("Avg Time at Table", f"{int(avg_dwell)} mins")
                d2.metric("Longest Sitting", f"{int(max_dwell)} mins")
                d3.metric("Shortest Sitting", f"{int(min_dwell)} mins")

                # Flag long sitters (over 2hrs)
                long_sit = dwell_df[dwell_df['dwell_mins'] > 120].sort_values('dwell_mins', ascending=False)
                if not long_sit.empty:
                    st.markdown(f"**Tables over 2 hours** ({len(long_sit)} tickets)")
                    long_display = long_sit[['date', 'venue', 'guest', 'covers', 'dwell_mins', 'subtotal']].copy()
                    long_display.columns = ['Date', 'Pub', 'Guest', 'Covers', 'Mins at Table', 'Revenue (£)']
                    long_display['Revenue (£)'] = long_display['Revenue (£)'].round(2)
                    st.dataframe(long_display, use_container_width=True, hide_index=True)

                if sf_venue == "All Pubs":
                    st.markdown("**Avg dwell time by pub**")
                    pub_dwell = dwell_df.groupby('venue')['dwell_mins'].mean().round(0).astype(int).reset_index()
                    pub_dwell.columns = ['Pub', 'Avg Mins at Table']
                    pub_dwell = pub_dwell.sort_values('Avg Mins at Table', ascending=False)
                    st.dataframe(pub_dwell, use_container_width=True, hide_index=True)
                st.markdown("---")

            # --- POPULAR DISHES ---
            if not df_items.empty:
                def items_table(df, by='quantity'):
                    grp = df.groupby('item').agg(
                        Qty_Sold=('quantity', 'sum'),
                        Revenue=('revenue', 'sum'),
                    ).reset_index()
                    grp = grp.sort_values('Qty_Sold' if by == 'quantity' else 'Revenue', ascending=False).head(15)
                    grp.columns = ['Dish', 'Times Ordered', 'Revenue (£)']
                    grp['Revenue (£)'] = grp['Revenue (£)'].round(2)
                    return grp

                if sf_venue == "All Pubs":
                    st.markdown("### Most Popular Dishes Across the Company")
                    ic1, ic2 = st.columns(2)
                    with ic1:
                        st.markdown("**By times ordered**")
                        st.dataframe(items_table(df_items, 'quantity'), use_container_width=True, hide_index=True)
                    with ic2:
                        st.markdown("**By revenue**")
                        st.dataframe(items_table(df_items, 'revenue'), use_container_width=True, hide_index=True)

                    st.markdown("---")
                    st.markdown("### Most Popular Items by Pub")
                    for pub_name in sorted(df_items['venue'].unique()):
                        df_pub_items = df_items[df_items['venue'] == pub_name]
                        with st.expander(pub_name):
                            pc1, pc2 = st.columns(2)
                            with pc1:
                                st.markdown("**By times ordered**")
                                st.dataframe(items_table(df_pub_items, 'quantity'), use_container_width=True, hide_index=True)
                            with pc2:
                                st.markdown("**By revenue**")
                                st.dataframe(items_table(df_pub_items, 'revenue'), use_container_width=True, hide_index=True)
                else:
                    st.markdown(f"### Most Popular Items — {sf_venue}")
                    ic1, ic2 = st.columns(2)
                    with ic1:
                        st.markdown("**By times ordered**")
                        st.dataframe(items_table(df_items, 'quantity'), use_container_width=True, hide_index=True)
                    with ic2:
                        st.markdown("**By revenue**")
                        st.dataframe(items_table(df_items, 'revenue'), use_container_width=True, hide_index=True)

                st.markdown("---")

            # --- DAILY REVENUE TREND ---
            if len(df_tickets['date'].unique()) > 1:
                st.markdown("### Daily Revenue")
                daily = df_tickets.groupby('date').agg(
                    Revenue=('subtotal', 'sum'),
                    Covers=('covers', 'sum'),
                    Tickets=('ticket_id', 'count'),
                ).reset_index().sort_values('date')
                daily.columns = ['Date', 'Revenue (£)', 'Covers', 'Tickets']
                daily['Revenue (£)'] = daily['Revenue (£)'].round(2)
                st.dataframe(daily, use_container_width=True, hide_index=True)
                st.markdown("---")

            # --- INDIVIDUAL TICKETS ---
            with st.expander("View individual tickets"):
                display_tickets = df_tickets[['date', 'venue', 'guest', 'covers', 'subtotal', 'tax', 'service_charge', 'total', 'spend_per_head', 'status']].copy()
                display_tickets.columns = ['Date', 'Pub', 'Guest', 'Covers', 'Subtotal (£)', 'Tax (£)', 'Service Charge (£)', 'Total (£)', 'Spend/Head (£)', 'Status']
                st.dataframe(display_tickets, use_container_width=True, hide_index=True)
    else:
        st.info("Select a date range and click **Load Sales Data** to view Tevalis POS data.")

# === ROOMS INTELLIGENCE TAB ===
with tab_rooms:
    st.subheader("🛏️ Rooms Intelligence")
    st.caption("Historical analysis and forward occupancy across all Chickpea properties")

    from pub_mapping import EVIIVO_PROPERTY_MAPPINGS

    ri_col1, ri_col2, ri_col3 = st.columns([1, 1, 2])
    with ri_col1:
        ri_from = st.date_input("Check-in from", value=date.today() - timedelta(days=90), key="ri_from", format="DD/MM/YYYY")
    with ri_col2:
        ri_to = st.date_input("Check-in to", value=date.today() + timedelta(days=60), key="ri_to", format="DD/MM/YYYY")
    with ri_col3:
        ri_venue = st.selectbox("Property", ["All Properties"] + sorted(EVIIVO_PROPERTY_MAPPINGS.keys()), key="ri_venue")

    if st.button("🔄 Clear Cache", key="clear_rooms_cache", help="Use this if you see 'object has no attribute' errors"):
        get_eviivo_client.clear()
        st.cache_resource.clear()
        st.success("Cache cleared — click Load Rooms Data now.")

    if st.button("Load Rooms Data", type="primary", key="load_rooms"):
        with st.spinner("Fetching room booking data from eviivo..."):
            property_mappings = get_all_eviivo_properties()
            try:
                if eviivo_client._ensure_authenticated():
                    all_stays = eviivo_client.get_all_historical_bookings(
                        property_mappings,
                        checkin_from=ri_from,
                        checkin_to=ri_to,
                    )
                    st.session_state['ri_data'] = all_stays
                    st.success(f"Loaded {len(all_stays)} room bookings ({ri_from.strftime('%d/%m/%Y')} – {ri_to.strftime('%d/%m/%Y')})")
                else:
                    st.error("Could not authenticate with eviivo. Check credentials.")
            except Exception as e:
                st.error(f"Error loading room data: {e}")

    if 'ri_data' in st.session_state:
        stays_raw = st.session_state['ri_data']
        if not stays_raw:
            st.info("No room bookings found for this period.")
        else:
            df_ri = pd.DataFrame(stays_raw)

            # Apply venue filter
            if ri_venue != "All Properties" and 'venue_name' in df_ri.columns:
                df_ri = df_ri[df_ri['venue_name'] == ri_venue]

            if len(df_ri) == 0:
                st.info("No bookings match the selected property filter.")
            else:
                # --- DATA PREPARATION ---
                df_ri['checkin_dt'] = pd.to_datetime(df_ri['date'], errors='coerce')
                df_ri['checkout_dt'] = pd.to_datetime(df_ri['checkout_date'], errors='coerce')
                df_ri['nights'] = (df_ri['checkout_dt'] - df_ri['checkin_dt']).dt.days.clip(lower=0)
                df_ri['party_size'] = pd.to_numeric(df_ri['party_size'], errors='coerce').fillna(1).astype(int)
                df_ri['total_value'] = pd.to_numeric(df_ri['total_value'], errors='coerce').fillna(0)
                df_ri['notes_lower'] = df_ri['notes'].fillna('').str.lower()
                df_ri['checkin_dow'] = df_ri['checkin_dt'].dt.day_name()
                df_ri['checkin_week'] = df_ri['checkin_dt'].dt.to_period('W')

                today_dt = pd.Timestamp(date.today())

                def detect_channel(notes_lower):
                    if any(k in notes_lower for k in ['booking.com', 'non-smoking', 'genius booker', 'payment_on_booking', 'breakfast is included']):
                        return 'Booking.com'
                    if 'expedia' in notes_lower:
                        return 'Expedia'
                    if 'airbnb' in notes_lower:
                        return 'Airbnb'
                    if 'hotels.com' in notes_lower:
                        return 'Hotels.com'
                    return 'Direct / Unknown'

                df_ri['channel'] = df_ri['notes_lower'].apply(detect_channel)
                df_ri['is_dog_friendly'] = df_ri['notes_lower'].str.contains(
                    r'\bdog\b|\bpet\b|\bcanine\b|\bpuppy\b|\bpuppies\b', regex=True
                )

                df_confirmed = df_ri[df_ri['status'] != 'Cancelled'].copy()
                df_cancelled = df_ri[df_ri['status'] == 'Cancelled'].copy()
                df_past = df_confirmed[df_confirmed['checkin_dt'] < today_dt]
                df_future = df_confirmed[df_confirmed['checkin_dt'] >= today_dt]

                # --- HEADLINE METRICS ---
                total_stays = len(df_confirmed)
                avg_nights = df_confirmed['nights'].mean() if total_stays else 0
                total_revenue = df_confirmed['total_value'].sum()
                cancel_count = len(df_cancelled)
                cancel_rate = cancel_count / max(len(df_ri), 1) * 100
                total_nights_sold = df_confirmed['nights'].sum()
                avg_rate = total_revenue / total_nights_sold if total_nights_sold > 0 else 0
                upcoming_count = len(df_future)

                m1, m2, m3, m4, m5, m6 = st.columns(6)
                m1.metric("Confirmed Stays", f"{total_stays:,}")
                m2.metric("Avg Length of Stay", f"{avg_nights:.1f} nights")
                m3.metric("Upcoming Bookings", f"{upcoming_count:,}")
                m4.metric("Room Revenue", f"£{total_revenue:,.0f}")
                m5.metric("Avg Rate / Night", f"£{avg_rate:.0f}")
                m6.metric("Cancellation Rate", f"{cancel_rate:.1f}%",
                          delta=f"{cancel_count} cancelled", delta_color="inverse")

                st.markdown("---")

                # --- BOOKING CHANNELS ---
                st.markdown("### 📡 Booking Channels")
                st.caption("Channel inferred from booking notes (Booking.com boilerplate, OTA keywords). 'Direct / Unknown' = no OTA markers detected.")

                channel_counts = df_ri.groupby('channel').agg(
                    Total=('channel', 'count'),
                    Confirmed=('status', lambda x: (x != 'Cancelled').sum()),
                    Cancelled=('status', lambda x: (x == 'Cancelled').sum()),
                ).reset_index()
                channel_revenue = df_confirmed.groupby('channel')['total_value'].sum().reset_index()
                channel_revenue.columns = ['channel', 'rev']
                channel_counts = channel_counts.merge(channel_revenue, on='channel', how='left').fillna(0)
                channel_counts['% of Total'] = (channel_counts['Total'] / channel_counts['Total'].sum() * 100).round(1).astype(str) + '%'
                channel_counts['Revenue'] = channel_counts['rev'].apply(lambda x: f"£{x:,.0f}")
                channel_counts = channel_counts.drop(columns=['rev'])
                channel_counts.columns = ['Channel', 'Total Bookings', 'Confirmed', 'Cancelled', '% of Total', 'Revenue (Confirmed)']
                st.dataframe(channel_counts.sort_values('Total Bookings', ascending=False), use_container_width=True, hide_index=True)

                ota_pct = channel_counts[channel_counts['Channel'] != 'Direct / Unknown']['Total Bookings'].sum() / max(len(df_ri), 1) * 100
                st.caption(f"**{ota_pct:.0f}%** of bookings came via third-party OTAs in this period.")

                st.markdown("---")

                # --- CANCELLATIONS ---
                st.markdown("### ❌ Cancellations")
                canc_col1, canc_col2 = st.columns(2)

                with canc_col1:
                    st.caption(f"**{cancel_count}** cancellations — **{cancel_rate:.1f}%** of all bookings")
                    if cancel_count > 0 and 'venue_name' in df_cancelled.columns:
                        by_venue = df_cancelled.groupby('venue_name').size().reset_index(name='Cancellations')
                        total_by_venue = df_ri.groupby('venue_name').size().reset_index(name='Total')
                        by_venue = by_venue.merge(total_by_venue, on='venue_name', how='left')
                        by_venue['Cancel Rate'] = (by_venue['Cancellations'] / by_venue['Total'] * 100).round(1).astype(str) + '%'
                        by_venue.columns = ['Property', 'Cancellations', 'Total Bookings', 'Cancel Rate']
                        st.dataframe(by_venue.sort_values('Cancellations', ascending=False), use_container_width=True, hide_index=True)
                    else:
                        st.success("No cancellations in this period.")

                with canc_col2:
                    if cancel_count > 0:
                        st.markdown("**Cancellations by channel**")
                        canc_ch = df_cancelled['channel'].value_counts().reset_index()
                        canc_ch.columns = ['Channel', 'Cancellations']
                        st.dataframe(canc_ch, use_container_width=True, hide_index=True)

                        canc_nights = df_cancelled['nights'].mean()
                        st.metric("Avg stay length at cancellation", f"{canc_nights:.1f} nights")

                st.markdown("---")

                # --- WEEKEND OCCUPANCY ---
                st.markdown("### 📅 Weekend Occupancy by Week")
                st.caption("Friday, Saturday and Sunday check-ins — flags upcoming quiet weekends")

                weekend_days = ['Friday', 'Saturday', 'Sunday']
                all_weeks = sorted(df_confirmed['checkin_week'].dropna().unique())

                if all_weeks:
                    week_data = []
                    for week in all_weeks:
                        week_df = df_confirmed[df_confirmed['checkin_week'] == week]
                        week_start = week.start_time.date()
                        fri = len(week_df[week_df['checkin_dow'] == 'Friday'])
                        sat = len(week_df[week_df['checkin_dow'] == 'Saturday'])
                        sun = len(week_df[week_df['checkin_dow'] == 'Sunday'])
                        total_wknd = fri + sat + sun
                        total_wkday = len(week_df) - total_wknd
                        is_future = week_start >= date.today()
                        week_data.append({
                            'Week': f"w/c {week_start.strftime('%d/%m/%y')}",
                            'Fri': fri,
                            'Sat': sat,
                            'Sun': sun,
                            'Weekend Total': total_wknd,
                            'Weekday Check-ins': total_wkday,
                            'Period': '🔮 Upcoming' if is_future else '✅ Past',
                        })

                    df_weeks = pd.DataFrame(week_data)
                    quiet_upcoming = df_weeks[(df_weeks['Period'] == '🔮 Upcoming') & (df_weeks['Weekend Total'] < 3)]
                    if len(quiet_upcoming) > 0:
                        st.warning(
                            f"⚠️ **{len(quiet_upcoming)} upcoming quiet weekend{'s' if len(quiet_upcoming) != 1 else ''}** "
                            f"with fewer than 3 check-ins: {', '.join(quiet_upcoming['Week'].tolist())}"
                        )
                    st.dataframe(df_weeks, use_container_width=True, hide_index=True)
                else:
                    st.info("No week data available.")

                st.markdown("---")

                # --- DOG-FRIENDLY STAYS ---
                st.markdown("### 🐕 Dog-Friendly Stays")
                df_dogs = df_confirmed[df_confirmed['is_dog_friendly']]
                dog_count = len(df_dogs)
                dog_pct = dog_count / max(len(df_confirmed), 1) * 100

                dog_col1, dog_col2 = st.columns(2)
                with dog_col1:
                    st.metric("Dog-Friendly Stays", f"{dog_count}", f"{dog_pct:.1f}% of confirmed stays")
                    if dog_count > 0 and 'venue_name' in df_dogs.columns:
                        by_venue = df_dogs.groupby('venue_name').agg(
                            Stays=('venue_name', 'count'),
                            Guests=('party_size', 'sum'),
                        ).reset_index()
                        by_venue.columns = ['Property', 'Dog-Friendly Stays', 'Total Guests']
                        st.dataframe(by_venue.sort_values('Dog-Friendly Stays', ascending=False), use_container_width=True, hide_index=True)
                    elif dog_count == 0:
                        st.info("No dog-friendly stays detected in booking notes for this period.")

                with dog_col2:
                    if dog_count > 0:
                        st.markdown("**Recent dog-friendly bookings**")
                        sample = df_dogs[['venue_name', 'guest_name', 'date', 'nights', 'notes']].copy()
                        sample['notes'] = sample['notes'].fillna('').str[:120]
                        sample.columns = ['Property', 'Guest', 'Check-in', 'Nights', 'Notes']
                        st.dataframe(sample.tail(10), use_container_width=True, hide_index=True)

                st.markdown("---")

                # --- LENGTH OF STAY ---
                st.markdown("### 📏 Length of Stay")
                los_col1, los_col2 = st.columns(2)

                with los_col1:
                    st.markdown("**Distribution (all properties)**")
                    los = df_confirmed['nights'].value_counts().sort_index().reset_index()
                    los.columns = ['Nights', 'Stays']
                    los['% of Total'] = (los['Stays'] / los['Stays'].sum() * 100).round(1).astype(str) + '%'
                    st.dataframe(los, use_container_width=True, hide_index=True)

                with los_col2:
                    st.markdown("**Avg nights by property**")
                    los_venue = df_confirmed.groupby('venue_name')['nights'].mean().round(1).reset_index()
                    los_venue.columns = ['Property', 'Avg Nights']
                    st.dataframe(los_venue.sort_values('Avg Nights', ascending=False), use_container_width=True, hide_index=True)

                st.markdown("---")

                # --- REVENUE BY PROPERTY ---
                st.markdown("### 💰 Revenue & Rate Analysis")
                if total_revenue > 0:
                    rev_by_venue = df_confirmed.groupby('venue_name').agg(
                        Stays=('total_value', 'count'),
                        Revenue=('total_value', 'sum'),
                        Nights=('nights', 'sum'),
                        Guests=('party_size', 'sum'),
                    ).reset_index()
                    rev_by_venue['ADR'] = (rev_by_venue['Revenue'] / rev_by_venue['Nights'].replace(0, 1)).round(2)
                    rev_by_venue['Rev/Guest'] = (rev_by_venue['Revenue'] / rev_by_venue['Guests'].replace(0, 1)).round(2)
                    rev_by_venue['Revenue'] = rev_by_venue['Revenue'].apply(lambda x: f"£{x:,.0f}")
                    rev_by_venue['ADR'] = rev_by_venue['ADR'].apply(lambda x: f"£{x:.0f}")
                    rev_by_venue['Rev/Guest'] = rev_by_venue['Rev/Guest'].apply(lambda x: f"£{x:.0f}")
                    rev_by_venue.columns = ['Property', 'Stays', 'Total Revenue', 'Nights Sold', 'Total Guests', 'ADR (£)', 'Rev / Guest (£)']
                    st.dataframe(rev_by_venue.sort_values('Stays', ascending=False), use_container_width=True, hide_index=True)
                    st.caption("ADR = Average Daily Rate. Revenue figures depend on rates being set in eviivo.")

                    # Top revenue weeks
                    if len(all_weeks) > 0:
                        weekly_rev = df_confirmed.groupby('checkin_week')['total_value'].sum().reset_index()
                        weekly_rev['week_label'] = weekly_rev['checkin_week'].apply(lambda w: f"w/c {w.start_time.strftime('%d/%m/%y')}")
                        weekly_rev = weekly_rev.sort_values('total_value', ascending=False).head(5)
                        weekly_rev['total_value'] = weekly_rev['total_value'].apply(lambda x: f"£{x:,.0f}")
                        weekly_rev = weekly_rev[['week_label', 'total_value']]
                        weekly_rev.columns = ['Week', 'Revenue']
                        st.markdown("**Top 5 weeks by revenue**")
                        st.dataframe(weekly_rev, use_container_width=True, hide_index=True)
                else:
                    st.info("No revenue data available. Check that nightly rates are configured in eviivo.")

                st.markdown("---")

                # --- FORWARD OCCUPANCY ---
                if len(df_future) > 0:
                    st.markdown("### 🔮 Forward Occupancy — Next 8 Weeks")
                    st.caption("Number of check-ins per week per property")

                    today_monday = date.today() - timedelta(days=date.today().weekday())
                    week_starts = [today_monday + timedelta(weeks=i) for i in range(8)]

                    fwd_data = []
                    for pub in sorted(df_confirmed['venue_name'].unique()):
                        row = {'Property': pub}
                        pub_future = df_future[df_future['venue_name'] == pub]
                        for ws in week_starts:
                            we = ws + timedelta(days=6)
                            ws_ts = pd.Timestamp(ws)
                            we_ts = pd.Timestamp(we)
                            count = len(pub_future[
                                (pub_future['checkin_dt'] >= ws_ts) & (pub_future['checkin_dt'] <= we_ts)
                            ])
                            row[ws.strftime('%d/%m')] = count if count > 0 else ''
                        fwd_data.append(row)

                    df_fwd = pd.DataFrame(fwd_data)
                    st.dataframe(df_fwd, use_container_width=True, hide_index=True)

                    # Upcoming revenue pipeline
                    if df_future['total_value'].sum() > 0:
                        pipeline = df_future['total_value'].sum()
                        st.metric("Revenue in pipeline (upcoming confirmed)", f"£{pipeline:,.0f}")

                    st.markdown("---")

                # --- PARTY SIZE ---
                st.markdown("### 👥 Party Size")
                ps_col1, ps_col2 = st.columns(2)

                with ps_col1:
                    ps = df_confirmed['party_size'].value_counts().sort_index().reset_index()
                    ps.columns = ['Party Size', 'Stays']
                    ps['% of Total'] = (ps['Stays'] / ps['Stays'].sum() * 100).round(1).astype(str) + '%'
                    st.dataframe(ps, use_container_width=True, hide_index=True)

                with ps_col2:
                    avg_ps = df_confirmed['party_size'].mean()
                    st.metric("Average Party Size", f"{avg_ps:.1f} guests")
                    total_c = len(df_confirmed)
                    solo = len(df_confirmed[df_confirmed['party_size'] == 1])
                    couples = len(df_confirmed[df_confirmed['party_size'] == 2])
                    groups = len(df_confirmed[df_confirmed['party_size'] >= 3])
                    st.markdown(f"Solo travellers: **{solo}** ({solo/max(total_c,1)*100:.0f}%)")
                    st.markdown(f"Couples: **{couples}** ({couples/max(total_c,1)*100:.0f}%)")
                    st.markdown(f"Groups (3+): **{groups}** ({groups/max(total_c,1)*100:.0f}%)")

    else:
        st.info("Select a date range and click **Load Rooms Data** to view room intelligence.")
