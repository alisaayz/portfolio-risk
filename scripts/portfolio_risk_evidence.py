"""Historical downside, exposures, and self-financing transaction-cost scenarios."""

from collections import defaultdict
import math
import json

import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, load_universe


COST_BPS = (0, 5, 25)
ROLE_LABELS = {
    'stock': 'Individual stocks', 'equity_etf': 'Equity ETFs', 'bond_etf': 'Bond ETFs',
    'gold_trust': 'Gold trust', 'unknown': 'Unclassified',
}


def matched_panel(connection, symbols, start, end):
    rows = connection.execute('''
        SELECT instrument_id, session_date, simple_return FROM returns_daily
        WHERE instrument_id IN (SELECT unnest(?)) AND session_date BETWEEN ? AND ?
    ''', [symbols, start, end]).df()
    return rows.pivot(index='session_date', columns='instrument_id', values='simple_return').sort_index().reindex(columns=symbols)


def downside_deviation(returns):
    return float(np.sqrt(252 * np.mean(np.minimum(returns, 0) ** 2)))


def rebalance(exposures, target, rate):
    """Buy and sell fractional exposures, charging rate on each dollar traded."""
    before = float(exposures.sum())
    after = before
    if rate:
        # Fixed-point map has Lipschitz constant rate for long-only unit weights.
        for _ in range(12):
            after = before - rate * np.abs(target * after - exposures).sum()
    positions = target * after
    traded = np.abs(positions - exposures)
    fee = rate * traded.sum()
    if not math.isclose(float(positions.sum() + fee), before, abs_tol=1e-12, rel_tol=1e-12):
        raise ValueError('Transaction-cost ledger failed to balance')
    return positions, float(fee), float(traded.sum()), int((traded > before * 1e-12).sum())


def replay(returns, target, trade_after, cost_bps, initial=None):
    rate = cost_bps / 10_000
    positions = target.copy()
    fees = notional = 0.
    trades = events = 0
    if initial is not None:
        positions, fees, notional, trades = rebalance(initial, target, rate)
        events = int(trades > 0)
    wealth = [1.]
    for index, day in enumerate(returns):
        positions *= 1 + day
        if trade_after[index]:
            positions, fee, traded, count = rebalance(positions, target, rate)
            fees += fee
            notional += traded
            trades += count
            events += int(count > 0)
        wealth.append(float(positions.sum()))
    return {'terminal_return': wealth[-1] - 1, 'fees_per_initial_dollar': fees,
            'traded_notional_per_initial_dollar': notional, 'trades': trades,
            'rebalance_events': events, 'wealth': np.array(wealth)}


def historical_evidence(connection, report, dates, synthetic=False):
    panel = matched_panel(connection, report['symbols'], report['history_start'], report['history_end'])
    panel = panel.reindex(dates[1:])
    values = panel.to_numpy()
    if not np.isfinite(values).all():
        raise ValueError('Incomplete matched historical risk evidence')
    registry = load_universe(ROOT / 'config/reference_universe.json')
    roles = {row['symbol']: row['kind'] for row in registry['instruments']} if not synthetic else {}
    composition = {} if synthetic else json.loads((ROOT / 'config/fund_evidence.json').read_text())['composition']
    # A month close is observable only with the next month's first session in the replay.
    # The final close has no trade, since there is no holding period after it.
    months = panel.index.to_period('M')
    schedules = {'daily': np.r_[np.ones(len(panel) - 1, dtype=bool), False],
                 'monthly': np.r_[months[:-1] != months[1:], False]}
    output = []
    for scenario in report['scenarios']:
        weights = scenario['weights']
        weighted = values @ weights
        worst = int(weighted.argmin())
        exposures = defaultdict(float)
        for symbol, weight in zip(report['symbols'], weights):
            if weight > 0:
                exposures[roles.get(symbol, 'unknown')] += float(weight)
        rows = []
        for label, schedule in schedules.items():
            for bps in COST_BPS:
                result = replay(values, weights, schedule, bps)
                result.pop('wealth')
                rows.append({'schedule': label, 'cost_bps': bps, **result})
        output.append({'portfolio_id': scenario['id'],
                       'downside_deviation': downside_deviation(weighted[-report['risk_window_sessions']:]),
                       'worst_session': str(panel.index[worst].date()), 'worst_return': float(weighted[worst]),
                       'exposures': {ROLE_LABELS[key]: value for key, value in exposures.items()},
                       'fund_snapshots': [{'symbol': symbol, **composition[symbol]}
                                          for symbol, weight in zip(report['symbols'], weights)
                                          if weight > 0 and symbol in composition and composition[symbol]['date'] <= report['history_end']],
                       'replay': rows})
    return {'portfolios': output, 'lookthrough': 'Underlying issuer overlap is unknown.',
            'classification_date': None if synthetic else registry['selected_on']}
