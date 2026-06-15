"""
Risk Management and Position Sizing Module
Calculates position sizes, enforces risk limits, and manages portfolio exposure.
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    TOTAL_CAPITAL, MAX_CAPITAL_PER_TRADE, MAX_RISK_PER_TRADE,
    MAX_DAILY_LOSS, MAX_WEEKLY_LOSS, MAX_MONTHLY_DRAWDOWN,
    MAX_OPEN_POSITIONS, MIN_RISK_REWARD_RATIO, CASH_BUFFER_RATIO,
    BROKERAGE_PER_ORDER, STT_RATE, EXCHANGE_TXN_RATE, GST_RATE,
    SEBI_CHARGES, STAMP_DUTY_BUY
)
from modules.database import get_connection, log_system_event


def calculate_brokerage(buy_value: float, sell_value: float) -> float:
    """
    Calculate total transaction costs for a round-trip trade (Zerodha delivery).
    """
    # Brokerage: ₹20 per order or 0, whichever is lower (Zerodha charges 0 for delivery)
    brokerage = 0  # Zerodha: Zero brokerage for delivery trades

    # STT: 0.1% on both buy and sell for delivery
    stt = (buy_value + sell_value) * 0.001

    # Exchange transaction charges
    exchange = (buy_value + sell_value) * EXCHANGE_TXN_RATE

    # GST on brokerage + exchange charges
    gst = (brokerage + exchange) * GST_RATE

    # SEBI charges
    sebi = (buy_value + sell_value) * SEBI_CHARGES

    # Stamp duty (on buy side only)
    stamp = buy_value * STAMP_DUTY_BUY

    total = brokerage + stt + exchange + gst + sebi + stamp
    return round(total, 2)


def calculate_position_size(entry_price: float, stop_loss: float,
                             current_capital: float = None,
                             existing_exposure: float = 0) -> dict:
    """
    Calculate position size based on risk management rules.
    
    Uses the smaller of:
    1. Risk-based sizing (max 2% capital at risk)
    2. Capital-per-trade cap (max 33%)
    3. Available capital (accounting for existing positions + cash buffer)
    
    Returns dict with quantity, position value, risk, and checks.
    """
    if current_capital is None:
        current_capital = TOTAL_CAPITAL

    # Validate inputs
    if entry_price <= 0 or stop_loss <= 0 or stop_loss >= entry_price:
        return {
            'valid': False,
            'reason': 'Invalid entry/stop-loss prices',
            'quantity': 0
        }

    risk_per_share = entry_price - stop_loss
    risk_pct = risk_per_share / entry_price * 100

    # ── Risk-based quantity ───────────────────────────────────────────────
    max_risk_amount = current_capital * MAX_RISK_PER_TRADE
    risk_based_qty = int(max_risk_amount / risk_per_share)

    # ── Capital-cap quantity ──────────────────────────────────────────────
    max_capital = current_capital * MAX_CAPITAL_PER_TRADE
    capital_based_qty = int(max_capital / entry_price)

    # ── Available capital quantity ────────────────────────────────────────
    cash_buffer = current_capital * CASH_BUFFER_RATIO
    available = current_capital - existing_exposure - cash_buffer
    available = max(0, available)
    available_qty = int(available / entry_price)

    # ── Take the minimum ─────────────────────────────────────────────────
    quantity = min(risk_based_qty, capital_based_qty, available_qty)
    quantity = max(0, quantity)

    if quantity == 0:
        return {
            'valid': False,
            'reason': 'No capital available or risk too high for position',
            'quantity': 0,
            'risk_based_qty': risk_based_qty,
            'capital_based_qty': capital_based_qty,
            'available_qty': available_qty,
        }

    position_value = quantity * entry_price
    total_risk = quantity * risk_per_share

    # Calculate target for minimum R:R
    min_target = entry_price + (risk_per_share * MIN_RISK_REWARD_RATIO)

    # Transaction costs
    est_sell_value = quantity * min_target
    txn_cost = calculate_brokerage(position_value, est_sell_value)

    return {
        'valid': True,
        'quantity': quantity,
        'entry_price': round(entry_price, 2),
        'stop_loss': round(stop_loss, 2),
        'position_value': round(position_value, 2),
        'risk_amount': round(total_risk, 2),
        'risk_pct_of_capital': round(total_risk / current_capital * 100, 2),
        'risk_per_share': round(risk_per_share, 2),
        'risk_pct_of_price': round(risk_pct, 2),
        'min_target_for_rr': round(min_target, 2),
        'estimated_txn_cost': txn_cost,
        'sizing_method': (
            'risk_based' if quantity == risk_based_qty else
            'capital_capped' if quantity == capital_based_qty else
            'availability_limited'
        ),
        'risk_based_qty': risk_based_qty,
        'capital_based_qty': capital_based_qty,
        'available_qty': available_qty,
    }


def check_portfolio_risk(current_capital: float = None) -> dict:
    """
    Check current portfolio risk against all limits.
    Returns status of each risk check.
    """
    if current_capital is None:
        current_capital = TOTAL_CAPITAL

    conn = get_connection()
    cursor = conn.cursor()

    # Count open positions
    cursor.execute("""
        SELECT COUNT(*) as count, COALESCE(SUM(entry_price * quantity), 0) as exposure
        FROM trade_journal WHERE status = 'OPEN'
    """)
    row = cursor.fetchone()
    open_count = row['count']
    total_exposure = float(row['exposure'])

    # Today's realized P&L
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT COALESCE(SUM(net_pnl), 0) as daily_pnl
        FROM trade_journal WHERE date_exit = ? AND status = 'CLOSED'
    """, (today,))
    daily_pnl = float(cursor.fetchone()['daily_pnl'])

    # This week's P&L
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT COALESCE(SUM(net_pnl), 0) as weekly_pnl
        FROM trade_journal WHERE date_exit >= ? AND status = 'CLOSED'
    """, (week_start,))
    weekly_pnl = float(cursor.fetchone()['weekly_pnl'])

    # This month's P&L
    month_start = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT COALESCE(SUM(net_pnl), 0) as monthly_pnl
        FROM trade_journal WHERE date_exit >= ? AND status = 'CLOSED'
    """, (month_start,))
    monthly_pnl = float(cursor.fetchone()['monthly_pnl'])

    conn.close()

    # Calculate limits
    max_daily = current_capital * MAX_DAILY_LOSS
    max_weekly = current_capital * MAX_WEEKLY_LOSS
    max_monthly = current_capital * MAX_MONTHLY_DRAWDOWN
    cash_available = current_capital - total_exposure

    checks = {
        'open_positions': {
            'current': open_count,
            'limit': MAX_OPEN_POSITIONS,
            'ok': open_count < MAX_OPEN_POSITIONS,
            'message': f"{open_count}/{MAX_OPEN_POSITIONS} positions open"
        },
        'daily_loss': {
            'current': abs(min(0, daily_pnl)),
            'limit': max_daily,
            'ok': abs(min(0, daily_pnl)) < max_daily,
            'message': f"Daily P&L: ₹{daily_pnl:+,.0f} (limit: -₹{max_daily:,.0f})"
        },
        'weekly_loss': {
            'current': abs(min(0, weekly_pnl)),
            'limit': max_weekly,
            'ok': abs(min(0, weekly_pnl)) < max_weekly,
            'message': f"Weekly P&L: ₹{weekly_pnl:+,.0f} (limit: -₹{max_weekly:,.0f})"
        },
        'monthly_drawdown': {
            'current': abs(min(0, monthly_pnl)),
            'limit': max_monthly,
            'ok': abs(min(0, monthly_pnl)) < max_monthly,
            'message': f"Monthly P&L: ₹{monthly_pnl:+,.0f} (limit: -₹{max_monthly:,.0f})"
        },
        'capital_deployed': {
            'current': total_exposure,
            'limit': current_capital * (1 - CASH_BUFFER_RATIO),
            'ok': total_exposure < current_capital * (1 - CASH_BUFFER_RATIO),
            'message': f"Deployed: ₹{total_exposure:,.0f} / ₹{current_capital:,.0f}"
        },
        'cash_available': {
            'current': cash_available,
            'min_required': current_capital * CASH_BUFFER_RATIO,
            'ok': cash_available > current_capital * CASH_BUFFER_RATIO,
            'message': f"Cash: ₹{cash_available:,.0f} (min buffer: ₹{current_capital * CASH_BUFFER_RATIO:,.0f})"
        }
    }

    # Overall
    all_ok = all(c['ok'] for c in checks.values())
    can_trade = all_ok

    # Specific blocks
    blocked_reasons = []
    if not checks['daily_loss']['ok']:
        blocked_reasons.append("⛔ DAILY LOSS LIMIT REACHED — No more trades today")
    if not checks['weekly_loss']['ok']:
        blocked_reasons.append("⛔ WEEKLY LOSS LIMIT REACHED — Review strategy")
    if not checks['monthly_drawdown']['ok']:
        blocked_reasons.append("⛔ MONTHLY DRAWDOWN LIMIT REACHED — Pause trading")
    if not checks['open_positions']['ok']:
        blocked_reasons.append(f"⛔ Maximum {MAX_OPEN_POSITIONS} positions already open")

    return {
        'can_trade': can_trade,
        'checks': checks,
        'blocked_reasons': blocked_reasons,
        'open_positions': open_count,
        'total_exposure': total_exposure,
        'cash_available': cash_available,
        'daily_pnl': daily_pnl,
        'weekly_pnl': weekly_pnl,
        'monthly_pnl': monthly_pnl,
    }


def get_portfolio_stats() -> dict:
    """Get overall portfolio performance statistics."""
    conn = get_connection()
    cursor = conn.cursor()

    # All closed trades
    cursor.execute("""
        SELECT * FROM trade_journal WHERE status = 'CLOSED' ORDER BY date_exit DESC
    """)
    trades = cursor.fetchall()

    # Open trades
    cursor.execute("SELECT * FROM trade_journal WHERE status = 'OPEN'")
    open_trades = cursor.fetchall()

    conn.close()

    if not trades:
        return {
            'total_trades': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'total_pnl': 0,
            'max_drawdown': 0,
            'avg_r_multiple': 0,
            'best_trade': 0,
            'worst_trade': 0,
            'avg_holding_days': 0,
            'expectancy': 0,
            'open_trades': len(open_trades),
        }

    pnls = [float(t['net_pnl']) for t in trades if t['net_pnl'] is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    r_multiples = [float(t['r_multiple']) for t in trades if t['r_multiple'] is not None]
    holding_days = [int(t['holding_days']) for t in trades if t['holding_days'] is not None]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(pnls) * 100 if pnls else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0

    # Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss) if pnls else 0

    # Max drawdown from equity curve
    cumulative = []
    running = 0
    for p in pnls:
        running += p
        cumulative.append(running)

    peak = 0
    max_dd = 0
    for c in cumulative:
        if c > peak:
            peak = c
        dd = peak - c
        if dd > max_dd:
            max_dd = dd

    return {
        'total_trades': len(pnls),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(win_rate, 1),
        'avg_pnl': round(sum(pnls) / len(pnls), 0) if pnls else 0,
        'total_pnl': round(total_pnl, 0),
        'total_pnl_pct': round(total_pnl / TOTAL_CAPITAL * 100, 1),
        'max_drawdown': round(max_dd, 0),
        'max_drawdown_pct': round(max_dd / TOTAL_CAPITAL * 100, 1),
        'avg_r_multiple': round(sum(r_multiples) / len(r_multiples), 2) if r_multiples else 0,
        'best_trade': round(max(pnls), 0) if pnls else 0,
        'worst_trade': round(min(pnls), 0) if pnls else 0,
        'avg_holding_days': round(sum(holding_days) / len(holding_days), 1) if holding_days else 0,
        'expectancy': round(expectancy, 0),
        'avg_win': round(avg_win, 0),
        'avg_loss': round(avg_loss, 0),
        'open_trades': len(open_trades),
        'profit_factor': round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else 0,
    }
