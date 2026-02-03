# Chickpea Pubs Dashboard

A Python/Streamlit web application for managing reservations and analytics across Chickpea pub venues, integrated with the SevenRooms API.

## Features

### Operations Tab
- Real-time reservation monitoring (next 90 days)
- Per-pub and all-pubs views with filtering
- Table clash detection (overlapping bookings)
- Week-over-week comparison
- Meal period breakdown (breakfast/lunch/dinner)
- Special notes and occasion tracking
- CSV export

### Analytics Tab
- Historical reservation analysis
- Covers trends and daily averages
- Per-pub performance metrics
- Customer feedback ratings and comments
- Category scores (food, service, ambience, drinks)

## Requirements

- Python 3.8+
- Dependencies listed in `requirements.txt`

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd chickpea
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure credentials:
   - Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
   - Add your SevenRooms API credentials and dashboard password

## Configuration

### Local Development

Create `.streamlit/secrets.toml`:
```toml
SEVENROOMS_CLIENT_ID = "your_client_id"
SEVENROOMS_CLIENT_SECRET = "your_client_secret"
DASHBOARD_PASSWORD = "your_password"
```

### Environment Variables

Alternatively, set environment variables:
```bash
export SEVENROOMS_CLIENT_ID="your_client_id"
export SEVENROOMS_CLIENT_SECRET="your_client_secret"
export DASHBOARD_PASSWORD="your_password"
```

## Usage

Run the dashboard:
```bash
streamlit run dashboard.py
```

The dashboard will be available at `http://localhost:8501`.

## Project Structure

```
chickpea/
├── dashboard.py          # Main Streamlit application
├── sevenrooms_api.py     # SevenRooms API client
├── config.py             # Configuration and credentials
├── requirements.txt      # Python dependencies
└── .streamlit/
    └── secrets.toml.example  # Secrets template
```

## API Integration

The application integrates with the SevenRooms API v2.2 to fetch:
- Venue information
- Reservations (past and future)
- Customer feedback and ratings

## Security

- Dashboard is password-protected
- API credentials are stored in Streamlit secrets or environment variables
- OAuth tokens auto-refresh (1-hour expiry)
- Sensitive files (`config.py`, `secrets.toml`) are excluded from git
