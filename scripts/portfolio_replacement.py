"""Historical risk criteria for a partial or full one-holding swap."""
from __future__ import annotations

import math

import numpy as np

from scripts.portfolio_baseline import analyze
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


def replacement_criteria(connection, config, constraints, replacement, target):
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
    return {
        'method': 'RP-001', 'symbol': symbol, 'replacement_weight': swap,
        'current_volatility': current_risk, 'target': target_risk,
        'target_source': 'current_estimate' if target is None else 'manual_reference',
        'remainder_volatility_contribution': remaining_risk,
        'risk_window_sessions': report['risk_window_sessions'],
        'risk_window_start': report['risk_window_start'], 'risk_window_end': report['risk_window_end'],
        'bands': bands,
    }
