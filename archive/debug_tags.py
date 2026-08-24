"""
Diagnostic — tries to fetch a guest profile directly using client_id from a reservation.
"""
import requests
import json
from datetime import datetime, timedelta

CLIENT_ID = "dcc8dabbbd8de6f13b9831b31535eac35f0792ba6caec7cd2418fb72d1cc90acac580700da9861dfa64f17988b3dcbdd651e3e5fcd626aeb1e70689a37daa962"
CLIENT_SECRET = "40590241a64c8988a36341b5245c04eaaac175d3742ab8e09bea7b7fd46cdf56dda467c75934b5a2c557725a4411efad473a0d54747a2aa6291e6a21c7d21d51"
API_BASE_URL = "https://api.sevenrooms.com/2_4"

def h(token):
    return {"Authorization": token, "Content-Type": "application/json"}

# Auth
resp = requests.post(f"{API_BASE_URL}/auth", data={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}, timeout=30)
resp.raise_for_status()
token = resp.json().get("data", {}).get("token") or resp.json().get("token")
print("Authenticated OK\n")

# Venues
resp = requests.get(f"{API_BASE_URL}/venues", headers=h(token), timeout=30)
venues = resp.json().get("data", {}).get("results", [])
venue = venues[0]
vid = venue.get("id")
vname = venue.get("name", vid)
print(f"Using venue: {vname}\n")

# Get a reservation to extract a client_id
from_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
to_date = datetime.now().strftime("%Y-%m-%d")
resp = requests.get(f"{API_BASE_URL}/reservations", headers=h(token),
    params={"venue_id": vid, "from_date": from_date, "to_date": to_date, "limit": 5}, timeout=60)
results = resp.json().get("data", {}).get("results", [])
client_id = results[0].get("client_id") if results else None
print(f"Sample client_id from reservation: {client_id}\n")

if client_id:
    # Try 1: GET /clients/{client_id}
    print("--- Try 1: GET /clients/{client_id} ---")
    r = requests.get(f"{API_BASE_URL}/clients/{client_id}", headers=h(token), timeout=30)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json().get("data", r.json())
        print(json.dumps(data, indent=2)[:3000])
    else:
        print(f"  Body: {r.text[:300]}")

    # Try 2: GET /clients?id=...
    print("\n--- Try 2: GET /clients?id=... ---")
    r = requests.get(f"{API_BASE_URL}/clients", headers=h(token),
                     params={"id": client_id}, timeout=30)
    print(f"  Status: {r.status_code}  Body: {r.text[:300]}")

    # Try 3: GET /clients?venue_group_client_id=...
    print("\n--- Try 3: GET /clients?venue_group_client_id=... ---")
    r = requests.get(f"{API_BASE_URL}/clients", headers=h(token),
                     params={"venue_group_client_id": client_id}, timeout=30)
    print(f"  Status: {r.status_code}  Body: {r.text[:300]}")

# Try 4: GET /clients with venue_group_id
venue_group_id = results[0].get("venue_group_id") if results else None
print(f"\n--- Try 4: GET /clients?venue_group_id=... ({venue_group_id}) ---")
r = requests.get(f"{API_BASE_URL}/clients", headers=h(token),
                 params={"venue_group_id": venue_group_id, "limit": 3}, timeout=30)
print(f"  Status: {r.status_code}  Body: {r.text[:500]}")
