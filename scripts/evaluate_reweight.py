"""Evaluate the reweighting rule on the fixed development grid and demo holdings."""
from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.evaluate_baselines import evaluation_origins
from scripts.portfolio_baseline import validate_configuration
from scripts.portfolio_reweight import propose


def run():
    config = ROOT / 'config'
    spec = json.loads((config / 'final_evaluation.json').read_text())
    demo = json.loads((config / 'demo_portfolios.json').read_text())
    validate_configuration(demo)
    if not demo['is_demo'] or any(p['input_type'] != 'weights' for p in demo['portfolios']):
        raise ValueError('Use fixed-weight demonstration portfolios')
    baseline = json.loads((config / 'forecast_baselines.json').read_text())
    database = ROOT / 'data/warehouse/portfolio-risk.duckdb'
    if sha256(database) != spec['warehouse_sha256']:
        raise ValueError('Expected the audited DS-002 market snapshot')
    modeling = ROOT / 'data/modeling' / spec['modeling_dataset_id']
    manifest = json.loads((modeling / 'manifest.json').read_text())
    membership = modeling / 'split_membership.parquet'
    if (manifest['recipe']['market_dataset_id'] != spec['market_dataset_id']
            or sha256(membership) != manifest['exports']['split_membership']['sha256']):
        raise ValueError('Development date manifest differs from the audited snapshot')
    with duckdb.connect(str(database), read_only=True) as conn:
        returns = conn.sql("""SELECT instrument_id, session_date, simple_return FROM returns_daily
            WHERE session_date < DATE '2026-01-01'""").df()
        dates = conn.execute('SELECT * FROM read_parquet(?)', [str(membership)]).df()
    panel = returns.pivot(index='session_date', columns='instrument_id', values='simple_return').sort_index().iloc[1:]
    if not np.isfinite(panel.to_numpy()).all():
        raise ValueError('Incomplete development return panel')
    origins = pd.concat([evaluation_origins(dates, year, 'primary', baseline)
                         for year in baseline['development_years']])
    grid = origins[['origin_date', 'target_end_date']].drop_duplicates().sort_values('origin_date')
    if len(grid) != 36 or grid.origin_date.duplicated().any() or not origins.groupby('origin_date').size().eq(16).all():
        raise ValueError('Expected 36 shared development origins')
    scores = []
    limit = .10
    for portfolio in demo['portfolios']:
        symbols = [p['instrument_id'] for p in portfolio['positions']]
        current = np.array([p['weight'] for p in portfolio['positions']])
        equal_delta = np.full(len(current), 1 / len(current)) - current
        equal_turnover = np.abs(equal_delta).sum() / 2
        equal_weight = current + equal_delta * min(1, limit / equal_turnover) if equal_turnover else current
        values = panel[symbols].to_numpy()
        for row in grid.itertuples(index=False):
            end = panel.index.get_loc(row.origin_date) + 1
            future = values[end:end + 20]
            if end < 252 or len(future) != 20 or panel.index[end + 19] != row.target_end_date:
                raise ValueError('Risk or outcome window differs from the accepted calendar')
            unchanged = np.std(future @ current, ddof=1) * np.sqrt(252)
            equal = np.std(future @ equal_weight, ddof=1) * np.sqrt(252)
            for lookback in (63, 126, 252):
                covariance = np.cov(values[end-lookback:end], rowvar=False, ddof=1) * 252
                weights, _ = propose(covariance, current, np.zeros_like(current), np.ones_like(current), limit, None)
                observed = np.std(future @ weights, ddof=1) * np.sqrt(252)
                order = np.argsort(np.diag(covariance), kind='stable')
                low, high = order[0], order[-1]
                shift = min(limit, current[high], 1 - current[low])
                heuristic = current.copy()
                heuristic[high] -= shift
                heuristic[low] += shift
                simple = np.std(future @ heuristic, ddof=1) * np.sqrt(252)
                scores.append({
                    'portfolio_id': portfolio['id'], 'origin': str(row.origin_date.date()),
                    'target_end': str(row.target_end_date.date()), 'lookback': lookback,
                    'reweighted_pct': observed * 100, 'unchanged_pct': unchanged * 100,
                    'toward_equal_pct': equal * 100, 'simple_shift_pct': simple * 100, 'move_pct': np.abs(weights - current).sum() * 50,
                    'lower_than_unchanged': bool(observed < unchanged), 'lower_than_equal': bool(observed < equal),
                })
    by_window = pd.DataFrame(scores).groupby(['lookback', 'portfolio_id'], as_index=False).agg(
        dates=('origin', 'size'), reweighted_mean_pct=('reweighted_pct', 'mean'),
        unchanged_mean_pct=('unchanged_pct', 'mean'), toward_equal_mean_pct=('toward_equal_pct', 'mean'),
        simple_shift_mean_pct=('simple_shift_pct', 'mean'),
        mean_move_pct=('move_pct', 'mean'), lower_than_unchanged=('lower_than_unchanged', 'sum'),
        lower_than_equal=('lower_than_equal', 'sum'))
    return {'evaluation': 'RW-001 development replay', 'dataset_id': spec['market_dataset_id'],
            'portfolio_config_sha256': sha256(config / 'demo_portfolios.json'),
            'rule_code_sha256': sha256(ROOT / 'scripts/portfolio_reweight.py'),
            'evaluation_code_sha256': sha256(ROOT / 'scripts/evaluate_reweight.py'), 'budget': limit,
            'summary': by_window.to_dict('records'), 'observations': scores}


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, allow_nan=False))
