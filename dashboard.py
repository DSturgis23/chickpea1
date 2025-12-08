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

st.title("Chickpea Pubs - Reservations Dashboard")

# Create tabs
tab_operations, tab_analytics = st.tabs(["📅 Operations", "📊 Analytics"])

# Initialize client
@st.cache_resource
def get_client():
    return SevenRoomsClient()

client = get_client()

# === DATA LOADING FUNCTIONS ===

def load_data():
    """Load venues and reservations from SevenRooms (fresh, no cache for Operations)"""
    if not client.authenticate():
        return None, None, None

    venues_resp = client.get_venues()
    venues = venues_resp.get("data", {}).get("results", []) if venues_resp else []

    # Fetch reservations from today through 90 days out
    from_date = datetime.now()
    to_date = datetime.now() + timedelta(days=90)
    res_resp = client.get_reservations(from_date=from_date, to_date=to_date)
    reservations = res_resp.get("data", {}).get("results", []) if res_resp else []

    # Fetch historical data for comparison (last 2 weeks)
    hist_from = datetime.now() - timedelta(days=14)
    hist_to = datetime.now() - timedelta(days=1)
    hist_resp = client.get_reservations(from_date=hist_from, to_date=hist_to)
    historical = hist_resp.get("data", {}).get("results", []) if hist_resp else []

    return venues, reservations, historical

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

# Sidebar - global controls only
st.sidebar.header("Settings")

# Load/Refresh button
if st.sidebar.button("Refresh Data", type="primary") or 'venues' not in st.session_state:
    with st.spinner("Loading from SevenRooms..."):
        venues, reservations, historical = load_data()
        if venues is not None:
            st.session_state['venues'] = venues
            st.session_state['reservations'] = reservations
            st.session_state['historical'] = historical
            st.sidebar.success(f"Loaded {len(venues)} pubs, {len(reservations)} future + {len(historical)} historical reservations")
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
    # Map shift categories - handle 'DAY' by looking at time
    def map_meal_period(row):
        shift = str(row.get('shift_category', '')).upper()
        if shift in ['BREAKFAST']:
            return 'Breakfast'
        elif shift in ['LUNCH']:
            return 'Lunch'
        elif shift in ['DINNER']:
            return 'Dinner'
        elif shift == 'DAY':
            # Determine from time - before 15:00 is Lunch, after is Dinner
            time_str = row.get('time_slot_iso', '')
            if time_str:
                try:
                    hour = int(str(time_str).split(':')[0])
                    return 'Lunch' if hour < 15 else 'Dinner'
                except:
                    pass
            return 'Lunch'  # Default DAY to Lunch
        return 'Other'
    df['meal_period'] = df.apply(map_meal_period, axis=1)

# Combine notes
df['all_notes'] = df.apply(lambda r: ' | '.join(filter(None, [str(r.get('notes') or ''), str(r.get('client_requests') or '')])), axis=1)

# Parse date
if 'date' in df.columns:
    df['reservation_date'] = pd.to_datetime(df['date'], errors='coerce').dt.date

# Map venue names
venue_map = {v['id']: v['name'] for v in venues}
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
            if shift in ['BREAKFAST']:
                return 'Breakfast'
            elif shift in ['LUNCH']:
                return 'Lunch'
            elif shift in ['DINNER']:
                return 'Dinner'
            elif shift == 'DAY':
                time_str = row.get('time_slot_iso', '')
                if time_str:
                    try:
                        hour = int(str(time_str).split(':')[0])
                        return 'Lunch' if hour < 15 else 'Dinner'
                    except:
                        pass
                return 'Lunch'
            return 'Other'
        df_hist['meal_period'] = df_hist.apply(map_meal_period_hist, axis=1)

# Helper function for formatting differences
def format_diff(current, last_week):
    """Format a value with difference from last week in brackets"""
    if last_week == '-' or last_week == 0:
        return str(current)
    diff = current - last_week
    if diff > 0:
        return f"{current} (+{diff})"
    elif diff < 0:
        return f"{current} ({diff})"
    else:
        return f"{current} (0)"

# === OPERATIONS TAB ===
with tab_operations:
    # Filters at top of Operations tab
    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 2, 2, 1])

    # Venue filter - exclude group-level entries
    venue_names = ["All Pubs"] + sorted([v['name'] for v in venues if 'chickpea' not in v['name'].lower()])
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
        hide_cancelled = st.checkbox("Hide cancelled", value=True, key="ops_hide_cancelled")

    with filter_col4:
        st.caption(f"{len(df)} total loaded")

    st.markdown("---")

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

    # Calculate same day last week for comparison
    last_week_date = selected_date - timedelta(days=7)

    # Filter historical data for last week comparison
    df_last_week = pd.DataFrame()
    if len(df_hist) > 0 and 'reservation_date' in df_hist.columns:
        df_last_week = df_hist[df_hist['reservation_date'] == last_week_date].copy()
        # Apply same filters (venue, exclude cancelled)
        if hide_cancelled and 'status' in df_last_week.columns:
            df_last_week = df_last_week[df_last_week['status'] != 'Canceled']
        if selected_venue != "All Pubs" and 'venue_name' in df_last_week.columns:
            df_last_week = df_last_week[df_last_week['venue_name'] == selected_venue]

    # Calculate meal period breakdown
    total_res = len(df_filtered)
    total_covers = int(df_filtered['party_size'].sum()) if 'party_size' in df_filtered.columns else 0

    # Last week totals
    lw_total_res = len(df_last_week) if len(df_last_week) > 0 else 0
    lw_total_covers = int(df_last_week['party_size'].sum()) if len(df_last_week) > 0 and 'party_size' in df_last_week.columns else 0
    st.subheader(f"Overview - {selected_date.strftime('%A %d/%m/%Y')}")
    if selected_venue != "All Pubs":
        st.caption(f"Showing: {selected_venue}")

    if 'meal_period' in df_filtered.columns:
        meal_stats = []
        for period in ['Breakfast', 'Lunch', 'Dinner']:
            period_df = df_filtered[df_filtered['meal_period'] == period]
            current_res = len(period_df)
            current_covers = int(period_df['party_size'].sum()) if 'party_size' in period_df.columns else 0

            # Get last week data
            if len(df_last_week) > 0 and 'meal_period' in df_last_week.columns:
                lw_period_df = df_last_week[df_last_week['meal_period'] == period]
                lw_res = len(lw_period_df)
                lw_covers = int(lw_period_df['party_size'].sum()) if 'party_size' in lw_period_df.columns else 0
            else:
                lw_res = '-'
                lw_covers = '-'

            row = {
                'Period': period,
                'Reservations': format_diff(current_res, lw_res),
                'Covers': format_diff(current_covers, lw_covers),
                'Last Week Res': lw_res,
                'Last Week Covers': lw_covers
            }
            meal_stats.append(row)

        # Add total row
        total_row = {
            'Period': 'Total',
            'Reservations': format_diff(total_res, lw_total_res),
            'Covers': format_diff(total_covers, lw_total_covers),
            'Last Week Res': lw_total_res if lw_total_res > 0 else '-',
            'Last Week Covers': lw_total_covers if lw_total_covers > 0 else '-'
        }
        meal_stats.insert(0, total_row)

        # Display as table
        meal_df = pd.DataFrame(meal_stats)
        # Rename columns for clarity
        meal_df.columns = ['Period', 'Reservations', 'Covers', f'Res ({last_week_date.strftime("%d/%m")})', f'Covers ({last_week_date.strftime("%d/%m")})']
        st.dataframe(meal_df, use_container_width=True, hide_index=True)
        st.caption(f"Last week comparison: {last_week_date.strftime('%A %d/%m/%Y')}")
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Reservations", total_res)
        with col2:
            st.metric("Covers", total_covers)
        with col3:
            st.metric(f"Last Week Res ({last_week_date.strftime('%d/%m')})", lw_total_res if lw_total_res > 0 else '-')
        with col4:
            st.metric(f"Last Week Covers ({last_week_date.strftime('%d/%m')})", lw_total_covers if lw_total_covers > 0 else '-')

    # Notes count
    if 'all_notes' in df_filtered.columns:
        with_notes = len(df_filtered[df_filtered['all_notes'].str.len() > 0])
        if with_notes > 0:
            st.caption(f"{with_notes} booking(s) with notes")

    # === HELPER FUNCTIONS FOR DISPLAY SECTIONS ===
    def show_reservations_table():
        st.subheader("All Reservations")
        display_cols = ['venue_name', 'time', 'guest_name', 'party_size', 'seating_area', 'table', 'all_notes', 'phone']
        display_cols = [c for c in display_cols if c in df_filtered.columns]
        col_names = ['Pub', 'Time', 'Guest', 'Covers', 'Area', 'Table', 'Notes', 'Phone']

        if len(df_filtered) > 0 and display_cols:
            df_display = df_filtered[display_cols].copy()
            df_display.columns = col_names[:len(display_cols)]
            df_display = df_display.sort_values('Time' if 'Time' in df_display.columns else df_display.columns[0])
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            csv = df_display.to_csv(index=False)
            st.download_button("Download CSV", csv, f"reservations_{selected_date}.csv", "text/csv")
        else:
            st.info("No reservations for the selected filters.")

    def show_alerts():
        st.subheader("Alerts")
        alert_col1, alert_col2, alert_col3 = st.columns(3)

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

    # === DISPLAY SECTIONS ===
    if selected_venue == "All Pubs":
        # All Pubs view: Bookings by Pub -> Alerts -> Reservations
        if 'venue_name' in df_filtered.columns and len(df_filtered) > 0:
            st.subheader("Bookings by Pub")

            # Build comprehensive stats by pub with meal period breakdown
            pub_list = []
            # Get all venues from both current and last week
            all_venues = set(df_filtered['venue_name'].unique())
            if len(df_last_week) > 0 and 'venue_name' in df_last_week.columns:
                all_venues.update(df_last_week['venue_name'].unique())

            for venue in all_venues:
                venue_df = df_filtered[df_filtered['venue_name'] == venue]
                row = {'Pub': venue}

                # Current totals
                current_res = len(venue_df)
                current_covers = int(venue_df['party_size'].sum()) if 'party_size' in venue_df.columns else 0

                # Last week totals for this venue
                if len(df_last_week) > 0 and 'venue_name' in df_last_week.columns:
                    lw_venue_df = df_last_week[df_last_week['venue_name'] == venue]
                    lw_res = len(lw_venue_df)
                    lw_covers = int(lw_venue_df['party_size'].sum()) if 'party_size' in lw_venue_df.columns else 0
                else:
                    lw_res = '-'
                    lw_covers = '-'

                # Format with difference
                row['Total Res'] = format_diff(current_res, lw_res)
                row['Total Covers'] = format_diff(current_covers, lw_covers)
                row['LW Res'] = lw_res
                row['LW Covers'] = lw_covers

                # By meal period
                if 'meal_period' in venue_df.columns:
                    for period in ['Breakfast', 'Lunch', 'Dinner']:
                        period_df = venue_df[venue_df['meal_period'] == period]
                        row[f'{period} Res'] = len(period_df)
                        row[f'{period} Covers'] = int(period_df['party_size'].sum()) if 'party_size' in period_df.columns else 0

                pub_list.append(row)

            pub_stats = pd.DataFrame(pub_list)
            pub_stats = pub_stats.sort_values('Total Covers', ascending=False)

            # Reorder columns - include last week columns after totals
            col_order = ['Pub', 'Total Res', 'Total Covers', 'LW Res', 'LW Covers']
            if 'meal_period' in df_filtered.columns:
                col_order += ['Breakfast Res', 'Breakfast Covers', 'Lunch Res', 'Lunch Covers', 'Dinner Res', 'Dinner Covers']
            pub_stats = pub_stats[[c for c in col_order if c in pub_stats.columns]]

            st.dataframe(pub_stats, use_container_width=True, hide_index=True)
            st.caption(f"LW = Last week ({last_week_date.strftime('%A %d/%m')})")

        show_alerts()
        show_reservations_table()
    else:
        # Individual pub view: Reservations -> Alerts
        show_reservations_table()
        show_alerts()

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
            ["All Pubs"] + sorted([v['name'] for v in venues if 'chickpea' not in v['name'].lower()]),
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
