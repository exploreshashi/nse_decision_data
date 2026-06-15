# NSE Short-Term Positional Trading Decision Support System
## Project Blueprint v1.0

---

> **DISCLAIMER:** This document describes a *decision-support system*, not an automated trading system. No software can guarantee profits. Markets are inherently unpredictable. Past patterns do not guarantee future results. The user assumes full responsibility for all trading decisions. This system is designed to organize research, enforce discipline, and manage risk — not to replace human judgment.

---

## 1. Executive Summary

**What we are building:** A daily pre-market research engine that scans NSE-listed Indian stocks across news, technical, and fundamental dimensions to surface 2–3 high-conviction short-term (0–4 day) positional trade ideas before 9:00 AM IST each trading day.

**What it is NOT:** An auto-trading bot, a guaranteed-profit machine, or a replacement for the trader's own judgment. It is a structured research assistant with built-in risk controls.

**Capital:** ₹6,00,000  
**Target:** Aggressive growth (the user's stated goal is to double in one year — roughly 100% annual return). We will design the system to *pursue* this goal while being transparent about the odds.

**Honest assessment of the 100% annual return target:**
- Professional hedge funds average 15–25% annually. Top-decile traders in India may achieve 40–80% in favorable years.
- 100% in one year from short-term trading requires a sustained win rate above 55% with an average risk-reward of at least 1:2, plus near-perfect position sizing — all while avoiding a single catastrophic drawdown.
- The system will aim for this but will track whether it is realistic. If early backtests and paper-trading show the system averaging 3–5% per month (36–60% annualized), that is already exceptional. The plan should include a checkpoint at 3 months to recalibrate expectations.

**Core philosophy:** Protect the capital first. Profits follow discipline, not predictions.

---

## 2. Feasibility Assessment

### 2.1 Is This Project Feasible?

**Yes, with caveats.**

| Dimension | Feasibility | Notes |
|---|---|---|
| Data availability | ✅ High | NSE data (OHLCV, delivery %) is freely available. Fundamental data is available through screeners. News is scrapable. |
| Technical signals | ✅ High | Well-defined, computable from OHLCV data. Libraries exist (pandas-ta, TA-Lib). |
| News scoring | ⚠️ Medium | Free news sources exist but are noisy. LLM-based scoring adds quality but needs tuning. Automated news is always 6–12 hours behind institutional desks. |
| Fundamental filters | ✅ High | Quarterly data from screeners (Screener.in, Trendlyne). Updated quarterly — sufficient for filtering, not for edge. |
| Recommendation engine | ⚠️ Medium | Combining signals into a single score is the hardest part. Requires iterative tuning and honest backtesting. |
| Execution before 9 AM | ✅ High | Schedulable with cron. Data available by 7–8 AM. |
| Doubling money in a year | ⛔ Low probability | Possible but unlikely. The system should track realistic hit rates and help the user adjust. |

### 2.2 What Could Make This Fail?

1. **Overfitting:** Designing rules that perfectly explain the past but fail in live markets.
2. **Stale news:** Retail-accessible news is already priced in by the time you read it.
3. **Emotional override:** The best system is worthless if the trader ignores stop-losses.
4. **Liquidity traps:** Small-cap stocks may show perfect setups but cannot be exited cleanly.
5. **Regime changes:** A strategy tuned for a bull market will bleed in a correction.

### 2.3 Protecting Against Overtrading and Emotional Trading

This is the most important design consideration. The system must:

- **Enforce a "No Trade" default.** The system starts each day assuming *no trades should be taken*. Stocks must earn their way onto the recommendation list.
- **Cap daily recommendations at 3.** Even if 10 stocks look good, only the top 3 (or fewer) are shown.
- **Require minimum confidence thresholds.** No recommendation below a defined composite score.
- **Display a daily "Market Health" score.** If the score is below threshold, the system explicitly says: "Market conditions are unfavorable. No trades recommended today."
- **Show cumulative risk exposure.** The dashboard must always show: total capital at risk across open positions, daily loss so far, and how close the trader is to the daily loss limit.
- **Require trade journaling.** Every trade must be logged with the reason for entry, the reason for exit, and an emotional state tag (calm, FOMO, revenge, confident). Patterns in emotional tags become visible over time.
- **Include a cooling-off trigger.** If the trader hits the daily loss limit, the system locks recommendations for the rest of the day and displays: "Daily loss limit reached. No further trades today."
- **Never use urgency language.** The system will never say "act fast" or "don't miss this." Every recommendation is framed as: "If the stock opens in this range and you choose to trade, here is the plan."

---

## 3. Data Source Plan

### 3.1 Price and Volume Data (Free)

| Source | Data | Access Method | Frequency |
|---|---|---|---|
| NSE India (nseindia.com) | OHLCV, delivery %, bhavcopy | HTTP/CSV download | Daily EOD |
| Yahoo Finance (via yfinance) | OHLCV, adjusted close | Python library | Daily / intraday (15-min delay) |
| Google Finance | Quick price checks | Scraping (fragile) | Real-time-ish |

**Primary:** yfinance for historical OHLCV (append `.NS` for NSE tickers).  
**Supplementary:** NSE bhavcopy CSVs for delivery volume % (important for confirming institutional interest).

### 3.2 Fundamental Data (Free / Freemium)

| Source | Data | Access |
|---|---|---|
| Screener.in | Financials, ratios, quarterly results, shareholding | Web scraping (rate-limited) |
| Trendlyne | Screeners, technicals, fundamentals | Web scraping / some free APIs |
| MoneyControl | Earnings, results, commentary | Web scraping |
| Tijori Finance | Financial data, annual reports | Web (some free) |
| BSE India | Corporate announcements, results | RSS / website |

**Strategy:** Build a quarterly refresh pipeline. Scrape Screener.in for key ratios per stock. Cache locally. Do not scrape on every run — this data changes quarterly.

### 3.3 News and Events (Free / LLM-Assisted)

| Source | Type | Access |
|---|---|---|
| MoneyControl | Market news, stock-specific | RSS + scraping |
| Economic Times Markets | Macro, stock news | RSS |
| Livemint | Business news | RSS |
| BSE/NSE corporate filings | Board meetings, results dates, announcements | RSS / API |
| Pulse by Zerodha | Aggregated news | RSS |
| Google News (India/Business) | Aggregated | RSS / scraping |

**News scoring approach:**
- Collect headlines and summaries from RSS feeds overnight (midnight to 7 AM).
- Use an LLM (local or API) to classify each headline into: Positive / Negative / Neutral for the specific stock.
- Assign a magnitude score (1–5) based on the nature of the event (e.g., earnings beat = 4, minor order win = 2).
- Flag stocks with recent high-magnitude events for priority analysis.

### 3.4 Market/Macro Data (Free)

| Data Point | Source |
|---|---|
| FII/DII daily figures | NSE / MoneyControl |
| Nifty 50, Bank Nifty futures | NSE / yfinance |
| SGX Nifty / GIFT Nifty | Web scraping (pre-market) |
| US market close (S&P 500, NASDAQ) | yfinance |
| USD/INR | yfinance / RBI |
| Crude oil (Brent) | yfinance |
| India VIX | NSE / yfinance |
| US 10Y yield | yfinance |

### 3.5 Paid Sources (For Later Phases)

| Source | Value | Cost |
|---|---|---|
| Ticker by Finology API | Clean fundamental data | ₹500–2000/mo |
| Kite Connect (Zerodha) | Real-time data, order placement | ₹2000/mo |
| ChartInk screener | Pre-built technical scans | Free tier available |
| Alpha Vantage (India) | Additional technical data | Free tier (5 calls/min) |

**MVP will use free sources only.** Paid APIs are Phase 2+ enhancements.

---

## 4. Trading Philosophy

### 4.1 Core Beliefs Encoded in the System

1. **Capital preservation first.** The system's primary objective is to prevent catastrophic loss. Growth is secondary to survival.
2. **Fewer, better trades.** Two high-conviction trades per week are better than ten mediocre ones.
3. **Every trade has a plan before entry.** Entry, target, stop-loss, and time-based exit are defined before the market opens.
4. **The stop-loss is sacred.** Once set, a stop-loss is only moved *in the direction of profit*, never against it.
5. **The market owes you nothing.** A great setup can fail. The system accounts for this with position sizing.
6. **News creates the catalyst; technicals confirm the timing.** We don't trade news alone (too slow) or technicals alone (no edge). The confluence of both creates opportunity.
7. **Skip days are good days.** Not trading when conditions are poor is a profitable strategy.

### 4.2 Trade Profile

| Parameter | Value |
|---|---|
| Holding period | 0–4 trading days (intraday to swing) |
| Direction | Long only (short-selling is complex for retail in India) |
| Universe | NSE-listed stocks with average daily turnover > ₹10 crore |
| Sectors | All, but avoid stocks under ASM/GSM surveillance |
| Market cap | Primarily mid-cap and large-cap (>₹5,000 crore). Small-caps only with very high conviction. |

### 4.3 When NOT to Trade

The system must explicitly flag these conditions and suppress recommendations:

- India VIX > 22 (extreme volatility — risk of whipsaws)
- Nifty below its 20-day EMA AND 50-day EMA (confirmed downtrend)
- FII net selling > ₹3,000 crore for 3+ consecutive days
- Major macro event day (RBI policy, Union Budget, US Fed decision, election results)
- Global markets sharply down (S&P 500 down >2% overnight)
- Friday afternoon entries for overnight holds over weekends (gap risk)
- When the trader has already hit the daily or weekly loss limit

---

## 5. Signal Framework

### 5.1 Signal Categories and Weights

The system evaluates stocks across four dimensions. Each produces a sub-score normalized to 0–100.

| Dimension | Weight | What It Captures |
|---|---|---|
| News/Catalyst Score | 30% | Is there a reason for this stock to move *now*? |
| Technical Setup Score | 35% | Is the price action confirming the direction? |
| Fundamental Filter | 15% | Is this a quality company (not a trap)? |
| Market Context Score | 20% | Is the broader market supportive? |

**Composite Score = (0.30 × News) + (0.35 × Technical) + (0.15 × Fundamental) + (0.20 × Market)**

Minimum composite score for recommendation: **65/100**

### 5.2 News/Catalyst Scoring (0–100)

| Event Type | Base Score | Modifier |
|---|---|---|
| Earnings beat (>10% above estimates) | 70 | +10 if margin expansion, +10 if guidance raised |
| Large order win (>5% of annual revenue) | 60 | +10 if from government/repeat client |
| Product launch / new segment | 50 | +10 if in high-growth sector |
| Promoter buying | 65 | +15 if >₹10 crore purchase |
| Debt reduction / rating upgrade | 55 | +10 if significant (>20% debt cut) |
| M&A announcement (acquirer) | 50 | Highly variable — needs manual judgment |
| Regulatory approval | 60 | +10 if removes major overhang |
| Negative news (fraud, SEBI action, downgrade) | Disqualify | Stock removed from consideration |
| No recent news | 20 | Low catalyst = low priority |

Freshness decay: Score reduces by 15% per day after the event. A 3-day-old catalyst scores 0.85³ = 61% of its original value.

### 5.3 Technical Setup Scoring (0–100)

Calculated from daily OHLCV data using the following sub-signals:

| Signal | Points (max) | Condition |
|---|---|---|
| Price above 20 EMA | 10 | Basic trend filter |
| Price above 50 EMA | 10 | Medium-term trend confirmation |
| 20 EMA above 50 EMA | 10 | Golden alignment |
| RSI (14) between 40–70 | 10 | Not overbought, not deeply oversold |
| MACD line above signal line | 10 | Momentum confirmation |
| Volume spike (>1.5x 20-day avg) | 15 | Institutional interest signal |
| Delivery volume >50% (from bhavcopy) | 10 | Genuine buying, not speculative |
| Breakout above recent resistance | 15 | Key technical event |
| Relative strength vs Nifty positive (10-day) | 10 | Outperforming the market |

**Disqualifiers (score → 0):**
- RSI > 80 (extremely overbought)
- Price >15% above 20 EMA (overextended)
- Declining volume on price rise (distribution)
- Stock in confirmed downtrend (lower lows, lower highs on weekly)

### 5.4 Fundamental Filter Scoring (0–100)

This is a *quality filter*, not a valuation model. For short-term trading, fundamentals prevent you from buying junk.

| Criterion | Points (max) | Condition |
|---|---|---|
| Revenue growth (YoY) > 10% | 15 | Growing business |
| Profit growth (YoY) > 15% | 15 | Improving profitability |
| ROE > 12% | 10 | Decent return on equity |
| Debt/Equity < 1.0 | 10 | Not overleveraged |
| Promoter holding > 40% | 10 | Skin in the game |
| Promoter pledge < 10% | 10 | Not using stock as collateral |
| FII + DII holding > 25% | 10 | Institutional validation |
| No negative audit qualifications | 10 | Clean accounting |
| Operating margin stable or improving | 10 | Not deteriorating |

**Hard disqualifiers:**
- Promoter pledge > 50%
- Debt/equity > 3.0
- Negative free cash flow for 3+ years
- SEBI/regulatory action pending
- Stock under ASM/GSM framework

### 5.5 Market Context Scoring (0–100)

| Factor | Points (max) | Condition |
|---|---|---|
| Nifty above 20 EMA | 15 | Bullish market |
| Bank Nifty above 20 EMA | 10 | Financial sector healthy |
| India VIX < 18 | 15 | Low volatility = trends persist |
| FII net buyers (last 3 days) | 15 | Foreign flow supportive |
| GIFT Nifty positive (pre-market) | 10 | Positive global cue |
| US markets closed green | 10 | Overnight risk reduced |
| Crude oil stable (not spiking) | 10 | No inflation shock |
| Sector trend (stock's sector vs Nifty) | 15 | Sector rotation favorable |

---

## 6. Risk Management Framework

### 6.1 Capital Allocation Rules

| Rule | Value | Rationale |
|---|---|---|
| Total trading capital | ₹6,00,000 | User-defined |
| Max capital per trade | ₹2,00,000 (33%) | No single trade should dominate |
| Max simultaneous positions | 3 | Diversification without over-diversification |
| Max capital deployed at once | ₹5,00,000 (83%) | Always keep ₹1,00,000 as cash buffer |
| Max risk per trade | ₹12,000 (2% of capital) | Survive 10 consecutive losses |
| Max daily loss | ₹24,000 (4% of capital) | Hard stop for the day |
| Max weekly loss | ₹48,000 (8% of capital) | Trigger for strategy review |
| Max monthly drawdown | ₹90,000 (15% of capital) | Pause trading, re-evaluate system |

### 6.2 Position Sizing Formula

Position sizing is driven by the stop-loss, not by conviction or "how much I want to make."

```
Risk Amount = Capital × Risk Per Trade %
            = ₹6,00,000 × 2%
            = ₹12,000

Stop Loss Distance = Entry Price - Stop Loss Price

Quantity = Risk Amount / Stop Loss Distance
         = ₹12,000 / (Entry - SL)

Position Value = Quantity × Entry Price
```

**Example:**
- Stock: INFY at ₹1,500
- Stop Loss: ₹1,470 (₹30 below entry)
- Quantity = ₹12,000 / ₹30 = 400 shares
- Position Value = 400 × ₹1,500 = ₹6,00,000

This exceeds the ₹2,00,000 per-trade cap. So we reduce:
- Max Quantity = ₹2,00,000 / ₹1,500 = 133 shares
- Actual Risk = 133 × ₹30 = ₹3,990 (well within ₹12,000 limit) ✅

**The system always takes the SMALLER of:**
1. Quantity from risk-based sizing
2. Quantity from max-capital-per-trade cap

### 6.3 Stop-Loss Framework

| Type | Method | Use Case |
|---|---|---|
| ATR-based | Entry - (1.5 × ATR14) | Default for most trades |
| Structure-based | Below recent swing low | When a clear support level exists |
| Percentage-based | 3–5% below entry | Fallback when ATR/structure unclear |
| Time-based | Exit after 4 trading days regardless | Prevent "hope trades" that drag on |

**Rules:**
- Stop-loss is set BEFORE entry and entered immediately.
- Stop-loss is never widened.
- After 50% of target is achieved, stop-loss moves to breakeven.
- After 75% of target, stop-loss moves to lock in 50% of unrealized gains.

### 6.4 Minimum Risk-Reward Ratio

**Minimum: 1:2 (risk ₹1 to make ₹2)**

The system will not recommend trades with R:R below 1:2. Preferred: 1:2.5 or better.

At a 1:2 ratio, a 40% win rate is still breakeven:
- 10 trades: 4 winners × ₹24,000 = ₹96,000; 6 losers × ₹12,000 = ₹72,000 → Net: +₹24,000

This builds in a margin of safety even with a sub-50% hit rate.

---

## 7. Recommendation Ranking Logic

### 7.1 Daily Pipeline (How Stocks Get Selected)

```
Step 1: Universe Filter
  - All NSE-listed stocks
  - Filter: Avg daily turnover > ₹10 crore (last 20 days)
  - Filter: Not in ASM/GSM/trade-to-trade segment
  - Filter: Market cap > ₹5,000 crore
  → ~300-400 stocks remain

Step 2: News Scan
  - Check overnight news for each stock in universe
  - Score each stock's news catalyst (0–100)
  - Flag stocks with score > 40 as "news-active"
  → ~20-50 stocks flagged

Step 3: Technical Screen
  - Calculate technical score for all news-active stocks
  - Also scan full universe for pure technical breakouts (score > 70)
  - Merge both lists
  → ~10-30 candidates

Step 4: Fundamental Filter
  - Apply hard disqualifiers
  - Score remaining candidates
  → ~8-20 candidates

Step 5: Market Context
  - Calculate single market context score (applies to all)
  - If market score < 30: output "No trades today"
  → Proceed or halt

Step 6: Composite Ranking
  - Calculate composite score for each candidate
  - Rank by composite score descending
  - Apply risk-reward filter (drop R:R < 1:2)
  → Top 5-8 candidates

Step 7: Position Sizing Check
  - Calculate position size for top candidates
  - Check against capital limits and existing positions
  - Check liquidity (can we get this quantity without impact?)
  → Top 3 or fewer recommendations

Step 8: Final Output
  - Format recommendations with all fields
  - Include rejected stocks and reasons
  - Include market view and risk level
  - Include "why not more trades" explanation
```

### 7.2 Breaking Ties

When two stocks have similar composite scores:
1. Prefer the one with a fresher catalyst (more recent news).
2. Prefer the one with better risk-reward ratio.
3. Prefer the one with higher delivery volume %.
4. Prefer the more liquid stock.
5. Prefer sector diversification (don't recommend 2 stocks from the same sector).

---

## 8. Daily Workflow: Before 9 AM IST

| Time | Task | Automated? |
|---|---|---|
| 12:00 AM – 6:00 AM | News RSS feeds collected, headlines stored | ✅ Yes (cron job) |
| 6:30 AM | Previous day's bhavcopy downloaded from NSE | ✅ Yes |
| 6:30 AM | FII/DII data scraped | ✅ Yes |
| 6:45 AM | GIFT Nifty / SGX Nifty pre-market fetched | ✅ Yes |
| 6:45 AM | US market close fetched (S&P 500, NASDAQ) | ✅ Yes |
| 7:00 AM | Technical indicators computed on updated data | ✅ Yes |
| 7:00 AM | News headlines scored by LLM | ✅ Yes |
| 7:15 AM | Market context score computed | ✅ Yes |
| 7:30 AM | Candidate stocks ranked | ✅ Yes |
| 7:30 AM | Position sizes calculated | ✅ Yes |
| 7:45 AM | Daily report generated | ✅ Yes |
| 7:45 AM – 8:30 AM | **Trader reviews report manually** | ❌ Manual |
| 8:30 AM – 9:00 AM | Trader decides which (if any) trades to take | ❌ Manual |
| 9:00 AM | Market opens. Trader places orders (if any). | ❌ Manual |

**Critical design decision:** The 7:45–9:00 AM window is *deliberately manual*. The system generates research; the human decides. This is not a bug — it is the most important feature.

---

## 9. App/Dashboard Design

### 9.1 Technology Choice

**Recommended: Streamlit web app (local)**

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| Python scripts | Simple, fast | No UI, hard to review | MVP foundation only |
| Jupyter notebook | Good for analysis | Not production, not schedulable | Research phase only |
| Streamlit | Fast UI, Python-native, free | Single-user, local only | ✅ Best for MVP |
| Flask/Django dashboard | Full control | More dev work | Phase 2+ |
| Telegram bot | Mobile alerts | Limited display | Add-on, not primary |
| Database-backed app | Scalable, persistent | Overkill for solo trader | Later phase |

**MVP: Streamlit + SQLite + cron scheduling**  
**Phase 2: Add Telegram alerts as a companion channel**

### 9.2 Dashboard Pages

**Page 1: Morning Brief (Default)**
- Date, market health score, overall risk level
- GIFT Nifty, US markets, FII/DII summary
- VIX level and interpretation
- "Should I trade today?" verdict (Green / Yellow / Red)

**Page 2: Today's Recommendations**
- 0–3 stock cards, each showing all fields from the output template
- Expandable reasoning for each
- Rejected stocks with reasons
- Risk exposure summary (total capital at risk if all trades taken)

**Page 3: Open Positions Tracker**
- Current open positions with live P&L (manual entry or API-linked)
- Stop-loss status (hit / approaching / safe)
- Time remaining before time-based exit

**Page 4: Trade Journal**
- Log of all past trades
- Entry/exit details, P&L, reason, emotional tag
- Running stats: win rate, avg R:R achieved, expectancy
- Charts: equity curve, drawdown chart, win rate over time

**Page 5: System Performance**
- Backtesting results
- Signal accuracy by dimension (news score accuracy, technical score accuracy)
- "What would have happened if I took every recommendation" vs "What I actually did"

**Page 6: Settings**
- Adjust capital, risk %, max positions
- Override market health threshold
- Manage stock universe (add/remove stocks)

---

## 10. Backtesting Plan

### 10.1 Approach

Backtesting short-term trading systems is inherently flawed because:
- You can't backtest news timing (you didn't know the news in advance).
- Execution slippage is real (especially at market open).
- Hindsight bias is severe in short-term strategies.

**Our approach: Walk-forward paper trading + limited signal backtesting**

### 10.2 What CAN Be Backtested

| Component | Method | Data Needed |
|---|---|---|
| Technical signals only | "If technical score > X on day T, what was the return on day T+1 to T+4?" | 2 years of OHLCV |
| Stop-loss effectiveness | "How often does the ATR-based stop get hit before the target?" | 2 years of OHLCV |
| Market context filter | "On days when market score < 30, what was the average Nifty return?" | 2 years of index data |
| Position sizing | "With 2% risk per trade, what is the max drawdown over 2 years?" | Simulated trade sequences |

### 10.3 What CANNOT Be Backtested (Honestly)

- News-driven signals (you'd be using future news)
- LLM-based news scoring (the model didn't exist in the past)
- The full composite score (depends on news + technicals + fundamentals together)

### 10.4 Walk-Forward Validation

1. **Month 1–2:** Paper trade. Run the system daily, generate recommendations, but don't trade with real money. Track hypothetical results.
2. **Month 3:** Trade with 50% capital (₹3,00,000). Compare real results to paper results.
3. **Month 4+:** If results are within acceptable range, scale to full capital.

### 10.5 Key Metrics to Track

| Metric | Target | Red Flag |
|---|---|---|
| Win rate | >45% | <35% for 30+ trades |
| Average R:R achieved | >1:1.8 | <1:1.2 |
| Expectancy per trade | >₹3,000 | Negative for 20+ trades |
| Max drawdown | <20% of capital | >25% |
| Sharpe ratio (annualized) | >1.5 | <0.8 |
| Avg holding period | 1–3 days | >5 days (system isn't working as designed) |
| Skip rate | 30–50% of trading days | <10% (overtrading) or >80% (too conservative) |

---

## 11. Project Phases

### Phase 1: Research and Design (This Document)

- **Objective:** Define the complete system before writing any code.
- **Inputs:** User requirements, market knowledge, data source research.
- **Output:** This blueprint document, approved by user.
- **Complexity:** Low (effort is in thinking, not coding).
- **Risks:** Analysis paralysis. Mitigate by time-boxing to 1 week.
- **Validation:** User reviews and approves the plan.

### Phase 2: Data Pipeline

- **Objective:** Build reliable daily data ingestion for OHLCV, bhavcopy, macro data.
- **Inputs:** NSE, yfinance, macro data sources.
- **Output:** A local SQLite database with clean daily data for 300+ stocks, auto-updated.
- **Tools:** Python, yfinance, pandas, SQLite, requests, BeautifulSoup.
- **Complexity:** Medium. NSE website is known to block scrapers; need headers/rotation.
- **Risks:** NSE blocking access, Yahoo Finance API instability.
- **Validation:** Compare 20 random stocks' data against a manual check on MoneyControl.

### Phase 3: News Collection and Scoring

- **Objective:** Collect overnight news and score it per stock.
- **Inputs:** RSS feeds (MoneyControl, ET, Livemint, BSE filings).
- **Output:** A table of stocks with news events and sentiment/magnitude scores.
- **Tools:** feedparser, requests, BeautifulSoup, OpenAI/Claude API (for LLM scoring) or rule-based NLP.
- **Complexity:** High. News parsing is messy. LLM scoring needs prompt engineering.
- **Risks:** RSS feeds changing format, LLM hallucinating scores, API costs.
- **Validation:** Manually review 50 news scores. Accuracy should be >75%.
- **Alternative (no LLM):** Keyword-based scoring using dictionaries of positive/negative financial terms. Lower quality but zero cost.

### Phase 4: Technical Signal Engine

- **Objective:** Calculate all technical indicators and produce a technical score per stock.
- **Inputs:** OHLCV data from Phase 2.
- **Output:** Technical score (0–100) for each stock in the universe.
- **Tools:** pandas, pandas-ta or TA-Lib, numpy.
- **Complexity:** Medium. Well-defined calculations, but need to handle edge cases (new listings, missing data).
- **Risks:** Garbage-in-garbage-out if data pipeline has errors.
- **Validation:** Spot-check 10 stocks' indicators against TradingView or ChartInk.

### Phase 5: Fundamental Filter

- **Objective:** Score stocks on fundamental quality and apply hard disqualifiers.
- **Inputs:** Quarterly financial data (scraped or API).
- **Output:** Fundamental score (0–100) and a pass/fail flag per stock.
- **Tools:** requests, BeautifulSoup (for Screener.in), pandas.
- **Complexity:** Medium. Screener.in scraping needs careful handling.
- **Risks:** Screener.in blocking scraping, data lag (quarterly updates).
- **Validation:** Compare 20 stocks' fundamental scores against manual Screener.in lookup.

### Phase 6: Trade Ranking and Recommendation Logic

- **Objective:** Combine all scores into a composite rank and select top 2–3 stocks.
- **Inputs:** News, technical, fundamental, and market scores.
- **Output:** Ranked list of candidates with composite scores.
- **Tools:** Python (pandas, custom logic).
- **Complexity:** High. This is the core "brain" of the system. Weight calibration is iterative.
- **Risks:** Overfitting weights, not enough candidates on most days.
- **Validation:** Paper trade for 30 days. Track whether top-ranked stocks outperform bottom-ranked.

### Phase 7: Risk and Position Sizing Module

- **Objective:** Calculate position size, stop-loss, target, and risk exposure for each recommendation.
- **Inputs:** Entry price, stop-loss price, ATR, capital, existing positions.
- **Output:** Quantity, risk amount, reward amount, R:R ratio.
- **Tools:** Python.
- **Complexity:** Low-Medium. Formulaic, but edge cases matter (e.g., stock price near capital limit).
- **Risks:** Rounding errors, not accounting for brokerage/taxes.
- **Validation:** Manually verify 10 position-sizing calculations.

### Phase 8: Dashboard / Web Interface

- **Objective:** Build the Streamlit dashboard with all pages described in Section 9.
- **Inputs:** All module outputs.
- **Output:** Interactive web app accessible at localhost.
- **Tools:** Streamlit, plotly, pandas.
- **Complexity:** Medium. UI work, not algorithmic complexity.
- **Risks:** Streamlit performance with large datasets.
- **Validation:** User testing — is the morning brief readable in under 5 minutes?

### Phase 9: Daily Automation

- **Objective:** Schedule the entire pipeline to run before 7:45 AM IST.
- **Inputs:** All modules.
- **Output:** Automated daily report generation.
- **Tools:** cron (Linux/Mac), Task Scheduler (Windows), or APScheduler (Python).
- **Complexity:** Low.
- **Risks:** Failures not being noticed. Need alerting (email/Telegram on failure).
- **Validation:** Run for 5 consecutive trading days and verify output.

### Phase 10: Backtesting and Performance Tracking

- **Objective:** Build backtesting for technical signals and a performance dashboard for live tracking.
- **Inputs:** Historical data, trade journal entries.
- **Output:** Backtest reports, equity curve, performance metrics.
- **Tools:** Python, pandas, plotly.
- **Complexity:** Medium-High. Backtesting correctly is harder than it looks.
- **Risks:** Survivorship bias, look-ahead bias.
- **Validation:** Compare backtest results with known market benchmarks.

---

## 12. MVP Scope (First Working Version)

The MVP should be deliverable in 2–3 weeks and include:

1. ✅ Data pipeline (OHLCV via yfinance for top 200 liquid NSE stocks)
2. ✅ Basic technical scoring (EMA, RSI, volume spike, breakout detection)
3. ✅ Simple news collection (RSS headlines, keyword-based scoring — no LLM yet)
4. ✅ Hard-coded fundamental filter (use a pre-built list of fundamentally sound stocks)
5. ✅ Market context score (VIX, Nifty trend, FII/DII)
6. ✅ Composite ranking with fixed weights
7. ✅ Risk-based position sizing
8. ✅ Morning report as a formatted text/HTML file
9. ✅ Basic trade journal (CSV-based)
10. ✅ Daily cron job

**NOT in MVP:**
- LLM-based news scoring
- Streamlit dashboard
- Telegram alerts
- Backtesting engine
- Automated bhavcopy parsing
- Real-time price updates

---

## 13. Future Enhancements (Post-MVP)

| Enhancement | Phase | Value |
|---|---|---|
| LLM-powered news analysis | 3+ | Much better catalyst detection |
| Streamlit dashboard | 8 | Better UX than text reports |
| Telegram morning alert | 9 | Mobile-friendly delivery |
| Bhavcopy integration (delivery %) | 2+ | Better volume quality signal |
| Sector rotation model | 6+ | Identify trending sectors |
| Earnings calendar integration | 3+ | Pre-position before results |
| Options data (PCR, OI analysis) | Future | Additional market sentiment |
| Portfolio heat map | 8+ | Visual risk monitoring |
| Machine learning ranking | Future | Data-driven weight optimization |
| Multi-timeframe analysis | 4+ | Weekly + daily confluence |
| Broker API integration | Future | One-click order placement |
| Mobile app | Future | Full mobile experience |

---

## 14. Key Assumptions

1. The user has a Demat + trading account with a discount broker (Zerodha, Groww, etc.).
2. The user can place orders manually between 9:00–9:15 AM IST.
3. The user has a machine (laptop/desktop) that can run Python scripts and a local web server.
4. The user understands that this system does NOT guarantee profits.
5. The user will follow stop-loss discipline and not override the system's risk limits.
6. The user's ₹6 lakh capital is *risk capital* — not money needed for living expenses, EMIs, or emergencies.
7. Free data sources will remain available (NSE bhavcopy, yfinance, RSS feeds).
8. The user is in the 0–30% tax bracket and understands STCG (15%) and brokerage implications.
9. Internet connectivity is reliable at 7:00 AM IST.
10. The user is prepared to paper-trade for at least 1 month before deploying real capital.

---

## 15. Questions Before Coding

I need your answers to these before starting implementation:

**A. Infrastructure**
1. What OS are you on? (Linux/Mac/Windows) — affects scheduling approach.
2. Are you comfortable running Python scripts from the terminal, or do you need everything in a GUI?
3. Do you have Python 3.9+ installed?

**B. Data and Accounts**
4. Do you have a Zerodha account (or another broker with API access)? If so, are you willing to pay for Kite Connect API (₹2,000/month)?
5. Do you have an OpenAI or Anthropic API key for LLM-based news scoring? Or should we start with keyword-based scoring only?
6. Are you willing to use a Google Sheet as a temporary trade journal, or do you want it built into the system from day one?

**C. Trading Preferences**
7. Do you want to trade only on the long side (buy), or also short-sell?
8. Are there sectors you want to exclude entirely (e.g., PSU banks, real estate)?
9. Are there specific stocks you always want in the watchlist?
10. What broker do you use? (For accurate brokerage/tax calculations in position sizing)

**D. Risk Tolerance (Verify)**
11. Is ₹6,00,000 your total investable capital, or do you have more? (This affects whether 2% risk per trade is appropriate or too aggressive.)
12. Can you afford to lose 30% of this capital (₹1,80,000) in a bad month without financial stress?
13. Have you traded short-term before? If so, what was your experience?

**E. Delivery Preferences**
14. Do you want the morning report as: (a) text file, (b) HTML email, (c) Telegram message, (d) Streamlit dashboard, or (e) all of the above?
15. What time do you typically wake up? (To calibrate the automation schedule)

**F. Scope and Pace**
16. Do you want the MVP as fast as possible (text report only, minimal UI), or are you willing to wait longer for the full dashboard?
17. Are you okay starting with paper trading for the first month?

---

## 16. Clear Next Steps

1. **You review this blueprint.** Challenge anything you disagree with. Ask questions.
2. **You answer the questions in Section 15.**
3. **I refine the plan** based on your feedback.
4. **You give final approval** to start coding.
5. **I build Phase 2 (Data Pipeline) first** — the foundation everything else depends on.
6. **We iterate phase by phase**, with you testing each module before I build the next.

---

## Appendix A: Sample Daily Output

```
═══════════════════════════════════════════════════════════════
  NSE TRADING SYSTEM — DAILY BRIEF
  Date: Monday, 14 April 2025
═══════════════════════════════════════════════════════════════

MARKET HEALTH: 🟢 FAVORABLE (Score: 72/100)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Nifty 50:     22,850 (+0.6%)  Above 20 EMA ✅
  Bank Nifty:   48,200 (+0.4%)  Above 20 EMA ✅
  India VIX:    14.2            Low volatility ✅
  GIFT Nifty:   22,910 (+0.3%)  Positive cue ✅
  FII (3-day):  +₹2,400 Cr     Net buyers ✅
  DII (3-day):  +₹1,100 Cr     Net buyers ✅
  S&P 500:      5,320 (+0.8%)   Green close ✅
  Crude (Brent): $82.40         Stable ✅
  USD/INR:      83.25           Stable ✅

  VERDICT: Conditions support trading today.

═══════════════════════════════════════════════════════════════
  RECOMMENDATION #1 OF 2
═══════════════════════════════════════════════════════════════

  Symbol:              PERSISTENT
  Direction:           BUY
  Composite Score:     78/100

  Entry Range:         ₹5,200 – ₹5,250
  Target Price:        ₹5,450
  Stop Loss:           ₹5,100
  Quantity:            80 shares
  Position Value:      ₹4,18,000

  Risk Amount:         ₹8,000  (1.3% of capital)
  Reward Amount:       ₹16,000
  Risk-Reward Ratio:   1 : 2.0
  Expected Holding:    2–3 trading days
  Confidence:          HIGH

  ─── WHY THIS TRADE ───
  Catalyst: Q4 results announced Friday. Revenue +18% YoY,
  PAT +22% YoY, operating margin expanded 150bps. Management
  guided for 15-18% revenue growth in FY26. Deal pipeline
  robust. This is a genuine positive surprise.

  Technical: Stock broke above ₹5,180 resistance on 2.3x
  average volume. RSI at 62 (healthy). 20 EMA > 50 EMA.
  Relative strength vs Nifty: positive 8 of last 10 days.

  Fundamentals: ROE 28%, D/E 0.1, promoter holding 31%
  (founder-led), FII holding 28%. No red flags.

  ─── KEY RISKS ───
  • IT sector selloff if US recession fears intensify.
  • Post-results gap-up may exhaust near-term upside.
  • If ₹5,100 breaks, next support is ₹4,950 (wider loss).

  ─── EXIT RULES ───
  • Target hit: Exit 100% at ₹5,450.
  • Stop loss hit: Exit 100% at ₹5,100. No exceptions.
  • Time exit: If neither target nor SL hit in 3 days, exit
    at market on Day 4 open.
  • Partial exit: If ₹5,350 reached, move SL to ₹5,220
    (breakeven).

═══════════════════════════════════════════════════════════════
  STOCKS CONSIDERED BUT REJECTED
═══════════════════════════════════════════════════════════════

  TATAELXSI  — Score: 58. Strong results but R:R only 1:1.4
               after gap-up. Rejected: R:R below minimum.
  HCLTECH    — Score: 62. Good setup but earnings next week.
               Rejected: Event risk too high.
  IRFC       — Score: 44. Volume spike but no catalyst found.
               Likely operator-driven. Rejected: No news basis.
  ADANIPORTS — Score: 51. Technicals good but promoter pledge
               at 17%. Rejected: Fundamental concern.

═══════════════════════════════════════════════════════════════
  RISK EXPOSURE SUMMARY
═══════════════════════════════════════════════════════════════

  If all 2 trades are taken:
    Capital deployed:   ₹5,12,000 / ₹6,00,000 (85%)
    Total risk:         ₹15,000 / ₹24,000 daily limit (63%)
    Cash remaining:     ₹88,000

  Open positions from previous days:
    None.

═══════════════════════════════════════════════════════════════
  REMINDERS
═══════════════════════════════════════════════════════════════
  • Place stop-loss orders immediately after entry.
  • Do not average down on losing positions.
  • This is a decision-support tool. You make the final call.
  • If you feel emotional or uncertain, skip today.
═══════════════════════════════════════════════════════════════
```

---

## Appendix B: Trade Journal Structure

Each trade logged with these fields:

| Field | Example |
|---|---|
| Trade ID | T-2025-0042 |
| Date (entry) | 2025-04-14 |
| Date (exit) | 2025-04-16 |
| Symbol | PERSISTENT |
| Direction | Long |
| Entry price | ₹5,220 |
| Exit price | ₹5,430 |
| Quantity | 80 |
| Gross P&L | +₹16,800 |
| Brokerage + taxes | ₹180 |
| Net P&L | +₹16,620 |
| Risk amount (planned) | ₹8,000 |
| R-multiple achieved | 2.08R |
| Composite score at entry | 78 |
| Exit reason | Target hit |
| Holding days | 2 |
| Emotional state | Calm |
| What went right | Catalyst was fresh, volume confirmed |
| What went wrong | Could have held for bigger move |
| Lesson | Stick to plan. A 2R win is excellent. |

---

## Appendix C: Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    SCHEDULER (cron)                       │
│                  Runs daily at 6:30 AM IST               │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│               DATA INGESTION LAYER                       │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ yfinance │ │   NSE    │ │   RSS    │ │  Macro   │   │
│  │  OHLCV   │ │ Bhavcopy │ │  News    │ │  Data    │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │
│       │            │            │             │          │
│       ▼            ▼            ▼             ▼          │
│  ┌──────────────────────────────────────────────────┐    │
│  │              SQLite Database                      │    │
│  │  Tables: prices, fundamentals, news, macro,      │    │
│  │          trades, journal, system_log              │    │
│  └──────────────────────┬───────────────────────────┘    │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│                ANALYSIS ENGINE                           │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  Technical   │  │    News      │  │ Fundamental  │   │
│  │   Scorer     │  │   Scorer     │  │   Filter     │   │
│  │  (0-100)     │  │  (0-100)     │  │  (0-100)     │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                  │           │
│         ▼                 ▼                  ▼           │
│  ┌──────────────────────────────────────────────────┐    │
│  │         Market Context Scorer (0-100)             │    │
│  └──────────────────────┬───────────────────────────┘    │
│                         │                                │
│                         ▼                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │         COMPOSITE RANKER                          │    │
│  │   News×0.30 + Tech×0.35 + Fund×0.15 + Mkt×0.20  │    │
│  └──────────────────────┬───────────────────────────┘    │
└─────────────────────────┼───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│           RISK & POSITION SIZING MODULE                   │
│                                                          │
│  • ATR-based stop-loss calculation                       │
│  • Risk-per-trade check (max 2% of capital)             │
│  • Capital-per-trade check (max 33% of capital)         │
│  • Daily risk limit check                                │
│  • R:R ratio filter (min 1:2)                           │
│  • Liquidity check                                       │
└────────────────────────┬────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│              OUTPUT LAYER                                │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Morning  │ │ Streamlit│ │ Telegram │ │  Trade   │   │
│  │ Report   │ │ Dashboard│ │   Bot    │ │ Journal  │   │
│  │ (HTML)   │ │ (Web UI) │ │ (Alert)  │ │ (SQLite) │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Appendix D: Realistic Expectations

| Scenario | Annual Return | Monthly Avg | Win Rate | Avg R:R | Likelihood |
|---|---|---|---|---|---|
| Exceptional | +80% to +120% | +5-8% | >55% | >1:2.5 | ~5-10% |
| Good | +40% to +80% | +3-5% | 48-55% | 1:2.0 | ~20-25% |
| Decent | +15% to +40% | +1-3% | 42-48% | 1:1.8 | ~30-35% |
| Breakeven | -5% to +15% | ~0-1% | 38-42% | 1:1.5 | ~20-25% |
| Loss | -5% to -25% | Negative | <38% | <1:1.5 | ~15-20% |

The "Good" scenario is what a well-built system with disciplined execution can realistically target. The "Exceptional" scenario requires both a good system AND a favorable market regime.

**The system will track which scenario it is operating in and alert the user if performance trends toward the "Loss" zone for 30+ days.**

---

*End of Blueprint v1.0*
*Ready for review. No code has been written.*
