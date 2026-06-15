"""
Credential manager.
Priority order:
  1. Streamlit Cloud secrets (st.secrets) — used when deployed on cloud
  2. data/secrets.json — used locally

Never hardcode real credentials in this file.
"""

import json
import os

_SECRETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "secrets.json")

_EMPTY = {
    "screener": {"email": "", "password": ""},
    "kite":     {"api_key": "", "api_secret": "", "user_id": ""},
}


def _load() -> dict:
    # 1. Try Streamlit Cloud secrets (available when deployed on share.streamlit.io)
    try:
        import streamlit as st
        if hasattr(st, "secrets") and ("screener" in st.secrets or "kite" in st.secrets):
            return {
                "screener": {
                    "email":    st.secrets.get("screener", {}).get("email", ""),
                    "password": st.secrets.get("screener", {}).get("password", ""),
                },
                "kite": {
                    "api_key":    st.secrets.get("kite", {}).get("api_key", ""),
                    "api_secret": st.secrets.get("kite", {}).get("api_secret", ""),
                    "user_id":    st.secrets.get("kite", {}).get("user_id", ""),
                },
            }
    except Exception:
        pass

    # 2. Local secrets.json
    if os.path.exists(_SECRETS_PATH):
        try:
            with open(_SECRETS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for section, vals in _EMPTY.items():
                data.setdefault(section, {})
                for k, v in vals.items():
                    data[section].setdefault(k, v)
            return data
        except Exception:
            pass

    return {k: dict(v) for k, v in _EMPTY.items()}


def _save(data: dict):
    os.makedirs(os.path.dirname(_SECRETS_PATH), exist_ok=True)
    with open(_SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


_cfg = _load()

SCREENER_EMAIL    = _cfg["screener"]["email"]
SCREENER_PASSWORD = _cfg["screener"]["password"]

KITE_API_KEY    = _cfg["kite"]["api_key"]
KITE_API_SECRET = _cfg["kite"]["api_secret"]
KITE_USER_ID    = _cfg["kite"]["user_id"]


def get_kite_creds() -> dict:
    return _load()["kite"]


def save_kite_creds(api_key: str, api_secret: str, user_id: str):
    data = _load()
    data["kite"].update({"api_key": api_key, "api_secret": api_secret, "user_id": user_id})
    _save(data)
    global KITE_API_KEY, KITE_API_SECRET, KITE_USER_ID
    KITE_API_KEY    = api_key
    KITE_API_SECRET = api_secret
    KITE_USER_ID    = user_id


def is_kite_configured() -> bool:
    creds = get_kite_creds()
    return bool(creds.get("api_key") and creds.get("api_secret"))


def is_screener_configured() -> bool:
    return bool(SCREENER_EMAIL and SCREENER_PASSWORD)
