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

    # Get password from environment variable or secrets
    correct_password = os.environ.get("DASHBOARD_PASSWORD")
    if not correct_password:
        try:
            correct_password = st.secrets.get("password")
        except:
            pass
    if not correct_password:
        correct_password = "chickpea2024"  # Default for testing

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("Chickpea Reservations")
    st.markdown("Please enter the password to access the dashboard.")

    password = st.text_input("Password", type="password", key="password_input")

    if st.button("Login", type="primary"):
        if password == correct_password:
            st.session_state.authenticated = True
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

# Sidebar controls
st.sidebar.header("Settings")

# Date selection
selected_date = st.sidebar.date_input(
    "View Date",
    value=date.today(),
    help="Select date to view reservations"
)

# Date range for fetching
date_range = st.sidebar.selectbox(
    "Fetch Range",
    ["Today only", "Next 7 days", "Next 30 days"],
    index=1
)

days_map = {"Today only": 0, "Next 7 days": 7, "Next 30 days": 30}
fetch_days = days_map[date_range]

# Connect button
if st.sidebar.button("Connect & Refresh", type="primary"):
    with st.spinner("Connecting to SevenRooms..."):
        if client.authenticate():
            st.sidebar.success("Connected!")
            st.session_state['authenticated'] = True

            # Fetch venues
            venues = client.get_venues()
            if venues:
                venue_list = venues.get("results", venues.get("venues", venues.get("data", {}).get("venues", [])))
                st.session_state['venues'] = venue_list

            # Fetch reservations
            since = datetime.now() - timedelta(days=1)
            reservations = client.get_reservations(since_date=since)
            if reservations:
                res_list = reservations.get("results", reservations.get("reservations", reservations.get("data", {}).get("reservations", [])))
                st.session_state['reservations'] = res_list
        else:
            st.sidebar.error("Authentication failed - check credentials")
            st.session_state['authenticated'] = False

# Venue filter
venues = st.session_state.get('venues', [])
venue_names = ["All Pubs"] + [v.get("name", v.get("id", f"Venue {i}")) for i, v in enumerate(venues)]
selected_venue = st.sidebar.selectbox("Select Pub", venue_names)

st.sidebar.markdown("---")

# Main content
if st.session_state.get('authenticated', False):
    reservations = st.session_state.get('reservations', [])

    if reservations:
        df = pd.DataFrame(reservations)

        # Normalize column names (SevenRooms uses various formats)
        col_mapping = {
            'venue_name': ['venue_name', 'venue', 'location'],
            'date': ['date', 'reservation_date', 'day'],
            'time': ['time', 'reservation_time', 'arrival_time'],
            'party_size': ['party_size', 'covers', 'guests', 'size'],
            'table': ['table', 'table_number', 'table_name', 'tables'],
            'status': ['status', 'reservation_status'],
            'guest_name': ['guest_name', 'client_name', 'name', 'first_name'],
            'notes': ['notes', 'special_requests', 'client_notes', 'reservation_notes'],
            'phone': ['phone', 'phone_number', 'client_phone'],
            'email': ['email', 'client_email'],
        }

        for standard, variants in col_mapping.items():
            for v in variants:
                if v in df.columns and standard not in df.columns:
                    df[standard] = df[v]
                    break

        # Filter by venue if selected
        if selected_venue != "All Pubs" and 'venue_name' in df.columns:
            df = df[df['venue_name'] == selected_venue]

        # Filter by selected date if date column exists
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date
            df_today = df[df['date'] == selected_date]
        else:
            df_today = df

        # === METRICS ROW ===
        st.subheader(f"Overview - {selected_date.strftime('%A %d %B %Y')}")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Reservations", len(df_today))
        with col2:
            if 'party_size' in df_today.columns:
                st.metric("Total Covers", int(df_today['party_size'].sum()))
            else:
                st.metric("Total Covers", "-")
        with col3:
            if 'status' in df_today.columns:
                confirmed = len(df_today[df_today['status'].str.lower().isin(['confirmed', 'booked', 'seated'])])
                st.metric("Confirmed", confirmed)
            else:
                st.metric("Confirmed", "-")
        with col4:
            if 'notes' in df_today.columns:
                with_notes = len(df_today[df_today['notes'].notna() & (df_today['notes'] != '')])
                st.metric("With Notes", with_notes)
            else:
                st.metric("With Notes", "-")

        # === ALERTS SECTION ===
        st.subheader("Alerts")

        alert_col1, alert_col2 = st.columns(2)

        # Clash detection
        with alert_col1:
            st.markdown("**Potential Clashes**")
            if 'table' in df_today.columns and 'time' in df_today.columns:
                # Group by venue, table, time to find clashes
                clash_cols = ['table', 'time']
                if 'venue_name' in df_today.columns:
                    clash_cols = ['venue_name'] + clash_cols

                clash_check = df_today.groupby(clash_cols).size().reset_index(name='count')
                clashes = clash_check[clash_check['count'] > 1]

                if len(clashes) > 0:
                    st.error(f"Found {len(clashes)} potential double-bookings!")
                    for _, clash in clashes.iterrows():
                        venue = clash.get('venue_name', 'Unknown')
                        st.write(f"- **{venue}**: Table {clash['table']} at {clash['time']}")
                else:
                    st.success("No clashes detected")
            else:
                st.info("Table/time data not available for clash detection")

        # Notes requiring attention
        with alert_col2:
            st.markdown("**Bookings with Notes**")
            if 'notes' in df_today.columns:
                noted = df_today[df_today['notes'].notna() & (df_today['notes'] != '')]
                if len(noted) > 0:
                    for _, row in noted.head(10).iterrows():
                        guest = row.get('guest_name', 'Guest')
                        venue = row.get('venue_name', '')
                        time = row.get('time', '')
                        note = row['notes'][:100] + ('...' if len(str(row['notes'])) > 100 else '')
                        st.warning(f"**{guest}** ({venue} @ {time}): {note}")
                    if len(noted) > 10:
                        st.caption(f"...and {len(noted) - 10} more")
                else:
                    st.success("No special notes to review")
            else:
                st.info("Notes data not available")

        # === OCCUPANCY BY PUB ===
        st.subheader("Occupancy by Pub")

        if 'venue_name' in df_today.columns:
            occupancy = df_today.groupby('venue_name').agg({
                'party_size': 'sum' if 'party_size' in df_today.columns else 'count'
            }).reset_index()
            occupancy.columns = ['Pub', 'Covers' if 'party_size' in df_today.columns else 'Reservations']
            occupancy = occupancy.sort_values(by=occupancy.columns[1], ascending=True)

            # Bar chart
            st.bar_chart(occupancy.set_index('Pub'))

            # Highlight quiet pubs for marketing
            if len(occupancy) > 0:
                avg_covers = occupancy.iloc[:, 1].mean()
                quiet_pubs = occupancy[occupancy.iloc[:, 1] < avg_covers * 0.5]
                if len(quiet_pubs) > 0:
                    st.info(f"**Marketing opportunity:** These pubs are below 50% of average - consider social media push:")
                    for _, row in quiet_pubs.iterrows():
                        st.write(f"- {row['Pub']}: {int(row.iloc[1])} covers")
        else:
            st.info("Venue data not available for occupancy breakdown")

        # === RESERVATIONS TABLE ===
        st.subheader("All Reservations")

        # Select columns to display
        display_cols = []
        for col in ['venue_name', 'date', 'time', 'guest_name', 'party_size', 'table', 'status', 'notes', 'phone']:
            if col in df_today.columns:
                display_cols.append(col)

        if display_cols:
            st.dataframe(
                df_today[display_cols].sort_values(by='time' if 'time' in display_cols else display_cols[0]),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.dataframe(df_today, use_container_width=True)

        # Download
        csv = df_today.to_csv(index=False)
        st.download_button(
            "Download CSV",
            csv,
            f"reservations_{selected_date}.csv",
            "text/csv"
        )
    else:
        st.warning("No reservations loaded. Click 'Connect & Refresh' in the sidebar.")

else:
    st.info("Click **Connect & Refresh** in the sidebar to load reservation data from SevenRooms.")

    st.markdown("""
    ### Dashboard Features

    - **All Pubs view** - see reservations across all 12 venues
    - **Individual pub filter** - drill down to specific locations
    - **Clash detection** - automatic alerts for double-bookings
    - **Occupancy analysis** - identify quiet pubs for marketing
    - **Notes alerts** - surface bookings with special requests
    - **CSV export** - download data for reporting

    ### Setup

    Update `config.py` with your SevenRooms API credentials:
    ```python
    CLIENT_ID = "your_client_id"
    CLIENT_SECRET = "your_client_secret"
    ```
    """)

# Footer
st.sidebar.markdown("---")
if st.sidebar.button("Logout"):
    st.session_state.authenticated = False
    st.rerun()
st.sidebar.caption("Chickpea Pub Group")
