import streamlit as st


def _secret(key: str, section: str = None) -> str:
    try:
        return st.secrets[section][key] if section else st.secrets[key]
    except Exception:
        return ""


CLIENT_ID     = _secret("sevenrooms_client_id")
CLIENT_SECRET = _secret("sevenrooms_client_secret")
API_BASE_URL  = "https://api.sevenrooms.com/2_4"

EVIIVO_CLIENT_ID     = _secret("client_id", "eviivo")
EVIIVO_CLIENT_SECRET = _secret("client_secret", "eviivo")
EVIIVO_AUTH_URL      = "https://auth.eviivo.com/api/connect/token"
EVIIVO_API_URL       = "https://io.eviivo.com/pms/v2"
