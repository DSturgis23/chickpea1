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

st.title("Chickpea Pubs - Table Reservations")

# Initialize client
@st.cache_resource
def get_client():
    return SevenRoomsClient()

client = get_client()

# === DATA LOADING FUNCTION ===
def load_data():
    """Load venues and reservations from SevenRooms"""
    if not client.authenticate():
        return None, None

    venues_resp = client.get_venues()
    venues = venues_resp.get("data", {}).get("results", []) if venues_resp else []

    # Fetch reservations from today through 90 days out
    from_date = datetime.now()
    to_date = datetime.now() + timedelta(days=90)
    res_resp = client.get_reservations(from_date=from_date, to_date=to_date)
    reservations = res_resp.get("data", {}).get("results", []) if res_resp else []

    return venues, reservations

# Sidebar controls
st.sidebar.header("Settings")

# Load/Refresh button
if st.sidebar.button("Refresh Data", type="primary") or 'venues' not in st.session_state:
    with st.spinner("Loading from SevenRooms..."):
        venues, reservations = load_data()
        if venues is not None:
            st.session_state['venues'] = venues
            st.session_state['reservations'] = reservations
            st.sidebar.success(f"Loaded {len(venues)} pubs, {len(reservations)} reservations")
        else:
            st.sidebar.error("Failed to connect - check credentials")

# Get data from session state
venues = st.session_state.get('venues', [])
reservations = st.session_state.get('reservations', [])

if not reservations:
    st.info("Click **Load Data** in the sidebar to fetch reservations from SevenRooms.")
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

# Combine notes
df['all_notes'] = df.apply(lambda r: ' | '.join(filter(None, [str(r.get('notes') or ''), str(r.get('client_requests') or '')])), axis=1)

# Parse date
if 'date' in df.columns:
    df['reservation_date'] = pd.to_datetime(df['date'], errors='coerce').dt.date

# Map venue names
venue_map = {v['id']: v['name'] for v in venues}
if 'venue_id' in df.columns:
    df['venue_name'] = df['venue_id'].map(venue_map).fillna('Unknown')

# === FILTERS ===
st.sidebar.markdown("---")
st.sidebar.subheader("Filters")

# Venue filter - exclude group-level entries
venue_names = ["All Pubs"] + sorted([v['name'] for v in venues if 'chickpea' not in v['name'].lower()])
selected_venue = st.sidebar.selectbox("Pub", venue_names)

# Date filter - future dates only
today = date.today()
future_dates = []
if 'reservation_date' in df.columns:
    future_dates = [d for d in df['reservation_date'].dropna().unique() if d >= today]
    future_dates = sorted(future_dates)

if future_dates:
    max_date = max(future_dates)
    # Default to today if available, otherwise first available date
    default_date = today if today in future_dates else future_dates[0]
    selected_date = st.sidebar.date_input(
        "Date",
        value=default_date,
        min_value=today,
        max_value=max_date
    )
else:
    selected_date = today
    st.sidebar.warning("No future reservations found")

# === APPLY FILTERS ===
df_filtered = df.copy()

# Debug info
st.sidebar.caption(f"Total loaded: {len(df)} | Selected: {selected_date} | Venue: {selected_venue}")

# Filter to future dates only
if 'reservation_date' in df_filtered.columns:
    df_filtered = df_filtered[df_filtered['reservation_date'] >= today]

# Filter by venue
if selected_venue != "All Pubs" and 'venue_name' in df_filtered.columns:
    df_filtered = df_filtered[df_filtered['venue_name'] == selected_venue]

# Filter by date - ensure types match
if 'reservation_date' in df_filtered.columns:
    # Convert selected_date to same type as dataframe
    df_filtered = df_filtered[df_filtered['reservation_date'] == selected_date]

st.sidebar.caption(f"After filters: {len(df_filtered)} reservations")

# === METRICS ===
st.subheader(f"Overview - {selected_date.strftime('%A %d %B %Y')}")
if selected_venue != "All Pubs":
    st.caption(f"Showing: {selected_venue}")

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Reservations", len(df_filtered))
with col2:
    covers = int(df_filtered['party_size'].sum()) if 'party_size' in df_filtered.columns else 0
    st.metric("Total Covers", covers)
with col3:
    if 'all_notes' in df_filtered.columns:
        with_notes = len(df_filtered[df_filtered['all_notes'].str.len() > 0])
        st.metric("With Notes", with_notes)
    else:
        st.metric("With Notes", 0)

# === HELPER FUNCTIONS FOR DISPLAY SECTIONS ===
def show_reservations_table():
    st.subheader("All Reservations")
    display_cols = ['venue_name', 'time', 'guest_name', 'party_size', 'table', 'all_notes', 'phone']
    display_cols = [c for c in display_cols if c in df_filtered.columns]

    if len(df_filtered) > 0 and display_cols:
        df_display = df_filtered[display_cols].copy()
        df_display.columns = ['Pub', 'Time', 'Guest', 'Covers', 'Table', 'Notes', 'Phone'][:len(display_cols)]
        df_display = df_display.sort_values('Time' if 'Time' in df_display.columns else df_display.columns[0])
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        csv = df_display.to_csv(index=False)
        st.download_button("Download CSV", csv, f"reservations_{selected_date}.csv", "text/csv")
    else:
        st.info("No reservations for the selected filters.")

def show_alerts():
    st.subheader("Alerts")
    alert_col1, alert_col2 = st.columns(2)

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

# === DISPLAY SECTIONS ===
if selected_venue == "All Pubs":
    # All Pubs view: Bookings by Pub -> Alerts -> Reservations
    if 'venue_name' in df_filtered.columns and len(df_filtered) > 0:
        st.subheader("Bookings by Pub")
        pub_stats = df_filtered.groupby('venue_name').agg(
            Reservations=('venue_name', 'count'),
            Covers=('party_size', 'sum')
        ).reset_index()
        pub_stats.columns = ['Pub', 'Reservations', 'Covers']
        pub_stats['Covers'] = pub_stats['Covers'].astype(int)
        pub_stats = pub_stats.sort_values('Covers', ascending=False)
        st.dataframe(pub_stats, use_container_width=True, hide_index=True)

    show_alerts()
    show_reservations_table()
else:
    # Individual pub view: Reservations -> Alerts
    show_reservations_table()
    show_alerts()

# Footer
st.sidebar.markdown("---")
if st.sidebar.button("Logout"):
    st.session_state.password_ok = False
    st.session_state.pop('venues', None)
    st.session_state.pop('reservations', None)
    st.rerun()
st.sidebar.caption("Chickpea Pub Group")
