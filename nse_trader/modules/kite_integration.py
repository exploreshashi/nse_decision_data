"""
Kite Connect Integration (Zerodha)
Provides real-time quotes and reliable historical OHLCV data.

Auth flow for Kite Connect:
  1. User enters API Key + Secret in Settings tab.
  2. Click "Get Login URL" → opens in browser.
  3. Log in on Zerodha → browser redirects to a URL containing ?request_token=xxxxx
  4. Paste that request_token back into Settings.
  5. Click "Generate Session" → access token stored locally.
  6. Token valid until midnight IST; auto-refreshed each morning.

NOTE: API Key + Secret are obtained at developers.kite.trade (separate from trading login).
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.database import log_system_event

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

KITE_BASE       = "https://api.kite.trade"
KITE_LOGIN_BASE = "https://kite.zerodha.com/connect/login"
SESSION_FILE    = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "kite_session.json"
)


# ═══════════════════════════════════════════════════════════════════════════════
# Session helpers
# ═══════════════════════════════════════════════════════════════════════════════

def get_login_url(api_key: str) -> str:
    """Return the Zerodha OAuth URL the user must visit in their browser."""
    return f"{KITE_LOGIN_BASE}?api_key={api_key}&v=3"


def generate_session(api_key: str, api_secret: str, request_token: str) -> dict:
    """
    Exchange a request_token for an access_token.
    Returns the full session dict (access_token, user_id, etc.)
    or raises on failure.
    """
    if not HAS_REQUESTS:
        raise RuntimeError("requests library not installed")

    # Checksum = SHA-256(api_key + request_token + api_secret)
    checksum = hashlib.sha256(
        f"{api_key}{request_token}{api_secret}".encode()
    ).hexdigest()

    resp = requests.post(
        f"{KITE_BASE}/session/token",
        data={
            "api_key":       api_key,
            "request_token": request_token,
            "checksum":      checksum,
        },
        headers={"X-Kite-Version": "3"},
        timeout=15,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Session generation failed ({resp.status_code}): {resp.text[:300]}"
        )

    data = resp.json().get("data", {})
    # Persist
    _save_session(api_key, data)
    log_system_event("kite", "INFO",
                     f"Session generated for {data.get('user_id', '?')}")
    return data


def _save_session(api_key: str, session_data: dict):
    payload = {
        "api_key":      api_key,
        "access_token": session_data.get("access_token", ""),
        "user_id":      session_data.get("user_id", ""),
        "date":         date.today().isoformat(),
    }
    # Save to file (local) — may not persist on cloud, but try anyway
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception:
        pass
    # Also save to Streamlit session_state (survives cloud restarts within session)
    try:
        import streamlit as st
        st.session_state["_kite_session"] = payload
    except Exception:
        pass


def load_session() -> dict | None:
    """
    Load today's saved session.
    Checks st.session_state first (survives cloud container restarts within
    same browser session), then falls back to the local file.
    Returns None if missing or expired.
    """
    today = date.today().isoformat()

    # Cloud-friendly: check Streamlit session state first
    try:
        import streamlit as st
        ss = getattr(st, "session_state", {})
        kite_ss = ss.get("_kite_session")
        if kite_ss and kite_ss.get("date") == today and kite_ss.get("access_token"):
            return kite_ss
    except Exception:
        pass

    # Local file fallback
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, encoding="utf-8") as f:
            s = json.load(f)
        if s.get("date") != today:
            return None
        if not s.get("access_token"):
            return None
        # Mirror to session_state for cloud resilience
        try:
            import streamlit as st
            st.session_state["_kite_session"] = s
        except Exception:
            pass
        return s
    except Exception:
        return None


def is_session_valid() -> bool:
    return load_session() is not None


def _auth_headers(api_key: str, access_token: str) -> dict:
    return {
        "Authorization": f"token {api_key}:{access_token}",
        "X-Kite-Version": "3",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Market data
# ═══════════════════════════════════════════════════════════════════════════════

def get_quotes(symbols: list) -> dict:
    """
    Fetch real-time quotes for a list of NSE symbols.
    symbols: plain symbol strings like ["RELIANCE", "TCS"]
    Returns dict: {symbol: {last_price, change_pct, volume, ohlc, ...}}
    """
    session = load_session()
    if not session or not HAS_REQUESTS:
        return {}

    api_key      = session["api_key"]
    access_token = session["access_token"]

    # Kite format: "NSE:RELIANCE"
    instruments = [f"NSE:{s}" for s in symbols]
    quotes      = {}

    # Kite allows max 500 instruments per call; chunk to be safe
    chunk_size = 200
    for i in range(0, len(instruments), chunk_size):
        chunk = instruments[i: i + chunk_size]
        try:
            resp = requests.get(
                f"{KITE_BASE}/quote",
                params={"i": chunk},
                headers=_auth_headers(api_key, access_token),
                timeout=15,
            )
            if resp.status_code != 200:
                log_system_event("kite", "WARNING",
                                 f"Quote API {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json().get("data", {})
            for instrument, q in data.items():
                sym = instrument.replace("NSE:", "")
                ohlc = q.get("ohlc", {})
                quotes[sym] = {
                    "last_price":  q.get("last_price"),
                    "change":      q.get("change"),
                    "change_pct":  q.get("net_change"),
                    "volume":      q.get("volume"),
                    "buy_qty":     q.get("buy_quantity"),
                    "sell_qty":    q.get("sell_quantity"),
                    "open":        ohlc.get("open"),
                    "high":        ohlc.get("high"),
                    "low":         ohlc.get("low"),
                    "close":       ohlc.get("close"),   # prev close
                    "52w_high":    q.get("upper_circuit_limit"),
                    "52w_low":     q.get("lower_circuit_limit"),
                    "timestamp":   q.get("timestamp"),
                }

        except Exception as e:
            log_system_event("kite", "WARNING", f"Quote fetch error: {e}")

        time.sleep(0.2)   # Kite rate limit: 3 req/sec

    return quotes


def get_historical(symbol: str, from_date: str, to_date: str,
                   interval: str = "day") -> list:
    """
    Fetch OHLCV history via Kite.
    Requires instrument_token — we look it up from the instruments dump.
    interval: "minute", "5minute", "15minute", "60minute", "day"
    Returns list of {"date", "open", "high", "low", "close", "volume"}.
    """
    session = load_session()
    if not session or not HAS_REQUESTS:
        return []

    api_key      = session["api_key"]
    access_token = session["access_token"]
    token        = _get_instrument_token(symbol, api_key, access_token)

    if not token:
        return []

    try:
        resp = requests.get(
            f"{KITE_BASE}/instruments/historical/{token}/{interval}",
            params={"from": from_date, "to": to_date, "continuous": 0, "oi": 0},
            headers=_auth_headers(api_key, access_token),
            timeout=20,
        )
        if resp.status_code != 200:
            return []

        candles = resp.json().get("data", {}).get("candles", [])
        return [
            {
                "date":   c[0][:10],
                "open":   c[1], "high": c[2],
                "low":    c[3], "close": c[4],
                "volume": c[5],
            }
            for c in candles
        ]

    except Exception as e:
        log_system_event("kite", "WARNING", f"Historical fetch {symbol}: {e}")
        return []


# ── Instrument token cache ────────────────────────────────────────────────────

_INSTRUMENTS_CACHE: dict = {}
_INSTRUMENTS_DATE: str   = ""

def _get_instrument_token(symbol: str, api_key: str, access_token: str) -> int | None:
    global _INSTRUMENTS_CACHE, _INSTRUMENTS_DATE

    today = date.today().isoformat()
    if _INSTRUMENTS_DATE != today or not _INSTRUMENTS_CACHE:
        try:
            resp = requests.get(
                f"{KITE_BASE}/instruments/NSE",
                headers=_auth_headers(api_key, access_token),
                timeout=20,
            )
            if resp.status_code == 200:
                for line in resp.text.splitlines()[1:]:   # skip header
                    parts = line.split(",")
                    if len(parts) >= 9:
                        _INSTRUMENTS_CACHE[parts[2].strip()] = int(parts[0].strip())
                _INSTRUMENTS_DATE = today
        except Exception as e:
            log_system_event("kite", "WARNING", f"Instruments fetch: {e}")

    return _INSTRUMENTS_CACHE.get(symbol)


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience
# ═══════════════════════════════════════════════════════════════════════════════

def get_nifty_live() -> dict | None:
    """Return live Nifty 50 quote."""
    session = load_session()
    if not session or not HAS_REQUESTS:
        return None
    api_key      = session["api_key"]
    access_token = session["access_token"]
    try:
        resp = requests.get(
            f"{KITE_BASE}/quote",
            params={"i": ["NSE:NIFTY 50"]},
            headers=_auth_headers(api_key, access_token),
            timeout=10,
        )
        data = resp.json().get("data", {})
        q = data.get("NSE:NIFTY 50", {})
        if q:
            return {
                "last_price": q.get("last_price"),
                "change_pct": q.get("net_change"),
                "ohlc":       q.get("ohlc", {}),
            }
    except Exception:
        pass
    return None


def kite_status() -> dict:
    """Return a status dict for the UI."""
    from credentials import get_kite_creds
    creds = get_kite_creds()
    has_keys    = bool(creds.get("api_key") and creds.get("api_secret"))
    has_session = is_session_valid()
    session     = load_session() if has_session else {}
    return {
        "configured":    has_keys,
        "session_valid": has_session,
        "user_id":       session.get("user_id") or creds.get("user_id", "—"),
        "api_key":       creds.get("api_key", ""),
        "api_secret":    creds.get("api_secret", ""),
        "client_id":     creds.get("user_id", ""),   # credential-level client ID
    }
