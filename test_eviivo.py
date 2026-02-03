"""
Quick test script for eviivo API connection - Discovery mode
"""

import requests
from datetime import date

# QA environment credentials
AUTH_URL = "https://qaext-auth.eviivo.com/api/connect/token"
CLIENT_ID = "d0c7d698-15b3-4b72-8ca9-b3229611ebdc"
CLIENT_SECRET = "T0BHKUEXZ6csLSvtseQP"
PROPERTY_NAME = "specialen1"

def test_connection():
    print("=" * 50)
    print("eviivo API Discovery")
    print("=" * 50)

    # Authenticate
    print("\n1. Authenticating...")
    auth_payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    auth_response = requests.post(
        AUTH_URL,
        data=auth_payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30
    )

    if auth_response.status_code != 200:
        print(f"Auth failed: {auth_response.text}")
        return

    token = auth_response.json().get("access_token")
    print(f"   Got token: {token[:30]}...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Try to find any working base path
    print("\n2. Scanning for valid API paths...")

    base_urls = [
        "https://qaext-io.eviivo.com",
    ]

    paths = [
        "/pms",
        "/api",
        "/v1",
        "/v2",
        "/pms/v1",
        "/pms/v2",
        "/swagger",
        "/swagger/v1/swagger.json",
        "/api/swagger.json",
        "/.well-known/openapi",
        "/openapi.json",
    ]

    for base in base_urls:
        for path in paths:
            url = f"{base}{path}"
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code != 404:
                    print(f"   {url} -> {response.status_code}")
                    if response.status_code == 200:
                        content_type = response.headers.get('content-type', '')
                        if 'json' in content_type:
                            print(f"      JSON: {str(response.json())[:200]}")
                        else:
                            print(f"      Type: {content_type}")
            except Exception as e:
                pass

    # Try property-specific paths with the test property
    print(f"\n3. Testing property '{PROPERTY_NAME}' with common patterns...")

    property_patterns = [
        f"/pms/property/{PROPERTY_NAME}",
        f"/pms/{PROPERTY_NAME}",
        f"/api/property/{PROPERTY_NAME}",
        f"/api/properties/{PROPERTY_NAME}",
        f"/v2/property/{PROPERTY_NAME}",
        f"/property/{PROPERTY_NAME}",
    ]

    for pattern in property_patterns:
        url = f"https://qaext-io.eviivo.com{pattern}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            status = response.status_code
            print(f"   {pattern} -> {status}")
            if status not in [404, 401]:
                print(f"      Response: {response.text[:200]}")
        except Exception as e:
            print(f"   {pattern} -> Error: {e}")

    print("\n" + "=" * 50)
    print("Summary: Authentication works but can't find valid endpoints.")
    print("You may need to check with eviivo for:")
    print("  1. Correct test property short name")
    print("  2. API documentation / Swagger URL")
    print("=" * 50)

if __name__ == "__main__":
    test_connection()
