"""
NSE Short-Term Positional Trading Decision Support System
Main Streamlit Dashboard  —  run with: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys, os, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    TOTAL_CAPITAL, DISCLAIMER, MAX_RECOMMENDATIONS,
    MIN_COMPOSITE_SCORE, MIN_RISK_REWARD_RATIO, STOCK_UNIVERSE,
)
from modules.database import init_database, get_connection, log_system_event
from modules.risk_manager import check_portfolio_risk, get_portfolio_stats
from modules.fundamental_filter import store_fundamentals
from credentials import (
    SCREENER_EMAIL, SCREENER_PASSWORD,
    save_kite_creds, is_kite_configured, is_screener_configured,
)

# ─── Cached data fetchers (TTL = 30 min so re-opens don't re-fetch) ───────────
@st.cache_data(ttl=1800, show_spinner=False)
def _cached_stock_prices(symbols_key: str, period: str) -> dict:
    from modules.data_fetcher import fetch_stock_prices
    return fetch_stock_prices(symbols_key.split("|"), period)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_index_data():
    from modules.data_fetcher import fetch_index_data, fetch_global_data
    return fetch_index_data(), fetch_global_data()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_fii_data():
    from modules.data_fetcher import fetch_fii_dii_data
    return fetch_fii_dii_data()


@st.cache_data(ttl=600, show_spinner=False)
def _cached_bulk_deals():
    from modules.data_fetcher import fetch_bulk_block_deals, fetch_corporate_announcements
    return fetch_bulk_block_deals(), fetch_corporate_announcements()


# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NSE Trading System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main .block-container{padding-top:1rem;max-width:1280px}
    .stApp,.main,section[data-testid="stSidebar"]{background-color:#0e1117;color:#e2e8f0}
    h1,h2,h3,h4,h5,h6{color:#f0f4ff!important}
    p,li,span,label,.stMarkdown p,.stMarkdown li{color:#cbd5e0!important}
    .stCaption,small{color:#94a3b8!important}
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown span{color:#e2e8f0!important}
    section[data-testid="stSidebar"] h2{color:#93c5fd!important}

    /* Metric cards */
    div[data-testid="stMetric"]{
        background:linear-gradient(135deg,#1e2433 0%,#1a2035 100%);
        border:1px solid #334155;border-radius:10px;
        padding:12px 16px;box-shadow:0 2px 8px rgba(0,0,0,.4)}
    div[data-testid="stMetric"] label,
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] p{
        color:#94a3b8!important;font-size:.76rem!important;
        text-transform:uppercase;letter-spacing:.04em}
    div[data-testid="stMetric"] [data-testid="stMetricValue"],
    div[data-testid="stMetric"] [data-testid="stMetricValue"] div{
        color:#f1f5f9!important;font-size:1.05rem!important;font-weight:600!important}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"]{gap:5px;background:transparent}
    .stTabs [data-baseweb="tab"]{
        background:#1e2433;border-radius:8px 8px 0 0;
        border:1px solid #334155;border-bottom:none;
        padding:8px 16px;color:#94a3b8!important;font-weight:500}
    .stTabs [aria-selected="true"]{
        background:#253352!important;color:#93c5fd!important;
        border-color:#3b82f6!important}
    .stTabs [data-baseweb="tab-panel"]{
        background:#131722;border:1px solid #334155;
        border-top:none;border-radius:0 8px 8px 8px;padding:18px}

    /* Recommendation cards */
    .rec-card{
        background:linear-gradient(135deg,#131d2e,#1a2540);
        border:1px solid #2563eb;border-radius:12px;
        padding:20px;margin:10px 0}
    .rec-card-short{
        background:linear-gradient(135deg,#1f0d0d,#2a1010);
        border:1px solid #dc2626;border-radius:12px;
        padding:20px;margin:10px 0}
    .rec-header{font-size:1.25rem;font-weight:700;
        color:#93c5fd!important;margin-bottom:10px;line-height:1.4}
    .rec-header-short{font-size:1.25rem;font-weight:700;
        color:#fca5a5!important;margin-bottom:10px;line-height:1.4}
    .score-badge{display:inline-block;padding:3px 10px;
        border-radius:20px;font-weight:600;font-size:.78rem;
        vertical-align:middle;margin-left:8px}
    .score-high{background:#14532d;color:#86efac;border:1px solid #22c55e}
    .score-med {background:#431407;color:#fed7aa;border:1px solid #f97316}
    .score-low {background:#450a0a;color:#fca5a5;border:1px solid #ef4444}

    /* Market health banner */
    .market-banner{border-radius:10px;padding:14px 22px;margin-bottom:14px;
        font-size:1.1rem;font-weight:700;color:#fff!important}
    .market-green {background:linear-gradient(90deg,#14532d,#166534)}
    .market-yellow{background:linear-gradient(90deg,#78350f,#92400e)}
    .market-red   {background:linear-gradient(90deg,#450a0a,#7f1d1d)}

    /* Market health grid */
    .mh-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
    .mh-cell{background:#1e2433;border:1px solid #334155;border-radius:8px;
        padding:10px 14px;min-width:0}
    .mh-label{font-size:.7rem;color:#94a3b8;text-transform:uppercase;
        letter-spacing:.05em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .mh-value{font-size:.92rem;font-weight:600;color:#f1f5f9;
        overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

    /* FII/DII panel */
    .fii-panel{background:#12203a;border:1px solid #1e4080;border-radius:10px;padding:14px 18px;margin:10px 0}
    .fii-buy  {color:#4ade80!important;font-weight:600}
    .fii-sell {color:#f87171!important;font-weight:600}
    .fii-net-pos{color:#4ade80!important;font-size:1.1rem;font-weight:700}
    .fii-net-neg{color:#f87171!important;font-size:1.1rem;font-weight:700}

    /* Hidden opportunity */
    .hidden-opp{background:#0f1e10;border:1px solid #22c55e;border-radius:8px;
        padding:10px 14px;margin:6px 0;color:#86efac!important}
    .hidden-opp-warn{background:#1a0f0a;border:1px solid #ef4444;border-radius:8px;
        padding:10px 14px;margin:6px 0;color:#fca5a5!important}
    .bulk-deal{background:#1a1f0e;border-left:3px solid #84cc16;
        padding:8px 12px;margin:4px 0;border-radius:0 6px 6px 0;color:#d9f99d!important}

    /* Rejected row */
    .rejected-row{background:#1a1f2e;border-left:3px solid #ef4444;
        padding:8px 14px;margin:5px 0;border-radius:0 6px 6px 0;
        font-size:.88rem;color:#cbd5e0!important}
    .rejected-row strong{color:#fca5a5!important}

    /* Warning box */
    .warning-box{background:#1c1208;border:1px solid #d97706;border-radius:8px;
        padding:14px 18px;margin:10px 0;color:#fde68a!important;line-height:1.7}

    /* Feedback insight */
    .insight-card{background:#0f1e2a;border:1px solid #0ea5e9;
        border-radius:8px;padding:10px 14px;margin:6px 0;color:#bae6fd!important}

    /* Expander */
    .stExpander{border:1px solid #334155!important;border-radius:8px!important}
    .stExpander summary{color:#93c5fd!important;font-weight:500}

    /* Inputs */
    .stTextInput input,.stNumberInput input,.stTextArea textarea{
        background:#1e2433!important;color:#e2e8f0!important;
        border:1px solid #334155!important}

    #MainMenu,footer,header{visibility:hidden}
</style>
""", unsafe_allow_html=True)


# ─── Initialise ───────────────────────────────────────────────────────────────
def initialize():
    init_database()
    store_fundamentals()
    if 'initialized' not in st.session_state:
        st.session_state.initialized   = True
        st.session_state.last_run      = None
        st.session_state.recommendations = None
        st.session_state.capital       = TOTAL_CAPITAL
        st.session_state.fii_data      = {}
        st.session_state.bulk_deals    = []
        st.session_state.announcements = []
        st.session_state.live_prices   = {}


# ─── Analysis pipeline ────────────────────────────────────────────────────────
def run_analysis():
    from modules.data_fetcher import (
        store_prices, store_macro_data, filter_liquid_stocks,
        store_fii_dii, store_bulk_block_deals,
    )
    from modules.news_engine import process_and_store_news
    from modules.recommendation_engine import generate_recommendations

    prog = st.progress(0, text="Starting analysis…")

    try:
        # Full F&O universe (live from NSE when reachable, else static fallback)
        from modules.data_fetcher import get_fno_universe
        stock_list, _lots = get_fno_universe()
        symbols_key   = "|".join(stock_list)

        # 1. Stock prices — batched fetch, cached 30 min
        prog.progress(5, text=f"📊 Fetching {len(stock_list)} F&O stocks (batched)…")
        price_data = _cached_stock_prices(symbols_key, "6mo")
        if not price_data:
            st.error("❌ Failed to fetch stock data. Check internet connection.")
            prog.empty(); return None
        store_prices(price_data)
        prog.progress(35, text=f"✅ {len(price_data)} stocks fetched (cached 30 min)")

        # 2. Indices — cached 10 min
        prog.progress(38, text="📈 Fetching index data…")
        index_data, global_data = _cached_index_data()
        if index_data:
            try: store_macro_data(index_data, global_data)
            except Exception: pass

        nifty_df     = index_data.get('NIFTY')   if index_data   else None
        banknifty_df = index_data.get('BANKNIFTY') if index_data else None

        # 3. Macro build
        prog.progress(45, text="🌍 Building macro picture…")
        macro = {}
        try:
            if index_data and 'VIX' in index_data and not index_data['VIX'].empty:
                macro['india_vix'] = float(index_data['VIX']['close'].iloc[-1])
            if global_data:
                if 'SP500' in global_data and not global_data['SP500'].empty:
                    sp = global_data['SP500']['close']
                    macro['sp500_close']      = float(sp.iloc[-1])
                    macro['sp500_change_pct'] = float((sp.iloc[-1]/sp.iloc[-2]-1)*100) if len(sp)>=2 else 0
                if 'CRUDE' in global_data and not global_data['CRUDE'].empty:
                    macro['crude_brent'] = float(global_data['CRUDE']['close'].iloc[-1])
                if 'USDINR' in global_data and not global_data['USDINR'].empty:
                    macro['usd_inr'] = float(global_data['USDINR']['close'].iloc[-1])
        except Exception: pass

        # 4. FII/DII — cached 5 min
        prog.progress(50, text="🏦 Fetching FII/DII flows…")
        fii_data = _cached_fii_data()
        if fii_data:
            store_fii_dii(fii_data)
            macro.update(fii_data)
        st.session_state.fii_data = fii_data

        # 5. Bulk/block deals + announcements — cached 10 min
        prog.progress(55, text="🔍 Fetching bulk/block deals & announcements…")
        bulk_deals, announcements = _cached_bulk_deals()
        if bulk_deals:
            store_bulk_block_deals(bulk_deals)
        st.session_state.bulk_deals   = bulk_deals
        st.session_state.announcements = announcements

        # 6. News
        prog.progress(62, text="📰 Collecting news…")
        try: process_and_store_news()
        except Exception as e:
            st.warning(f"⚠️ News issues: {e}")

        # 7. Filter liquid stocks
        prog.progress(70, text="🔍 Filtering liquid stocks…")
        try:
            from modules.data_fetcher import filter_liquid_stocks
            liquid        = filter_liquid_stocks(price_data)
            filtered_data = {s: df for s, df in price_data.items() if s in liquid}
        except Exception:
            filtered_data = {}
        if not filtered_data:
            filtered_data = price_data

        # 8. Generate recommendations (LONG + SHORT)
        prog.progress(78, text="🧠 Generating LONG + SHORT recommendations…")
        results = generate_recommendations(
            price_data       = filtered_data,
            nifty_df         = nifty_df,
            banknifty_df     = banknifty_df,
            macro_data       = macro,
            current_capital  = st.session_state.capital,
            bulk_deals       = bulk_deals,
        )

        # 9. Kite live prices — only for recommended stocks (fast: 5-10 symbols)
        prog.progress(95, text="📡 Fetching live prices via Kite…")
        try:
            from modules.kite_integration import is_session_valid, get_quotes
            if is_session_valid():
                rec_symbols = (
                    [r['symbol'] for r in results.get('recommendations', [])] +
                    [r['symbol'] for r in results.get('short_recommendations', [])]
                )
                if rec_symbols:
                    live_quotes = get_quotes(rec_symbols)
                    if live_quotes:
                        st.session_state.live_prices = live_quotes
                        for rec in results.get('recommendations', []):
                            if rec.get('symbol') in live_quotes:
                                rec['live_price'] = live_quotes[rec['symbol']].get('last_price')
                        for rec in results.get('short_recommendations', []):
                            if rec.get('symbol') in live_quotes:
                                rec['live_price'] = live_quotes[rec['symbol']].get('last_price')
        except Exception:
            pass

        prog.progress(100, text="✅ Analysis complete!")
        time.sleep(0.4); prog.empty()
        return results

    except Exception as e:
        prog.empty()
        st.error(f"❌ Analysis failed: {e}")
        st.exception(e)
        return None


# ─── Render: FII / DII panel ─────────────────────────────────────────────────
def render_fii_panel(fii_data: dict):
    """Prominent FII/DII display with buy/sell breakdown."""
    if not fii_data:
        st.markdown(
            '<div class="fii-panel">🏦 <strong>FII/DII data unavailable</strong> — '
            'NSE API may be slow. Re-run analysis or check later.</div>',
            unsafe_allow_html=True,
        )
        return

    fii_net  = fii_data.get('fii_net_cr', 0)
    dii_net  = fii_data.get('dii_net_cr', 0)
    fii_buy  = fii_data.get('fii_buy_cr', 0)
    fii_sell = fii_data.get('fii_sell_cr', 0)
    dii_buy  = fii_data.get('dii_buy_cr', 0)
    dii_sell = fii_data.get('dii_sell_cr', 0)

    fii_cls  = "fii-net-pos" if fii_net >= 0 else "fii-net-neg"
    dii_cls  = "fii-net-pos" if dii_net >= 0 else "fii-net-neg"
    fii_arrow= "▲" if fii_net >= 0 else "▼"
    dii_arrow= "▲" if dii_net >= 0 else "▼"

    st.markdown(f"""
    <div class="fii-panel">
      <strong>🏦 FII / DII Daily Flows</strong>&nbsp;&nbsp;
      <span style="font-size:.8rem;color:#64748b">{fii_data.get('fii_date','Today')}</span>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:10px">
        <div>
          <div style="color:#93c5fd;font-weight:600;margin-bottom:4px">FII / FPI (Foreign)</div>
          <div class="{fii_cls}" style="font-size:1.3rem">{fii_arrow} ₹{abs(fii_net):,.0f} Cr net</div>
          <div style="margin-top:6px;font-size:.85rem">
            <span class="fii-buy">▲ Buy ₹{fii_buy:,.0f} Cr</span>&nbsp;&nbsp;
            <span class="fii-sell">▼ Sell ₹{fii_sell:,.0f} Cr</span>
          </div>
          <div style="font-size:.78rem;color:#64748b;margin-top:4px">
            {"Net buyers — bullish signal for market" if fii_net >= 0 else "Net sellers — institutional headwind"}
          </div>
        </div>
        <div>
          <div style="color:#93c5fd;font-weight:600;margin-bottom:4px">DII (Domestic)</div>
          <div class="{dii_cls}" style="font-size:1.3rem">{dii_arrow} ₹{abs(dii_net):,.0f} Cr net</div>
          <div style="margin-top:6px;font-size:.85rem">
            <span class="fii-buy">▲ Buy ₹{dii_buy:,.0f} Cr</span>&nbsp;&nbsp;
            <span class="fii-sell">▼ Sell ₹{dii_sell:,.0f} Cr</span>
          </div>
          <div style="font-size:.78rem;color:#64748b;margin-top:4px">
            {"Mutual funds & insurers absorbing FII selling" if dii_net >= 0 and fii_net < 0
             else ("Both buying — strong market conviction" if dii_net >= 0
             else "Both selling — reduce exposure today")}
          </div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ─── Render: Market health ────────────────────────────────────────────────────
def render_market_health(market: dict):
    if not market:
        st.info("Run analysis to see market health"); return

    verdict      = market.get('verdict', 'UNKNOWN')
    verdict_text = market.get('verdict_text', 'Unknown')
    score        = market.get('score', 0)
    emoji        = '🟢' if verdict == 'FAVORABLE' else ('🟡' if verdict == 'CAUTIOUS' else '🔴')
    css          = 'market-green' if verdict == 'FAVORABLE' else ('market-yellow' if verdict == 'CAUTIOUS' else 'market-red')

    st.markdown(
        f'<div class="market-banner {css}">'
        f'{emoji} Market Health: {verdict_text} &nbsp;|&nbsp; Score: {score}/100'
        f'</div>',
        unsafe_allow_html=True,
    )

    details = market.get('details', {})
    if details:
        cells = "".join(
            f'<div class="mh-cell"><span class="mh-label">{k.replace("_"," ").title()}</span>'
            f'<span class="mh-value">{v}</span></div>'
            for k, v in list(details.items())[:12]
        )
        st.markdown(f'<div class="mh-grid">{cells}</div>', unsafe_allow_html=True)
        st.markdown("")

    for w in market.get('warnings', []):
        st.markdown(f'<div class="warning-box">⚠️ {w}</div>', unsafe_allow_html=True)


# ─── Render: LONG recommendation card ────────────────────────────────────────
def render_recommendation(rec: dict, idx: int):
    cs         = rec['composite_score']
    badge_cls  = 'score-high' if cs >= 75 else ('score-med' if cs >= 65 else 'score-low')
    bulk_tag   = " 🔵 BULK BUY" if rec.get('bulk_bonus', 0) > 0 else ""
    feedback_tag = f" | Weights: {'feedback-adjusted' if rec.get('weights', {}).get('adjusted') else 'base'}"

    st.markdown(f"""
    <div class="rec-card">
      <div class="rec-header">
        📌 #{idx+1} — {rec['symbol']} ({rec.get('sector','')})
        <span class="score-badge {badge_cls}">Score: {cs}/100 · {rec['confidence']}</span>
        {bulk_tag}
      </div>
    </div>
    """, unsafe_allow_html=True)

    live_price = rec.get('live_price')
    live_badge = (
        f'<span style="background:#0f5132;color:#6ee7b7;padding:2px 8px;'
        f'border-radius:10px;font-size:.75rem;margin-left:8px">'
        f'📡 Live ₹{live_price:,.2f}</span>'
        if live_price else ''
    )
    if live_badge:
        st.markdown(live_badge, unsafe_allow_html=True)

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Direction", f"🟢 {rec['direction']}")
    c2.metric("Entry Range", f"₹{rec['entry_low']:,.0f} – ₹{rec['entry_high']:,.0f}")
    c3.metric("Target",     f"₹{rec['target_price']:,.0f}")
    c4.metric("Stop Loss",  f"₹{rec['stop_loss']:,.0f}")

    c5,c6,c7,c8 = st.columns(4)
    c5.metric("Qty",            f"{rec['quantity']} shares")
    c6.metric("Position Value", f"₹{rec['position_value']:,.0f}")
    c7.metric("Risk Amount",    f"₹{rec['risk_amount']:,.0f}")
    c8.metric("R : Reward",     f"1 : {rec['risk_reward_ratio']}")

    # Hidden signals (always visible — key differentiator)
    hidden = rec.get('hidden_signals', [])
    if hidden:
        for h in hidden:
            css_cls = "hidden-opp" if "BULK" in h or "📰" in h or "📊" in h else "insight-card"
            st.markdown(f'<div class="{css_cls}">{h}</div>', unsafe_allow_html=True)

    # Detailed analysis expander
    with st.expander(f"📊 Full Analysis — {rec['symbol']}"):
        st.markdown("#### Score Breakdown")
        sc1,sc2,sc3,sc4 = st.columns(4)
        sc1.metric("News",        f"{rec['news_score']}/100")
        sc2.metric("Technical",   f"{rec['technical_score']}/100")
        sc3.metric("Fundamental", f"{rec['fundamental_score']}/100")
        sc4.metric("Market",      f"{rec['market_score']}/100")

        st.markdown("---")
        st.markdown("#### 📰 News Catalyst")
        st.info(rec.get('news_trigger', '—'))

        st.markdown("#### 📈 Technical Setup")
        st.success(rec.get('technical_setup', '—'))

        st.markdown("#### 🏦 Fundamental Quality")
        st.info(rec.get('fundamental_brief', '—'))

        indicators = rec.get('indicators', {})
        if indicators:
            ic = st.columns(5)
            ic[0].write(f"EMA 20: ₹{indicators.get('ema_20',0):,.0f}")
            ic[1].write(f"EMA 50: ₹{indicators.get('ema_50',0):,.0f}")
            ic[2].write(f"RSI: {indicators.get('rsi',0):.0f}")
            ic[3].write(f"Vol Ratio: {indicators.get('volume_ratio',0):.1f}×")
            ic[4].write(f"Rel Str: {indicators.get('relative_strength',0):+.1f}%")

        st.markdown("---")
        st.markdown("#### ⚠️ Key Risks")
        st.warning(rec.get('key_risks', '—'))

        st.markdown("#### 🚪 Exit Rules")
        st.markdown(rec.get('exit_rules', '—'))

        st.caption(f"Composite: {rec['reasoning']}")

    st.markdown("---")


# ─── Render: SHORT recommendation card ───────────────────────────────────────
def render_short_recommendation(rec: dict, idx: int):
    score     = rec['short_score']
    badge_cls = 'score-high' if score >= 75 else ('score-med' if score >= 60 else 'score-low')

    st.markdown(f"""
    <div class="rec-card-short">
      <div class="rec-header-short">
        🔻 SHORT #{idx+1} — {rec['symbol']} ({rec.get('sector','')})
        <span class="score-badge {badge_cls}">Short Score: {score}/100 · {rec['confidence']}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    live_price = rec.get('live_price')
    if live_price:
        st.markdown(
            f'<span style="background:#4c0519;color:#fca5a5;padding:2px 8px;'
            f'border-radius:10px;font-size:.75rem">📡 Live ₹{live_price:,.2f}</span>',
            unsafe_allow_html=True,
        )

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Direction",      "🔴 SHORT (Futures)")
    c2.metric("Entry Range",    f"₹{rec['entry_low']:,.0f} – ₹{rec['entry_high']:,.0f}")
    c3.metric("Target (cover)", f"₹{rec['target_price']:,.0f}")
    c4.metric("Stop Loss",      f"₹{rec['stop_loss']:,.0f}")

    c5,c6,c7,c8 = st.columns(4)
    c5.metric("Lot Size",        f"{rec['lot_size']} shares")
    c6.metric("Margin Required", f"₹{rec['margin_required']:,.0f}")
    c7.metric("Max Risk",        f"₹{rec['risk_amount']:,.0f}")
    c8.metric("R : Reward",      f"1 : {rec['risk_reward_ratio']}")

    with st.expander(f"📊 Short Analysis — {rec['symbol']}"):
        st.markdown("#### 🐻 Why SHORT?")
        st.error(rec.get('technical_weakness', '—'))

        bc = rec.get('bearish_catalyst', '')
        if bc and 'No specific' not in bc:
            st.markdown("#### 📰 Bearish Catalyst")
            st.warning(bc)

        st.markdown("#### ⚠️ Key Risks of Shorting")
        st.info(rec.get('key_risks', '—'))

        st.markdown("#### 🚪 Exit Rules (Futures)")
        st.markdown(rec.get('exit_rules', '—'))

        st.markdown("#### 💡 Full Reasoning")
        st.caption(rec.get('reasoning', '—'))

        st.markdown("---")
        col1, col2 = st.columns(2)
        col1.metric("RSI",     f"{rec.get('rsi', 0):.0f} (overbought >70)")
        col2.metric("EMA Ext.", f"{rec.get('dist_pct', 0):.0f}% above 20 EMA")

    st.markdown("---")


# ─── Render: Hidden Opportunities ────────────────────────────────────────────
def render_hidden_opportunities():
    st.subheader("🔭 Hidden Opportunities")

    # Bulk / block deals
    bulk_deals = getattr(st.session_state, 'bulk_deals', [])
    if bulk_deals:
        st.markdown("##### 🔵 Today's Bulk / Block Deals (Institutional Footprint)")
        for d in bulk_deals[:15]:
            bs_icon = "▲ BUY" if 'BUY' in d.get('buy_sell','') else "▼ SELL"
            color   = "hidden-opp" if 'BUY' in d.get('buy_sell','') else "hidden-opp-warn"
            st.markdown(
                f'<div class="{color}">'
                f'<strong>[{d["type"]}] {d["symbol"]}</strong> — '
                f'{bs_icon} by <em>{d["client"]}</em> | '
                f'Qty: {d["quantity"]:,} @ ₹{d["price"]:,.0f} | '
                f'Value: ₹{d["value_cr"]:.1f} Cr | {d["date"]}'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("Bulk/block deals will appear here after running analysis. "
                "These reveal large institutional transactions not visible in price data.")

    st.markdown("---")

    # Corporate announcements
    announcements = getattr(st.session_state, 'announcements', [])
    if announcements:
        high_impact = [a for a in announcements if a['impact'] == 'HIGH']
        medium      = [a for a in announcements if a['impact'] == 'MEDIUM']

        if high_impact:
            st.markdown("##### 🔴 High-Impact Announcements")
            for a in high_impact[:8]:
                st.markdown(
                    f'<div class="hidden-opp-warn">'
                    f'<strong>{a["title"]}</strong><br>'
                    f'<span style="font-size:.82rem;color:#94a3b8">'
                    f'{a["source"]} | {a["date"]}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        if medium:
            with st.expander(f"📣 {len(medium)} Medium-Impact Announcements"):
                for a in medium[:10]:
                    st.markdown(
                        f'<div class="bulk-deal">'
                        f'<strong>{a["title"]}</strong> — '
                        f'<span style="font-size:.82rem">{a["source"]} | {a["date"]}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
    else:
        st.info("Corporate announcements (board meetings, results, dividends, orders) "
                "will appear here after running analysis.")

    st.markdown("---")

    # Recent historical bulk deals from DB
    try:
        from modules.data_fetcher import get_recent_bulk_deals
        hist_deals = get_recent_bulk_deals(days=5, min_value_cr=10)
        if hist_deals:
            st.markdown("##### 📅 Significant Bulk Deals (Last 5 Days, ≥₹10 Cr)")
            df = pd.DataFrame(hist_deals)[
                ['deal_type','symbol','client_name','buy_sell','quantity','price','value_cr','deal_date']
            ]
            st.dataframe(df, use_container_width=True)
    except Exception:
        pass


# ─── Render: Rejected stocks ─────────────────────────────────────────────────
def _score_bar(label: str, value: float, max_val: float = 100, threshold: float = 60) -> str:
    """Return an HTML mini progress bar for a sub-score."""
    pct   = min(int(value / max_val * 100), 100)
    color = "#22c55e" if value >= threshold else ("#f59e0b" if value >= threshold * 0.65 else "#ef4444")
    return (
        f'<div style="margin:3px 0">'
        f'<span style="font-size:.78rem;color:#94a3b8;width:110px;display:inline-block">{label}</span>'
        f'<span style="display:inline-block;width:{pct}%;max-width:120px;height:8px;'
        f'background:{color};border-radius:4px;vertical-align:middle"></span>'
        f'<span style="font-size:.78rem;color:#cbd5e1;margin-left:6px">{value:.0f}</span>'
        f'</div>'
    )


def render_rejected(rejected: list):
    if not rejected:
        st.info("No stocks were rejected today — all passed or there was no data to score.")
        return

    st.caption(f"{len(rejected)} stocks were scored but didn't meet entry criteria. "
               "Click any stock to see the specific reasons.")

    for rej in rejected:
        symbol    = rej.get('symbol', '?')
        score     = rej.get('score', 0)
        reason    = rej.get('reason', 'Did not meet criteria')
        sub       = rej.get('sub_scores', {})
        why_wait  = rej.get('why_wait', [])

        # One-line header: symbol + score badge + top reason
        badge_color = "#ef4444" if score < 40 else "#f59e0b"
        header_html = (
            f'<span style="font-weight:600;color:#e2e8f0">{symbol}</span>'
            f'&nbsp;&nbsp;<span style="background:{badge_color};color:#fff;'
            f'padding:1px 7px;border-radius:10px;font-size:.75rem">Score {score:.0f}</span>'
            f'&nbsp;&nbsp;<span style="color:#94a3b8;font-size:.82rem">{reason}</span>'
        )
        with st.expander(symbol + f"  ·  Score {score:.0f}  ·  {reason}"):
            if sub:
                st.markdown("**Signal Breakdown:**", unsafe_allow_html=False)
                bars = (
                    _score_bar("📰 News",        sub.get('news', 0),        threshold=60) +
                    _score_bar("📊 Technical",   sub.get('technical', 0),   threshold=60) +
                    _score_bar("🏢 Fundamental", sub.get('fundamental', 0), threshold=50) +
                    _score_bar("🌐 Market",      sub.get('market', 0),      threshold=55)
                )
                st.markdown(f'<div style="margin-bottom:10px">{bars}</div>', unsafe_allow_html=True)

            if why_wait:
                st.markdown("**Why the algorithm says wait:**")
                for i, point in enumerate(why_wait, 1):
                    st.markdown(
                        f'<div style="padding:4px 0;color:#cbd5e1;font-size:.87rem">'
                        f'<span style="color:#f59e0b;font-weight:bold">{i}.</span> {point}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption(reason)


def render_short_rejected(short_rejected: list):
    if not short_rejected:
        st.info("No stocks showed partial short signals today.")
        return

    st.caption(f"{len(short_rejected)} stocks had some bearish signals but not enough to recommend a short. "
               "Expand to see what signals are present and what's missing.")

    for sr in short_rejected:
        symbol = sr.get('symbol', '?')
        score  = sr.get('short_score', 0)
        sigs   = sr.get('signals', [])
        missing = sr.get('missing', [])

        with st.expander(f"{symbol}  ·  Partial short score {score:.0f}/100  ·  Need {55} to qualify"):
            bd = sr.get('breakdown', {})
            if bd:
                bars = (
                    _score_bar("RSI Overbought",   bd.get('rsi', 0),           max_val=30, threshold=18) +
                    _score_bar("EMA Extension",    bd.get('ema_extension', 0), max_val=25, threshold=15) +
                    _score_bar("MACD Bearish",     bd.get('macd', 0),          max_val=20, threshold=12) +
                    _score_bar("Vol on Down Day",  bd.get('vol_spike_down', 0),max_val=15, threshold=10) +
                    _score_bar("Failed Breakout",  bd.get('failed_breakout', 0),max_val=10, threshold=7)
                )
                st.markdown(f'<div style="margin-bottom:10px">{bars}</div>', unsafe_allow_html=True)

            if sigs:
                st.markdown("**Bearish signals already present:**")
                for s in sigs:
                    st.markdown(
                        f'<div style="color:#86efac;font-size:.85rem;padding:2px 0">✓ {s}</div>',
                        unsafe_allow_html=True,
                    )

            if missing:
                st.markdown("**What still needs to happen for a SHORT entry:**")
                for i, m in enumerate(missing, 1):
                    st.markdown(
                        f'<div style="color:#fca5a5;font-size:.85rem;padding:2px 0">'
                        f'<span style="color:#f59e0b">{i}.</span> {m}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )


# ─── Render: Risk summary ─────────────────────────────────────────────────────
def render_risk_summary(risk_check: dict):
    if not risk_check: return
    for name, check in risk_check.get('checks', {}).items():
        icon = "✅" if check['ok'] else "❌"
        st.write(f"{icon} {check['message']}")
    for reason in risk_check.get('blocked_reasons', []):
        st.error(reason)


# ─── Render: Trade journal ────────────────────────────────────────────────────
def render_trade_journal():
    conn = get_connection()

    st.subheader("📂 Open Positions")
    open_trades = pd.read_sql_query(
        "SELECT * FROM trade_journal WHERE status='OPEN' ORDER BY date_entry DESC", conn
    )
    if open_trades.empty:
        st.info("No open positions")
    else:
        st.dataframe(
            open_trades[['trade_id','symbol','direction','entry_price',
                          'quantity','date_entry','risk_amount_planned']],
            use_container_width=True,
        )

    st.markdown("---")
    st.subheader("➕ Log New Trade")
    with st.form("new_trade"):
        t1,t2,t3,t4 = st.columns(4)
        symbol        = t1.text_input("Symbol", placeholder="e.g. RELIANCE")
        direction     = t2.selectbox("Direction", ["LONG","SHORT (Futures)"])
        entry_price   = t3.number_input("Entry Price (₹)", min_value=0.0, step=0.1)
        quantity      = t4.number_input("Quantity", min_value=1, step=1)

        t2a,t2b,t2c = st.columns(3)
        risk_planned    = t2a.number_input("Planned Risk (₹)", min_value=0.0, value=12000.0)
        comp_score      = t2b.number_input("Composite Score", min_value=0.0, max_value=100.0)
        emotional_state = t2c.selectbox("Emotional State",
            ["Calm","Confident","FOMO","Anxious","Revenge","Bored"])

        if st.form_submit_button("Log Trade Entry") and symbol and entry_price > 0:
            trade_id = f"T-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            conn.execute("""
                INSERT INTO trade_journal
                (trade_id,date_entry,symbol,direction,entry_price,quantity,
                 risk_amount_planned,composite_score_at_entry,emotional_state,status)
                VALUES (?,?,?,?,?,?,?,?,?,'OPEN')
            """, (trade_id, datetime.now().strftime('%Y-%m-%d'),
                  symbol.upper(), direction, entry_price, quantity,
                  risk_planned, comp_score, emotional_state))
            conn.commit()
            st.success(f"✅ Trade {trade_id} logged!")
            st.rerun()

    st.markdown("---")
    st.subheader("🔒 Close Trade")
    if not open_trades.empty:
        with st.form("close_trade"):
            trade_to_close = st.selectbox(
                "Select Trade", open_trades['trade_id'].tolist(),
                format_func=lambda x: f"{x} — {open_trades[open_trades['trade_id']==x]['symbol'].values[0]}"
            )
            cl1,cl2,cl3 = st.columns(3)
            exit_price     = cl1.number_input("Exit Price (₹)", min_value=0.0, step=0.1)
            exit_reason    = cl2.selectbox("Exit Reason",
                ["Target Hit","Stop Loss Hit","Time Exit","Trailing SL","Manual Exit","Break Even"])
            exit_emotional = cl3.selectbox("Emotional State at Exit",
                ["Calm","Relieved","Frustrated","Greedy","Fearful","Disciplined"])

            cl2a,cl2b = st.columns(2)
            what_right = cl2a.text_area("What went right?", height=68)
            what_wrong = cl2b.text_area("What went wrong?", height=68)
            lesson = st.text_input("Key lesson")

            if st.form_submit_button("Close Trade") and exit_price > 0:
                row = open_trades[open_trades['trade_id']==trade_to_close].iloc[0]
                ep  = float(row['entry_price']); qty = int(row['quantity'])
                gpl = (exit_price - ep)*qty if row['direction']=='LONG' else (ep - exit_price)*qty
                from modules.risk_manager import calculate_brokerage
                txn    = calculate_brokerage(ep*qty, exit_price*qty)
                net    = gpl - txn
                rp     = float(row['risk_amount_planned']) if row['risk_amount_planned'] else 12000
                r_mult = net / rp if rp > 0 else 0
                hold   = (datetime.now() - datetime.strptime(row['date_entry'],'%Y-%m-%d')).days

                conn.execute("""
                    UPDATE trade_journal SET
                        date_exit=?,exit_price=?,gross_pnl=?,brokerage_taxes=?,
                        net_pnl=?,r_multiple=?,exit_reason=?,holding_days=?,
                        emotional_state=?,what_went_right=?,what_went_wrong=?,
                        lesson=?,status='CLOSED'
                    WHERE trade_id=?
                """, (datetime.now().strftime('%Y-%m-%d'), exit_price, round(gpl,2),
                      txn, round(net,2), round(r_mult,2), exit_reason, hold,
                      exit_emotional, what_right, what_wrong, lesson, trade_to_close))
                conn.commit()
                if net >= 0:
                    st.success(f"✅ Closed! Net P&L: +₹{net:,.0f} ({r_mult:+.1f}R)")
                else:
                    st.error(f"Closed. Net P&L: -₹{abs(net):,.0f} ({r_mult:+.1f}R)")
                st.rerun()

    st.markdown("---")
    st.subheader("📜 Trade History")
    closed = pd.read_sql_query(
        "SELECT * FROM trade_journal WHERE status='CLOSED' ORDER BY date_exit DESC LIMIT 50", conn
    )
    conn.close()
    if closed.empty:
        st.info("No closed trades yet.")
    else:
        cols = ['trade_id','symbol','direction','entry_price','exit_price',
                'quantity','net_pnl','r_multiple','exit_reason','holding_days',
                'emotional_state','date_entry','date_exit']
        st.dataframe(closed[[c for c in cols if c in closed.columns]], use_container_width=True)


# ─── Render: Performance + Feedback loop ─────────────────────────────────────
def render_performance():
    stats = get_portfolio_stats()

    if stats['total_trades'] == 0:
        st.info("📊 No closed trades yet. Close trades to see performance metrics.")
        st.markdown("Start paper-trading to build a track record.")
        return

    st.subheader("📊 Performance Overview")
    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Total Trades",     stats['total_trades'])
    m2.metric("Win Rate",         f"{stats['win_rate']}%",
              delta="Good" if stats['win_rate']>=45 else "Needs work")
    m3.metric("Total P&L",        f"₹{stats['total_pnl']:+,.0f}",
              delta=f"{stats['total_pnl_pct']:+.1f}%")
    m4.metric("Expectancy/Trade", f"₹{stats['expectancy']:+,.0f}")

    m5,m6,m7,m8 = st.columns(4)
    m5.metric("Avg R-Multiple",   f"{stats['avg_r_multiple']:+.2f}R")
    m6.metric("Profit Factor",    f"{stats['profit_factor']:.2f}")
    m7.metric("Max Drawdown",     f"₹{stats['max_drawdown']:,.0f}")
    m8.metric("Avg Holding Days", f"{stats['avg_holding_days']:.1f}")

    # Equity curve
    conn = get_connection()
    trades_df = pd.read_sql_query(
        "SELECT date_exit,net_pnl FROM trade_journal WHERE status='CLOSED' ORDER BY date_exit", conn
    )
    conn.close()
    if not trades_df.empty:
        trades_df['cumulative_pnl'] = trades_df['net_pnl'].cumsum()
        trades_df['date_exit']      = pd.to_datetime(trades_df['date_exit'])
        st.subheader("📈 Equity Curve")
        st.line_chart(trades_df.set_index('date_exit')['cumulative_pnl'], use_container_width=True)

    # ── Feedback loop section ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔄 Feedback Loop — System Learning")
    st.caption(
        "The system compares closed trades with the recommendations that generated them, "
        "identifies which signals predicted winners, and adjusts composite weights accordingly."
    )

    try:
        from modules.feedback_engine import get_signal_accuracy, get_adjusted_weights
        acc     = get_signal_accuracy()
        weights = get_adjusted_weights()

        if acc['total_matched'] == 0:
            st.info(acc['message'])
        else:
            st.success(f"✅ {acc['message']}")

            f1,f2,f3 = st.columns(3)
            f1.metric("Matched Trades",  acc['total_matched'])
            f2.metric("Feedback Win Rate", f"{acc['win_rate']}%")
            f3.metric("Avg R-Multiple",  f"{acc['avg_r_multiple']:+.2f}R")

            # Signal predictive power
            st.markdown("#### Signal Predictive Power")
            sig_data = []
            for sig, v in acc['signal_accuracy'].items():
                sig_data.append({
                    'Signal':           sig.replace('_score','').replace('_',' ').title(),
                    'Avg (Winners)':    v['avg_winner'],
                    'Avg (Losers)':     v['avg_loser'],
                    'Predictive Power': v['predictive_power'],
                })
            st.dataframe(pd.DataFrame(sig_data), use_container_width=True, hide_index=True)

            # Adjusted weights
            st.markdown("#### Current Composite Weights")
            wc1,wc2,wc3,wc4 = st.columns(4)
            wc1.metric("News Weight",        f"{weights.get('news',0)*100:.0f}%",
                       delta="adjusted" if weights.get('adjusted') else "base")
            wc2.metric("Technical Weight",   f"{weights.get('technical',0)*100:.0f}%")
            wc3.metric("Fundamental Weight", f"{weights.get('fundamental',0)*100:.0f}%")
            wc4.metric("Market Weight",      f"{weights.get('market',0)*100:.0f}%")
            if weights.get('adjusted'):
                st.success(f"✅ Weights feedback-adjusted: {weights.get('reason','')}")
            else:
                st.info(f"ℹ️ Using base weights — {weights.get('reason','')}")

            # Score win-rate table
            if acc.get('score_win_rates'):
                st.markdown("#### Win Rate by Composite Score Bucket")
                wr_data = [
                    {'Score Range': k, 'Trades': v['count'], 'Win Rate %': v['win_rate']}
                    for k, v in acc['score_win_rates'].items()
                ]
                st.dataframe(pd.DataFrame(wr_data), use_container_width=True, hide_index=True)

            # Insights
            if acc.get('insights'):
                st.markdown("#### 💡 Pattern Insights")
                for insight in acc['insights']:
                    st.markdown(
                        f'<div class="insight-card">{insight}</div>',
                        unsafe_allow_html=True,
                    )

    except Exception as e:
        st.warning(f"Feedback engine unavailable: {e}")


# ─── Render: Settings ────────────────────────────────────────────────────────
def render_settings():
    st.subheader("⚙️ System Settings")

    # ── Data source status ─────────────────────────────────────────────────
    st.markdown("### 🔌 Data Source Status")
    from modules.kite_integration import kite_status
    kst = kite_status()

    col_s, col_k = st.columns(2)
    with col_s:
        if is_screener_configured():
            st.success(f"✅ Screener.in — {SCREENER_EMAIL}")
        else:
            st.error("❌ Screener.in — not configured")

    with col_k:
        if kst["session_valid"]:
            st.success(f"✅ Kite Connect — logged in as {kst['user_id']}")
        elif kst["configured"]:
            st.warning("🔑 Kite Connect — API keys set, session needed")
        else:
            st.error("❌ Kite Connect — API keys not set")

    st.markdown("---")

    # ── Screener.in: Refresh fundamentals ─────────────────────────────────
    st.markdown("### 📊 Screener.in — Refresh Fundamental Data")
    st.markdown(
        "Pulls live ROE, D/E, promoter holding, revenue/profit growth for all stocks "
        "from your Screener.in premium account. Cached for 7 days."
    )

    scr_col1, scr_col2 = st.columns([2, 1])
    with scr_col1:
        n_stocks = st.slider("Stocks to refresh", 10, len(STOCK_UNIVERSE), 50, 10)
    with scr_col2:
        force_refresh = st.checkbox("Force re-scrape (ignore cache)")

    if st.button("🔄 Refresh Fundamentals from Screener.in", type="primary"):
        from modules.screener_fetcher import refresh_fundamentals
        symbols = STOCK_UNIVERSE[:n_stocks]
        with st.spinner(f"Scraping {n_stocks} stocks from Screener.in… (~{n_stocks*2} sec)"):
            result = refresh_fundamentals(
                symbols, SCREENER_EMAIL, SCREENER_PASSWORD, force=force_refresh
            )
        if result["fetched"] > 0 or result["cached"] > 0:
            st.success(
                f"✅ Screener refresh done: "
                f"{result['fetched']} freshly scraped, "
                f"{result['cached']} already cached"
            )
            if result["failed"]:
                st.warning(f"⚠️ Failed: {', '.join(result['failed'][:10])}")
        else:
            st.error("❌ Screener refresh failed — check credentials or network")

    # Show cache status
    conn = get_connection()
    cached_count = conn.execute(
        "SELECT COUNT(*) FROM fundamentals WHERE roe IS NOT NULL"
    ).fetchone()[0]
    conn.close()
    st.caption(f"Currently {cached_count} stocks have live fundamental data in the database.")

    st.markdown("---")

    # ── Kite Connect setup ─────────────────────────────────────────────────
    st.markdown("### 📡 Kite Connect — Setup")

    if not kst["configured"]:
        st.info("""
        **How to get Kite Connect API credentials:**
        1. Go to [developers.kite.trade](https://developers.kite.trade) and log in with your Zerodha account
        2. Click **Create new app**
        3. App type: **Connect** | Redirect URL: `http://127.0.0.1`
        4. Copy the **API Key** and **API Secret**
        5. Enter them below
        """)

    with st.form("kite_creds_form"):
        k1, k2, k3 = st.columns(3)
        api_key    = k1.text_input("API Key",    value=kst.get("api_key",""),    type="password")
        api_secret = k2.text_input("API Secret", value=kst.get("api_secret",""), type="password")
        user_id    = k3.text_input("Client ID",  value=kst.get("client_id",""),  placeholder="e.g. YS5607")
        if st.form_submit_button("💾 Save Kite Credentials"):
            if api_key and api_secret:
                save_kite_creds(api_key, api_secret, user_id)
                st.success("✅ Kite credentials saved!")
                st.rerun()
            else:
                st.error("API Key and Secret are required")

    if kst["configured"]:
        st.markdown("#### Generate Daily Session Token")
        st.markdown(
            "Kite access tokens expire at **midnight IST**. "
            "You need to re-authenticate each morning."
        )

        from modules.kite_integration import get_login_url
        login_url = get_login_url(kst["api_key"])
        st.markdown(
            f"**Step 1:** [Click here to log in to Zerodha]({login_url})  \n"
            "After logging in, your browser will redirect to a URL like:  \n"
            "`http://127.0.0.1/?request_token=XXXXX&action=login&status=success`  \n"
            "**Copy the `request_token` value from that URL.**"
        )

        with st.form("kite_session_form"):
            req_token = st.text_input("Paste Request Token here")
            if st.form_submit_button("🔑 Generate Session"):
                if req_token.strip():
                    try:
                        from modules.kite_integration import generate_session
                        session = generate_session(
                            kst["api_key"], kst["api_secret"], req_token.strip()
                        )
                        st.success(
                            f"✅ Kite session active for {session.get('user_name','?')} "
                            f"({session.get('user_id','?')}). Valid until midnight IST."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Session error: {e}")
                else:
                    st.warning("Paste the request_token first")

        if kst["session_valid"]:
            st.success(f"✅ Active session — user {kst['user_id']}. Kite live data is enabled.")
            if st.button("🔍 Test Kite — Fetch Nifty Quote"):
                from modules.kite_integration import get_nifty_live
                q = get_nifty_live()
                if q:
                    st.metric("Nifty 50",
                              f"₹{q['last_price']:,.2f}",
                              delta=f"{q['change_pct']:+.2f}%")
                else:
                    st.error("Could not fetch Nifty quote — check session")

    st.markdown("---")

    # ── Capital settings ───────────────────────────────────────────────────
    st.markdown("### Capital Settings")
    new_capital = st.number_input(
        "Trading Capital (₹)", min_value=100000, max_value=10000000,
        value=int(st.session_state.capital), step=50000,
    )
    if new_capital != st.session_state.capital:
        st.session_state.capital = new_capital
        st.success(f"Capital updated to ₹{new_capital:,.0f}")

    st.info(f"""
    Max risk per trade: 2%  (₹{new_capital*0.02:,.0f})   |   Max capital per trade: 33%  (₹{new_capital*0.33:,.0f})
    Max daily loss: 4%  (₹{new_capital*0.04:,.0f})       |   Max weekly loss: 8%  (₹{new_capital*0.08:,.0f})
    Max monthly drawdown: 20%  (₹{new_capital*0.20:,.0f}) |   Cash buffer: ₹{new_capital*0.17:,.0f}
    """)

    st.markdown("### Data Management")
    c1, c2, c3 = st.columns(3)
    if c1.button("🗑️ Clear News"):
        c = get_connection(); c.execute("DELETE FROM news"); c.commit(); c.close()
        st.success("News cleared")
    if c2.button("🗑️ Clear Recs"):
        c = get_connection()
        for t in ("recommendations","rejected_stocks","short_recommendations"):
            c.execute(f"DELETE FROM {t}")
        c.commit(); c.close()
        st.success("Recommendations cleared")
    if c3.button("🗑️ Clear Deals"):
        c = get_connection(); c.execute("DELETE FROM bulk_deals"); c.commit(); c.close()
        st.success("Bulk deals cleared")

    st.markdown("---")
    st.markdown(DISCLAIMER)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    initialize()

    # Initialise session state for new data
    if 'fii_data'      not in st.session_state: st.session_state.fii_data      = {}
    if 'bulk_deals'    not in st.session_state: st.session_state.bulk_deals    = []
    if 'announcements' not in st.session_state: st.session_state.announcements = []

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 📊 NSE Trading System")
        st.markdown("*Decision Support — Short-Term Positional*")
        st.markdown("---")
        st.markdown(f"**Capital:** ₹{st.session_state.capital:,.0f}")
        st.markdown(f"**Date:** {datetime.now().strftime('%A, %d %B %Y')}")
        st.markdown(f"**Time:** {datetime.now().strftime('%I:%M %p IST')}")
        st.markdown("---")

        if st.button("🚀 Run Morning Analysis", use_container_width=True, type="primary"):
            st.session_state.recommendations = run_analysis()
            st.session_state.last_run        = datetime.now()

        if st.session_state.last_run:
            mins_ago = int((datetime.now() - st.session_state.last_run).total_seconds() / 60)
            if mins_ago < 60:
                st.caption(f"Last run: {st.session_state.last_run.strftime('%I:%M %p')} ({mins_ago}m ago — data cached)")
            else:
                st.caption(f"Last run: {st.session_state.last_run.strftime('%I:%M %p')}")

        if st.button("⚡ Clear Cache & Re-fetch", use_container_width=True):
            _cached_stock_prices.clear()
            _cached_index_data.clear()
            _cached_fii_data.clear()
            _cached_bulk_deals.clear()
            st.success("Cache cleared — next run will re-fetch all data")
            st.rerun()

        st.markdown("---")
        risk = check_portfolio_risk(st.session_state.capital)
        if risk['can_trade']:
            st.success("✅ Ready to trade")
        else:
            st.error("⛔ Trading blocked")
            for r in risk.get('blocked_reasons', []):
                st.caption(r)

        # Quick FII summary in sidebar
        fii = st.session_state.fii_data
        if fii:
            net = fii.get('fii_net_cr', 0)
            cls = "fii-net-pos" if net >= 0 else "fii-net-neg"
            arr = "▲" if net >= 0 else "▼"
            st.markdown(
                f'<div style="margin-top:8px;padding:8px;background:#12203a;'
                f'border-radius:6px;border:1px solid #1e4080">'
                f'<span style="font-size:.78rem;color:#64748b">FII TODAY</span><br>'
                f'<span class="{cls}" style="font-size:1rem;font-weight:700">'
                f'{arr} ₹{abs(net):,.0f} Cr</span></div>',
                unsafe_allow_html=True,
            )

        # Kite Connect live Nifty in sidebar
        try:
            from modules.kite_integration import is_session_valid, get_nifty_live
            if is_session_valid():
                if st.button("🔴 Live Nifty", use_container_width=True):
                    q = get_nifty_live()
                    if q:
                        chg = q.get('change_pct', 0)
                        arrow = "▲" if chg >= 0 else "▼"
                        color = "#22c55e" if chg >= 0 else "#ef4444"
                        st.markdown(
                            f'<div style="padding:6px 8px;background:#0f2a1a;border-radius:6px;'
                            f'border:1px solid #166534;text-align:center">'
                            f'<span style="color:#94a3b8;font-size:.75rem">NIFTY 50</span><br>'
                            f'<span style="color:{color};font-size:1.1rem;font-weight:700">'
                            f'{arrow} {q["last_price"]:,.2f}</span>'
                            f'<span style="color:{color};font-size:.8rem"> ({chg:+.2f}%)</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.markdown(
                    '<div style="padding:5px 8px;background:#1e1a0a;border-radius:6px;'
                    'font-size:.75rem;color:#78716c">🔑 Kite session needed for live quotes</div>',
                    unsafe_allow_html=True,
                )
        except Exception:
            pass

        st.markdown("---")
        st.caption("⚠️ Decision-support only. Not financial advice.")

    # ── Tabs ──────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🌅 Morning Brief",
        "🔻 Short Trades",
        "🔭 Hidden Opps",
        "📋 Trade Journal",
        "📊 Performance",
        "⚙️ Settings",
    ])

    results = st.session_state.recommendations

    # ── Tab 1: Morning Brief ──────────────────────────────────────────────
    with tab1:
        st.title("🌅 Morning Brief")

        if results is None:
            st.markdown("""
            ### Welcome to the NSE Trading System
            Click **🚀 Run Morning Analysis** in the sidebar to begin.

            The system will:
            1. Fetch prices for the full NSE F&O universe (~190 stocks)
            2. Pull live FII/DII flows from NSE
            3. Detect bulk/block deals (institutional footprint)
            4. Collect corporate announcements
            5. Score news, technical, fundamentals, market context
            6. Generate LONG recommendations (standard)
            7. Generate SHORT recommendations (futures)
            8. Apply feedback-adjusted weights from your trade history
            """)
            st.info("💡 Best run between 8:00–9:00 AM IST before market open.")
            return

        # FII/DII Panel  ← NEW
        st.subheader("🏦 FII / DII Flows")
        render_fii_panel(st.session_state.fii_data)

        st.markdown("---")

        # Market health
        st.subheader("🌐 Market Health")
        render_market_health(results.get('market'))

        st.markdown("---")

        # Risk
        st.subheader("🛡️ Portfolio Risk Status")
        render_risk_summary(results.get('risk_check'))

        st.markdown("---")

        # LONG recommendations
        recs = results.get('recommendations', [])
        if recs:
            weights = results.get('weights', {})
            adj_badge = " *(feedback-adjusted weights)*" if weights.get('adjusted') else ""
            st.subheader(f"📌 LONG Recommendations ({len(recs)}){adj_badge}")
            st.caption(results.get('message', ''))
            for i, rec in enumerate(recs):
                render_recommendation(rec, i)

            total_risk  = sum(r['risk_amount'] for r in recs)
            total_value = sum(r['position_value'] for r in recs)
            st.markdown(f"""
            **If all {len(recs)} LONG trades are taken:**
            - Capital deployed: ₹{total_value:,.0f} / ₹{st.session_state.capital:,.0f} ({total_value/st.session_state.capital*100:.0f}%)
            - Total risk: ₹{total_risk:,.0f} / ₹{st.session_state.capital*0.04:,.0f} daily limit
            - Cash remaining: ₹{st.session_state.capital - total_value:,.0f}
            """)
        else:
            if results.get('can_trade'):
                st.warning("🚫 No stocks meet the LONG criteria today — healthy discipline.")
            else:
                st.error(results.get('message', 'Trading not recommended today'))

        st.markdown("---")

        # Rejected
        st.subheader("❌ Stocks Considered but Rejected")
        render_rejected(results.get('rejected', []))

        st.markdown("---")
        st.markdown("""
        <div class="warning-box">
        📝 <strong>Reminders:</strong><br>
        • Place stop-loss orders immediately after entry<br>
        • Do not average down on losing positions<br>
        • This is a decision-support tool — you make the final call<br>
        • If you feel emotional or uncertain, skip today
        </div>
        """, unsafe_allow_html=True)

    # ── Tab 2: Short Trades ───────────────────────────────────────────────
    with tab2:
        st.title("🔻 Short Trade Recommendations (Futures)")
        st.markdown("""
        > These are **futures short** setups for stocks showing overbought conditions,
        > bearish technical signals, or negative catalysts.
        > Short selling in spot market is not recommended for retail traders in India —
        > these setups assume you trade **stock futures** with margin.
        """)

        st.markdown("""
        <div class="warning-box">
        ⚠️ <strong>Futures Risk Warning:</strong>
        Futures require margin (approx 15-25% of notional). Losses can exceed margin.
        Short squeezes can move against you rapidly.
        Always use stop-losses. Verify actual lot sizes on NSE/your broker before trading.
        </div>
        """, unsafe_allow_html=True)

        if results is None:
            st.info("Run Morning Analysis first to see short recommendations.")
        else:
            short_recs = results.get('short_recommendations', [])
            if short_recs:
                st.success(f"Found {len(short_recs)} short setup(s) today")
                for i, rec in enumerate(short_recs):
                    render_short_recommendation(rec, i)

                total_margin = sum(r['margin_required'] for r in short_recs)
                total_risk   = sum(r['risk_amount'] for r in short_recs)
                st.markdown(f"""
                **If all {len(short_recs)} short trades are taken:**
                - Total margin required: ₹{total_margin:,.0f}
                - Total max risk: ₹{total_risk:,.0f}
                """)
            else:
                st.info(
                    "No short setups meet criteria today. "
                    "This typically means the market is not showing extreme overbought conditions. "
                    "Good — it means the broader bias is still constructive."
                )

            st.markdown("---")
            st.subheader("🟡 Stocks Considered for Short — But Rejected")
            render_short_rejected(results.get('short_rejected', []))

    # ── Tab 3: Hidden Opportunities ───────────────────────────────────────
    with tab3:
        st.title("🔭 Hidden Opportunities")
        st.markdown(
            "Bulk/block deals, corporate announcements, and institutional footprints "
            "that are not visible in standard price data."
        )
        if results is None:
            st.info("Run Morning Analysis first.")
        else:
            render_hidden_opportunities()

    # ── Tab 4: Trade Journal ──────────────────────────────────────────────
    with tab4:
        st.title("📋 Trade Journal")
        render_trade_journal()

    # ── Tab 5: Performance + Feedback ────────────────────────────────────
    with tab5:
        st.title("📊 Performance & Feedback Loop")
        render_performance()

    # ── Tab 6: Settings ───────────────────────────────────────────────────
    with tab6:
        render_settings()


if __name__ == "__main__":
    main()
