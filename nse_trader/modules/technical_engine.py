"""
Technical Analysis Scoring Engine
Computes indicators and produces a 0-100 technical score per stock.
"""

import pandas as pd
import numpy as np
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    EMA_SHORT, EMA_LONG, RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    RSI_EXTREME_OB, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ATR_PERIOD, ATR_SL_MULTIPLIER, VOLUME_SPIKE_THRESHOLD,
    BREAKOUT_LOOKBACK, OVEREXTENDED_THRESHOLD, REL_STRENGTH_PERIOD,
    NIFTY_SYMBOL
)
from modules.database import get_connection, log_system_event


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_macd(series: pd.Series, fast=12, slow=26, signal=9) -> tuple:
    """MACD line, signal line, histogram."""
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()


def detect_breakout(close: pd.Series, high: pd.Series, volume: pd.Series,
                    lookback: int = 20) -> tuple:
    """
    Detect if the latest close is a breakout above recent resistance.
    Returns (is_breakout, resistance_level).
    """
    if len(close) < lookback + 1:
        return False, 0.0

    # Resistance = highest high in the lookback period (excluding last bar)
    resistance = high.iloc[-(lookback+1):-1].max()
    current_close = close.iloc[-1]
    prev_close = close.iloc[-2]

    # Breakout: close above resistance AND previous close was below
    is_breakout = (current_close > resistance) and (prev_close <= resistance)

    return is_breakout, float(resistance)


def compute_relative_strength(stock_close: pd.Series, nifty_close: pd.Series,
                               period: int = 10) -> float:
    """
    Relative strength vs Nifty over last N days.
    Positive = outperforming Nifty.
    """
    if len(stock_close) < period + 1 or len(nifty_close) < period + 1:
        return 0.0

    stock_return = (stock_close.iloc[-1] / stock_close.iloc[-period - 1] - 1) * 100
    nifty_return = (nifty_close.iloc[-1] / nifty_close.iloc[-period - 1] - 1) * 100

    return round(stock_return - nifty_return, 2)


def score_technical(df: pd.DataFrame, nifty_df: pd.DataFrame = None) -> dict:
    """
    Compute technical score (0-100) for a stock.
    
    Args:
        df: DataFrame with columns [date, open, high, low, close, volume]
        nifty_df: Nifty DataFrame for relative strength calculation
    
    Returns:
        dict with score, indicators, and breakdown
    """
    if df is None or len(df) < 60:
        return {
            'score': 0, 'disqualified': True,
            'reason': 'Insufficient data (need 60+ days)'
        }

    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    current_price = float(close.iloc[-1])

    # ── Compute indicators ────────────────────────────────────────────────
    ema_20 = compute_ema(close, EMA_SHORT)
    ema_50 = compute_ema(close, EMA_LONG)
    rsi = compute_rsi(close, RSI_PERIOD)
    macd_line, macd_signal_line, macd_hist = compute_macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    atr = compute_atr(high, low, close, ATR_PERIOD)

    # Latest values
    latest_ema20 = float(ema_20.iloc[-1])
    latest_ema50 = float(ema_50.iloc[-1])
    latest_rsi = float(rsi.iloc[-1])
    latest_macd = float(macd_line.iloc[-1])
    latest_macd_sig = float(macd_signal_line.iloc[-1])
    latest_macd_hist = float(macd_hist.iloc[-1])
    latest_atr = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else current_price * 0.02

    # Volume analysis
    avg_volume_20 = float(volume.tail(20).mean())
    latest_volume = float(volume.iloc[-1])
    volume_ratio = latest_volume / avg_volume_20 if avg_volume_20 > 0 else 1.0

    # Breakout detection
    is_breakout, resistance_level = detect_breakout(close, high, volume, BREAKOUT_LOOKBACK)

    # Relative strength vs Nifty
    rel_strength = 0.0
    if nifty_df is not None and len(nifty_df) >= REL_STRENGTH_PERIOD + 1:
        rel_strength = compute_relative_strength(
            close, nifty_df['close'], REL_STRENGTH_PERIOD
        )

    # Distance from 20 EMA
    ema_distance_pct = (current_price - latest_ema20) / latest_ema20

    # ── DISQUALIFIERS ─────────────────────────────────────────────────────
    if latest_rsi > RSI_EXTREME_OB:
        return {
            'score': 0, 'disqualified': True,
            'reason': f'RSI extremely overbought at {latest_rsi:.1f}',
            'indicators': {
                'ema_20': latest_ema20, 'ema_50': latest_ema50,
                'rsi': latest_rsi, 'atr': latest_atr,
                'volume_ratio': volume_ratio
            }
        }

    if ema_distance_pct > OVEREXTENDED_THRESHOLD:
        return {
            'score': 0, 'disqualified': True,
            'reason': f'Overextended: {ema_distance_pct*100:.1f}% above 20 EMA',
            'indicators': {
                'ema_20': latest_ema20, 'ema_50': latest_ema50,
                'rsi': latest_rsi, 'atr': latest_atr,
                'volume_ratio': volume_ratio
            }
        }

    # Check for distribution: price rising but volume declining over 5 days
    if len(close) >= 5:
        price_trend = close.iloc[-1] > close.iloc[-5]
        vol_trend = volume.iloc[-5:].is_monotonic_decreasing
        if price_trend and vol_trend and volume_ratio < 0.7:
            return {
                'score': 0, 'disqualified': True,
                'reason': 'Distribution detected: rising price on declining volume',
                'indicators': {
                    'ema_20': latest_ema20, 'ema_50': latest_ema50,
                    'rsi': latest_rsi, 'atr': latest_atr,
                    'volume_ratio': volume_ratio
                }
            }

    # ── SCORING ───────────────────────────────────────────────────────────
    score = 0
    breakdown = {}

    # 1. Price above 20 EMA (10 pts)
    if current_price > latest_ema20:
        score += 10
        breakdown['above_ema20'] = 10
    else:
        breakdown['above_ema20'] = 0

    # 2. Price above 50 EMA (10 pts)
    if current_price > latest_ema50:
        score += 10
        breakdown['above_ema50'] = 10
    else:
        breakdown['above_ema50'] = 0

    # 3. 20 EMA above 50 EMA - golden alignment (10 pts)
    if latest_ema20 > latest_ema50:
        score += 10
        breakdown['ema_alignment'] = 10
    else:
        breakdown['ema_alignment'] = 0

    # 4. RSI in healthy zone 40-70 (10 pts)
    if RSI_OVERSOLD <= latest_rsi <= RSI_OVERBOUGHT:
        score += 10
        breakdown['rsi_healthy'] = 10
    elif 30 <= latest_rsi < RSI_OVERSOLD:
        score += 5  # Approaching oversold could be opportunity
        breakdown['rsi_healthy'] = 5
    else:
        breakdown['rsi_healthy'] = 0

    # 5. MACD line above signal line (10 pts)
    if latest_macd > latest_macd_sig:
        score += 10
        breakdown['macd_bullish'] = 10
    elif latest_macd_hist > macd_hist.iloc[-2] if len(macd_hist) >= 2 else False:
        score += 5  # Histogram improving
        breakdown['macd_bullish'] = 5
    else:
        breakdown['macd_bullish'] = 0

    # 6. Volume spike (15 pts)
    if volume_ratio >= VOLUME_SPIKE_THRESHOLD * 1.5:
        score += 15
        breakdown['volume_spike'] = 15
    elif volume_ratio >= VOLUME_SPIKE_THRESHOLD:
        score += 10
        breakdown['volume_spike'] = 10
    elif volume_ratio >= 1.0:
        score += 3
        breakdown['volume_spike'] = 3
    else:
        breakdown['volume_spike'] = 0

    # 7. Breakout above resistance (15 pts)
    if is_breakout:
        score += 15
        breakdown['breakout'] = 15
    else:
        # Check if near resistance (within 1%)
        if resistance_level > 0 and current_price >= resistance_level * 0.99:
            score += 5
            breakdown['breakout'] = 5
        else:
            breakdown['breakout'] = 0

    # 8. Relative strength vs Nifty (10 pts)
    if rel_strength > 3.0:
        score += 10
        breakdown['rel_strength'] = 10
    elif rel_strength > 1.0:
        score += 7
        breakdown['rel_strength'] = 7
    elif rel_strength > 0:
        score += 3
        breakdown['rel_strength'] = 3
    else:
        breakdown['rel_strength'] = 0

    # 9. Short-term momentum (2-4 day) (10 pts)
    if len(close) >= 5:
        momentum_2d = (close.iloc[-1] / close.iloc[-3] - 1) * 100
        momentum_4d = (close.iloc[-1] / close.iloc[-5] - 1) * 100

        if momentum_2d > 1 and momentum_4d > 2:
            score += 10
            breakdown['momentum'] = 10
        elif momentum_2d > 0.5 or momentum_4d > 1:
            score += 5
            breakdown['momentum'] = 5
        else:
            breakdown['momentum'] = 0
    else:
        breakdown['momentum'] = 0

    # Cap at 100
    score = min(score, 100)

    # ── Compute stop-loss and target ──────────────────────────────────────
    atr_stop = current_price - (ATR_SL_MULTIPLIER * latest_atr)

    # Structure-based stop: below recent swing low (last 10 days)
    recent_low = float(low.tail(10).min())
    structure_stop = recent_low * 0.995  # Slightly below the low

    # Use the tighter stop that's still reasonable
    stop_loss = max(atr_stop, structure_stop)

    # Ensure stop is at least 1% below entry
    if stop_loss > current_price * 0.99:
        stop_loss = current_price * 0.97  # Default 3%

    # Target based on risk-reward
    risk = current_price - stop_loss
    target = current_price + (risk * 2.5)  # Default 1:2.5 R:R

    return {
        'score': score,
        'disqualified': False,
        'indicators': {
            'ema_20': round(latest_ema20, 2),
            'ema_50': round(latest_ema50, 2),
            'rsi': round(latest_rsi, 1),
            'macd_line': round(latest_macd, 2),
            'macd_signal': round(latest_macd_sig, 2),
            'macd_histogram': round(latest_macd_hist, 2),
            'atr': round(latest_atr, 2),
            'volume_ratio': round(volume_ratio, 2),
            'relative_strength': round(rel_strength, 2),
            'breakout': is_breakout,
            'breakout_level': round(resistance_level, 2),
            'ema_distance_pct': round(ema_distance_pct * 100, 2),
        },
        'breakdown': breakdown,
        'levels': {
            'current_price': round(current_price, 2),
            'stop_loss': round(stop_loss, 2),
            'target': round(target, 2),
            'risk': round(risk, 2),
            'reward': round(target - current_price, 2),
            'risk_reward_ratio': round((target - current_price) / risk, 2) if risk > 0 else 0,
        }
    }


def score_all_stocks(price_data: dict, nifty_df: pd.DataFrame = None) -> dict:
    """Score all stocks and return results."""
    results = {}

    for symbol, df in price_data.items():
        try:
            result = score_technical(df, nifty_df)
            result['symbol'] = symbol
            results[symbol] = result
        except Exception as e:
            log_system_event("technical", "ERROR", f"Failed scoring {symbol}: {e}")

    return results


def store_technical_scores(scores: dict, date_str: str = None):
    """Store technical scores in database."""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    conn = get_connection()
    cursor = conn.cursor()

    for symbol, data in scores.items():
        if data.get('disqualified', True) and data['score'] == 0:
            continue

        indicators = data.get('indicators', {})
        breakdown = data.get('breakdown', {})

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO technical_scores
                (symbol, date, ema_20, ema_50, rsi_14, macd_line, macd_signal,
                 macd_histogram, atr_14, volume_ratio, relative_strength,
                 breakout_detected, breakout_level, technical_score, score_breakdown)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, date_str,
                indicators.get('ema_20'),
                indicators.get('ema_50'),
                indicators.get('rsi'),
                indicators.get('macd_line'),
                indicators.get('macd_signal'),
                indicators.get('macd_histogram'),
                indicators.get('atr'),
                indicators.get('volume_ratio'),
                indicators.get('relative_strength'),
                1 if indicators.get('breakout') else 0,
                indicators.get('breakout_level'),
                data['score'],
                str(breakdown)
            ))
        except Exception as e:
            continue

    conn.commit()
    conn.close()
