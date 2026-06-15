"""
Recommendation Engine
Combines news, technical, fundamental, and market scores into final
LONG and SHORT recommendations with full detailed reasoning.
Weights are adjusted dynamically by the feedback engine.
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    WEIGHT_NEWS, WEIGHT_TECHNICAL, WEIGHT_FUNDAMENTAL, WEIGHT_MARKET,
    MIN_COMPOSITE_SCORE, MAX_RECOMMENDATIONS, MIN_RISK_REWARD_RATIO,
    TOTAL_CAPITAL, MAX_HOLDING_DAYS, DEFAULT_HOLDING_DAYS, ATR_SL_MULTIPLIER,
    RSI_OVERBOUGHT, RSI_EXTREME_OB, OVEREXTENDED_THRESHOLD,
)
from modules.database import get_connection, log_system_event
from modules.technical_engine import score_technical
from modules.news_engine import aggregate_stock_news_score
from modules.fundamental_filter import score_fundamental, get_stock_sector
from modules.market_context import score_market_context
from modules.risk_manager import calculate_position_size, check_portfolio_risk, calculate_brokerage
from modules.data_fetcher import get_price_dataframe, get_recent_bulk_deals

# Short-trade minimum threshold (lower than long — fewer requirements)
MIN_SHORT_SCORE = 55
MAX_SHORT_RECOMMENDATIONS = 3

# Default futures lot size when unknown (user should verify on NSE)
DEFAULT_LOT_SIZE = 500
# Approximate margin for stock futures (20% of notional)
FUTURES_MARGIN_RATIO = 0.20


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def generate_recommendations(price_data: dict,
                              nifty_df=None,
                              banknifty_df=None,
                              macro_data: dict = None,
                              current_capital: float = None,
                              bulk_deals: list = None) -> dict:
    """
    Run the full recommendation pipeline (LONG + SHORT).
    Returns a dict consumed by app.py.
    """
    if current_capital is None:
        current_capital = TOTAL_CAPITAL
    if bulk_deals is None:
        bulk_deals = []
    today = datetime.now().strftime('%Y-%m-%d')

    # ── 1. Market context ─────────────────────────────────────────────────
    market_result = score_market_context(nifty_df, banknifty_df, macro_data)
    market_score  = market_result['score']

    if market_result['verdict'] == 'NO_TRADE':
        return {
            'date': today, 'market': market_result,
            'recommendations': [], 'short_recommendations': [],
            'rejected': [], 'message': market_result['verdict_text'],
            'can_trade': False,
            'risk_check': check_portfolio_risk(current_capital),
        }

    # ── 2. Portfolio risk gate ────────────────────────────────────────────
    risk_check = check_portfolio_risk(current_capital)
    if not risk_check['can_trade']:
        return {
            'date': today, 'market': market_result,
            'recommendations': [], 'short_recommendations': [],
            'rejected': [], 'message': ' | '.join(risk_check['blocked_reasons']),
            'can_trade': False, 'risk_check': risk_check,
        }

    # ── 3. Feedback-adjusted weights ──────────────────────────────────────
    weights = _get_weights()

    # ── 4. Build bulk-deal lookup for bonus signals ───────────────────────
    bulk_buy_symbols  = {d['symbol'] for d in bulk_deals if 'BUY'  in d.get('buy_sell', '')}
    bulk_sell_symbols = {d['symbol'] for d in bulk_deals if 'SELL' in d.get('buy_sell', '')}

    # ── 5. Score every stock ──────────────────────────────────────────────
    long_candidates  = []
    short_candidates = []
    short_rejected   = []
    rejected         = []

    for symbol, df in price_data.items():
        try:
            tech_result = score_technical(df, nifty_df)

            # ── LONG scoring ──────────────────────────────────────────────
            if tech_result.get('disqualified'):
                rejected.append({
                    'symbol':     symbol,
                    'reason':     f"Technical: {tech_result.get('reason', 'disqualified')}",
                    'score':      0,
                    'sub_scores': {'news': 0, 'technical': 0, 'fundamental': 0, 'market': round(market_score, 1)},
                    'why_wait':   _build_long_why_wait(None, tech_result, None, market_score, 0),
                })
            else:
                fund_result = score_fundamental(symbol)
                if fund_result.get('disqualified'):
                    rejected.append({
                        'symbol':     symbol,
                        'reason':     f"Fundamental: {fund_result.get('reason', 'disqualified')}",
                        'score':      tech_result['score'],
                        'sub_scores': {'news': 0, 'technical': tech_result['score'], 'fundamental': 0, 'market': round(market_score, 1)},
                        'why_wait':   _build_long_why_wait(None, tech_result, fund_result, market_score, 0),
                    })
                else:
                    news_result = aggregate_stock_news_score(symbol)

                    # Bulk-deal bonus: +5 if large buyers active
                    bulk_bonus = 5 if symbol in bulk_buy_symbols else 0

                    composite = (
                        weights['news']        * news_result['score'] +
                        weights['technical']   * tech_result['score'] +
                        weights['fundamental'] * fund_result['score'] +
                        weights['market']      * market_score +
                        bulk_bonus
                    )

                    levels   = tech_result.get('levels', {})
                    rr_ratio = levels.get('risk_reward_ratio', 0)

                    sub_scores = {
                        'news':        round(news_result['score'], 1),
                        'technical':   round(tech_result['score'], 1),
                        'fundamental': round(fund_result['score'], 1),
                        'market':      round(market_score, 1),
                    }

                    if composite < MIN_COMPOSITE_SCORE:
                        rejected.append({
                            'symbol':     symbol,
                            'reason':     f"Composite {composite:.0f} < minimum {MIN_COMPOSITE_SCORE}",
                            'score':      round(composite, 1),
                            'sub_scores': sub_scores,
                            'why_wait':   _build_long_why_wait(news_result, tech_result, fund_result, market_score, composite),
                        })
                    elif rr_ratio < MIN_RISK_REWARD_RATIO:
                        rejected.append({
                            'symbol':     symbol,
                            'reason':     f"R:R {rr_ratio:.1f} < minimum {MIN_RISK_REWARD_RATIO}",
                            'score':      round(composite, 1),
                            'sub_scores': sub_scores,
                            'why_wait':   [
                                f"Risk/reward ratio is only {rr_ratio:.1f}:1 — need at least {MIN_RISK_REWARD_RATIO}:1 to justify entry",
                                "The stop-loss level is too close to a potential target — wider room needed",
                                "Wait for a pullback to a stronger support level to improve the entry price",
                            ],
                        })
                    else:
                        long_candidates.append({
                            'symbol':           symbol,
                            'composite_score':  round(composite, 1),
                            'news_score':       round(news_result['score'], 1),
                            'technical_score':  tech_result['score'],
                            'fundamental_score':fund_result['score'],
                            'market_score':     market_score,
                            'bulk_bonus':       bulk_bonus,
                            'tech_result':      tech_result,
                            'fund_result':      fund_result,
                            'news_result':      news_result,
                            'sector':           get_stock_sector(symbol),
                        })

            # ── SHORT scoring ─────────────────────────────────────────────
            short_result = _score_short(df, nifty_df, symbol)
            if short_result['score'] >= MIN_SHORT_SCORE:
                news_result_s = aggregate_stock_news_score(symbol)
                # Negative news amplifies short conviction
                neg_bonus = 10 if news_result_s.get('sentiment') == 'NEGATIVE' else 0
                # Bulk sellers amplify short conviction
                sell_bonus = 5 if symbol in bulk_sell_symbols else 0
                short_result['final_score'] = round(
                    short_result['score'] + neg_bonus + sell_bonus, 1
                )
                short_result['news_result'] = news_result_s
                short_candidates.append({
                    'symbol':     symbol,
                    'short_score':short_result['final_score'],
                    'short_data': short_result,
                    'sector':     get_stock_sector(symbol),
                })
            elif short_result['score'] >= 15:
                # Track stocks that show partial bearish signals but not enough to short
                short_rejected.append({
                    'symbol':      symbol,
                    'short_score': short_result['score'],
                    'breakdown':   short_result.get('breakdown', {}),
                    'signals':     short_result.get('signals', []),
                    'missing':     _build_short_missing(short_result),
                })

        except Exception as e:
            log_system_event("recommender", "ERROR", f"Error scoring {symbol}: {e}")

    # ── 6. Select top LONG recommendations ───────────────────────────────
    long_candidates.sort(key=lambda x: x['composite_score'], reverse=True)
    recommendations = _select_with_sector_diversity(
        long_candidates, MAX_RECOMMENDATIONS, rejected
    )
    recommendations = _attach_position_sizing(
        recommendations, current_capital, risk_check, nifty_df, bulk_deals
    )

    # ── 7. Select top SHORT recommendations ──────────────────────────────
    short_candidates.sort(key=lambda x: x['short_score'], reverse=True)
    short_recommendations = _build_short_recs(
        short_candidates[:MAX_SHORT_RECOMMENDATIONS], current_capital, bulk_deals
    )

    # ── 8. Persist ───────────────────────────────────────────────────────
    rejected.sort(key=lambda x: x.get('score', 0), reverse=True)
    _store_recommendations(recommendations, today)
    _store_rejected(rejected[:10], today)
    _store_short_recommendations(short_recommendations, today)

    short_rejected.sort(key=lambda x: x['short_score'], reverse=True)

    return {
        'date':                 today,
        'market':               market_result,
        'recommendations':      recommendations,
        'short_recommendations':short_recommendations,
        'rejected':             rejected[:12],
        'short_rejected':       short_rejected[:10],
        'message':              f"Found {len(recommendations)} LONG and "
                                f"{len(short_recommendations)} SHORT recommendations "
                                f"from {len(price_data)} stocks scanned",
        'can_trade':            True,
        'risk_check':           risk_check,
        'total_scanned':        len(price_data),
        'weights':              weights,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REJECTION EXPLANATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _build_long_why_wait(news_result, tech_result, fund_result, market_score, composite) -> list:
    """
    Generate 3-5 specific human-readable reasons why a stock isn't a buy yet.
    Returns a list of strings ordered from most important to least.
    """
    reasons = []

    # Technical disqualifiers
    if tech_result and tech_result.get('disqualified'):
        t_reason = tech_result.get('reason', '')
        if 'downtrend' in t_reason.lower():
            reasons.append("Stock is in a confirmed downtrend — price below both 50 and 200 EMA")
        elif 'death cross' in t_reason.lower():
            reasons.append("Death cross pattern: 50 EMA crossed below 200 EMA — bearish structural signal")
        elif 'below' in t_reason.lower():
            reasons.append(f"Technical structure broken: {t_reason}")
        else:
            reasons.append(f"Technical filter failed: {t_reason}")
        reasons.append("Wait for price to reclaim the 50-day EMA and hold for 2+ days before considering entry")
        return reasons[:4]

    # Fundamental disqualifiers
    if fund_result and fund_result.get('disqualified'):
        f_reason = fund_result.get('reason', '')
        reasons.append(f"Hard fundamental barrier: {f_reason}")
        if 'debt' in f_reason.lower():
            reasons.append("High debt levels increase risk — company must deleverage before this becomes a buy")
        elif 'pledge' in f_reason.lower():
            reasons.append("Promoter pledge signals financial stress at the management level")
        return reasons[:3]

    # Sub-score analysis
    n_score = news_result.get('score', 50) if news_result else 50
    t_score = tech_result.get('score', 0)  if tech_result else 0
    f_score = fund_result.get('score', 0)  if fund_result else 0

    scores = [
        ('News/Catalyst',  n_score, 60),
        ('Technical',      t_score, 60),
        ('Fundamental',    f_score, 50),
        ('Market Context', market_score, 55),
    ]

    # Report the weakest scores first
    scores.sort(key=lambda x: x[1])
    for label, val, threshold in scores[:3]:
        if val < threshold:
            if label == 'News/Catalyst':
                reasons.append(f"No strong news catalyst (score {val:.0f}/100) — need a trigger event to move the stock")
            elif label == 'Technical':
                reasons.append(f"Technical momentum weak (score {val:.0f}/100) — no confirmed breakout or trend signal yet")
            elif label == 'Fundamental':
                reasons.append(f"Fundamental quality below threshold (score {val:.0f}/100) — ROE, growth, or margins need to improve")
            elif label == 'Market Context':
                reasons.append(f"Broad market unfavourable (score {val:.0f}/100) — avoid new longs in risk-off environment")

    # Technical-specific hints
    if tech_result and not tech_result.get('disqualified'):
        t_reasons = tech_result.get('reasons', [])
        for r in t_reasons[:2]:
            if r not in reasons:
                reasons.append(r)

    if composite > 0:
        gap = MIN_COMPOSITE_SCORE - composite
        reasons.append(f"Composite score {composite:.0f} is {gap:.0f} points below the entry threshold of {MIN_COMPOSITE_SCORE}")

    return reasons[:5]


def _build_short_missing(short_result: dict) -> list:
    """
    For a stock that scored partially on short signals, describe what's missing
    to trigger a short recommendation.
    """
    missing = []
    bd = short_result.get('breakdown', {})
    score = short_result.get('score', 0)
    gap = MIN_SHORT_SCORE - score

    if bd.get('rsi', 0) == 0:
        missing.append(f"RSI is not overbought yet — needs to be above 70 (preferably 80) to signal exhaustion")
    if bd.get('ema_extension', 0) == 0:
        missing.append("Price is not overextended above 20 EMA — no mean-reversion setup visible")
    if bd.get('macd', 0) == 0:
        missing.append("MACD still showing bullish momentum — bearish crossover not confirmed")
    if bd.get('vol_spike_down', 0) == 0:
        missing.append("No distribution volume (high-volume down day) to confirm selling pressure")
    if bd.get('failed_breakout', 0) == 0:
        missing.append("No failed breakout pattern — stock has not rejected a key resistance level")

    missing.append(f"Short score is {score}/100 — needs {MIN_SHORT_SCORE} to qualify ({gap} more points needed)")
    return missing[:4]


# ═══════════════════════════════════════════════════════════════════════════════
# SHORT SCORING
# ═══════════════════════════════════════════════════════════════════════════════

def _score_short(df, nifty_df, symbol: str) -> dict:
    """
    Score a stock for SHORT (futures) potential.
    Returns dict with score 0-100 and breakdown.
    """
    if df is None or len(df) < 30:
        return {'score': 0, 'disqualified': True, 'reason': 'Insufficient data'}

    try:
        from modules.technical_engine import compute_ema, compute_rsi, compute_macd, compute_atr
        close  = df['close']
        volume = df['volume']

        score      = 0
        breakdown  = {}
        signals    = []

        latest_price = float(close.iloc[-1])

        # ── 1. RSI overbought (30 pts) ─────────────────────────────────
        rsi = compute_rsi(close, 14)
        if not rsi.empty:
            rsi_val = float(rsi.iloc[-1])
            if rsi_val >= RSI_EXTREME_OB:        # > 80
                score += 30; breakdown['rsi'] = 30
                signals.append(f"RSI extremely overbought: {rsi_val:.0f}")
            elif rsi_val >= RSI_OVERBOUGHT:      # > 70
                score += 18; breakdown['rsi'] = 18
                signals.append(f"RSI overbought: {rsi_val:.0f}")
            else:
                breakdown['rsi'] = 0
        else:
            rsi_val = 50
            breakdown['rsi'] = 0

        # ── 2. Price above 20 EMA (overextended) (25 pts) ─────────────
        ema20 = compute_ema(close, 20)
        ema50 = compute_ema(close, 50)
        if not ema20.empty:
            ema20_val = float(ema20.iloc[-1])
            ema50_val = float(ema50.iloc[-1]) if not ema50.empty else ema20_val
            dist_pct  = (latest_price - ema20_val) / ema20_val * 100

            if dist_pct > 15:
                score += 25; breakdown['ema_extension'] = 25
                signals.append(f"Price {dist_pct:.0f}% above 20 EMA — severely overextended")
            elif dist_pct > 8:
                score += 15; breakdown['ema_extension'] = 15
                signals.append(f"Price {dist_pct:.0f}% above 20 EMA — overextended")
            elif dist_pct > 0 and ema20_val < ema50_val:
                # Bearish EMA alignment even if not overextended
                score += 8; breakdown['ema_extension'] = 8
                signals.append("20 EMA below 50 EMA — bearish alignment")
            else:
                breakdown['ema_extension'] = 0
        else:
            ema20_val = latest_price
            dist_pct  = 0

        # ── 3. MACD bearish (20 pts) ───────────────────────────────────
        macd_line, macd_signal, macd_hist = compute_macd(close)
        if macd_line is not None and not macd_line.empty and len(macd_hist) >= 2:
            h_now  = float(macd_hist.iloc[-1])
            h_prev = float(macd_hist.iloc[-2])
            if h_now < 0 and h_prev >= 0:
                score += 20; breakdown['macd'] = 20
                signals.append("MACD histogram just crossed below zero — bearish crossover")
            elif h_now < h_prev < 0:
                score += 12; breakdown['macd'] = 12
                signals.append("MACD histogram declining in negative zone — momentum weak")
            elif h_now < 0:
                score += 6; breakdown['macd'] = 6
                signals.append("MACD below signal line — bearish")
            else:
                breakdown['macd'] = 0
        else:
            breakdown['macd'] = 0

        # ── 4. Volume spike on down day (15 pts) ──────────────────────
        if len(df) >= 21:
            avg_vol   = float(volume.iloc[-21:-1].mean())
            last_vol  = float(volume.iloc[-1])
            last_ret  = float(close.iloc[-1] / close.iloc[-2] - 1) * 100
            vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1

            if vol_ratio >= 1.5 and last_ret < -0.5:
                score += 15; breakdown['vol_spike_down'] = 15
                signals.append(f"Volume {vol_ratio:.1f}x on down day ({last_ret:.1f}%) — distribution")
            elif last_ret < -1.0:
                score += 7; breakdown['vol_spike_down'] = 7
                signals.append(f"Significant down day: {last_ret:.1f}%")
            else:
                breakdown['vol_spike_down'] = 0
        else:
            breakdown['vol_spike_down'] = 0

        # ── 5. Failed breakout (10 pts) ───────────────────────────────
        if len(close) >= 21:
            recent_high = float(close.iloc[-21:-1].max())
            if float(close.iloc[-5]) >= recent_high * 0.98 and latest_price < recent_high * 0.97:
                score += 10; breakdown['failed_breakout'] = 10
                signals.append(f"Failed breakout at ₹{recent_high:,.0f} — reversal signal")
            else:
                breakdown['failed_breakout'] = 0
        else:
            breakdown['failed_breakout'] = 0

        # ── ATR for SL/Target ─────────────────────────────────────────
        atr = compute_atr(df, 14)
        atr_val = float(atr.iloc[-1]) if atr is not None and not atr.empty else latest_price * 0.02

        # Short entry = current price
        entry     = latest_price
        sl        = round(entry + ATR_SL_MULTIPLIER * atr_val, 2)
        target    = round(entry - 2.0 * ATR_SL_MULTIPLIER * atr_val, 2)
        risk_pt   = sl - entry
        reward_pt = entry - target
        rr        = round(reward_pt / risk_pt, 2) if risk_pt > 0 else 0

        return {
            'score':       min(score, 100),
            'breakdown':   breakdown,
            'signals':     signals,
            'entry':       round(entry, 2),
            'stop_loss':   sl,
            'target':      target,
            'rsi':         rsi_val,
            'ema20_val':   round(ema20_val, 2),
            'dist_pct':    round(dist_pct, 1),
            'atr':         round(atr_val, 2),
            'risk_reward': rr,
        }

    except Exception as e:
        return {'score': 0, 'disqualified': True, 'reason': str(e)}


def _build_short_recs(candidates: list, capital: float, bulk_deals: list) -> list:
    """Convert short candidates into full recommendation dicts."""
    recs = []
    bulk_sellers = {d['symbol']: d for d in bulk_deals if 'SELL' in d.get('buy_sell', '')}

    for c in candidates:
        sd     = c['short_data']
        symbol = c['symbol']

        if sd.get('disqualified') or sd.get('risk_reward', 0) < MIN_RISK_REWARD_RATIO:
            continue

        entry   = sd['entry']
        sl      = sd['stop_loss']
        target  = sd['target']
        risk_pt = sl - entry

        # Position sizing based on 2% risk rule
        risk_amount = capital * 0.02
        qty_by_risk = int(risk_amount / risk_pt) if risk_pt > 0 else 0

        # Lot-size cap (futures are traded in lots) — use real NSE lot size if known
        try:
            from modules.data_fetcher import get_lot_size
            lot_size = get_lot_size(symbol, DEFAULT_LOT_SIZE)
        except Exception:
            lot_size = DEFAULT_LOT_SIZE
        qty      = max(lot_size, round(qty_by_risk / lot_size) * lot_size)
        notional = qty * entry
        margin   = round(notional * FUTURES_MARGIN_RATIO, 2)

        # Cap by capital
        if margin > capital * 0.33:
            qty      = int((capital * 0.33) / (entry * FUTURES_MARGIN_RATIO) / lot_size) * lot_size
            notional = qty * entry
            margin   = round(notional * FUTURES_MARGIN_RATIO, 2)

        if qty <= 0:
            continue

        actual_risk   = round(qty * risk_pt, 2)
        actual_reward = round(qty * (entry - target), 2)

        # Bearish catalyst text
        news_r   = sd.get('news_result', {})
        catalyst = "No specific negative catalyst" if news_r.get('sentiment') != 'NEGATIVE' \
                   else (news_r.get('headlines', [{}])[0].get('headline', '') if news_r.get('headlines') else '')

        bulk_ctx = ""
        if symbol in bulk_sellers:
            bd = bulk_sellers[symbol]
            bulk_ctx = (f" BULK DEAL ALERT: {bd['client_name']} sold "
                        f"{bd['quantity']:,} shares at ₹{bd['price']:,.0f} "
                        f"(₹{bd['value_cr']:.1f} Cr).")

        signals_text = " | ".join(sd.get('signals', []))
        confidence   = 'HIGH' if sd['score'] >= 75 else ('MEDIUM' if sd['score'] >= 60 else 'LOW')

        reasoning = (
            f"{symbol} shows {len(sd.get('signals', []))} bearish signals: {signals_text}."
            f"{bulk_ctx} "
            f"RSI at {sd.get('rsi', 0):.0f}, price {sd.get('dist_pct', 0):.0f}% "
            f"above 20 EMA. Short score: {sd['score']}/100."
        )

        exit_rules = (
            f"Cover (buy back) at ₹{target:,.0f} (target). "
            f"Stop loss: ₹{sl:,.0f} (exit immediately if breached). "
            f"Partial cover: at 50% of target, move SL to breakeven. "
            f"Time exit: Close on Day 3 if neither target nor SL hit."
        )

        key_risks = (
            f"Short squeezes can be violent — always use tight stops. "
            f"Any positive news/results announcement invalidates the setup. "
            f"Futures carry overnight margin risk."
        )

        recs.append({
            'symbol':           symbol,
            'direction':        'SHORT (Futures)',
            'entry_low':        round(entry * 0.997, 2),
            'entry_high':       round(entry * 1.003, 2),
            'target_price':     target,
            'stop_loss':        sl,
            'lot_size':         lot_size,
            'quantity':         qty,
            'notional_value':   round(notional, 2),
            'margin_required':  margin,
            'risk_amount':      actual_risk,
            'reward_amount':    actual_reward,
            'risk_reward_ratio':round(sd['risk_reward'], 1),
            'short_score':      sd['score'],
            'confidence':       confidence,
            'bearish_catalyst': catalyst,
            'technical_weakness':signals_text,
            'reasoning':        reasoning,
            'key_risks':        key_risks,
            'exit_rules':       exit_rules,
            'sector':           c['sector'],
            'rsi':              round(sd.get('rsi', 0), 1),
            'dist_pct':         sd.get('dist_pct', 0),
        })

    return recs


# ═══════════════════════════════════════════════════════════════════════════════
# LONG RECOMMENDATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _select_with_sector_diversity(candidates, max_recs, rejected):
    """Pick top candidates while avoiding 2 from the same sector."""
    selected        = []
    selected_sectors= set()

    for c in candidates:
        if len(selected) >= max_recs:
            break
        sector = c['sector']
        if sector in selected_sectors:
            if len(selected) < max_recs - 1:
                c['composite_score'] -= 3
            else:
                rejected.append({
                    'symbol': c['symbol'],
                    'reason': f"Sector diversification — {sector} already selected",
                    'score':  c['composite_score'],
                })
                continue
        selected.append(c)
        selected_sectors.add(sector)

    return selected


def _attach_position_sizing(candidates, capital, risk_check, nifty_df, bulk_deals):
    """Calculate position sizes and build full recommendation dicts."""
    bulk_buyers = {d['symbol']: d for d in bulk_deals if 'BUY' in d.get('buy_sell', '')}
    recs = []
    total_exposure = risk_check['total_exposure']

    for c in candidates:
        levels     = c['tech_result']['levels']
        entry_price= levels['current_price']
        stop_loss  = levels['stop_loss']
        target     = levels['target']

        sizing = calculate_position_size(
            entry_price=entry_price,
            stop_loss=stop_loss,
            current_capital=capital,
            existing_exposure=total_exposure,
        )
        if not sizing['valid']:
            continue

        total_exposure += sizing['position_value']

        cs         = c['composite_score']
        confidence = 'HIGH' if cs >= 80 else ('MEDIUM-HIGH' if cs >= 72 else 'MEDIUM')
        reasoning  = _build_detailed_reasoning(c, bulk_buyers)

        recs.append({
            'symbol':           c['symbol'],
            'direction':        'BUY',
            'entry_low':        round(entry_price * 0.995, 2),
            'entry_high':       round(entry_price * 1.005, 2),
            'target_price':     round(target, 2),
            'stop_loss':        round(stop_loss, 2),
            'quantity':         sizing['quantity'],
            'position_value':   sizing['position_value'],
            'risk_amount':      sizing['risk_amount'],
            'reward_amount':    round(sizing['quantity'] * (target - entry_price), 2),
            'risk_reward_ratio':round(levels['risk_reward_ratio'], 1),
            'expected_holding': DEFAULT_HOLDING_DAYS,
            'composite_score':  cs,
            'news_score':       c['news_score'],
            'technical_score':  c['technical_score'],
            'fundamental_score':c['fundamental_score'],
            'market_score':     c['market_score'],
            'bulk_bonus':       c.get('bulk_bonus', 0),
            'confidence':       confidence,
            'reasoning':        reasoning['summary'],
            'news_trigger':     reasoning['news_trigger'],
            'technical_setup':  reasoning['technical_setup'],
            'fundamental_brief':reasoning['fundamental_brief'],
            'key_risks':        reasoning['key_risks'],
            'exit_rules':       reasoning['exit_rules'],
            'hidden_signals':   reasoning['hidden_signals'],
            'sector':           c['sector'],
            'indicators':       c['tech_result']['indicators'],
            'fund_data':        c['fund_result'].get('data', {}),
        })

    return recs


# ═══════════════════════════════════════════════════════════════════════════════
# DETAILED REASONING BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _build_detailed_reasoning(candidate: dict, bulk_buyers: dict) -> dict:
    """Build a full, human-readable analysis for a LONG recommendation."""
    symbol     = candidate['symbol']
    tech       = candidate['tech_result']
    fund       = candidate['fund_result']
    news       = candidate['news_result']
    indicators = tech.get('indicators', {})
    fund_data  = fund.get('data', {})
    levels     = tech.get('levels', {})

    entry  = levels.get('current_price', 0)
    sl     = levels.get('stop_loss', 0)
    target = levels.get('target', 0)
    risk   = levels.get('risk', 0)
    rr     = levels.get('risk_reward_ratio', 0)

    cs    = candidate['composite_score']
    ns    = candidate['news_score']
    ts    = candidate['technical_score']
    fs    = candidate['fundamental_score']
    ms    = candidate['market_score']

    # ── News trigger ──────────────────────────────────────────────────────
    if news.get('headlines'):
        top_hl    = news['headlines'][0]
        freshness = _freshness_label(top_hl.get('date', ''))
        news_trigger = (
            f"[{freshness}] {top_hl['headline']} "
            f"(Source: {top_hl.get('source', '')}) — "
            f"Sentiment: {top_hl.get('sentiment', '')} | "
            f"News score: {ns:.0f}/100"
        )
        if len(news['headlines']) > 1:
            news_trigger += (
                f" + {len(news['headlines'])-1} more related headline(s). "
                f"Overall news sentiment: {news.get('sentiment', 'NEUTRAL')}."
            )
    else:
        news_trigger = (
            "No specific news catalyst found. Trade is purely technical. "
            "Lower confidence — size down if uncertain."
        )

    # ── Technical setup ───────────────────────────────────────────────────
    tech_lines = []

    rsi_val = indicators.get('rsi', 0)
    if 40 <= rsi_val <= 65:
        tech_lines.append(f"RSI {rsi_val:.0f} — ideal zone (not overbought, momentum intact)")
    elif rsi_val > 65:
        tech_lines.append(f"RSI {rsi_val:.0f} — elevated; target may be compressed")
    else:
        tech_lines.append(f"RSI {rsi_val:.0f} — recovering from oversold")

    e20 = indicators.get('ema_20', 0)
    e50 = indicators.get('ema_50', 0)
    if e20 > e50 and entry > e20:
        tech_lines.append(f"Price ₹{entry:,.0f} above 20 EMA ₹{e20:,.0f} > 50 EMA ₹{e50:,.0f} — bullish alignment")
    elif entry > e20:
        tech_lines.append(f"Price above 20 EMA (₹{e20:,.0f}) but 20 EMA below 50 EMA (₹{e50:,.0f}) — caution")

    vr = indicators.get('volume_ratio', 0)
    if vr >= 2.0:
        tech_lines.append(f"Exceptional volume spike: {vr:.1f}× average — strong institutional interest")
    elif vr >= 1.5:
        tech_lines.append(f"Volume spike: {vr:.1f}× average — confirms price move")

    if indicators.get('breakout'):
        bl = indicators.get('breakout_level', 0)
        tech_lines.append(f"Breakout above ₹{bl:,.0f} resistance — key level cleared")

    rs = indicators.get('relative_strength', 0)
    if rs > 3:
        tech_lines.append(f"Outperforming Nifty by {rs:.1f}% over 10 days — sector leader")
    elif rs > 0:
        tech_lines.append(f"Modest outperformance vs Nifty (+{rs:.1f}%)")
    else:
        tech_lines.append(f"Underperforming Nifty by {abs(rs):.1f}% — watch for continuation")

    tech_lines.append(f"Technical score: {ts}/100")
    technical_setup = " | ".join(tech_lines)

    # ── Fundamental brief ─────────────────────────────────────────────────
    fund_lines = []
    roe = fund_data.get('roe', 'N/A')
    de  = fund_data.get('debt_equity', 'N/A')
    ph  = fund_data.get('promoter_holding', 'N/A')
    rg  = fund_data.get('revenue_growth', 'N/A')
    pg  = fund_data.get('profit_growth', 'N/A')

    fund_lines.append(f"ROE: {roe}%")
    if isinstance(de, (int, float)):
        label = 'conservative' if de < 0.5 else ('moderate' if de < 1.0 else 'leveraged')
        fund_lines.append(f"D/E: {de:.1f} ({label})")
    else:
        fund_lines.append(f"D/E: {de}")
    fund_lines.append(f"Promoter holding: {ph}% | Revenue growth: {rg}% | Profit growth: {pg}%")
    fund_lines.append(f"Fundamental score: {fs}/100")
    fundamental_brief = " | ".join(fund_lines)

    # ── Hidden signals ────────────────────────────────────────────────────
    hidden = []
    if symbol in bulk_buyers:
        bd = bulk_buyers[symbol]
        hidden.append(
            f"🔵 BULK DEAL: {bd['client_name']} BOUGHT {bd['quantity']:,} shares "
            f"@ ₹{bd['price']:,.0f} (₹{bd['value_cr']:.1f} Cr) — "
            f"strong institutional conviction"
        )
    if candidate.get('bulk_bonus', 0) > 0 and symbol not in bulk_buyers:
        hidden.append("🔵 Institutional buying detected via bulk deal data")
    if ns > 70:
        hidden.append(f"📰 High news momentum (score {ns:.0f}) — catalyst is fresh and significant")
    if vr >= 2.0:
        hidden.append(f"📊 Volume {vr:.1f}× — exceptional institutional footprint today")

    if not hidden:
        hidden.append("No extraordinary hidden signals today — trade driven by standard confluence")

    # ── Composite summary ─────────────────────────────────────────────────
    drivers = []
    if ns >= 65:   drivers.append(f"strong news catalyst ({ns:.0f}/100)")
    if ts >= 65:   drivers.append(f"quality technical setup ({ts}/100)")
    if fs >= 65:   drivers.append(f"solid fundamentals ({fs}/100)")
    if ms >= 65:   drivers.append(f"supportive market ({ms}/100)")

    summary = (
        f"{symbol} earns a composite score of {cs}/100 driven by: "
        f"{', '.join(drivers) if drivers else 'moderate signals across all dimensions'}. "
        f"Entry ₹{entry:,.0f} | Target ₹{target:,.0f} | SL ₹{sl:,.0f} | R:R 1:{rr:.1f}. "
        f"Signal weights used: "
        f"News {candidate.get('weights', {}).get('news', WEIGHT_NEWS)*100:.0f}% / "
        f"Technical {candidate.get('weights', {}).get('technical', WEIGHT_TECHNICAL)*100:.0f}% / "
        f"Fundamental {candidate.get('weights', {}).get('fundamental', WEIGHT_FUNDAMENTAL)*100:.0f}% / "
        f"Market {candidate.get('weights', {}).get('market', WEIGHT_MARKET)*100:.0f}%."
    )

    # ── Key risks ─────────────────────────────────────────────────────────
    risks = []
    if isinstance(de, (int, float)) and de > 0.7:
        risks.append(f"Elevated debt (D/E {de:.1f}) — sensitive to rate changes")
    if rsi_val > 65:
        risks.append(f"RSI {rsi_val:.0f} — overbought risk, may consolidate before moving")
    ext = indicators.get('ema_distance_pct', 0)
    if ext > 8:
        risks.append(f"Stock is {ext:.0f}% above 20 EMA — overextended, pullback risk")
    if not news.get('headlines'):
        risks.append("No news catalyst — pure technical play, higher reversal risk")
    risks.append("Broader market reversal or sector rotation could override stock-specific setup")
    risks.append(f"Time-based exit: close by end of Day {MAX_HOLDING_DAYS} regardless of P&L")

    # ── Exit rules ────────────────────────────────────────────────────────
    partial_target = round(entry + risk * 1.5, 2) if risk > 0 else target
    trailing_sl    = round(entry + risk * 0.25, 2) if risk > 0 else sl

    exit_rules = (
        f"PRIMARY TARGET: Exit 100% at ₹{target:,.0f}. "
        f"STOP LOSS: Exit immediately at ₹{sl:,.0f} — non-negotiable. "
        f"TRAILING: If price reaches ₹{partial_target:,.0f} (~1.5× risk), "
        f"move SL to ₹{trailing_sl:,.0f} (breakeven+). "
        f"TIME EXIT: Close entire position by Day {MAX_HOLDING_DAYS} open, "
        f"even if target/SL not triggered."
    )

    return {
        'summary':          summary,
        'news_trigger':     news_trigger,
        'technical_setup':  technical_setup,
        'fundamental_brief':fundamental_brief,
        'key_risks':        " | ".join(risks),
        'exit_rules':       exit_rules,
        'hidden_signals':   hidden,
    }


def _freshness_label(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str[:10], '%Y-%m-%d')
        days = (datetime.now() - d).days
        if days == 0: return "TODAY"
        if days == 1: return "YESTERDAY"
        return f"{days}d AGO"
    except Exception:
        return "RECENT"


# ═══════════════════════════════════════════════════════════════════════════════
# WEIGHTS — feedback-adjusted or base
# ═══════════════════════════════════════════════════════════════════════════════

def _get_weights() -> dict:
    """Return current composite weights (feedback-adjusted if enough data)."""
    try:
        from modules.feedback_engine import get_adjusted_weights
        w = get_adjusted_weights()
        if w.get('adjusted'):
            return w
    except Exception:
        pass
    return {
        'news': WEIGHT_NEWS, 'technical': WEIGHT_TECHNICAL,
        'fundamental': WEIGHT_FUNDAMENTAL, 'market': WEIGHT_MARKET,
        'adjusted': False,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def _store_recommendations(recs: list, date_str: str):
    conn = get_connection()
    for rec in recs:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO recommendations
                (date, symbol, direction, entry_low, entry_high, target_price,
                 stop_loss, quantity, position_value, risk_amount, reward_amount,
                 risk_reward_ratio, expected_holding, composite_score,
                 news_score, technical_score, fundamental_score, market_score,
                 confidence, reasoning, news_trigger, technical_setup,
                 key_risks, exit_rules)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_str, rec['symbol'], rec['direction'],
                rec['entry_low'], rec['entry_high'], rec['target_price'],
                rec['stop_loss'], rec['quantity'], rec['position_value'],
                rec['risk_amount'], rec['reward_amount'], rec['risk_reward_ratio'],
                rec['expected_holding'], rec['composite_score'],
                rec['news_score'], rec['technical_score'],
                rec['fundamental_score'], rec['market_score'],
                rec['confidence'], rec['reasoning'], rec['news_trigger'],
                rec['technical_setup'], rec['key_risks'], rec['exit_rules'],
            ))
        except Exception as e:
            log_system_event("recommender", "ERROR", f"Store rec {rec['symbol']}: {e}")
    conn.commit()
    conn.close()


def _store_short_recommendations(recs: list, date_str: str):
    conn = get_connection()
    for rec in recs:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO short_recommendations
                (date, symbol, entry_low, entry_high, target_price, stop_loss,
                 lot_size, margin_required, risk_amount, reward_amount,
                 risk_reward_ratio, short_score, confidence, reasoning,
                 bearish_catalyst, technical_weakness, key_risks, exit_rules)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                date_str, rec['symbol'],
                rec['entry_low'], rec['entry_high'],
                rec['target_price'], rec['stop_loss'],
                rec['lot_size'], rec['margin_required'],
                rec['risk_amount'], rec['reward_amount'],
                rec['risk_reward_ratio'], rec['short_score'],
                rec['confidence'], rec['reasoning'],
                rec['bearish_catalyst'], rec['technical_weakness'],
                rec['key_risks'], rec['exit_rules'],
            ))
        except Exception as e:
            log_system_event("recommender", "ERROR", f"Store short {rec['symbol']}: {e}")
    conn.commit()
    conn.close()


def _store_rejected(rejected: list, date_str: str):
    conn = get_connection()
    for rej in rejected:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO rejected_stocks
                (date, symbol, composite_score, rejection_reason)
                VALUES (?,?,?,?)
            """, (date_str, rej['symbol'], rej.get('score', 0), rej['reason']))
        except Exception:
            continue
    conn.commit()
    conn.close()
