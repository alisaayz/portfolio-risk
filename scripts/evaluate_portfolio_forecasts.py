"""Evaluate fixed demo portfolio forecasts on the saved development grid."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
from tempfile import TemporaryDirectory

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.evaluate_baselines import score_common_origins
from scripts.portfolio_baseline import validate_configuration
from scripts.verify_training_experiment import verify


DEMO = ROOT / 'config/demo_portfolios.json'
YEARS = (2023, 2024, 2025)
CUTOFF = pd.Timestamp('2026-01-01')
HORIZON = 20
LOOKBACK = 60
ANNUAL_SESSIONS = 252
BOOTSTRAP_SEED = 42
BOOTSTRAP_DRAWS = 20_000


def evaluate(panel, saved, portfolios, model, ewma):
    """Compose asset predictions and independently reconcile their saved outcomes."""
    if panel.index.max() >= CUTOFF or not panel.index.is_unique or not panel.index.is_monotonic_increasing:
        raise ValueError('Require unique ordered development return dates')
    if not np.isfinite(panel.to_numpy()).all() or (panel <= -1).any().any():
        raise ValueError('Incomplete or invalid development return panel')

    grid = saved[['year', 'origin_date', 'target_end_date']].drop_duplicates().sort_values('origin_date')
    if (grid.empty or set(grid.year) != set(YEARS) or grid.origin_date.duplicated().any()
            or not grid.groupby('year').size().eq(12).all()
            or (grid.origin_date.dt.year != grid.year).any() or (grid.target_end_date.dt.year != grid.year).any()
            or (grid.target_end_date >= CUTOFF).any()
            or (grid.target_end_date.iloc[:-1].to_numpy() > grid.origin_date.iloc[1:].to_numpy()).any()):
        raise ValueError('Expected the complete pre-2026 primary grid with nonoverlapping target windows')

    methods = ['trailing_20', ewma, model]
    saved = saved.set_index(['origin_date', 'method', 'instrument_id']).sort_index()
    if not saved.index.is_unique:
        raise ValueError('Duplicate holding forecasts')
    origins, predictions, outcomes = [], [], []
    for row in grid.itertuples(index=False):
        position = panel.index.get_loc(row.origin_date)
        if position < LOOKBACK - 1 or position + HORIZON >= len(panel) or panel.index[position + HORIZON] != row.target_end_date:
            raise ValueError('Return window does not match the saved origin and target end')
        for portfolio in portfolios:
            symbols = [holding['instrument_id'] for holding in portfolio['positions']]
            weights = np.array([holding['weight'] for holding in portfolio['positions']])
            history = panel[symbols].iloc[position - LOOKBACK + 1:position + 1].to_numpy()
            future = panel[symbols].iloc[position + 1:position + 1 + HORIZON].to_numpy()
            target_by_asset = ANNUAL_SESSIONS * np.mean(future**2, axis=0)
            trailing_by_asset = ANNUAL_SESSIONS * np.mean(history[-HORIZON:]**2, axis=0)
            lengths = np.linalg.norm(history, axis=0)
            if (lengths == 0).any():
                raise ValueError('A flat history cannot provide a co-movement estimate')
            unit_columns = history / lengths
            correlation = unit_columns.T @ unit_columns

            key = {'instrument_id': portfolio['id'], 'origin_date': row.origin_date}
            origins.append({**key, 'year': row.year, 'target_end_date': row.target_end_date})
            outcomes.append({**key, 'target_variance': ANNUAL_SESSIONS * np.mean((future @ weights)**2)})
            for method in methods:
                rows = saved.loc[(row.origin_date, method)].reindex(symbols)
                np.testing.assert_allclose(rows.target_variance, target_by_asset, rtol=1e-11, atol=1e-13)
                variances = rows.predicted_variance.to_numpy()
                if not np.isfinite(variances).all() or (variances < 0).any():
                    raise ValueError('Incomplete or invalid holding forecasts')
                if method == 'trailing_20':
                    np.testing.assert_allclose(variances, trailing_by_asset, rtol=1e-11, atol=1e-13)
                    forecast = ANNUAL_SESSIONS * np.mean((history[-HORIZON:] @ weights)**2)
                else:
                    exposures = weights * np.sqrt(variances)
                    forecast = exposures @ correlation @ exposures
                    # Independently compute the same quadratic form as a sum of squares.
                    np.testing.assert_allclose(forecast, np.sum((unit_columns @ exposures)**2), rtol=1e-12, atol=1e-15)
                predictions.append({**key, 'method': method, 'predicted_variance': forecast})

    scores = score_common_origins(pd.DataFrame(predictions), pd.DataFrame(origins),
                                  pd.DataFrame(outcomes), methods, floor=1e-12)
    return scores.rename(columns={'instrument_id': 'portfolio_id'})


def paired_intervals(scores, model, ewma):
    """Resample contiguous dates within year after averaging paired demo losses."""
    date_losses = scores.groupby(['year', 'origin_date', 'method']).volatility_absolute_error_pp.mean().unstack()
    deltas = date_losses[model] - date_losses[ewma]
    result = []
    for block_length in (2, 3, 4):
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        samples = []
        for _, year in deltas.groupby(level='year'):
            values = year.to_numpy()
            blocks = len(values) // block_length
            starts = rng.integers(len(values), size=(BOOTSTRAP_DRAWS, blocks, 1))
            indices = (starts + np.arange(block_length)) % len(values)
            samples.append(values[indices].mean(axis=(1, 2)))
        lower, upper = np.quantile(np.mean(samples, axis=0), [.025, .975])
        result.append({'block_dates': block_length, 'dates': len(deltas),
                       'model_minus_ewma_mae_pp': float(deltas.mean()),
                       'exploratory_interval_pp': [float(lower), float(upper)]})
    return result


def run(database, experiment, modeling, output):
    verified = verify(experiment)
    training = json.loads((experiment / 'summary.json').read_text())
    manifest_path = modeling / 'manifest.json'
    if sha256(manifest_path) != training['recipe']['modeling_manifest_sha256']:
        raise ValueError('Modeling manifest does not match the training experiment')
    manifest = json.loads(manifest_path.read_text())
    dataset_id = manifest['recipe']['market_dataset_id']
    demo = json.loads(DEMO.read_text())
    validate_configuration(demo)
    portfolios = demo['portfolios']
    if not demo['is_demo'] or any(portfolio['input_type'] != 'weights' for portfolio in portfolios):
        raise ValueError('Use the fixed-weight demonstration portfolios')
    symbols = sorted({row['instrument_id'] for p in portfolios for row in p['positions']})
    model, ewma = training['selected_model'], training['selected_ewma']

    database_hash = sha256(database)
    with duckdb.connect(str(database), read_only=True) as connection:
        if connection.execute('SELECT dataset_id FROM active_dataset').fetchall() != [(dataset_id,)]:
            raise ValueError('The active warehouse differs from the model training dataset')
        returns = connection.execute('''
            SELECT instrument_id, session_date, simple_return FROM returns_daily
            WHERE instrument_id IN (SELECT unnest(?)) AND session_date < ?
        ''', [symbols, CUTOFF.date()]).df()
        saved = connection.execute('''
            SELECT year, origin_date, target_end_date, instrument_id, method, predicted_variance, target_variance
            FROM read_parquet(?) WHERE evaluation_mode = 'primary' AND method IN (SELECT unnest(?))
        ''', [str(experiment / 'per_origin_errors.parquet'), ['trailing_20', ewma, model]]).df()
    if sha256(database) != database_hash:
        raise ValueError('Warehouse changed while evaluating')
    panel = returns.pivot(index='session_date', columns='instrument_id', values='simple_return').sort_index()
    # The first warehouse session has no previous close. Any later gap is rejected.
    if not panel.empty and panel.iloc[0].isna().all():
        panel = panel.iloc[1:]
    scores = evaluate(panel, saved, portfolios, model, ewma)
    scores = scores.sort_values(['year', 'portfolio_id', 'origin_date', 'method']).reset_index(drop=True)
    metrics = scores.groupby(['year', 'portfolio_id', 'method'], as_index=False).agg(
        windows=('origin_date', 'size'),
        volatility_mae_pp=('volatility_absolute_error_pp', 'mean'),
        variance_qlike=('variance_qlike', 'mean'),
    )
    recipe = {
        'protocol_id': 'PF-001', 'market_dataset_id': dataset_id, 'warehouse_sha256': database_hash,
        'training_experiment_id': verified['experiment_id'],
        'training_manifest_sha256': sha256(experiment / 'manifest.json'),
        'demo_configuration_sha256': sha256(DEMO), 'code_sha256': sha256(Path(__file__)),
        'scoring_code_sha256': sha256(ROOT / 'scripts/evaluate_baselines.py'),
        'python': platform.python_version(), 'platform': platform.system(),
        'packages': {name: version(name) for name in ('duckdb', 'numpy', 'pandas')},
        'development_years': YEARS, 'horizon_sessions': HORIZON, 'lookback_sessions': LOOKBACK,
        'bootstrap_seed': BOOTSTRAP_SEED, 'bootstrap_draws': BOOTSTRAP_DRAWS,
    }
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    summary = {'experiment_id': identity, 'recipe': recipe, 'model': model, 'ewma': ewma,
               'paired_scores': len(scores), 'metrics': metrics.to_dict('records'),
               'exploratory_intervals': paired_intervals(scores, model, ewma), 'final_test_scores_computed': False}

    output.mkdir(parents=True, exist_ok=True)
    destination = output / identity
    with TemporaryDirectory(dir=output, prefix='.pending-') as pending:
        staging = Path(pending) / identity
        staging.mkdir()
        with duckdb.connect() as connection:
            connection.register('scores', scores)
            connection.table('scores').write_parquet(str(staging / 'scores.parquet'), compression='zstd')
        (staging / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
        digests = {path.name: sha256(path) for path in sorted(staging.iterdir())}
        (staging / 'manifest.json').write_text(json.dumps(digests, indent=2) + '\n')
        if not destination.exists():
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
        if staging.exists():
            if any(sha256(destination / path.name) != sha256(path) for path in staging.iterdir()):
                raise ValueError('Replay differs from saved portfolio forecast evidence')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--modeling', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/warehouse/portfolio-risk.duckdb')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/experiments/portfolio_forecasts')
    args = parser.parse_args()
    print(json.dumps(run(args.database, args.experiment, args.modeling, args.output), indent=2))


if __name__ == '__main__':
    main()
