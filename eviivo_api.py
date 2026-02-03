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
            "scope": "pmsapi"
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

        url = f"{self.api_url}/properties/{property_short_name}/bookings"
        params = {
            "stayDate": stay_date
        }

        try:
            response = requests.get(url, headers=self._get_headers(), params=params, timeout=60)
            response.raise_for_status()
            data = response.json()

            # eviivo returns bookings in a list
            bookings = data if isinstance(data, list) else data.get("bookings", data.get("data", []))

            # Normalize each booking
            normalized = []
            for booking in bookings:
                normalized.append(self._normalize_booking(booking, property_short_name))

            return normalized

        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch bookings for {property_short_name}: {e}")
            return []

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
                    booking['venue_name'] = venue_name
                all_bookings.extend(bookings)

        return all_bookings

    def _normalize_booking(self, booking, property_short_name):
        """
        Convert eviivo booking format to unified schema

        Args:
            booking: Raw booking data from eviivo API
            property_short_name: The property this booking belongs to

        Returns:
            Dict with normalized fields matching the unified data model
        """
        # Extract guest info - eviivo uses FirstName/Surname
        first_name = booking.get("FirstName", booking.get("firstName", ""))
        surname = booking.get("Surname", booking.get("surname", booking.get("lastName", "")))
        guest_name = f"{first_name} {surname}".strip() or "Guest"

        # Guest count - try various field names
        guest_count = (
            booking.get("NumberOfGuests") or
            booking.get("numberOfGuests") or
            booking.get("Adults", 0) + booking.get("Children", 0) or
            booking.get("adults", 0) + booking.get("children", 0) or
            1
        )

        # Phone number
        phone = (
            booking.get("Telephone") or
            booking.get("telephone") or
            booking.get("Phone") or
            booking.get("phone") or
            booking.get("Mobile") or
            booking.get("mobile") or
            ""
        )

        # Room type/name
        room_type = (
            booking.get("RoomTypeName") or
            booking.get("roomTypeName") or
            booking.get("RoomType") or
            booking.get("roomType") or
            booking.get("UnitName") or
            booking.get("unitName") or
            "Room"
        )

        # Check-in time - default to 14:00 if not specified
        checkin_time = booking.get("CheckInTime") or booking.get("checkInTime") or "14:00"

        # Arrival/stay date
        arrival_date = (
            booking.get("ArrivalDate") or
            booking.get("arrivalDate") or
            booking.get("CheckIn") or
            booking.get("checkIn") or
            ""
        )

        # Booking reference
        booking_ref = (
            booking.get("BookingRef") or
            booking.get("bookingRef") or
            booking.get("Reference") or
            booking.get("reference") or
            booking.get("Id") or
            booking.get("id") or
            ""
        )

        # Notes/special requests
        notes = (
            booking.get("Notes") or
            booking.get("notes") or
            booking.get("SpecialRequests") or
            booking.get("specialRequests") or
            booking.get("Comments") or
            booking.get("comments") or
            ""
        )

        return {
            "source": "eviivo",
            "type": "room_stay",
            "venue_name": "",  # Will be filled in by get_all_bookings
            "guest_name": guest_name,
            "party_size": int(guest_count),
            "phone": phone,
            "detail": room_type,
            "time": checkin_time,
            "date": arrival_date,
            "booking_ref": str(booking_ref),
            "notes": notes,
            "status": booking.get("Status") or booking.get("status") or "Confirmed",
            "property_short_name": property_short_name,
            "raw_booking": booking  # Keep original for debugging
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
