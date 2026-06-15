# NSE Short-Term Positional Trading Decision Support System

> ⚠️ **DISCLAIMER:** This is a decision-support system, NOT financial advice. It does NOT guarantee profits. Markets are unpredictable. You assume full responsibility for all trading decisions.

---

## What This System Does

Every trading day, the engine ("Run Morning Analysis"):

1. **Resolves the F&O universe** — the full NSE Futures & Options underlying list (~190 stocks), fetched live from NSE's lot-size file when reachable, with a static fallback list baked into `config.py`.
2. **Fetches** ~6 months of daily OHLCV for the whole universe from Yahoo Finance (yfinance), in batched, multi-threaded requests.
3. **Pulls macro/market context** — Nifty, Bank Nifty, India VIX, and global cues (S&P 500, crude, USD/INR, US 10Y).
4. **Pulls NSE-only signals when reachable** — FII/DII cash flows, bulk/block deals, corporate announcements. (These are skipped automatically when NSE is unreachable, e.g. on cloud — see *Cloud Notes*.)
5. **Collects news** from RSS feeds and scores sentiment with a keyword dictionary (no LLM).
6. **Computes technical indicators** (EMA 20/50, RSI, MACD, ATR, volume, breakout, relative strength) and a 0–100 technical score per stock.
7. **Scores fundamentals** (ROE, D/E, promoter holding/pledge, growth, margins) — live from your Screener.in account when refreshed, else a static snapshot.
8. **Assesses market health** (trend, VIX, FII stance, global cues) → FAVORABLE / CAUTIOUS / NO_TRADE.
9. **Ranks** every stock with a weighted composite score and emits **0–3 LONG** and **0–3 SHORT (futures)** recommendations with entry, target, stop-loss, position size, and full reasoning.
10. **Enforces risk limits** (2% risk/trade, daily/weekly/monthly loss caps, max 3 open positions, min 1:2 R:R).

---

## The Recommendation Engine — How Scoring Works

Each stock gets four sub-scores (0–100), combined into a composite:

| Dimension | Base Weight | What It Measures |
|-----------|-------------|------------------|
| News / Catalyst | 30% | Is there a reason to move now? |
| Technical | 35% | Is price action confirming? |
| Fundamental | 15% | Is this a quality company? |
| Market Context | 20% | Is the broad market supportive? |

`composite = 0.30·news + 0.35·technical + 0.15·fundamental + 0.20·market (+ bulk-deal bonus)`

A stock becomes a **LONG recommendation** only if it clears **all** of:
- composite ≥ **65/100**
- risk:reward ≥ **1:2**
- passes hard technical/fundamental disqualifiers (no death-cross, not overextended, D/E and pledge within limits, etc.)

**SHORT (futures)** candidates are scored separately (RSI overbought, EMA overextension, MACD bearish cross, distribution volume, failed breakout) and require a short-score ≥ 55, amplified by negative news and bulk-sell deals. Lot sizes come from the live NSE F&O lot file when available.

Final picks are filtered for **sector diversity** and sized by the risk manager.

---

## The Feedback Loop — How the System Learns (`modules/feedback_engine.py`)

**This is a manual-journaling feedback loop, not an automatic outcome tracker.** It only learns from trades **you log and close** in the Trade Journal tab. It does **not** automatically check whether a past recommendation hit its target or stop.

How it works:

1. Every run **stores its recommendations** (with the four sub-scores) in the `recommendations` table.
2. You **log a trade** (Trade Journal → Log New Trade) and later **close it** with exit price + reason. Closing computes net P&L and R-multiple.
3. The feedback engine **joins closed trades to the recommendation** that generated them (same symbol, within ±5 days of entry).
4. From the matched set it computes each signal's **predictive power** = `avg score in winners − avg score in losers`.
5. `get_adjusted_weights()` then **re-weights the composite**: `70% base + 30% driven by predictive power`, renormalised to sum to 1.0.
6. The recommendation engine calls these adjusted weights on the **next run**, so signals that actually predicted winners get more influence.

**Important thresholds & caveats:**
- Adjustment only activates after **≥ 10 matched closed trades**. Below that, you see analytics but the engine keeps the base 30/35/15/20 weights.
- A closed trade only counts if it **matches a stored recommendation** by symbol and date window. A trade on a symbol the engine never recommended won't feed the loop.
- The loop is only as good as your journaling discipline. No journal entries → no learning.

### Does feedback persist? (Local vs Cloud)

- **Locally:** Yes. Everything lives in `data/trading_system.db` (SQLite). Recommendations and the trade journal persist across restarts, so the feedback loop accumulates indefinitely on your machine. This is the recommended way to build the learning history.
- **On Streamlit Community Cloud:** **No, not reliably.** Streamlit Cloud has an **ephemeral filesystem** — the container is rebuilt from the GitHub repo on every redeploy and after idle sleep, **wiping `data/trading_system.db`**. Any trades you log on the cloud app can vanish on the next reboot, so the feedback loop will keep resetting. To get persistent learning on the web you must back the journal/recommendations with an **external database** (e.g. Postgres/Supabase, or a synced SQLite). Until then, **do your journaling on the local app** to preserve the learning loop.

---

## Quick Start (Local — Windows)

### Prerequisites
- Python 3.9+ ([Download](https://www.python.org/downloads/))
- Internet connection

### Setup
```
pip install -r requirements.txt
streamlit run app.py        # or double-click START.bat
```
Open `http://localhost:8501` → click **🚀 Run Morning Analysis** in the sidebar.

Running locally is **recommended** for the full universe + FII/DII + bulk deals + persistent feedback, all of which depend on NSE being reachable from your (Indian) IP.

---

## Cloud Notes (Streamlit Community Cloud)

The app is deployable to `share.streamlit.io`, but be aware of three platform limits that affect it:

1. **NSE geo-blocks datacenter IPs.** FII/DII, bulk/block deals, and the live F&O list call `nseindia.com`, which rejects/ times out from US-hosted cloud servers. The app now **probes NSE once and skips those calls fast** when unreachable (instead of hanging on long timeouts). It falls back to the static F&O universe in `config.py`. Those NSE-only panels will simply show "unavailable" on cloud.
2. **yfinance can be rate-limited on cloud IPs.** Price fetching uses **batched** `yf.download` (≈4 requests for the whole universe instead of ~190), which is faster and far less likely to be throttled — but Yahoo can still intermittently block shared cloud IPs.
3. **Ephemeral storage** wipes the SQLite DB on reboot (see *Does feedback persist?* above).

**Most reliable cloud setup:** connect **Kite Connect (Zerodha)** in the Settings tab — Kite's API works from any IP and gives clean live quotes/history. For the heavy daily run and for building a persistent feedback history, prefer the **local** app.

### Secrets on cloud
Set credentials under the app's **Settings → Secrets** (TOML), mirroring `.streamlit/secrets.toml.example`:
```toml
[screener]
email = "you@example.com"
password = "..."

[kite]
api_key = "..."
api_secret = "..."
user_id = "..."
```

---

## Performance

Batched price fetching + single-transaction DB writes bring a full-universe run down from ~10–15 min (old per-ticker fetch) to roughly **1–2 min locally** once dependencies are warm. Subsequent re-runs within 30 min reuse cached data (`st.cache_data`). Use **⚡ Clear Cache & Re-fetch** in the sidebar to force fresh data.

---

## System Architecture

```
nse_trader/
├── app.py                       # Streamlit dashboard + run_analysis pipeline
├── config.py                    # Settings, risk rules, F&O fallback universe, weights
├── credentials.py               # Screener/Kite creds (st.secrets on cloud, secrets.json local)
├── launch_web.py                # Optional: local Streamlit + ngrok public tunnel
├── requirements.txt
├── data/
│   ├── trading_system.db        # SQLite (auto-created; ephemeral on cloud)
│   └── fno_universe.json        # Cached live F&O symbol + lot-size list (7-day TTL)
└── modules/
    ├── database.py              # Schema + connections
    ├── data_fetcher.py          # Batched prices, macro, FII/DII, bulk deals, F&O list
    ├── technical_engine.py      # Indicators + technical score
    ├── news_engine.py           # RSS collection + keyword sentiment
    ├── fundamental_filter.py    # Fundamental score (live Screener → static fallback)
    ├── screener_fetcher.py      # Screener.in login + scrape
    ├── market_context.py        # Market health score
    ├── risk_manager.py          # Position sizing + risk gates
    ├── recommendation_engine.py # Composite ranking, LONG + SHORT, reasoning
    ├── feedback_engine.py       # Signal predictive power + adjusted weights
    └── kite_integration.py      # Zerodha Kite live quotes / history
```

---

## Risk Management Rules (Built-in)

| Rule | Limit |
|------|-------|
| Max risk per trade | 2% of capital |
| Max capital per trade | 33% |
| Max open positions | 3 |
| Max daily loss | 4% |
| Max weekly loss | 8% |
| Max monthly drawdown | 20% |
| Min risk:reward ratio | 1:2 |
| Cash buffer | ~17% always in cash |
| Holding period | Max 4 trading days |

If the daily loss limit is hit, the engine stops generating recommendations.

---

## Customization

- **Capital:** Settings tab, or `config.py → TOTAL_CAPITAL`.
- **Universe:** the live F&O list is used automatically; edit the static fallback in `config.py → STOCK_UNIVERSE`. Force a refresh by deleting `data/fno_universe.json`.
- **Risk / weights / thresholds:** `config.py` (commented).
- **Fundamentals:** Settings → "Refresh Fundamentals from Screener.in", or the static `FUNDAMENTAL_DATA` dict.

---

## Limitations

- News is from RSS feeds — hours behind institutional terminals.
- Fundamental fallback is a static snapshot (refresh from Screener for live data).
- Analysis is based on previous-day close (intraday only via Kite live quotes).
- F&O membership and lot sizes change; sync periodically (delete the cache to refresh).
- This system organizes research and enforces discipline. It cannot predict the future.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Module not found" | `pip install -r requirements.txt` |
| Run Morning Analysis hangs/fails on cloud | Expected for NSE panels (geo-block) — now skipped fast. If prices also fail, Yahoo is rate-limiting the cloud IP; run locally or use Kite. |
| No stock data fetched | yfinance rate-limited or SSL/CA issue — retry, run locally, or connect Kite. |
| FII/DII / bulk deals blank | NSE unreachable from this host (cloud) — works locally. |
| Feedback loop keeps resetting | You're on cloud (ephemeral DB) — journal locally or wire an external DB. |
| Database error | Delete `data/trading_system.db` and restart. |

---

*Built for disciplined, research-driven trading. The best trade is often no trade at all.*
