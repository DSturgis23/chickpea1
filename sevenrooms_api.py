"""
SevenRooms API Client
Handles authentication and data fetching from SevenRooms
Supports per-venue credentials (each venue has its own client_id/secret)
"""

import requests
import os
from datetime import datetime, timedelta


def _get_venue_credentials():
    """Get per-venue credentials from streamlit secrets, config.py, or env vars.

    Returns list of dicts: [{"name": ..., "client_id": ..., "client_secret": ..., "venue_id": ...}, ...]
    """
    # Try Streamlit secrets first (primary method)
    try:
        import streamlit as st
        venues = st.secrets.get("sevenrooms", {}).get("venues", [])
        if venues:
            return [
                {
                    "name": v["name"],
                    "client_id": v["client_id"],
                    "client_secret": v["client_secret"],
                    "venue_id": v["venue_id"],
                }
                for v in venues
            ]
    except Exception:
        pass

    # Try config.py (legacy single-credential mode)
    try:
        from config import CLIENT_ID, CLIENT_SECRET, API_BASE_URL
        return [{"name": "default", "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "venue_id": None}]
    except ImportError:
        pass

    # Try legacy streamlit secrets
    try:
        import streamlit as st
        client_id = st.secrets.get("sevenrooms_client_id")
        client_secret = st.secrets.get("sevenrooms_client_secret")
        if client_id and client_secret:
            return [{"name": "default", "client_id": client_id, "client_secret": client_secret, "venue_id": None}]
    except Exception:
        pass

    # Fall back to environment variables
    client_id = os.environ.get("SEVENROOMS_CLIENT_ID", "")
    client_secret = os.environ.get("SEVENROOMS_CLIENT_SECRET", "")
    if client_id:
        return [{"name": "default", "client_id": client_id, "client_secret": client_secret, "venue_id": None}]

    return []


class SevenRoomsClient:
    def __init__(self):
        self.base_url = os.environ.get("SEVENROOMS_API_URL", "https://api.sevenrooms.com/2_4")
        self.venue_credentials = _get_venue_credentials()
        # Per-venue tokens: {venue_id: {"token": ..., "expiry": ...}}
        self._tokens = {}

    def authenticate(self):
        """Authenticate all venue credentials. Returns True if at least one succeeds."""
        if not self.venue_credentials:
            print("No SevenRooms credentials configured")
            return False

        success_count = 0
        for vc in self.venue_credentials:
            if self._authenticate_venue(vc):
                success_count += 1

        print(f"Authenticated {success_count}/{len(self.venue_credentials)} venues")
        return success_count > 0

    def _authenticate_venue(self, venue_cred):
        """Authenticate a single venue's credentials."""
        auth_url = f"{self.base_url}/auth"
        payload = {
            "client_id": venue_cred["client_id"],
            "client_secret": venue_cred["client_secret"],
        }

        try:
            response = requests.post(auth_url, data=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            token = data.get("data", {}).get("token") or data.get("token") or data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            expiry = datetime.now() + timedelta(seconds=expires_in)

            key = venue_cred.get("venue_id") or venue_cred["name"]
            self._tokens[key] = {"token": token, "expiry": expiry, "cred": venue_cred}
            return True

        except requests.exceptions.RequestException as e:
            print(f"Auth failed for {venue_cred.get('name', 'unknown')}: {e}")
            return False

    def _ensure_authenticated(self):
        """Ensure we have valid tokens. Re-auth expired ones."""
        if not self._tokens:
            return self.authenticate()

        now = datetime.now()
        for key, info in list(self._tokens.items()):
            if info["expiry"] <= now:
                self._authenticate_venue(info["cred"])

        return bool(self._tokens)

    def _get_headers(self, token):
        """Get headers with authentication token."""
        return {
            "Authorization": token,
            "Content-Type": "application/json",
        }

    def _fetch_paginated(self, endpoint, params, token, timeout=60, results_key="results"):
        """Fetch all pages from a paginated endpoint."""
        url = f"{self.base_url}{endpoint}"
        all_results = []
        cursor = None

        while True:
            if cursor:
                params["cursor"] = cursor

            try:
                response = requests.get(url, headers=self._get_headers(token), params=params, timeout=timeout)

                if response.status_code == 404:
                    return None  # Endpoint not found
                response.raise_for_status()
                data = response.json()

                results = data.get("data", {}).get(results_key, [])
                all_results.extend(results)

                cursor = data.get("data", {}).get("cursor")
                if not cursor:
                    break

            except requests.exceptions.RequestException as e:
                print(f"Fetch error on {endpoint}: {e}")
                break

        return all_results

    def get_venues(self):
        """Fetch venue details for all configured venues."""
        if not self._ensure_authenticated():
            return None

        venues = []
        for key, info in self._tokens.items():
            venue_id = info["cred"].get("venue_id")
            if not venue_id:
                # Legacy mode: try /venues endpoint
                try:
                    response = requests.get(
                        f"{self.base_url}/venues",
                        headers=self._get_headers(info["token"]),
                        timeout=30,
                    )
                    response.raise_for_status()
                    data = response.json()
                    results = data.get("data", {}).get("results", [])
                    venues.extend(results)
                except requests.exceptions.RequestException as e:
                    print(f"Failed to fetch venues list: {e}")
                continue

            # Per-venue mode: fetch individual venue details
            try:
                response = requests.get(
                    f"{self.base_url}/venues/{venue_id}",
                    headers=self._get_headers(info["token"]),
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                venue_data = data.get("data", {})
                if venue_data:
                    venues.append(venue_data)
            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch venue {info['cred'].get('name', venue_id)}: {e}")

        return {"status": 200, "data": {"results": venues}}

    def get_reservations(self, from_date=None, to_date=None, venue_id=None, since_date=None):
        """
        Fetch reservations from all venues (aggregated).

        Args:
            from_date: datetime or string (YYYY-MM-DD)
            to_date: datetime or string (YYYY-MM-DD)
            venue_id: Optional - filter to a specific venue
            since_date: Legacy parameter, ignored
        """
        if not self._ensure_authenticated():
            return None

        if from_date is None:
            from_date = datetime.now()
        if to_date is None:
            to_date = datetime.now() + timedelta(days=90)

        if isinstance(from_date, datetime):
            from_date = from_date.strftime("%Y-%m-%d")
        if isinstance(to_date, datetime):
            to_date = to_date.strftime("%Y-%m-%d")

        all_reservations = []

        for key, info in self._tokens.items():
            cred_venue_id = info["cred"].get("venue_id")

            # If filtering by venue_id, skip non-matching venues
            if venue_id and cred_venue_id and venue_id != cred_venue_id:
                continue

            params = {"from_date": from_date, "to_date": to_date, "limit": 400}
            if cred_venue_id:
                params["venue_id"] = cred_venue_id

            results = self._fetch_paginated("/reservations", params, info["token"])
            if results:
                all_reservations.extend(results)

        return {"status": 200, "data": {"results": all_reservations}}

    def get_reservations_export(self, since_date=None):
        """Fetch reservations export (for larger/historical data)."""
        if not self._ensure_authenticated():
            return None

        if since_date is None:
            since_date = datetime.now() - timedelta(days=90)
        if isinstance(since_date, datetime):
            since_date = since_date.strftime("%Y-%m-%d")

        all_reservations = []

        for key, info in self._tokens.items():
            params = {"updated_since": since_date}
            cred_venue_id = info["cred"].get("venue_id")
            if cred_venue_id:
                params["venue_id"] = cred_venue_id

            url = f"{self.base_url}/reservations/export"
            cursor = None

            while True:
                if cursor:
                    params["cursor"] = cursor
                try:
                    response = requests.get(
                        url, headers=self._get_headers(info["token"]), params=params, timeout=120
                    )
                    response.raise_for_status()
                    data = response.json()

                    reservations = data.get("results", data.get("reservations", []))
                    all_reservations.extend(reservations)

                    cursor = data.get("cursor") or data.get("next_cursor")
                    if not cursor:
                        break
                except requests.exceptions.RequestException as e:
                    print(f"Export fetch error: {e}")
                    break

        return all_reservations

    def get_feedback(self, from_date=None, to_date=None, venue_id=None):
        """
        Fetch guest feedback/reviews from all venues.
        Uses /venues/{venue_id}/feedback endpoint with start_date/end_date params.
        Enriches feedback with guest details from reservation lookups.

        Args:
            from_date: datetime or string (YYYY-MM-DD)
            to_date: datetime or string (YYYY-MM-DD)
            venue_id: Optional venue ID to filter by
        """
        if not self._ensure_authenticated():
            return None

        if from_date is None:
            from_date = datetime.now() - timedelta(days=90)
        if to_date is None:
            to_date = datetime.now()

        if isinstance(from_date, datetime):
            from_date = from_date.strftime("%Y-%m-%d")
        if isinstance(to_date, datetime):
            to_date = to_date.strftime("%Y-%m-%d")

        all_feedback = []

        for key, info in self._tokens.items():
            cred_venue_id = info["cred"].get("venue_id")

            if venue_id and cred_venue_id and venue_id != cred_venue_id:
                continue

            if not cred_venue_id:
                continue

            # Use the correct per-venue feedback endpoint
            # Response uses "reservation_feedback" key, not "results"
            endpoint = f"/venues/{cred_venue_id}/feedback"
            params = {"start_date": from_date, "end_date": to_date, "limit": 400}

            results = self._fetch_paginated(
                endpoint, params, info["token"], results_key="reservation_feedback"
            )
            if results:
                # Enrich each feedback record with venue_id
                for fb in results:
                    fb["venue_id"] = cred_venue_id

                # Look up guest details for low-rated feedback
                low_rated = [fb for fb in results if self._parse_rating(fb.get("overall")) < 3]
                if low_rated:
                    self._enrich_feedback_with_guest_data(low_rated, info["token"])

                print(f"Found {len(results)} feedback ({len(low_rated)} low-rated) from {info['cred'].get('name', key)}")
                all_feedback.extend(results)

        return {
            "status": 200,
            "data": {"results": all_feedback},
            "endpoint_used": "venues/{venue_id}/feedback" if all_feedback else None,
        }

    @staticmethod
    def _parse_rating(value):
        """Parse a rating value to float, defaulting to 5 if unparseable."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return 5

    def _enrich_feedback_with_guest_data(self, feedback_list, token):
        """Look up reservation details to get guest name/email/phone for feedback records."""
        for fb in feedback_list:
            res_id = fb.get("reservation_id")
            if not res_id:
                continue
            try:
                response = requests.get(
                    f"{self.base_url}/reservations/{res_id}",
                    headers=self._get_headers(token),
                    timeout=15,
                )
                if response.status_code == 200:
                    res_data = response.json().get("data", {})
                    fb["first_name"] = res_data.get("first_name", "")
                    fb["last_name"] = res_data.get("last_name", "")
                    fb["email"] = res_data.get("email", "")
                    fb["phone_number"] = res_data.get("phone_number", "")
            except requests.exceptions.RequestException:
                pass


# Test connection
if __name__ == "__main__":
    client = SevenRoomsClient()

    print("Testing SevenRooms API connection...")
    if client.authenticate():
        print("Authentication successful!")

        print("\nFetching venues...")
        venues = client.get_venues()
        if venues:
            for v in venues.get("data", {}).get("results", []):
                print(f"  - {v.get('name')} ({v.get('id', '')[:20]}...)")

        print("\nFetching recent reservations...")
        reservations = client.get_reservations()
        if reservations:
            results = reservations.get("data", {}).get("results", [])
            print(f"  Total: {len(results)} reservations")
    else:
        print("Authentication failed!")
