"""
Diagnostic Script — Run this if START.bat fails.
It checks every dependency and module one by one and tells you exactly what's wrong.

Usage: python diagnose.py
"""

import sys
import os

print("=" * 60)
print("  NSE Trading System — Diagnostic Check")
print("=" * 60)
print()

# Change to script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")
print(f"Working directory: {os.getcwd()}")
print(f"Python version:    {sys.version}")
print(f"Python path:       {sys.executable}")
print()

errors = []
warnings = []

# ── Check 1: Python version ──────────────────────────────────────────────
print("[1/10] Python version...", end=" ")
v = sys.version_info
if v.major >= 3 and v.minor >= 9:
    print(f"OK ({v.major}.{v.minor}.{v.micro})")
else:
    msg = f"FAIL — Need Python 3.9+, you have {v.major}.{v.minor}"
    print(msg)
    errors.append(msg)

# ── Check 2: Core packages ───────────────────────────────────────────────
packages = {
    'streamlit': 'streamlit',
    'yfinance': 'yfinance',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'feedparser': 'feedparser',
    'requests': 'requests',
    'bs4': 'beautifulsoup4',
    'plotly': 'plotly',
}

print("[2/10] Package imports:")
for import_name, pip_name in packages.items():
    try:
        mod = __import__(import_name)
        ver = getattr(mod, '__version__', '?')
        print(f"       {import_name}: OK (v{ver})")
    except ImportError:
        msg = f"{import_name} NOT INSTALLED — run: pip install {pip_name}"
        print(f"       {import_name}: MISSING")
        errors.append(msg)

# ── Check 3: Project files ───────────────────────────────────────────────
print("[3/10] Project files...", end=" ")
required_files = [
    'config.py', 'app.py',
    'modules/__init__.py', 'modules/database.py',
    'modules/data_fetcher.py', 'modules/technical_engine.py',
    'modules/news_engine.py', 'modules/fundamental_filter.py',
    'modules/market_context.py', 'modules/risk_manager.py',
    'modules/recommendation_engine.py',
]
missing = [f for f in required_files if not os.path.exists(f)]
if missing:
    msg = f"Missing files: {', '.join(missing)}"
    print(f"FAIL — {msg}")
    errors.append(msg)
else:
    print(f"OK (all {len(required_files)} files present)")

# ── Check 4: Config import ───────────────────────────────────────────────
print("[4/10] Config module...", end=" ")
try:
    from config import TOTAL_CAPITAL, STOCK_UNIVERSE, DB_PATH, DATA_DIR
    print(f"OK (capital={TOTAL_CAPITAL}, {len(STOCK_UNIVERSE)} stocks)")
except Exception as e:
    msg = f"Config import failed: {e}"
    print(f"FAIL — {msg}")
    errors.append(msg)

# ── Check 5: Database module ─────────────────────────────────────────────
print("[5/10] Database module...", end=" ")
try:
    from modules.database import init_database, get_connection
    init_database()
    conn = get_connection()
    conn.execute("SELECT 1")
    conn.close()
    print(f"OK (DB at {DB_PATH})")
except Exception as e:
    msg = f"Database failed: {e}"
    print(f"FAIL — {msg}")
    errors.append(msg)

# ── Check 6: Data directory writable ─────────────────────────────────────
print("[6/10] Data directory...", end=" ")
try:
    os.makedirs("data", exist_ok=True)
    test_file = os.path.join("data", "_test_write.tmp")
    with open(test_file, "w") as f:
        f.write("test")
    os.remove(test_file)
    print(f"OK (writable: {os.path.abspath('data')})")
except Exception as e:
    msg = f"Cannot write to data directory: {e}"
    print(f"FAIL — {msg}")
    errors.append(msg)

# ── Check 7: Technical engine ────────────────────────────────────────────
print("[7/10] Technical engine...", end=" ")
try:
    from modules.technical_engine import compute_ema, compute_rsi, score_technical
    import pandas as pd
    import numpy as np
    test_prices = pd.Series(np.random.randn(100).cumsum() + 500)
    ema = compute_ema(test_prices, 20)
    print("OK")
except Exception as e:
    msg = f"Technical engine failed: {e}"
    print(f"FAIL — {msg}")
    errors.append(msg)

# ── Check 8: Fundamental filter ──────────────────────────────────────────
print("[8/10] Fundamental filter...", end=" ")
try:
    from modules.fundamental_filter import score_fundamental, store_fundamentals
    store_fundamentals()
    r = score_fundamental('RELIANCE')
    print(f"OK (RELIANCE score={r['score']})")
except Exception as e:
    msg = f"Fundamental filter failed: {e}"
    print(f"FAIL — {msg}")
    errors.append(msg)

# ── Check 9: News engine ─────────────────────────────────────────────────
print("[9/10] News engine...", end=" ")
try:
    from modules.news_engine import score_headline
    r = score_headline("Company reports strong profit growth")
    print(f"OK (sentiment={r['sentiment']})")
except Exception as e:
    msg = f"News engine failed: {e}"
    print(f"FAIL — {msg}")
    errors.append(msg)

# ── Check 10: Streamlit runnable ─────────────────────────────────────────
print("[10/10] Streamlit launch check...", end=" ")
try:
    import streamlit
    print(f"OK (v{streamlit.__version__})")
except ImportError:
    msg = "Streamlit not installed — run: pip install streamlit"
    print(f"FAIL — {msg}")
    errors.append(msg)

# ── Summary ──────────────────────────────────────────────────────────────
print()
print("=" * 60)
if errors:
    print(f"  RESULT: {len(errors)} ERROR(S) FOUND")
    print("=" * 60)
    print()
    print("Fix these issues:")
    for i, err in enumerate(errors, 1):
        print(f"  {i}. {err}")
    print()
    print("After fixing, run this script again to verify.")
else:
    print("  RESULT: ALL CHECKS PASSED ✅")
    print("=" * 60)
    print()
    print("Everything looks good! Run START.bat to launch the dashboard.")
    print("Or run: streamlit run app.py")

print()
input("Press Enter to exit...")
