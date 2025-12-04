"""
SevenRooms API Client
Handles authentication and data fetching from SevenRooms
"""

import requests
from datetime import datetime, timedelta
from config import CLIENT_ID, CLIENT_SECRET, API_BASE_URL


class SevenRoomsClient:
    def __init__(self):
        self.client_id = CLIENT_ID
        self.client_secret = CLIENT_SECRET
        self.base_url = API_BASE_URL
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
            self.token = data.get("token") or data.get("access_token")

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
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def get_reservations(self, since_date=None, venue_id=None):
        """
        Fetch reservations from SevenRooms

        Args:
            since_date: datetime or string (YYYY-MM-DD) - fetch reservations updated since this date
            venue_id: Optional venue ID to filter by
        """
        if not self._ensure_authenticated():
            return None

        if since_date is None:
            since_date = datetime.now() - timedelta(days=30)

        if isinstance(since_date, datetime):
            since_date = since_date.strftime("%Y-%m-%d")

        url = f"{self.base_url}/reservations"
        params = {"updated_since": since_date}

        if venue_id:
            params["venue_id"] = venue_id

        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch reservations: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return None

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
