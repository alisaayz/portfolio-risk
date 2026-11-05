"""Run the frozen checkpoint 3 policy comparison on the saved DS-002 snapshot."""

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.portfolio_reweight import bounds_for_holdings, propose, simple_shift
from scripts.portfolio_risk_evidence import COST_BPS, downside_deviation, matched_panel, replay
from scripts.replacement_evidence import block_indices


EXAMPLES = (
    ('equity_heavy', ('AAPL', 'SPY', 'BND'), (.30, .50, .20), {'AAPL': {'locked': True}}),
    ('higher_bond', ('AAPL', 'SPY', 'BND'), (.10, .40, .50), {}),
    ('equity_bond_gold', ('QQQ', 'IWM', 'IEF', 'GLD'), (.35, .25, .25, .15), {}),
    ('stock_fund_credit', ('MSFT', 'JPM', 'EFA', 'LQD', 'HYG'), (.25, .15, .25, .25, .10), {'LQD': {'maximum': .30}}),
)


def score_policies(panel):
    scores = []
    for name, symbols, weights, constraints in EXAMPLES:
        values = panel[list(symbols)].to_numpy()
        current = np.array(weights)
        lower, upper, limit = bounds_for_holdings({'holdings': constraints, 'turnover_limit': .10}, symbols, current)
        for year in (2023, 2024, 2025):
            days = np.flatnonzero(panel.index.year == year)
            for origin in days[:-20:20]:
                training, future = values[origin - 251:origin + 1], values[origin + 1:origin + 21]
                if len(training) != 252 or len(future) != 20:
                    raise ValueError('Evaluation horizon differs from the frozen plan')
                covariance = np.cov(training, rowvar=False, ddof=1) * 252
                simple, _ = simple_shift(covariance, current, lower, upper, limit, None)
                optimal, _ = propose(covariance, current, lower, upper, limit, None)
                for policy, candidate in [('keep', current), ('simple', simple), ('optimizer', optimal)]:
                    turnover = float(np.abs(candidate - current).sum() / 2)
                    if (abs(candidate.sum() - 1) > 1e-10 or (candidate < lower - 1e-10).any()
                            or (candidate > upper + 1e-10).any() or turnover > limit + 1e-10):
                        raise ValueError(f'{policy} failed feasibility at {panel.index[origin]}')
                    results = [replay(future, candidate, np.zeros(20, dtype=bool), bps, initial=current)
                               for bps in COST_BPS]
                    wealth = results[0]['wealth']
                    np.testing.assert_allclose(wealth[1:], np.cumprod(1 + future, axis=0) @ candidate,
                                               rtol=0, atol=1e-12)
                    scores.append({'portfolio': name, 'origin': str(panel.index[origin].date()), 'year': year,
                                   'policy': policy, 'turnover': turnover,
                                   'downside': downside_deviation(wealth[1:] / wealth[:-1] - 1),
                                   **{f'net_{bps}': result['terminal_return']
                                      for bps, result in zip(COST_BPS, results)}})
    return pd.DataFrame(scores)


def summarize(scores):
    metrics = ['turnover', 'downside', 'net_0', 'net_5', 'net_25']
    summary = scores.groupby('policy')[metrics].mean()
    by_date = scores.groupby(['year', 'origin', 'policy'])[metrics].mean().unstack('policy')
    differences = by_date['downside']['optimizer'] - by_date['downside']['simple']
    net_difference = summary.loc['optimizer', 'net_5'] - summary.loc['simple', 'net_5']
    generator = np.random.default_rng(42)
    draws = []
    for _, group in differences.groupby(level='year'):
        values = group.to_numpy()
        draws.append(values[block_indices(len(values), 3, 2000, generator)])
    interval = np.quantile(np.concatenate(draws, axis=1).mean(axis=1), [.025, .975])
    select = differences.mean() <= -.0025 and (differences < 0).mean() > .5 and net_difference >= -.001
    return {'observations': len(scores), 'shared_dates': len(by_date), 'portfolios': scores.portfolio.nunique(),
            'feasible': len(scores), 'metrics': summary.to_dict('index'), 'default': 'optimizer' if select else 'simple',
            'optimizer_minus_simple_downside': float(differences.mean()),
            'optimizer_minus_simple_downside_interval': interval.tolist(),
            'optimizer_lower_downside_dates': int((differences < 0).sum()),
            'optimizer_minus_simple_net_5': float(net_difference)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    args = parser.parse_args()
    spec = json.loads((ROOT / 'config/final_evaluation.json').read_text())
    if sha256(args.database) != spec['warehouse_sha256']:
        raise ValueError('Expected the archived DS-002 warehouse checksum')
    symbols = sorted({symbol for _, holdings, _, _ in EXAMPLES for symbol in holdings})
    with duckdb.connect(str(args.database), read_only=True) as connection:
        panel = matched_panel(connection, symbols, '2020-01-01', '2025-12-31').iloc[1:]
    if not np.isfinite(panel.to_numpy()).all():
        raise ValueError('Incomplete aligned return panel')
    scores = score_policies(panel)
    print(json.dumps({'dataset_id': spec['market_dataset_id'], 'warehouse_sha256': spec['warehouse_sha256'],
                      'protocol_sha256': sha256(ROOT / 'docs/V2_RISK_PROTOCOL.md'),
                      **summarize(scores), 'cases': scores.to_dict('records')}, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
