"""Run the frozen EV-002 retrospective model holdout."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
import subprocess
from tempfile import TemporaryDirectory

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.evaluate_baselines import KEYS, ewma_variance, score_matched_variances
from scripts.evaluate_portfolio_forecasts import ANNUAL_SESSIONS, DEMO
from scripts.portfolio_baseline import validate_configuration
from scripts.train_risk_model import fit_candidate, predict_variance, validate_configuration as validate_training
from scripts.verify_training_experiment import verify


PROTOCOL = ROOT / 'config/final_evaluation.json'
WAREHOUSE = ROOT / 'data/warehouse/portfolio-risk.duckdb'
OUTPUT = ROOT / 'data/experiments/final_evaluation'
START = pd.Timestamp('2026-01-01')
END = pd.Timestamp('2027-01-01')
HORIZON = 20


def verify_freeze(commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Provide the full freeze commit SHA')
    subprocess.run(['git', 'merge-base', '--is-ancestor', commit, 'HEAD'], cwd=ROOT, check=True)
    tracked = ['scripts', 'sql', 'config', 'requirements.txt', 'docs/FINAL_EVALUATION_PROTOCOL.md']
    for file in (PROTOCOL, Path(__file__)):
        subprocess.run(['git', 'cat-file', '-e', f'{commit}:{file.relative_to(ROOT)}'], cwd=ROOT, check=True)
    subprocess.run(['git', 'diff', '--quiet', commit, '--', *tracked], cwd=ROOT, check=True)


def load_inputs(spec):
    experiment = ROOT / 'data/experiments/trained_models' / spec['training_experiment_id']
    modeling = ROOT / 'data/modeling' / spec['modeling_dataset_id']
    verify(experiment)
    trained = json.loads((experiment / 'summary.json').read_text())
    recipe = trained['recipe']
    if (trained['selected_model'] != spec['trained_method'] or trained['selected_ewma'] != spec['ewma_method']
            or recipe['modeling_dataset_id'] != spec['modeling_dataset_id']
            or recipe['modeling_manifest_sha256'] != sha256(modeling / 'manifest.json')):
        raise ValueError('Development selection or modeling provenance differs from the freeze')
    if recipe['python'] != platform.python_version() or any(
            version(package) != pinned for package, pinned in recipe['packages'].items()):
        raise ValueError('Runtime versions differ from the frozen model environment')
    manifest = json.loads((modeling / 'manifest.json').read_text())
    if manifest['recipe']['market_dataset_id'] != spec['market_dataset_id'] or sha256(WAREHOUSE) != spec['warehouse_sha256']:
        raise ValueError('Market snapshot differs from the freeze')
    for name in ('split_membership', 'features_daily', 'development_examples'):
        if sha256(modeling / f'{name}.parquet') != manifest['exports'][name]['sha256']:
            raise ValueError(f'Hash mismatch for {name}')

    with duckdb.connect() as conn:
        train = conn.execute('''SELECT * FROM read_parquet(?)
            WHERE final_refit_eligible ORDER BY instrument_id, origin_date''',
                             [str(modeling / 'development_examples.parquet')]).df()
        features = conn.execute('SELECT * FROM read_parquet(?) ORDER BY instrument_id, origin_date',
                                [str(modeling / 'features_daily.parquet')]).df()
        dates = conn.execute('''SELECT instrument_id, origin_date, target_end_date,
                primary_test_scorable_when_opened AS is_primary
            FROM read_parquet(?) WHERE test_eligible_when_opened ORDER BY origin_date, instrument_id''',
                             [str(modeling / 'split_membership.parquet')]).df()
    return recipe['training_configuration'], train, features, dates


def check_membership(train, dates, spec):
    counts = train.groupby('instrument_id').size()
    valid_train = (train.feature_ready & train.target_complete
                   & (train.target_end_date > train.origin_date)
                   & (train.origin_date < START) & (train.target_end_date < START)
                   & np.isfinite(train.target_variance) & (train.target_variance >= 0))
    if (len(counts) != spec['instrument_count'] or not counts.eq(spec['refit_rows_per_instrument']).all()
            or train.duplicated(KEYS).any() or not valid_train.all()):
        raise ValueError('Refit requires the complete eligible pre-2026 sample')
    valid_dates = (dates.origin_date >= START) & (dates.origin_date < dates.target_end_date) & (dates.target_end_date < END)
    if (dates.duplicated(KEYS).any() or not valid_dates.all()
            or set(dates.instrument_id) != set(counts.index)):
        raise ValueError('Invalid test dates or instrument universe')
    grid = dates[['origin_date', 'target_end_date', 'is_primary']].drop_duplicates()
    if (grid.origin_date.duplicated().any() or len(grid) != spec['daily_origins_per_instrument']
            or len(dates) != len(grid) * len(counts)):
        raise ValueError('Test methods require a common and complete origin grid')
    primary = grid.loc[grid.is_primary, ['origin_date', 'target_end_date']]
    if primary.apply(lambda column: column.dt.strftime('%Y-%m-%d')).values.tolist() != spec['primary_windows']:
        raise ValueError('Primary windows differ from the freeze')
    return grid


def return_panel(features):
    panel = features.pivot(index='origin_date', columns='instrument_id', values='return_1').sort_index().iloc[1:]
    if panel.empty or not np.isfinite(panel.to_numpy()).all() or (panel <= -1).any().any():
        raise ValueError('Require complete calendar-aligned simple returns')
    return panel


def holding_forecasts(config, train, features, dates, spec):
    validate_training(config)
    method = spec['trained_method']
    candidate = next(candidate for candidate in config['candidates'] if candidate['method'] == method)
    baseline = features.loc[features.origin_date <= dates.origin_date.max()].copy()
    baseline['ewma'] = np.nan
    for _, group in baseline.groupby('instrument_id'):
        squared = ANNUAL_SESSIONS * group.return_1.to_numpy()**2
        forecast, _ = ewma_variance(squared, spec['ewma_decay'])
        reference = pd.Series(squared).ewm(alpha=1-spec['ewma_decay'], adjust=False).mean().to_numpy()
        np.testing.assert_allclose(forecast, reference, atol=1e-12, rtol=0, equal_nan=True)
        baseline.loc[group.index, 'ewma'] = forecast
    rows = dates[KEYS].merge(baseline, on=KEYS, how='left', validate='one_to_one')
    if not rows.feature_ready.eq(True).all():
        raise ValueError('Frozen dates require ready feature vectors')
    model = fit_candidate(train, candidate, config)
    trained = predict_variance(model, rows)
    np.testing.assert_array_equal(trained, predict_variance(fit_candidate(train, candidate, config), rows))
    return rows[KEYS].assign(**{method: trained, spec['ewma_method']: rows.ewma,
                                spec['trailing_method']: rows.variance_20})


def portfolio_forecasts(holdings, panel, grid, demo, spec):
    methods = [spec[key] for key in ('trailing_method', 'ewma_method', 'trained_method')]
    wide = holdings.set_index(['origin_date', 'instrument_id'])
    records = []
    for origin in grid.origin_date:
        end = panel.index.get_loc(origin) + 1
        history = panel.iloc[end - spec['portfolio_lookback_sessions']:end]
        if len(history) != spec['portfolio_lookback_sessions']:
            raise ValueError('Incomplete portfolio co-movement window')
        for portfolio in demo['portfolios']:
            symbols = [position['instrument_id'] for position in portfolio['positions']]
            weights = np.array([position['weight'] for position in portfolio['positions']])
            returns = history[symbols].to_numpy()
            norms = np.linalg.norm(returns, axis=0)
            if (norms == 0).any():
                raise ValueError('Flat holding history cannot estimate co-movement')
            standardized = returns / norms
            covariance = standardized.T @ standardized
            predicted = {methods[0]: ANNUAL_SESSIONS * np.mean((returns[-HORIZON:] @ weights)**2)}
            for method in methods[1:]:
                exposures = weights * np.sqrt(wide.loc[origin, method].reindex(symbols).to_numpy())
                predicted[method] = exposures @ covariance @ exposures
                np.testing.assert_allclose(predicted[method], np.sum((standardized @ exposures)**2), rtol=1e-12)
            records.append({'instrument_id': portfolio['id'], 'origin_date': origin, **predicted})
    return pd.DataFrame(records)


def realized(panel, grid, demo):
    """Use exact forward dates and independently compare the NumPy target with SQL."""
    expected = panel.loc[(panel.index >= START) & (panel.index < END)]
    weights = pd.DataFrame([{'portfolio_id': portfolio['id'], **position}
                            for portfolio in demo['portfolios'] for position in portfolio['positions']])
    with duckdb.connect(str(WAREHOUSE), read_only=True) as conn:
        returns = conn.execute('''SELECT instrument_id, session_date, simple_return FROM returns_daily
            WHERE session_date >= ? AND session_date < ?''', [START.date(), END.date()]).df()
    returns_wide = returns.pivot(index='session_date', columns='instrument_id', values='simple_return')
    pd.testing.assert_frame_equal(expected, returns_wide, check_names=False, check_freq=False, rtol=1e-12, atol=1e-14)
    with duckdb.connect() as conn:
        conn.register('holdings_returns', returns)
        conn.register('weights', weights)
        sql_targets = conn.sql("""
            WITH returns AS (
                SELECT instrument_id, session_date, simple_return AS r FROM holdings_returns
                UNION ALL
                SELECT portfolio_id, session_date, sum(weight * simple_return)
                FROM holdings_returns JOIN weights USING(instrument_id) GROUP BY portfolio_id, session_date
            )
            SELECT instrument_id, session_date AS origin_date,
                   lead(session_date, 20) OVER dates AS end_date,
                   count(r) OVER forward_window AS observed,
                   252 * avg(r * r) OVER forward_window AS target_variance
            FROM returns
            WINDOW dates AS (PARTITION BY instrument_id ORDER BY session_date),
                   forward_window AS (dates ROWS BETWEEN 1 FOLLOWING AND 20 FOLLOWING)
        """).df().set_index(['origin_date', 'instrument_id']).sort_index()
    portfolio_returns = {
        portfolio['id']: sum(expected[p['instrument_id']] * p['weight'] for p in portfolio['positions'])
        for portfolio in demo['portfolios']
    }
    paths = expected.assign(**portfolio_returns)
    observations = []
    for row in grid.itertuples(index=False):
        position = paths.index.get_loc(row.origin_date)
        future = paths.iloc[position + 1:position + 1 + HORIZON]
        if len(future) != HORIZON or future.index[-1] != row.target_end_date:
            raise ValueError('Incomplete outcome or incorrect target end')
        reference = ANNUAL_SESSIONS * np.mean(future.to_numpy()**2, axis=0)
        matching = sql_targets.loc[row.origin_date].reindex(paths.columns)
        if not matching.observed.eq(HORIZON).all() or not matching.end_date.eq(row.target_end_date).all():
            raise ValueError('SQL outcome differs from the frozen exchange session horizon')
        np.testing.assert_allclose(reference, matching.target_variance, rtol=1e-12)
        observations.extend({'instrument_id': entity, 'origin_date': row.origin_date, 'target_variance': value}
                            for entity, value in zip(paths.columns, reference))
    return pd.DataFrame(observations)


def interval(differences, block, spec):
    rng = np.random.default_rng(spec['bootstrap_seed'])
    n = len(differences)
    starts = rng.integers(n, size=(spec['bootstrap_draws'], n // block, 1))
    indices = (starts + np.arange(block)) % n
    return np.quantile(differences[indices].mean(axis=(1, 2)), [.025, .975]).tolist()


def summarize(scores, portfolio_ids, spec):
    methods = [spec[key] for key in ('trained_method', 'ewma_method', 'trailing_method')]
    model = methods[0]
    by_entity = scores.groupby(['sample', 'scope', 'instrument_id', 'method'], as_index=False).agg(
        observations=('origin_date', 'size'), volatility_mae_pp=('volatility_absolute_error_pp', 'mean'),
        variance_qlike=('variance_qlike', 'mean'), prediction_floors=('prediction_floored', 'sum'))
    by_scope = by_entity.groupby(['sample', 'scope', 'method'], as_index=False).agg(
        observations=('observations', 'sum'), volatility_mae_pp=('volatility_mae_pp', 'mean'),
        variance_qlike=('variance_qlike', 'mean'), prediction_floors=('prediction_floors', 'sum'))
    comparisons = []
    for scope, group in scores.loc[scores['sample'] == 'primary'].groupby('scope'):
        losses = group.groupby(['origin_date', 'method']).volatility_absolute_error_pp.mean().unstack()
        for comparator in methods[1:]:
            differences = (losses[model] - losses[comparator]).to_numpy()
            for block in spec['bootstrap_block_lengths']:
                comparisons.append({'scope': scope, 'baseline': comparator, 'block_dates': block,
                                    'model_minus_baseline_mae_pp': float(differences.mean()),
                                    'nominal_95_interval_pp': interval(differences, block, spec)})
    primary = by_entity.loc[(by_entity['sample'] == 'primary') & by_entity.instrument_id.isin(portfolio_ids)]
    demo_mae = primary.pivot(index='instrument_id', columns='method', values='volatility_mae_pp')
    demo_comparisons = [row for row in comparisons
                        if row['scope'] == 'portfolio' and row['block_dates'] == spec['bootstrap_block_lengths'][0]]
    advance = (all(row['model_minus_baseline_mae_pp'] <= -spec['portfolio_minimum_improvement_pp']
                   and row['nominal_95_interval_pp'][1] < 0 for row in demo_comparisons)
               and (demo_mae[model].to_numpy()[:, None] <= demo_mae[methods[1:]].to_numpy()).all())
    return {'aggregates': by_scope.to_dict('records'), 'entities': by_entity.to_dict('records'),
            'paired_intervals': comparisons, 'advance_to_forward_dashboard_trial': bool(advance)}


def run(commit, score):
    verify_freeze(commit)
    spec = json.loads(PROTOCOL.read_text())
    configuration, train, features, dates = load_inputs(spec)
    grid = check_membership(train, dates, spec)
    metadata = {'freeze_commit': commit, 'protocol_sha256': sha256(PROTOCOL), 'training_rows': len(train),
                'latest_training_target_end': str(train.target_end_date.max().date()),
                'primary_market_dates': int(grid.is_primary.sum()), 'daily_market_dates': len(grid)}
    if not score:
        return metadata
    demo = json.loads(DEMO.read_text())
    validate_configuration(demo)
    if not demo['is_demo'] or any(portfolio['input_type'] != 'weights' for portfolio in demo['portfolios']):
        raise ValueError('Use the frozen fixed-weight demo portfolios')
    portfolio_ids = {portfolio['id'] for portfolio in demo['portfolios']}
    methods = [spec[key] for key in ('trailing_method', 'ewma_method', 'trained_method')]
    panel = return_panel(features)
    holdings = holding_forecasts(configuration, train, features, dates, spec)
    portfolios = portfolio_forecasts(holdings, panel, grid, demo, spec)
    portfolio_dates = portfolios[KEYS].merge(grid, on='origin_date', validate='many_to_one')
    origins = pd.concat([dates, portfolio_dates], ignore_index=True)
    predictions = pd.concat([holdings, portfolios], ignore_index=True).melt(
        id_vars=KEYS, var_name='method', value_name='predicted_variance')
    if not np.isfinite(predictions.predicted_variance).all() or (predictions.predicted_variance < 0).any():
        raise ValueError('Invalid frozen forecast variance')

    OUTPUT.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT / commit
    with TemporaryDirectory(dir=OUTPUT, prefix='.pending-') as pending:
        staging = Path(pending) / commit
        staging.mkdir()
        with duckdb.connect() as conn:
            conn.register('predictions', predictions)
            conn.table('predictions').write_parquet(str(staging / 'predictions.parquet'))
        metadata['frozen_predictions_sha256'] = sha256(staging / 'predictions.parquet')
        outcomes = realized(panel, grid, demo)
        daily = score_matched_variances(predictions, origins, outcomes, methods, spec['qlike_floor'])
        daily['scope'] = np.where(daily.instrument_id.isin(portfolio_ids), 'portfolio', 'instrument')
        scores = pd.concat([daily.assign(sample='daily'), daily.loc[daily.is_primary].assign(sample='primary')],
                           ignore_index=True)
        result = {**metadata, **summarize(scores, portfolio_ids, spec)}
        with duckdb.connect() as conn:
            conn.register('scores', scores)
            conn.table('scores').write_parquet(str(staging / 'scores.parquet'))
        (staging / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        hashes = {path.name: sha256(path) for path in sorted(staging.iterdir())}
        (staging / 'manifest.json').write_text(json.dumps(hashes, indent=2) + '\n')
        if sha256(WAREHOUSE) != spec['warehouse_sha256']:
            raise ValueError('Warehouse changed during the run')
        if not destination.exists():
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
        if staging.exists() and any(sha256(destination / path.name) != sha256(path) for path in staging.iterdir()):
            raise ValueError('Replay differs from the existing holdout evidence')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-commit', required=True)
    parser.add_argument('--score', action='store_true', help='Compute held-out outcomes after the freeze check')
    args = parser.parse_args()
    print(json.dumps(run(args.freeze_commit, args.score), indent=2))


if __name__ == '__main__':
    main()
