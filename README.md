# Chickpea Pubs Dashboard

Streamlit web app for managing reservations and analytics across Chickpea pub venues. Integrates with the SevenRooms API (reservations, F&B, guest data) and the Eviivo PMS API (accommodation).

## Running the app

```
cd "C:\Users\Delilah Sturgis\Documents\Chickpea\chickpea"
streamlit run dashboard.py
```

Open http://localhost:8501 — password: see `.streamlit/secrets.toml`

---

## Tabs

### Operations
- Real-time reservations (next 90 days), all-pubs and per-pub views
- Service briefing for managers (occasions, allergies, returning guests, loyal members)
- Week-on-week covers comparison, meal period breakdown
- Table clash detection, CSV export

### Analytics
- Historical reservation trends, covers by day/week/period
- Per-pub performance metrics
- Customer feedback ratings and comments (food, service, ambience, drinks)

### Marketing
- Guest marketing tools and campaign data

---

## Files

| File | Purpose |
|---|---|
| `dashboard.py` | Main Streamlit app |
| `sevenrooms_api.py` | SevenRooms API client — auth, fetching, parsing |
| `eviivo_api.py` | Eviivo API client |
| `config.py` | Reads credentials from `.streamlit/secrets.toml` |
| `pub_mapping.py` | Venue name mappings |
| `requirements.txt` | Python dependencies |

---

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Create `.streamlit/secrets.toml` (never commit this file):
   ```toml
   password = "your_dashboard_password"
   sevenrooms_client_id = "your_client_id"
   sevenrooms_client_secret = "your_client_secret"

   [eviivo]
   client_id = "your_eviivo_client_id"
   client_secret = "your_eviivo_client_secret"
   ```

---

## API integrations

**SevenRooms** (v2.4) — reservations, guest profiles, feedback  
**Eviivo PMS** — accommodation bookings and room data
