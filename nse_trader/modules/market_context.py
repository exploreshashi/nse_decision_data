"""
Market Context Scoring Module
Evaluates the overall market environment and produces a 0-100 score.
Determines whether market conditions support trading today.
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    VIX_HIGH, VIX_MODERATE, FII_SELLING_THRESHOLD, MARKET_MIN_SCORE,
    EMA_SHORT
)
from modules.database import get_connection, log_system_event
from modules.technical_engine import compute_ema


def score_market_context(nifty_df: pd.DataFrame = None,
                          banknifty_df: pd.DataFrame = None,
                          macro_data: dict = None) -> dict:
    """
    Score the overall market context (0-100).
    
    Args:
        nifty_df: Nifty 50 OHLCV DataFrame
        banknifty_df: Bank Nifty OHLCV DataFrame  
        macro_data: dict with VIX, FII/DII, global data
    
    Returns:
        dict with score, verdict, and detailed breakdown
    """
    score = 0
    breakdown = {}
    details = {}
    warnings = []

    # ── 1. Nifty above 20 EMA (15 pts) ───────────────────────────────────
    nifty_trend = 'UNKNOWN'
    if nifty_df is not None and len(nifty_df) >= 25:
        nifty_close = nifty_df['close']
        nifty_ema20 = compute_ema(nifty_close, EMA_SHORT)
        latest_nifty = float(nifty_close.iloc[-1])
        latest_nifty_ema = float(nifty_ema20.iloc[-1])

        if latest_nifty > latest_nifty_ema:
            score += 15
            breakdown['nifty_trend'] = 15
            nifty_trend = 'BULLISH'
            details['nifty'] = f"₹{latest_nifty:,.0f} (above 20 EMA: ₹{latest_nifty_ema:,.0f})"
        else:
            breakdown['nifty_trend'] = 0
            nifty_trend = 'BEARISH'
            details['nifty'] = f"₹{latest_nifty:,.0f} (below 20 EMA: ₹{latest_nifty_ema:,.0f})"
            warnings.append("Nifty is below 20 EMA — market in short-term downtrend")

        # Check if Nifty is in a confirmed downtrend (lower lows over 5 days)
        if len(nifty_close) >= 10:
            recent_5 = nifty_close.iloc[-5:]
            if recent_5.iloc[-1] < recent_5.iloc[0] and recent_5.min() == recent_5.iloc[-1]:
                warnings.append("Nifty making lower lows — confirmed downtrend")
    else:
        breakdown['nifty_trend'] = 5  # Neutral if no data
        details['nifty'] = 'Data unavailable'

    # ── 2. Bank Nifty above 20 EMA (10 pts) ──────────────────────────────
    banknifty_trend = 'UNKNOWN'
    if banknifty_df is not None and len(banknifty_df) >= 25:
        bn_close = banknifty_df['close']
        bn_ema20 = compute_ema(bn_close, EMA_SHORT)
        latest_bn = float(bn_close.iloc[-1])
        latest_bn_ema = float(bn_ema20.iloc[-1])

        if latest_bn > latest_bn_ema:
            score += 10
            breakdown['banknifty_trend'] = 10
            banknifty_trend = 'BULLISH'
            details['banknifty'] = f"₹{latest_bn:,.0f} (above 20 EMA)"
        else:
            breakdown['banknifty_trend'] = 0
            banknifty_trend = 'BEARISH'
            details['banknifty'] = f"₹{latest_bn:,.0f} (below 20 EMA)"
    else:
        breakdown['banknifty_trend'] = 5
        details['banknifty'] = 'Data unavailable'

    # ── 3. India VIX (15 pts) ─────────────────────────────────────────────
    vix_level = 'UNKNOWN'
    vix_value = None
    if macro_data and macro_data.get('india_vix'):
        vix_value = float(macro_data['india_vix'])
        if vix_value < VIX_MODERATE:
            score += 15
            breakdown['vix'] = 15
            vix_level = 'LOW'
            details['vix'] = f"{vix_value:.1f} (low — trends persist)"
        elif vix_value < VIX_HIGH:
            score += 8
            breakdown['vix'] = 8
            vix_level = 'MODERATE'
            details['vix'] = f"{vix_value:.1f} (moderate — some caution)"
        else:
            breakdown['vix'] = 0
            vix_level = 'HIGH'
            details['vix'] = f"{vix_value:.1f} (HIGH — volatility risk)"
            warnings.append(f"India VIX at {vix_value:.1f} — extreme volatility, avoid trading")
    else:
        breakdown['vix'] = 7
        details['vix'] = 'Data unavailable'

    # ── 4. FII activity (15 pts) ──────────────────────────────────────────
    fii_stance = 'UNKNOWN'
    if macro_data and macro_data.get('fii_net_cr') is not None:
        fii_net = float(macro_data['fii_net_cr'])
        if fii_net > 500:
            score += 15
            breakdown['fii'] = 15
            fii_stance = 'NET_BUYERS'
            details['fii'] = f"₹{fii_net:,.0f} Cr (net buyers)"
        elif fii_net > -500:
            score += 10
            breakdown['fii'] = 10
            fii_stance = 'NEUTRAL'
            details['fii'] = f"₹{fii_net:,.0f} Cr (neutral)"
        elif fii_net > FII_SELLING_THRESHOLD:
            score += 5
            breakdown['fii'] = 5
            fii_stance = 'MILD_SELLING'
            details['fii'] = f"₹{fii_net:,.0f} Cr (mild selling)"
        else:
            breakdown['fii'] = 0
            fii_stance = 'HEAVY_SELLING'
            details['fii'] = f"₹{fii_net:,.0f} Cr (heavy selling)"
            warnings.append("FII heavy selling — institutional headwind")
    else:
        breakdown['fii'] = 7
        details['fii'] = 'Data unavailable'

    # ── 5. GIFT Nifty / pre-market (10 pts) ──────────────────────────────
    if macro_data and macro_data.get('gift_nifty_change_pct') is not None:
        gift_chg = float(macro_data['gift_nifty_change_pct'])
        if gift_chg > 0.3:
            score += 10
            breakdown['gift_nifty'] = 10
            details['gift_nifty'] = f"+{gift_chg:.1f}% (positive global cue)"
        elif gift_chg > -0.3:
            score += 6
            breakdown['gift_nifty'] = 6
            details['gift_nifty'] = f"{gift_chg:+.1f}% (flat)"
        else:
            breakdown['gift_nifty'] = 0
            details['gift_nifty'] = f"{gift_chg:+.1f}% (negative)"
    else:
        breakdown['gift_nifty'] = 5
        details['gift_nifty'] = 'Data unavailable'

    # ── 6. US markets (10 pts) ────────────────────────────────────────────
    global_cue = 'UNKNOWN'
    if macro_data and macro_data.get('sp500_change_pct') is not None:
        sp_chg = float(macro_data['sp500_change_pct'])
        if sp_chg > 0.5:
            score += 10
            breakdown['us_markets'] = 10
            global_cue = 'POSITIVE'
            details['us_markets'] = f"S&P 500: {sp_chg:+.1f}% (green)"
        elif sp_chg > -0.5:
            score += 6
            breakdown['us_markets'] = 6
            global_cue = 'FLAT'
            details['us_markets'] = f"S&P 500: {sp_chg:+.1f}% (flat)"
        elif sp_chg > -2.0:
            score += 2
            breakdown['us_markets'] = 2
            global_cue = 'NEGATIVE'
            details['us_markets'] = f"S&P 500: {sp_chg:+.1f}% (red)"
        else:
            breakdown['us_markets'] = 0
            global_cue = 'SHARP_NEGATIVE'
            details['us_markets'] = f"S&P 500: {sp_chg:+.1f}% (SHARP FALL)"
            warnings.append("US markets sharply down — high gap-down risk")
    else:
        breakdown['us_markets'] = 5
        details['us_markets'] = 'Data unavailable'

    # ── 7. Crude oil (10 pts) ─────────────────────────────────────────────
    if macro_data and macro_data.get('crude_brent') is not None:
        crude = float(macro_data['crude_brent'])
        if crude < 80:
            score += 10
            breakdown['crude'] = 10
            details['crude'] = f"${crude:.1f} (favorable)"
        elif crude < 90:
            score += 7
            breakdown['crude'] = 7
            details['crude'] = f"${crude:.1f} (moderate)"
        elif crude < 100:
            score += 3
            breakdown['crude'] = 3
            details['crude'] = f"${crude:.1f} (elevated)"
        else:
            breakdown['crude'] = 0
            details['crude'] = f"${crude:.1f} (SPIKE — inflation risk)"
            warnings.append("Crude above $100 — inflation and fiscal risk")
    else:
        breakdown['crude'] = 5
        details['crude'] = 'Data unavailable'

    # ── 8. Overall sector trend (15 pts) — based on Nifty 5-day return ───
    if nifty_df is not None and len(nifty_df) >= 6:
        nifty_5d = float(nifty_df['close'].iloc[-1] / nifty_df['close'].iloc[-6] - 1) * 100
        if nifty_5d > 1.0:
            score += 15
            breakdown['sector_trend'] = 15
            details['5d_trend'] = f"Nifty 5-day: +{nifty_5d:.1f}% (bullish momentum)"
        elif nifty_5d > 0:
            score += 10
            breakdown['sector_trend'] = 10
            details['5d_trend'] = f"Nifty 5-day: +{nifty_5d:.1f}% (mild positive)"
        elif nifty_5d > -1.0:
            score += 5
            breakdown['sector_trend'] = 5
            details['5d_trend'] = f"Nifty 5-day: {nifty_5d:+.1f}% (choppy)"
        else:
            breakdown['sector_trend'] = 0
            details['5d_trend'] = f"Nifty 5-day: {nifty_5d:+.1f}% (weak)"
    else:
        breakdown['sector_trend'] = 5
        details['5d_trend'] = 'Data unavailable'

    # Cap at 100
    score = min(score, 100)

    # ── Determine verdict ─────────────────────────────────────────────────
    if vix_value and vix_value >= VIX_HIGH:
        verdict = 'NO_TRADE'
        verdict_text = '🔴 DO NOT TRADE — VIX too high, extreme volatility'
    elif score >= 70:
        verdict = 'FAVORABLE'
        verdict_text = '🟢 FAVORABLE — Conditions support trading'
    elif score >= MARKET_MIN_SCORE:
        verdict = 'CAUTIOUS'
        verdict_text = '🟡 CAUTIOUS — Trade selectively, reduce position sizes'
    else:
        verdict = 'NO_TRADE'
        verdict_text = '🔴 UNFAVORABLE — No trades recommended today'

    return {
        'score': score,
        'verdict': verdict,
        'verdict_text': verdict_text,
        'breakdown': breakdown,
        'details': details,
        'warnings': warnings,
        'nifty_trend': nifty_trend,
        'banknifty_trend': banknifty_trend,
        'vix_level': vix_level,
        'fii_stance': fii_stance,
        'global_cue': global_cue,
    }


def store_market_health(result: dict, date_str: str = None):
    """Store market health assessment."""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    conn = get_connection()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO market_health
            (date, market_score, verdict, nifty_trend, banknifty_trend,
             vix_level, fii_stance, global_cue, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date_str, result['score'], result['verdict'],
            result['nifty_trend'], result['banknifty_trend'],
            result['vix_level'], result['fii_stance'],
            result['global_cue'], str(result['details'])
        ))
        conn.commit()
    except Exception as e:
        log_system_event("market", "ERROR", f"Failed to store market health: {e}")
    finally:
        conn.close()
