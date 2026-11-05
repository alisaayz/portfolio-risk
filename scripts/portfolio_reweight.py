"""Constrained historical-risk scenarios for existing holdings."""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize

from scripts.portfolio_baseline import analyze


WEIGHT_TOLERANCE = 1e-10
RISK_TOLERANCE = 1e-8


def fraction(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f'{name} must be between 0% and 100%')
    return float(value)


def bounds_for_holdings(constraints, symbols, current):
    if not isinstance(constraints, dict) or set(constraints) != {'turnover_limit', 'holdings'}:
        raise ValueError('Provide a move limit and holding constraints')
    limit = fraction(constraints['turnover_limit'], 'Move limit')
    holdings = constraints['holdings']
    if not isinstance(holdings, dict) or set(holdings) - set(symbols):
        raise ValueError('Holding constraints must refer to existing positions')
    lower, upper = np.zeros(len(current)), np.ones(len(current))
    for index, symbol in enumerate(symbols):
        rule = holdings.get(symbol, {})
        if not isinstance(rule, dict) or set(rule) - {'minimum', 'maximum', 'locked'}:
            raise ValueError(f'Invalid weight constraints for {symbol}')
        minimum = fraction(rule.get('minimum', 0), f'{symbol} minimum')
        maximum = fraction(rule.get('maximum', 1), f'{symbol} maximum')
        locked = rule.get('locked', False)
        if type(locked) is not bool:
            raise ValueError(f'{symbol} lock must be true or false')
        weight = current[index]
        if not minimum <= weight <= maximum:
            raise ValueError(f'{symbol} limits must include its current weight. Edit the limits and try again.')
        lower[index], upper[index] = (weight, weight) if locked else (minimum, maximum)
    return lower, upper, limit


def propose(covariance, current, lower, upper, limit, target):
    """Minimize estimated variance, then stop at the target along that path."""
    def volatility(weights):
        return math.sqrt(max(0.0, float(weights @ covariance @ weights)))

    before = volatility(current)
    if target is not None and before <= target + RISK_TOLERANCE:
        return current, 'already_within_target'
    buy_limit = upper - current
    sell_limit = current - lower
    if limit == 0 or (upper > lower).sum() < 2 or not buy_limit.any() or not sell_limit.any():
        return current, 'no_improvement'

    count = len(current)
    scale = max(float(np.diag(covariance).max()), 1e-12)
    scaled = covariance / scale
    unit = np.ones(count)
    balance = np.r_[unit, -unit]
    purchase = np.r_[unit, np.zeros(count)]

    def weights_for(trades):
        return current + (trades[:count] - trades[count:])

    def variance(trades):
        weights = weights_for(trades)
        return weights @ scaled @ weights

    def gradient(trades):
        derivative = 2 * (scaled @ weights_for(trades))
        return np.r_[derivative, -derivative]

    solution = minimize(variance, np.zeros(2 * count), jac=gradient, method='SLSQP',
                        bounds=list(zip(np.zeros(2 * count), np.r_[buy_limit, sell_limit])),
                        constraints=[
                            {'type': 'eq', 'fun': lambda trades: balance @ trades, 'jac': lambda _: balance},
                            {'type': 'ineq', 'fun': lambda trades: limit - purchase @ trades, 'jac': lambda _: -purchase},
                        ],
                        options={'ftol': 1e-12, 'maxiter': 300})
    if not solution.success:
        raise ValueError('Could not verify a solution for these constraints. Review the limits and try again.')
    candidate = np.clip(weights_for(solution.x), lower, upper)
    after = volatility(candidate)
    if after >= before - RISK_TOLERANCE:
        return current, 'no_improvement'
    status = 'lower_risk' if target is None else 'target_unreachable'
    if target is not None and after <= target:
        # Along this segment the feasible set is convex and the first crossing minimizes
        # the size of the move on this particular path.
        left, right = 0.0, 1.0
        for _ in range(48):
            mid = (left + right) / 2
            if volatility(current + mid * (candidate - current)) <= target:
                right = mid
            else:
                left = mid
        candidate = current + right * (candidate - current)
        status = 'target_met'
    if (not np.isfinite(candidate).all()
            or abs(float(candidate.sum()) - 1) > WEIGHT_TOLERANCE
            or (candidate < lower - WEIGHT_TOLERANCE).any()
            or (candidate > upper + WEIGHT_TOLERANCE).any()
            or np.abs(candidate - current).sum() / 2 > limit + WEIGHT_TOLERANCE):
        raise ValueError('The calculated scenario did not satisfy the weight constraints')
    return candidate, status


def assess_reweight(connection, config, constraints, target):
    if len(config['portfolios']) != 1 or config['portfolios'][0]['input_type'] != 'weights':
        raise ValueError('Reweighting requires one current portfolio entered as weights')
    report, _ = analyze(connection, config)
    current = report['scenarios'][0]
    symbols, original = report['symbols'], current['weights']
    lower, upper, limit = bounds_for_holdings(constraints, symbols, original)
    candidate, status = propose(report['annualized_covariance'], original, lower, upper, limit, target)
    moved = np.abs(candidate - original).sum() / 2
    alternative = current
    if moved > 0:
        alternative_config = {
            **config,
            'portfolios': [{**config['portfolios'][0], 'id': 'reweight_current'}, {
                'id': 'reweighted', 'name': 'Reweighted scenario', 'input_type': 'weights',
                'positions': [{'instrument_id': symbol, 'weight': float(weight)}
                              for symbol, weight in zip(symbols, candidate) if weight > 0],
            }],
        }
        comparison, _ = analyze(connection, alternative_config)
        alternative = comparison['scenarios'][1]
        np.testing.assert_allclose(alternative['weights'], candidate, rtol=0, atol=WEIGHT_TOLERANCE)
        expected_risk = math.sqrt(max(0.0, float(candidate @ report['annualized_covariance'] @ candidate)))
        np.testing.assert_allclose(alternative['annualized_sample_volatility'], expected_risk, rtol=0, atol=RISK_TOLERANCE)
    return {
        'method': 'RW-001', 'status': status, 'turnover': moved, 'target': target, 'turnover_limit': limit,
        'as_of_date': report['risk_window_end'], 'risk_window_sessions': report['risk_window_sessions'],
        'current_volatility': current['annualized_sample_volatility'],
        'alternative_volatility': alternative['annualized_sample_volatility'],
        'current_drawdown': current['maximum_drawdown'], 'alternative_drawdown': alternative['maximum_drawdown'],
        'current_largest_weight': original.max(), 'alternative_largest_weight': candidate.max(),
        'holdings': [
            {'symbol': symbol, 'current_weight': original[index], 'alternative_weight': candidate[index],
             'current_risk_share': current['risk_shares'][index], 'alternative_risk_share': alternative['risk_shares'][index]}
            for index, symbol in enumerate(symbols)
        ],
    }
