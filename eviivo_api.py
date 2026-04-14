"""
eviivo API Client
Handles OAuth authentication and booking data fetching from eviivo PMS
"""

import requests
import os
from datetime import datetime, timedelta


def _get_credentials():
    """Get credentials from config.py, streamlit secrets, or env vars"""
    # Try config.py first (local dev)
    try:
        from config import (
            EVIIVO_CLIENT_ID, EVIIVO_CLIENT_SECRET,
            EVIIVO_AUTH_URL, EVIIVO_API_URL
        )
        return EVIIVO_CLIENT_ID, EVIIVO_CLIENT_SECRET, EVIIVO_AUTH_URL, EVIIVO_API_URL
    except ImportError:
        pass

    # Try Streamlit secrets (cloud deployment)
    try:
        import streamlit as st
        eviivo_secrets = st.secrets.get("eviivo", {})
        client_id = eviivo_secrets.get("client_id")
        client_secret = eviivo_secrets.get("client_secret")
        auth_url = eviivo_secrets.get("auth_url", "https://auth.eviivo.com/api/connect/token")
        api_url = eviivo_secrets.get("api_url", "https://io.eviivo.com/pms/v2")
        if client_id and client_secret:
            return client_id, client_secret, auth_url, api_url
    except Exception:
        pass

    # Fall back to environment variables
    return (
        os.environ.get("EVIIVO_CLIENT_ID", ""),
        os.environ.get("EVIIVO_CLIENT_SECRET", ""),
        os.environ.get("EVIIVO_AUTH_URL", "https://auth.eviivo.com/api/connect/token"),
        os.environ.get("EVIIVO_API_URL", "https://io.eviivo.com/pms/v2")
    )


class EviivoClient:
    def __init__(self):
        self.client_id, self.client_secret, self.auth_url, self.api_url = _get_credentials()
        self.token = None
        self.token_expiry = None

    def authenticate(self):
        """Get OAuth access token from eviivo"""
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": ""
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            response = requests.post(self.auth_url, data=payload, headers=headers, timeout=30)
            response.raise_for_status()

            data = response.json()
            self.token = data.get("access_token")

            # Token expiry - default 1 hour if not specified
            expires_in = data.get("expires_in", 3600)
            self.token_expiry = datetime.now() + timedelta(seconds=expires_in)

            return True

        except requests.exceptions.RequestException as e:
            print(f"eviivo authentication failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return False

    def _ensure_authenticated(self):
        """Ensure we have a valid token"""
        if self.token is None or (self.token_expiry and datetime.now() >= self.token_expiry):
            return self.authenticate()
        return True

    def _get_headers(self):
        """Get headers with OAuth bearer token"""
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Auth-ClientId": self.client_id,
            "Content-Type": "application/json"
        }

    def get_bookings(self, property_short_name, stay_date):
        """
        Fetch bookings for a single property on a given date

        Args:
            property_short_name: eviivo property short name
            stay_date: date object or string (YYYY-MM-DD) for the stay date

        Returns:
            List of normalized booking records, or empty list on error
        """
        if not self._ensure_authenticated():
            return []

        if isinstance(stay_date, datetime):
            stay_date = stay_date.strftime("%Y-%m-%d")
        elif hasattr(stay_date, 'strftime'):
            stay_date = stay_date.strftime("%Y-%m-%d")

        url = f"{self.api_url}/property/{property_short_name}/bookings"
        params = {
            "request.stayDate": stay_date
        }

        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            # eviivo returns {"Bookings": [...]}
            bookings = data.get("Bookings", data if isinstance(data, list) else [])

            normalized = []
            for booking in bookings:
                normalized.append(self._normalize_booking(booking, property_short_name))

            return normalized

        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch bookings for {property_short_name}: {e}")
            return []

    def get_bookings_range(self, property_short_name, checkin_from, checkin_to):
        """Fetch all bookings for a property within a check-in date range.
        Automatically chunks into 31-day batches (API maximum)."""
        if not self._ensure_authenticated():
            return []

        # Normalise to datetime objects
        if isinstance(checkin_from, str):
            checkin_from = datetime.strptime(checkin_from, "%Y-%m-%d")
        elif not isinstance(checkin_from, datetime):
            checkin_from = datetime(checkin_from.year, checkin_from.month, checkin_from.day)

        if isinstance(checkin_to, str):
            checkin_to = datetime.strptime(checkin_to, "%Y-%m-%d")
        elif not isinstance(checkin_to, datetime):
            checkin_to = datetime(checkin_to.year, checkin_to.month, checkin_to.day)

        url = f"{self.api_url}/property/{property_short_name}/bookings"
        all_bookings = []
        chunk_start = checkin_from

        while chunk_start <= checkin_to:
            chunk_end = min(chunk_start + timedelta(days=30), checkin_to)
            params = {
                "request.CheckInFrom": chunk_start.strftime("%Y-%m-%d"),
                "request.CheckInTo": chunk_end.strftime("%Y-%m-%d"),
            }
            try:
                response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)
                if not response.ok:
                    print(f"Eviivo HTTP {response.status_code} for {property_short_name} ({chunk_start.date()} – {chunk_end.date()}): {response.text[:200]}")
                    chunk_start = chunk_end + timedelta(days=1)
                    continue
                bookings = response.json().get("Bookings", [])
                all_bookings.extend([self._normalize_booking(b, property_short_name) for b in bookings])
            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch {property_short_name} ({chunk_start.date()} – {chunk_end.date()}): {e}")
            chunk_start = chunk_end + timedelta(days=1)

        return all_bookings

    def get_all_historical_bookings(self, property_mappings, checkin_from, checkin_to):
        """Fetch historical bookings across all properties within a check-in date range."""
        all_bookings = []
        for venue_name, property_short_name in property_mappings.items():
            if property_short_name:
                bookings = self.get_bookings_range(property_short_name, checkin_from, checkin_to)
                print(f"Eviivo [{property_short_name}]: {len(bookings)} bookings returned")
                for booking in bookings:
                    booking['venue_name'] = venue_name.strip()
                all_bookings.extend(bookings)
        return all_bookings

    def get_all_bookings(self, property_mappings, stay_date):
        """
        Fetch bookings from all mapped properties for a given date

        Args:
            property_mappings: dict mapping SevenRooms venue names to eviivo property shortnames
            stay_date: date object or string (YYYY-MM-DD)

        Returns:
            List of all normalized booking records across all properties
        """
        all_bookings = []

        for venue_name, property_short_name in property_mappings.items():
            if property_short_name:  # Skip unmapped venues
                bookings = self.get_bookings(property_short_name, stay_date)
                # Add venue name to each booking for display
                for booking in bookings:
                    booking['venue_name'] = venue_name.strip()
                all_bookings.extend(bookings)

        return all_bookings

    def _normalize_booking(self, record, property_short_name):
        """Convert eviivo booking record to unified schema."""
        b = record.get("Booking", {})
        guests = record.get("Guests", [])

        # Primary guest
        primary = next((g for g in guests if g.get("PrimaryGuest")), guests[0] if guests else {})
        first_name = primary.get("FirstName", "")
        surname = primary.get("Surname", "")
        guest_name = f"{first_name} {surname}".strip() or "Guest"

        # Party size
        adults = b.get("NumberOfAdults", 0) or 0
        children = b.get("NumberOfChildren", 0) or 0
        guest_count = max(adults + children, 1)

        # Room name (room number / type)
        room = b.get("Room", {})
        room_name = room.get("LocalisedName", "Room")

        # Dates
        checkin_date = b.get("CheckinDate", "")
        checkout_date = b.get("CheckoutDate", "")
        arrival_time = b.get("EstimatedArrivalTime") or "14:00"

        # Contact
        phone = primary.get("Telephone", "")
        email = primary.get("Email", "")

        # Total value
        total = b.get("Total", {}).get("GrossAmount", {}).get("Value", 0) or 0

        # Booking channel / source (OTA vs direct)
        channel = (
            b.get("BookingSource")
            or b.get("Source")
            or b.get("DistributionChannel")
            or b.get("Channel")
            or b.get("BookingOrigin")
            or record.get("BookingSource")
            or record.get("Source")
            or ""
        )
        # Normalise to Direct / OTA / Other
        channel_lower = str(channel).lower()
        if not channel or channel_lower in ("", "none", "unknown"):
            channel_normalised = "Unknown"
        elif any(x in channel_lower for x in ("direct", "phone", "walk", "email", "reception", "website")):
            channel_normalised = "Direct"
        elif any(x in channel_lower for x in ("booking.com", "expedia", "airbnb", "ota", "tripadvisor",
                                               "laterooms", "hotels.com", "agoda", "hostelworld")):
            channel_normalised = "OTA"
        else:
            channel_normalised = channel.strip() or "Other"

        # Room type
        room_type = room.get("RoomType", {})
        room_type_name = room_type.get("LocalisedName", "") if isinstance(room_type, dict) else ""

        return {
            "source": "eviivo",
            "type": "room_stay",
            "venue_name": "",  # filled in by get_all_bookings
            "guest_name": guest_name,
            "party_size": guest_count,
            "phone": phone,
            "email": email,
            "detail": f"Room {room_name}",
            "time": arrival_time,
            "date": checkin_date,
            "checkout_date": checkout_date,
            "booking_ref": b.get("BookingReference", ""),
            "notes": b.get("BookingNote", ""),
            "status": "Cancelled" if b.get("Cancelled") else "Confirmed",
            "checkin_status": b.get("CheckinStatus", ""),
            "total_value": total,
            "property_short_name": property_short_name,
            "booking_channel_raw": channel,
            "booking_channel": channel_normalised,
            "room_name": room_name,
            "room_type": room_type_name,
        }


# Test connection
if __name__ == "__main__":
    # Use test environment credentials
    import os
    os.environ["EVIIVO_CLIENT_ID"] = "d0c7d698-15b3-4b72-8ca9-b3229611ebdc"
    os.environ["EVIIVO_CLIENT_SECRET"] = "T0BHKUEXZ6csLSvtseQP"
    os.environ["EVIIVO_AUTH_URL"] = "https://qaext-auth.eviivo.com/api/connect/token"
    os.environ["EVIIVO_API_URL"] = "https://qaext-io.eviivo.com/pms/v2"

    client = EviivoClient()

    print("Testing eviivo API connection...")
    if client.authenticate():
        print("Authentication successful!")
        print(f"Token: {client.token[:20]}..." if client.token else "No token")

        # Test with a sample property (would need real property name)
        print("\nNote: To test booking retrieval, you need a valid property short name.")
        print("Example: bookings = client.get_bookings('your-property', '2026-02-02')")
    else:
        print("Authentication failed!")
