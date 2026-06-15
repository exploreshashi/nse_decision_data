"""
Feedback Engine
Analyses closed trade outcomes against the recommendations that generated them.
Adjusts signal weights so the composite scorer improves over time.
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import WEIGHT_NEWS, WEIGHT_TECHNICAL, WEIGHT_FUNDAMENTAL, WEIGHT_MARKET
from modules.database import get_connection

# Minimum matched trades before weight adjustment kicks in
MIN_TRADES = 10
# Rolling window
WINDOW = 50


# ─── Core matching ────────────────────────────────────────────────────────────

def _get_matched_pairs() -> pd.DataFrame:
    """Join closed trades to recommendations by symbol within ±5 days of entry."""
    conn = get_connection()

    trades = pd.read_sql_query("""
        SELECT trade_id, symbol, date_entry, net_pnl, r_multiple, exit_reason,
               composite_score_at_entry
        FROM trade_journal
        WHERE status = 'CLOSED' AND net_pnl IS NOT NULL
        ORDER BY date_entry DESC
        LIMIT ?
    """, conn, params=(WINDOW,))

    recs = pd.read_sql_query("""
        SELECT date, symbol, composite_score, news_score, technical_score,
               fundamental_score, market_score, direction
        FROM recommendations
        ORDER BY date DESC
    """, conn)

    conn.close()

    if trades.empty or recs.empty:
        return pd.DataFrame()

    trades['date_entry'] = pd.to_datetime(trades['date_entry'])
    recs['date'] = pd.to_datetime(recs['date'])

    matched = []
    for _, t in trades.iterrows():
        sym_recs = recs[
            (recs['symbol'] == t['symbol']) &
            (recs['date'] >= t['date_entry'] - pd.Timedelta(days=5)) &
            (recs['date'] <= t['date_entry'] + pd.Timedelta(days=1))
        ]
        if sym_recs.empty:
            continue
        r = sym_recs.sort_values('date', ascending=False).iloc[0]
        matched.append({
            'trade_id':         t['trade_id'],
            'symbol':           t['symbol'],
            'net_pnl':          float(t['net_pnl']),
            'r_multiple':       float(t['r_multiple']) if t['r_multiple'] else 0,
            'is_win':           1 if float(t['net_pnl']) > 0 else 0,
            'exit_reason':      t['exit_reason'] or '',
            'news_score':       float(r['news_score']),
            'technical_score':  float(r['technical_score']),
            'fundamental_score':float(r['fundamental_score']),
            'market_score':     float(r['market_score']),
            'composite_score':  float(r['composite_score']),
        })

    return pd.DataFrame(matched) if matched else pd.DataFrame()


# ─── Public API ───────────────────────────────────────────────────────────────

def get_signal_accuracy() -> dict:
    """
    Calculate per-signal predictive power and overall win-rate stats.
    Returns a dict consumed by both the UI and weight adjuster.
    """
    pairs = _get_matched_pairs()

    base = {
        'total_matched': 0, 'wins': 0, 'losses': 0,
        'win_rate': 0.0, 'avg_r_multiple': 0.0,
        'signal_accuracy': {}, 'score_win_rates': {},
        'exit_analysis': {}, 'insights': [],
        'message': 'No matched trades yet — log trades and close them to build the feedback loop.',
    }

    if pairs.empty or len(pairs) < 3:
        return base

    total = len(pairs)
    wins  = int(pairs['is_win'].sum())

    signal_accuracy = {}
    for sig in ['news_score', 'technical_score', 'fundamental_score', 'market_score']:
        w = pairs.loc[pairs['is_win'] == 1, sig]
        l = pairs.loc[pairs['is_win'] == 0, sig]
        signal_accuracy[sig] = {
            'avg_winner':       round(float(w.mean()) if len(w) > 0 else 0, 1),
            'avg_loser':        round(float(l.mean()) if len(l) > 0 else 0, 1),
            'predictive_power': round(float(w.mean() - l.mean()) if len(w) > 0 and len(l) > 0 else 0, 1),
        }

    # Win rate by composite score bucket
    bins   = [0, 65, 70, 75, 80, 100]
    labels = ['65-', '65-70', '70-75', '75-80', '80+']
    pairs['bucket'] = pd.cut(pairs['composite_score'], bins=bins, labels=labels)
    score_win_rates = {}
    for bucket, grp in pairs.groupby('bucket', observed=True):
        if len(grp) > 0:
            score_win_rates[str(bucket)] = {
                'count':    len(grp),
                'win_rate': round(float(grp['is_win'].mean()) * 100, 1),
            }

    # Exit reason breakdown
    exit_analysis = {}
    for reason, grp in pairs.groupby('exit_reason'):
        exit_analysis[reason] = {
            'count':  len(grp),
            'avg_r':  round(float(grp['r_multiple'].mean()), 2),
        }

    insights = _derive_insights(pairs, signal_accuracy)

    return {
        'total_matched':  total,
        'wins':           wins,
        'losses':         total - wins,
        'win_rate':       round(wins / total * 100, 1),
        'avg_r_multiple': round(float(pairs['r_multiple'].mean()), 2),
        'signal_accuracy': signal_accuracy,
        'score_win_rates': score_win_rates,
        'exit_analysis':   exit_analysis,
        'insights':        insights,
        'message':         f'Feedback loop: {total} matched trades analysed.',
    }


def get_adjusted_weights() -> dict:
    """
    Return composite weights adjusted by signal predictive power.
    Falls back to base weights when insufficient data.
    """
    base = {
        'news': WEIGHT_NEWS, 'technical': WEIGHT_TECHNICAL,
        'fundamental': WEIGHT_FUNDAMENTAL, 'market': WEIGHT_MARKET,
    }

    acc = get_signal_accuracy()
    if acc['total_matched'] < MIN_TRADES:
        return {**base, 'adjusted': False,
                'reason': f"Need {MIN_TRADES} matched trades (have {acc['total_matched']})"}

    sig_map = {
        'news': 'news_score', 'technical': 'technical_score',
        'fundamental': 'fundamental_score', 'market': 'market_score',
    }

    # Predictive power must be ≥ 0; neutral signals keep their base weight
    power = {
        name: max(0.0, acc['signal_accuracy'].get(db_key, {}).get('predictive_power', 0))
        for name, db_key in sig_map.items()
    }
    total_power = sum(power.values()) or 1.0

    adjusted = {}
    total_base = sum(base.values())
    for name in base:
        ratio = power[name] / total_power
        # 70% base, 30% feedback-driven
        adjusted[name] = round(base[name] * 0.70 + ratio * 0.30 * total_base, 4)

    # Renormalise so weights sum to 1.0
    s = sum(adjusted.values())
    for name in adjusted:
        adjusted[name] = round(adjusted[name] / s, 4)

    return {
        **adjusted, 'adjusted': True,
        'reason': f'Adjusted from {acc["total_matched"]} trades',
        'base': base,
    }


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _derive_insights(pairs: pd.DataFrame, signal_accuracy: dict) -> list:
    """Generate human-readable pattern insights from trade history."""
    insights = []

    # 1. Most predictive signal
    by_power = sorted(
        signal_accuracy.items(),
        key=lambda x: x[1].get('predictive_power', 0), reverse=True
    )
    if by_power and by_power[0][1]['predictive_power'] > 5:
        best_sig = by_power[0][0].replace('_score', '').replace('_', ' ').title()
        power    = by_power[0][1]['predictive_power']
        insights.append(
            f"🔬 {best_sig} score is your most predictive signal "
            f"(winners averaged {power:+.0f} pts higher than losers)"
        )

    # 2. News catalyst effect
    if 'news_score' in signal_accuracy:
        hi = pairs.loc[pairs['news_score'] >= 70]
        lo = pairs.loc[pairs['news_score'] < 50]
        if len(hi) >= 3 and len(lo) >= 3:
            hi_wr = hi['is_win'].mean() * 100
            lo_wr = lo['is_win'].mean() * 100
            if hi_wr - lo_wr > 15:
                insights.append(
                    f"📰 Trades with news score ≥ 70 win {hi_wr:.0f}% vs {lo_wr:.0f}% "
                    f"for weak-news trades — catalyst quality matters"
                )

    # 3. High composite score validation
    high = pairs.loc[pairs['composite_score'] >= 75]
    low  = pairs.loc[pairs['composite_score'] < 70]
    if len(high) >= 3 and len(low) >= 3:
        h_wr = high['is_win'].mean() * 100
        l_wr = low['is_win'].mean() * 100
        insights.append(
            f"🎯 Score ≥ 75 → {h_wr:.0f}% win rate vs {l_wr:.0f}% for score < 70 "
            f"across {len(pairs)} trades"
        )

    # 4. Stop-loss discipline check
    sl_trades = pairs.loc[pairs['exit_reason'].str.contains('Stop', case=False, na=False)]
    if len(sl_trades) >= 3:
        avg_r = sl_trades['r_multiple'].mean()
        if avg_r < -1.5:
            insights.append(
                f"⚠️ Stop-loss exits averaging {avg_r:.1f}R — "
                f"check if stop distances are set too wide"
            )

    # 5. Expectancy trend
    if len(pairs) >= 10:
        recent = pairs.head(10)['r_multiple'].mean()
        older  = pairs.tail(max(1, len(pairs) - 10))['r_multiple'].mean()
        if recent - older > 0.3:
            insights.append(
                f"📈 System improving: recent 10 trades avg {recent:+.2f}R "
                f"vs older trades {older:+.2f}R"
            )
        elif older - recent > 0.3:
            insights.append(
                f"📉 Recent performance dipping: last 10 trades {recent:+.2f}R "
                f"vs historical {older:+.2f}R — review signal calibration"
            )

    return insights
