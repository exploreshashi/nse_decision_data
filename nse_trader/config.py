"""
NSE Short-Term Positional Trading Decision Support System
Configuration and Constants
"""

import os
from datetime import time

# ─── PATHS ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "trading_system.db")
FNO_CACHE_PATH = os.path.join(DATA_DIR, "fno_universe.json")

# Official NSE F&O lot-size file — lists every F&O underlying and its lot size.
# When reachable (local network) we use it as the live source of truth for the
# F&O universe; on cloud (NSE is geo-blocked) we fall back to STOCK_UNIVERSE.
FNO_LOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"

# ─── CAPITAL & RISK RULES ────────────────────────────────────────────────────
TOTAL_CAPITAL = 600000          # ₹6,00,000
RESERVE_CAPITAL = 100000        # ₹1,00,000 additional buffer (not used in sizing)
MAX_CAPITAL_PER_TRADE = 0.33    # 33% of total capital
MAX_RISK_PER_TRADE = 0.02       # 2% of total capital = ₹12,000
MAX_DAILY_LOSS = 0.04           # 4% of total capital = ₹24,000
MAX_WEEKLY_LOSS = 0.08          # 8% = ₹48,000
MAX_MONTHLY_DRAWDOWN = 0.20    # 20% = ₹1,20,000 (user requested max)
MAX_OPEN_POSITIONS = 3
MIN_RISK_REWARD_RATIO = 2.0     # Minimum 1:2
CASH_BUFFER_RATIO = 0.17        # Always keep ~17% cash (₹1,00,000)

# ─── BROKERAGE (Zerodha) ─────────────────────────────────────────────────────
BROKERAGE_PER_ORDER = 20        # ₹20 flat per executed order
STT_RATE = 0.001                # 0.1% on sell side (delivery)
EXCHANGE_TXN_RATE = 0.0000345   # NSE transaction charges
GST_RATE = 0.18                 # 18% on brokerage + transaction charges
SEBI_CHARGES = 0.000001         # ₹10 per crore
STAMP_DUTY_BUY = 0.00015       # 0.015% on buy side

# ─── FUTURES SPECIFIC ────────────────────────────────────────────────────────
FUTURES_BROKERAGE = 20          # ₹20 flat
FUTURES_STT_SELL = 0.000125     # 0.0125% on sell side
FUTURES_LOT_SIZES = {}          # Will be populated from NSE data

# ─── STOCK UNIVERSE FILTERS ──────────────────────────────────────────────────
MIN_AVG_TURNOVER_CR = 10        # Minimum ₹10 crore daily turnover
MIN_MARKET_CAP_CR = 5000        # Minimum ₹5,000 crore market cap
MIN_PRICE = 50                  # Avoid penny stocks
MAX_PRICE = 50000               # Practical upper limit

# ─── SIGNAL WEIGHTS ──────────────────────────────────────────────────────────
WEIGHT_NEWS = 0.30
WEIGHT_TECHNICAL = 0.35
WEIGHT_FUNDAMENTAL = 0.15
WEIGHT_MARKET = 0.20
MIN_COMPOSITE_SCORE = 65        # Minimum score to recommend

# ─── TECHNICAL PARAMETERS ────────────────────────────────────────────────────
EMA_SHORT = 20
EMA_LONG = 50
RSI_PERIOD = 14
RSI_OVERSOLD = 40
RSI_OVERBOUGHT = 70
RSI_EXTREME_OB = 80
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.5
VOLUME_SPIKE_THRESHOLD = 1.5    # 1.5x 20-day average
DELIVERY_VOLUME_MIN = 50        # Minimum 50% delivery
BREAKOUT_LOOKBACK = 20          # Days to check for resistance
OVEREXTENDED_THRESHOLD = 0.15   # 15% above 20 EMA = too stretched
REL_STRENGTH_PERIOD = 10        # 10-day relative strength vs Nifty
MOMENTUM_LOOKBACK = 4           # 2-4 day momentum window

# ─── MARKET HEALTH THRESHOLDS ────────────────────────────────────────────────
VIX_HIGH = 22                   # Above this = no trading
VIX_MODERATE = 18               # Above this = caution
FII_SELLING_THRESHOLD = -3000   # ₹-3000 crore for 3 days = bearish
MARKET_MIN_SCORE = 30           # Below this = no trades

# ─── NEWS SCORING ────────────────────────────────────────────────────────────
NEWS_FRESHNESS_DECAY = 0.85     # Score reduces by 15% per day
NEWS_MAX_AGE_DAYS = 5           # Ignore news older than 5 days

# Keyword dictionaries for sentiment scoring
POSITIVE_KEYWORDS = {
    # Earnings & Growth
    'beat': 3, 'beats': 3, 'surpass': 3, 'exceeded': 3, 'record': 3,
    'strong results': 4, 'profit surge': 4, 'revenue growth': 3,
    'profit growth': 3, 'margin expansion': 3, 'revenue jump': 3,
    'pat growth': 3, 'net profit up': 3, 'ebitda growth': 3,
    'sales growth': 3, 'topline growth': 3, 'bottomline growth': 3,
    'outperform': 3, 'upgrade': 4, 'raised target': 4,
    'guidance raised': 4, 'outlook positive': 3,
    # Orders & Business
    'order win': 3, 'order book': 2, 'new order': 3, 'bagged order': 3,
    'contract win': 3, 'deal win': 3, 'partnership': 2,
    'expansion': 2, 'capex': 2, 'capacity addition': 2,
    'product launch': 2, 'new product': 2, 'foray': 2,
    # Corporate Actions
    'dividend': 2, 'buyback': 3, 'bonus': 2, 'stock split': 2,
    'debt reduction': 3, 'debt free': 4, 'rating upgrade': 3,
    'promoter buying': 4, 'promoter increase': 3,
    'fii increase': 3, 'dii increase': 2,
    # Regulatory
    'approval': 3, 'clearance': 2, 'license': 2, 'patent': 3,
    'regulatory nod': 3,
    # M&A
    'acquisition': 2, 'merger': 2, 'takeover': 2, 'stake hike': 3,
    # Sector
    'sector rally': 2, 'bull run': 2, 'breakout': 3, 'all-time high': 3,
    '52-week high': 3, 'multi-year high': 3,
}

NEGATIVE_KEYWORDS = {
    # Earnings & Performance
    'miss': -3, 'missed': -3, 'disappointing': -3, 'weak results': -4,
    'profit decline': -3, 'revenue decline': -3, 'margin contraction': -3,
    'loss widens': -4, 'net loss': -3, 'revenue fall': -3,
    'sales decline': -3, 'degrowth': -3, 'slowdown': -2,
    'underperform': -3, 'downgrade': -4, 'target cut': -4,
    'guidance lowered': -4, 'outlook negative': -3, 'outlook cautious': -2,
    # Corporate Issues
    'fraud': -5, 'scam': -5, 'default': -5, 'npa': -3,
    'sebi action': -4, 'sebi investigation': -4, 'penalty': -3,
    'ban': -4, 'suspension': -4, 'delisting': -5,
    'promoter selling': -4, 'promoter pledge': -3, 'pledge increase': -3,
    'fii selling': -2, 'stake sale': -2,
    # Debt & Risk
    'debt concern': -3, 'high debt': -3, 'credit downgrade': -4,
    'cash crunch': -4, 'liquidity concern': -3,
    # Regulatory
    'regulatory risk': -3, 'policy change': -2, 'tax raid': -4,
    'ed raid': -4, 'cbi probe': -4, 'income tax': -3,
    # Market
    'crash': -4, 'selloff': -3, 'correction': -2, 'bear': -2,
    '52-week low': -3, 'circuit limit': -3, 'lower circuit': -4,
}

# ─── FUNDAMENTAL THRESHOLDS ──────────────────────────────────────────────────
MIN_ROE = 12
MAX_DEBT_EQUITY = 1.0
HARD_MAX_DEBT_EQUITY = 3.0      # Disqualifier
MIN_PROMOTER_HOLDING = 40
MAX_PROMOTER_PLEDGE = 10
HARD_MAX_PROMOTER_PLEDGE = 50   # Disqualifier
MIN_INSTITUTIONAL_HOLDING = 25  # FII + DII
MIN_REVENUE_GROWTH = 10         # YoY %
MIN_PROFIT_GROWTH = 15          # YoY %

# ─── HOLDING PERIOD ──────────────────────────────────────────────────────────
MAX_HOLDING_DAYS = 4            # Time-based exit
DEFAULT_HOLDING_DAYS = "2-3"

# ─── SCHEDULE ─────────────────────────────────────────────────────────────────
REPORT_TIME = time(8, 30)       # 8:30 AM IST
DATA_FETCH_TIME = time(6, 30)   # 6:30 AM IST
MARKET_OPEN = time(9, 15)       # 9:15 AM IST
MARKET_CLOSE = time(15, 30)     # 3:30 PM IST

# ─── DISPLAY ─────────────────────────────────────────────────────────────────
MAX_RECOMMENDATIONS = 3
MAX_REJECTED_DISPLAY = 5

# ─── NSE F&O UNIVERSE (static fallback) ──────────────────────────────────────
# This is the static fallback universe of liquid NSE stocks, built to mirror the
# NSE Futures & Options underlying list (~190 names). The LIVE F&O list is fetched
# at runtime from FNO_LOTS_URL (see modules/data_fetcher.get_fno_universe); this
# static list is used when NSE is unreachable (e.g. on Streamlit Cloud, where NSE
# geo-blocks datacenter IPs). Sync periodically with the NSE F&O securities list.
STOCK_UNIVERSE = [
    # ── Index heavyweights / Nifty 50 (all in F&O) ──
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "HCLTECH", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TATAMOTORS", "NTPC", "TITAN", "BAJFINANCE",
    "ULTRACEMCO", "WIPRO", "ONGC", "NESTLEIND", "JSWSTEEL",
    "POWERGRID", "M&M", "TATASTEEL", "ADANIENT", "ADANIPORTS",
    "COALINDIA", "BAJAJFINSV", "TECHM", "HDFCLIFE", "INDUSINDBK",
    "GRASIM", "DRREDDY", "CIPLA", "BRITANNIA", "APOLLOHOSP",
    "EICHERMOT", "SBILIFE", "BPCL", "TATACONSUM", "HEROMOTOCO",
    "HINDALCO", "BAJAJ-AUTO", "SHRIRAMFIN", "LTIM", "JIOFIN",
    "TRENT", "BEL",
    # ── Banks / Financials in F&O ──
    "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "AUBANK",
    "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "RBLBANK", "CUB",
    "YESBANK", "INDIANB", "BANKINDIA",
    "CHOLAFIN", "MUTHOOTFIN", "MANAPPURAM", "LICHSGFIN", "PFC",
    "RECLTD", "IRFC", "SBICARD", "ABCAPITAL", "CANFINHOME",
    "BAJAJHFL", "PEL", "POONAWALLA", "M&MFIN", "IEX",
    "MFSL", "ICICIGI", "ICICIPRULI", "HDFCAMC", "LICI",
    "BSE", "MCX", "CDSL", "ANGELONE", "POLICYBZR", "PAYTM",
    # ── IT ──
    "PERSISTENT", "COFORGE", "MPHASIS", "LTTS", "TATAELXSI",
    "KPITTECH", "TATATECH", "OFSS", "CYIENT",
    # ── Pharma / Healthcare ──
    "MAXHEALTH", "FORTIS", "LALPATHLAB", "AUROPHARMA", "BIOCON",
    "LUPIN", "TORNTPHARM", "ALKEM", "IPCALAB", "LAURUSLABS",
    "ZYDUSLIFE", "GLENMARK", "MANKIND", "SYNGENE", "GRANULES",
    "DIVISLAB",
    # ── Chemicals ──
    "PIIND", "DEEPAKNTR", "SRF", "ATUL", "NAVINFLUOR",
    "TATACHEM", "AARTIIND", "FLUOROCHEM",
    # ── Capital goods / Infra / Defence ──
    "ABB", "SIEMENS", "CUMMINSIND", "HAL", "BHEL",
    "BDL", "MAZDOCK", "CGPOWER", "SUZLON", "POLYCAB",
    "KAYNES", "DIXON", "KEI", "APLAPOLLO", "SUPREMEIND",
    "ASTRAL", "BHARATFORG", "THERMAX", "HONAUT",
    # ── Auto / Ancillary ──
    "TVSMOTOR", "ASHOKLEY", "ESCORTS", "MOTHERSON", "SONACOMS",
    "EXIDEIND", "BOSCHLTD", "MRF", "APOLLOTYRE", "BALKRISIND",
    "TIINDIA", "UNOMINDA",
    # ── Metals / Mining ──
    "VEDL", "JINDALSTEL", "SAIL", "NMDC", "NATIONALUM",
    "HINDCOPPER", "JSWENERGY", "RATNAMANI",
    # ── Energy / Power / Oil & Gas ──
    "TATAPOWER", "ADANIGREEN", "ADANIENSOL", "NHPC", "SJVN",
    "TORNTPOWER", "CESC", "IOC", "HINDPETRO", "GAIL",
    "IGL", "MGL", "PETRONET", "OIL", "GUJGASLTD", "ATGL",
    # ── Cement ──
    "AMBUJACEM", "ACC", "DALBHARAT",
    # ── FMCG / Consumer ──
    "PIDILITIND", "HAVELLS", "VOLTAS", "GODREJCP", "DABUR",
    "COLPAL", "BERGEPAINT", "MARICO", "UNITDSPR", "UBL",
    "VBL", "PGHH", "CROMPTON", "KALYANKJIL",
    # ── Retail / Internet / New-age ──
    "DMART", "NAUKRI", "ZOMATO", "NYKAA", "DELHIVERY",
    "INDHOTEL", "JUBLFOOD", "PAGEIND", "ABFRL", "PHOENIXLTD",
    # ── Real Estate ──
    "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "LODHA",
    # ── Telecom / Media ──
    "IDEA", "INDUSTOWER", "TATACOMM", "SUNTV", "HFCL",
    # ── Transport / Logistics / PSU ──
    "CONCOR", "RVNL", "IRCTC", "GMRAIRPORT",
    # ── Misc large/midcaps in F&O ──
    "INDIGO", "PNBHOUSING", "HUDCO", "SOLARINDS",
]

# ─── NIFTY 50 BENCHMARK ──────────────────────────────────────────────────────
NIFTY_SYMBOL = "^NSEI"
BANKNIFTY_SYMBOL = "^NSEBANK"
INDIA_VIX_SYMBOL = "^INDIAVIX"

# ─── DISCLAIMER ───────────────────────────────────────────────────────────────
DISCLAIMER = """
⚠️ IMPORTANT DISCLAIMER:
This is a DECISION-SUPPORT SYSTEM, not trading advice. It does NOT guarantee 
profits. Markets are inherently unpredictable. Past patterns do not guarantee 
future results. The user assumes full responsibility for all trading decisions.
Always use stop-losses. Never risk money you cannot afford to lose.
"""
