"""
SevenRooms API Client
Handles authentication and data fetching from SevenRooms
"""

import requests
import os
from datetime import datetime, timedelta


def _get_credentials():
    """Get credentials from config.py, streamlit secrets, or env vars"""
    # Try config.py first (local dev)
    try:
        from config import CLIENT_ID, CLIENT_SECRET, API_BASE_URL
        return CLIENT_ID, CLIENT_SECRET, API_BASE_URL
    except ImportError:
        pass

    # Try Streamlit secrets (cloud deployment)
    try:
        import streamlit as st
        client_id = st.secrets.get("sevenrooms_client_id")
        client_secret = st.secrets.get("sevenrooms_client_secret")
        if client_id and client_secret:
            return client_id, client_secret, "https://api.sevenrooms.com/2_2"
    except Exception:
        pass

    # Fall back to environment variables
    return (
        os.environ.get("SEVENROOMS_CLIENT_ID", ""),
        os.environ.get("SEVENROOMS_CLIENT_SECRET", ""),
        os.environ.get("SEVENROOMS_API_URL", "https://api.sevenrooms.com/2_2")
    )


class SevenRoomsClient:
    def __init__(self):
        self.client_id, self.client_secret, self.base_url = _get_credentials()
        self.token = None
        self.token_expiry = None

    def authenticate(self):
        """Get authentication token from SevenRooms"""
        auth_url = f"{self.base_url}/auth"

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        try:
            response = requests.post(auth_url, data=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            # Token may be nested in data.token or at top level
            self.token = data.get("data", {}).get("token") or data.get("token") or data.get("access_token")

            # Assume token valid for 1 hour if not specified
            expires_in = data.get("expires_in", 3600)
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in)

            return True

        except requests.exceptions.RequestException as e:
            print(f"Authentication failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return False

    def _ensure_authenticated(self):
        """Ensure we have a valid token"""
        if self.token is None or (self.token_expiry and datetime.now() >= self.token_expiry):
            return self.authenticate()
        return True

    def _get_headers(self):
        """Get headers with authentication"""
        return {
            "Authorization": self.token,
            "Content-Type": "application/json"
        }

    def get_reservations(self, from_date=None, to_date=None, venue_id=None, since_date=None):
        """
        Fetch all reservations from SevenRooms (handles pagination)

        Args:
            from_date: datetime or string (YYYY-MM-DD) - fetch reservations from this date
            to_date: datetime or string (YYYY-MM-DD) - fetch reservations up to this date
            venue_id: Optional venue ID to filter by
            since_date: Legacy parameter, ignored if from_date is provided
        """
        if not self._ensure_authenticated():
            return None

        # Default to today through 90 days out
        if from_date is None:
            from_date = datetime.now()
        if to_date is None:
            to_date = datetime.now() + timedelta(days=90)

        if isinstance(from_date, datetime):
            from_date = from_date.strftime("%Y-%m-%d")
        if isinstance(to_date, datetime):
            to_date = to_date.strftime("%Y-%m-%d")

        url = f"{self.base_url}/reservations"
        params = {"from_date": from_date, "to_date": to_date, "limit": 400}

        if venue_id:
            params["venue_id"] = venue_id

        all_reservations = []
        cursor = None

        while True:
            if cursor:
                params["cursor"] = cursor

            try:
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)
                response.raise_for_status()
                data = response.json()

                results = data.get("data", {}).get("results", [])
                all_reservations.extend(results)

                # Check for more pages
                cursor = data.get("data", {}).get("cursor")
                if not cursor:
                    break

            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch reservations: {e}")
                break

        return {"status": 200, "data": {"results": all_reservations}}

    def get_reservations_export(self, since_date=None):
        """
        Fetch reservations export (for larger/historical data)
        """
        if not self._ensure_authenticated():
            return None

        if since_date is None:
            since_date = datetime.now() - timedelta(days=90)

        if isinstance(since_date, datetime):
            since_date = since_date.strftime("%Y-%m-%d")

        url = f"{self.base_url}/reservations/export"
        params = {"updated_since": since_date}

        all_reservations = []
        cursor = None

        while True:
            if cursor:
                params["cursor"] = cursor

            try:
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=120)
                response.raise_for_status()
                data = response.json()

                reservations = data.get("results", data.get("reservations", []))
                all_reservations.extend(reservations)

                # Check for pagination
                cursor = data.get("cursor") or data.get("next_cursor")
                if not cursor:
                    break

            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch reservations export: {e}")
                break

        return all_reservations

    def get_venues(self):
        """Fetch list of venues/hotels"""
        if not self._ensure_authenticated():
            return None

        url = f"{self.base_url}/venues"

        try:
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch venues: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None


    def get_feedback(self, from_date=None, to_date=None, venue_id=None):
        """
        Fetch guest feedback/reviews from SevenRooms
        Tries multiple possible endpoint paths

        Args:
            from_date: datetime or string (YYYY-MM-DD)
            to_date: datetime or string (YYYY-MM-DD)
            venue_id: Optional venue ID to filter by
        """
        if not self._ensure_authenticated():
            return None

        # Default to last 90 days
        if from_date is None:
            from_date = datetime.now() - timedelta(days=90)
        if to_date is None:
            to_date = datetime.now()

        if isinstance(from_date, datetime):
            from_date = from_date.strftime("%Y-%m-%d")
        if isinstance(to_date, datetime):
            to_date = to_date.strftime("%Y-%m-%d")

        # Try different possible endpoint paths
        endpoints = [
            "/reservation_feedback",
            "/reservations/feedback",
            "/feedback",
            "/reviews"
        ]

        all_feedback = []

        for endpoint in endpoints:
            url = f"{self.base_url}{endpoint}"
            params = {"from_date": from_date, "to_date": to_date, "limit": 400}

            if venue_id:
                params["venue_id"] = venue_id

            cursor = None

            while True:
                if cursor:
                    params["cursor"] = cursor

                try:
                    response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)

                    if response.status_code == 404:
                        print(f"Endpoint {endpoint} not found, trying next...")
                        break

                    response.raise_for_status()
                    data = response.json()

                    # Try different response structures
                    results = (
                        data.get("data", {}).get("results", []) or
                        data.get("results", []) or
                        data.get("data", []) or
                        (data if isinstance(data, list) else [])
                    )

                    if results:
                        all_feedback.extend(results)
                        print(f"Found {len(results)} feedback records from {endpoint}")

                    cursor = (
                        data.get("data", {}).get("cursor") or
                        data.get("cursor") or
                        data.get("next_cursor")
                    )
                    if not cursor:
                        break

                except requests.exceptions.RequestException as e:
                    print(f"Failed to fetch from {endpoint}: {e}")
                    break

            # If we found data, stop trying other endpoints
            if all_feedback:
                break

        return {"status": 200, "data": {"results": all_feedback}, "endpoint_used": endpoint if all_feedback else None}


# Test connection
if __name__ == "__main__":
    client = SevenRoomsClient()

    print("Testing SevenRooms API connection...")
    if client.authenticate():
        print("Authentication successful!")
        print(f"Token: {client.token[:20]}...")

        print("\nFetching venues...")
        venues = client.get_venues()
        print(f"Venues: {venues}")

        print("\nFetching recent reservations...")
        reservations = client.get_reservations()
        print(f"Reservations: {reservations}")
    else:
        print("Authentication failed!")
