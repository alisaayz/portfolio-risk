"""Historical risk criteria for a partial or full one-holding swap."""
from __future__ import annotations

import hashlib
import json
import math

import duckdb
import numpy as np

from scripts.audit_market_data import ROOT, load_universe

from scripts.portfolio_baseline import analyze
from scripts.replacement_evidence import add_replacement_evidence
from scripts.portfolio_reweight import WEIGHT_TOLERANCE, bounds_for_holdings, fraction


CORRELATIONS = (-0.75, -0.5, 0.0, 0.5, 0.75)


def volatility_band(remaining_risk, swap, target, correlation):
    """Return the standalone volatility range that satisfies the variance limit."""
    discriminant = target**2 - remaining_risk**2 * (1 - correlation**2)
    if discriminant < -1e-15:
        return None
    center = -correlation * remaining_risk
    radius = math.sqrt(max(0.0, discriminant))
    lower, upper = max(0.0, center - radius), center + radius
    if upper < lower - 1e-12:
        return None
    return {'minimum': lower / swap, 'maximum': max(lower, upper) / swap}


def replacement_criteria(connection, config, constraints, replacement, target, universe=None, options=None, database=None):
    if len(config['portfolios']) != 1 or config['portfolios'][0]['input_type'] != 'weights':
        raise ValueError('Replacement criteria require one current portfolio entered as weights')
    if not isinstance(replacement, dict) or set(replacement) != {'symbol', 'weight'}:
        raise ValueError('Choose one holding and an amount to replace')
    symbol, swap = replacement['symbol'], fraction(replacement['weight'], 'Replacement weight')
    if swap == 0:
        raise ValueError('Replacement weight must be above zero')

    report, _ = analyze(connection, config)
    current = report['scenarios'][0]
    symbols, weights = report['symbols'], current['weights']
    if not isinstance(symbol, str) or symbol not in symbols:
        raise ValueError('Choose an existing holding')
    lower, _, limit = bounds_for_holdings(constraints, symbols, weights)
    index = symbols.index(symbol)
    maximum = min(float(weights[index] - lower[index]), limit)
    if maximum <= 0 or swap > maximum + WEIGHT_TOLERANCE:
        raise ValueError(f'{symbol} allows up to {100 * maximum:.4g}% to be replaced under your limits')
    swap = min(swap, maximum)

    covariance = report['annualized_covariance']
    remainder = weights.copy()
    remainder[index] -= swap
    remaining_risk = math.sqrt(max(0, float(remainder @ covariance @ remainder)))
    current_risk = float(current['annualized_sample_volatility'])
    target_risk = current_risk if target is None else target
    if remaining_risk > 0:
        bands = [{'correlation': rho, 'volatility': volatility_band(remaining_risk, swap, target_risk, rho)}
                 for rho in CORRELATIONS]
    else:
        bands = [{'correlation': None, 'volatility': {'minimum': 0.0, 'maximum': target_risk / swap}}]
    result = {
        'method': 'RP-001', 'symbol': symbol, 'replacement_weight': swap,
        'current_volatility': current_risk, 'target': target_risk,
        'target_source': 'current_estimate' if target is None else 'manual_reference',
        'remainder_volatility_contribution': remaining_risk,
        'risk_window_sessions': report['risk_window_sessions'],
        'risk_window_start': report['risk_window_start'], 'risk_window_end': report['risk_window_end'],
        'bands': bands,
    }

    if universe is not None:
        result['screen'] = screen_candidates(connection, report, remainder, result, universe)
        if options is not None:
            add_replacement_evidence(connection, database, report, weights, remainder, result, universe, options)
    return result


def accepted_screen_universe(database):
    registry = load_universe(ROOT / 'config/reference_universe.json')
    registry_hash = hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest()
    with duckdb.connect(str(database), read_only=True) as connection:
        dataset_id, recipe = connection.execute('''
            SELECT dataset_id, recipe_json FROM active_dataset JOIN dataset_versions USING (dataset_id)
        ''').fetchone()
        accepted = {row[0] for row in connection.execute(
            'SELECT DISTINCT instrument_id FROM accepted_prices_daily').fetchall()}
    policy = json.loads(recipe)['policy']
    if (policy['policy_id'] != 'DS-002' or policy.get('universe_id') != registry['universe_id']
            or policy.get('universe_sha256') != registry_hash):
        raise ValueError('Candidate screening requires the audited DS-002 research universe')
    return {
        'policy': policy['policy_id'], 'dataset_id': dataset_id, 'universe_id': registry['universe_id'],
        'classification_date': registry['selected_on'],
        'instruments': [row for row in registry['instruments'] if row['symbol'] in accepted],
    }


def screen_candidates(connection, report, remainder, criteria, universe):
    held = report['symbols']
    candidates = {row['symbol']: row for row in universe['instruments'] if row['symbol'] not in held}
    start, end = report['risk_window_start'], report['risk_window_end']
    rows = connection.execute('''
        SELECT instrument_id, session_date, simple_return FROM returns_daily
        WHERE instrument_id IN (SELECT unnest(?)) AND session_date BETWEEN ? AND ?
    ''', [held + sorted(candidates), start, end]).df()
    panel = rows.pivot(index='session_date', columns='instrument_id', values='simple_return').sort_index()
    original = panel[held].dropna()
    if len(original) != report['risk_window_sessions']:
        raise ValueError('The original risk window could not be matched')
    remaining_returns = original.to_numpy() @ remainder
    scale = math.sqrt(252)
    remaining_risk = float(np.std(remaining_returns, ddof=1) * scale)
    np.testing.assert_allclose(remaining_risk, criteria['remainder_volatility_contribution'], rtol=0, atol=1e-10)
    results = []
    swap, target = criteria['replacement_weight'], criteria['target']
    for symbol, candidate in candidates.items():
        label = {'symbol': symbol, 'research_role': candidate['research_role']}
        matched = panel.reindex(index=original.index, columns=[symbol])[symbol].to_numpy()
        if not np.isfinite(matched).all():
            results.append({**label, 'status': 'unavailable'})
            continue
        volatility = float(np.std(matched, ddof=1) * scale)
        covariance = float(np.cov(remaining_returns, matched, ddof=1)[0, 1] * 252)
        correlation = float(np.clip(covariance / (remaining_risk * volatility), -1, 1)) if remaining_risk and volatility else None
        estimate = float(np.std(remaining_returns + swap * matched, ddof=1) * scale)
        variance = remaining_risk**2 + (swap * volatility)**2 + 2 * swap * covariance
        np.testing.assert_allclose(estimate**2, variance, rtol=0, atol=1e-12)
        results.append({**label, 'status': 'meets_target' if estimate <= target else 'above_target',
                        'standalone_volatility': volatility, 'correlation': correlation,
                        'portfolio_volatility': estimate})
    results.sort(key=lambda row: (row.get('portfolio_volatility', math.inf), row['symbol']))
    return {key: universe[key] for key in ('policy', 'dataset_id', 'universe_id')} | {'candidates': results}
