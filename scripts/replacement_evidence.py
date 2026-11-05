"""Eligibility and matched-window historical sensitivity for a replacement."""

from datetime import date
import json
import math

import duckdb
import numpy as np
from sklearn.covariance import ledoit_wolf

from scripts.audit_market_data import ROOT
from scripts.portfolio_reweight import fraction
from scripts.portfolio_risk_evidence import ROLE_LABELS, matched_panel


WINDOWS = (63, 126, 252)


def validate_filters(options):
    keys = {'role', 'max_position', 'min_dollar_volume', 'max_fund_fee'}
    if not isinstance(options, dict) or set(options) - keys:
        raise ValueError('Provide supported replacement filters')
    role = options.get('role')
    if role is not None and (not isinstance(role, str) or role not in ROLE_LABELS or role == 'unknown'):
        raise ValueError('Choose an available replacement exposure')
    cap = options.get('max_position')
    fee = options.get('max_fund_fee')
    volume = options.get('min_dollar_volume')
    if volume is not None and (type(volume) not in (int, float) or not 0 <= volume <= 1e12):
        raise ValueError('Enter a dollar-volume floor from 0 to 1 trillion USD')
    return {'role': role, 'max_position': None if cap is None else fraction(cap, 'Position cap'),
            'min_dollar_volume': volume, 'max_fund_fee': None if fee is None else fraction(fee, 'Fund fee cap')}


def volume_evidence(database, symbols, dates):
    if not len(dates):
        return {}
    expected = [day.date() for day in dates]
    with duckdb.connect(str(database), read_only=True) as connection:
        rows = connection.execute('''
            SELECT instrument_id, count(*) AS sessions, median(close * volume) AS median_dollars
            FROM accepted_prices_daily
            WHERE instrument_id IN (SELECT unnest(?)) AND session_date IN (SELECT unnest(?))
              AND isfinite(close) AND close > 0 AND volume > 0
            GROUP BY instrument_id
        ''', [symbols, expected]).fetchall()
    return {symbol: {'median_usd': amount, 'start': expected[0].isoformat(), 'end': expected[-1].isoformat()}
            for symbol, count, amount in rows if count == len(expected) == 20 and math.isfinite(amount)}


def eligibility(filters, candidate, largest, volume, fee):
    reasons = []
    if filters['role'] is not None and filters['role'] != candidate['kind']:
        reasons.append('Different exposure from the requested role')
    if filters['max_position'] is not None and largest > filters['max_position'] + 1e-10:
        reasons.append('Resulting portfolio exceeds the position cap')
    floor = filters['min_dollar_volume']
    if floor is not None and (volume is None or volume['median_usd'] < floor):
        reasons.append('Dollar-volume evidence unavailable' if volume is None else 'Below the dollar-volume floor')
    cap = filters['max_fund_fee']
    if cap is not None and candidate['kind'] != 'stock' and (fee is None or fee['annual_ratio'] > cap):
        reasons.append('Dated fund fee unavailable' if fee is None else 'Above the annual fund fee cap')
    return reasons


def block_indices(count, block, draws, generator):
    starts = generator.integers(count, size=(draws, math.ceil(count / block), 1))
    return ((starts + np.arange(block)) % count).reshape(draws, -1)[:, :count]


def paired_interval(current, alternative, indices):
    difference = (np.std(alternative[indices], axis=1, ddof=1) -
                  np.std(current[indices], axis=1, ddof=1)) * math.sqrt(252)
    return np.quantile(difference, [.025, .975]).tolist()


def window_scores(matrix, current, alternative, fixed_target):
    results = []
    for size in WINDOWS:
        sample = matrix[-size:]
        if len(sample) < size or not np.isfinite(sample).all():
            continue
        shrunk, _ = ledoit_wolf(sample)
        for method, covariance in [('sample', np.cov(sample, rowvar=False, ddof=1)), ('shrinkage', shrunk)]:
            estimate = math.sqrt(max(0, float(alternative @ covariance @ alternative) * 252))
            baseline = math.sqrt(max(0, float(current @ covariance @ current) * 252))
            target = baseline if fixed_target is None else fixed_target
            results.append({'window': size, 'estimator': method, 'portfolio_volatility': estimate,
                            'target': target, 'within_target': estimate <= target + 1e-12})
    return results


def qualification(scores):
    if len(scores) != 2 * len(WINDOWS):
        return 'incomplete'
    passes = sum(row['within_target'] for row in scores)
    return 'stable' if passes == len(scores) else 'sensitive' if passes else 'above'


def rank_candidates(rows):
    complete = [row for row in rows if row['decision'] in {'stable', 'sensitive', 'above'}]
    for index in range(2 * len(WINDOWS)):
        ranking = sorted(complete, key=lambda row: (row['window_scores'][index]['portfolio_volatility'], row['symbol']))
        for rank, row in enumerate(ranking, start=1):
            row['window_scores'][index]['rank'] = rank


def add_replacement_evidence(connection, database, report, current, remainder, result, universe, options):
    filters = validate_filters(options)
    accepted = {row['symbol']: row for row in universe['instruments']}
    candidates = result['screen']['candidates']
    symbols = report['symbols']
    panel = matched_panel(connection, symbols + [row['symbol'] for row in candidates],
                          report['history_start'], report['history_end'])
    # Exclude the anchor close, and align to actual common return dates.
    aligned = panel.loc[panel.index > report['history_start']]
    aligned = aligned.loc[aligned[symbols].notna().any(axis=1)].tail(max(WINDOWS))
    if not np.isfinite(aligned[symbols].to_numpy()).all():
        raise ValueError('Incomplete current portfolio evidence')
    volumes = volume_evidence(database, [row['symbol'] for row in candidates], aligned.index[-20:])
    fees = json.loads((ROOT / 'config/fund_evidence.json').read_text())['fees']
    end = date.fromisoformat(report['history_end'])
    largest = max(float(remainder.max()), result['replacement_weight'])
    selected = report['risk_window_sessions']
    indices = block_indices(selected, 10, 400, np.random.default_rng(42)) if selected >= 126 else None
    target = result['target'] if result['target_source'] == 'manual_reference' else None
    base_weights = np.r_[current, 0.]
    new_weights = np.r_[remainder, result['replacement_weight']]
    for row in candidates:
        symbol = row['symbol']
        fee = fees.get(symbol)
        if fee and not 0 <= (end - date.fromisoformat(fee['date'])).days <= 366:
            fee = None
        volume = volumes.get(symbol)
        candidate = accepted[symbol]
        reasons = eligibility(filters, candidate, largest, volume, fee)
        matrix = aligned[symbols + [symbol]].to_numpy()
        scores = [] if reasons else window_scores(matrix, base_weights, new_weights, target)
        row.update(kind=candidate['kind'], exclusions=reasons, fund_fee=fee, dollar_volume=volume,
                   decision='excluded' if reasons else qualification(scores), window_scores=scores,
                   largest_position=largest, paired_interval=None)
        sample = matrix[-selected:]
        if not reasons and indices is not None and len(sample) == selected and np.isfinite(sample).all():
            row['paired_interval'] = paired_interval(sample @ base_weights, sample @ new_weights, indices)
    rank_candidates(candidates)
    result['screen'].update(filters=filters, classification_date=universe['classification_date'])
