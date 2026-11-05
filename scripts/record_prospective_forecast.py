"""Write a local PF-002 forecast record for the current eligible after-close window."""

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
from tempfile import NamedTemporaryFile

import duckdb
import exchange_calendars as xcals
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, load_universe, sha256
from scripts.build_modeling_dataset import read_market_inputs
from scripts.evaluate_baselines import ewma_variance
from scripts.evaluate_final import portfolio_forecasts, return_panel
from scripts.portfolio_replacement import accepted_screen_universe
from scripts.train_risk_model import fit_candidate, predict_variance


PROTOCOL = ROOT / 'config/prospective_forecast.json'
FEATURE_SQL = ROOT / 'sql/modeling_features.sql'


def schedule(spec):
    calendar = xcals.get_calendar(spec['calendar'], start=spec['first_origin'], end='2034-12-31')
    stride = spec['stride_sessions']
    for index in range(0, spec['enrollment_slots'] * stride, stride):
        origin = calendar.sessions[index]
        yield (origin, calendar.sessions[index + spec['horizon_sessions']],
               calendar.session_close(origin), calendar.session_open(calendar.sessions[index + 1]))


def open_window(now, spec):
    for slot in schedule(spec):
        if slot[2] <= now < slot[3]:
            return slot
    raise ValueError('No scheduled forecast window is open. PF-002 cannot backfill a past origin.')


def timing(now, spec):
    origin, target, _, deadline = open_window(now, spec)
    return origin, target, deadline


def accepted_prices(database):
    expected = load_universe(ROOT / 'config/reference_universe.json')
    universe = accepted_screen_universe(database)
    with duckdb.connect(str(database), read_only=True) as connection:
        evaluation = json.loads((ROOT / 'config/evaluation_protocol.json').read_text())
        dataset, manifest, prices, _ = read_market_inputs(connection, evaluation)
    if dataset != universe['dataset_id'] or set(prices.instrument_id) != {row['symbol'] for row in expected['instruments']}:
        raise ValueError('The active dataset must contain the complete audited reference universe')
    return dataset, manifest, prices


def preflight(database, training, now):
    spec = json.loads(PROTOCOL.read_text())
    upcoming = next((slot for slot in schedule(spec) if now < slot[3]), None)
    dataset, manifest, prices = accepted_prices(database)
    latest = prices.groupby('instrument_id').session_date.max()
    report = {'protocol': spec['protocol'], 'dataset_id': dataset, 'latest_common_close': str(latest.min().date()),
              'instrument_count': len(latest), 'training_digest_matches': sha256(training) == spec['training_sample_sha256']}
    if upcoming is None:
        return {**report, 'state': 'schedule_ended'}
    origin, target, close, deadline = upcoming
    first, last = capture_times(manifest)
    return {**report, 'state': 'window_open' if now >= close else 'before_window',
            'origin': str(origin.date()), 'target_end': str(target.date()),
            'close_utc': close.isoformat(), 'deadline_utc': deadline.isoformat(),
            'snapshot_matches_origin': bool(latest.eq(origin).all()),
            'capture_in_window': bool(close <= first <= last <= now < deadline)}


def read_training(path, spec):
    if sha256(path) != spec['training_sample_sha256']:
        raise ValueError('Training artifact differs from the locked development input')
    with duckdb.connect() as connection:
        train = connection.execute('''
            SELECT * FROM read_parquet(?) WHERE final_refit_eligible ORDER BY instrument_id, origin_date
        ''', [str(path)]).df()
    if (len(train) != spec['training_rows'] or train.target_end_date.isna().any()
            or train.target_end_date.max() >= pd.Timestamp(spec['training_cutoff_exclusive'])):
        raise ValueError('Training outcomes must predate the frozen cutoff')
    return train


def predict(prices, train, origin, spec, baseline, config):
    if prices.empty or not prices.groupby('instrument_id').session_date.max().eq(origin).all():
        raise ValueError('Every accepted history must end exactly at the eligible origin')
    with duckdb.connect() as connection:
        connection.register('modeling_prices', prices)
        features = connection.execute(FEATURE_SQL.read_text()).df()
    panel = return_panel(features)
    rows = features.loc[features.origin_date.eq(origin)].copy()
    if not rows.feature_ready.all():
        raise ValueError('The scheduled origin lacks ready features')
    ewma = {}
    for symbol, returns in panel.items():
        values, _ = ewma_variance(252 * returns.to_numpy() ** 2, baseline['ewma_decay'])
        ewma[symbol] = float(values[-1])
    candidate = next(row for row in config['candidates'] if row['method'] == baseline['trained_method'])
    estimator = fit_candidate(train, candidate, config)
    holdings = rows[['instrument_id', 'origin_date']].assign(**{
        baseline['trained_method']: predict_variance(estimator, rows),
        baseline['ewma_method']: rows.instrument_id.map(ewma),
        baseline['trailing_method']: rows.variance_20,
    })
    demo = {'portfolios': [{'id': portfolio['id'],
                            'positions': [{'instrument_id': symbol, 'weight': weight}
                                          for symbol, weight in portfolio['positions'].items()]}
                           for portfolio in spec['portfolio_weights']]}
    forecasts = portfolio_forecasts(holdings, panel, pd.DataFrame({'origin_date': [origin]}), demo, baseline)
    records = forecasts.drop(columns='origin_date').rename(columns={'instrument_id': 'portfolio_id'})
    if not np.isfinite(records.drop(columns='portfolio_id').to_numpy()).all():
        raise ValueError('Forecast includes a nonfinite variance')
    return records.to_dict('records')


def write_once(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode='w', dir=path.parent) as staging:
        json.dump(record, staging, indent=2, sort_keys=True, allow_nan=False)
        staging.write('\n')
        staging.flush()
        os.fsync(staging.fileno())
        os.link(staging.name, path)


def capture_times(manifest):
    first = pd.Timestamp(manifest['retrieved_at_utc'])
    completions = [pd.Timestamp(row['retrieved_at_utc']) for row in manifest['instruments'].values()]
    if (not completions or pd.isna(first) or first.tzinfo is None
            or any(pd.isna(time) or time.tzinfo is None or time < first for time in completions)):
        raise ValueError('Require offset-aware and ordered capture times in the audited manifest')
    return first, max(completions)


def record(database, training, ledger):
    spec = json.loads(PROTOCOL.read_text())
    origin, target, close, deadline = open_window(datetime.now(timezone.utc), spec)
    before = sha256(database)
    dataset, manifest, prices = accepted_prices(database)
    if not prices.groupby('instrument_id').session_date.max().eq(origin).all():
        raise ValueError('The accepted market snapshot does not reach the scheduled origin')
    first, last = capture_times(manifest)
    if not close <= first <= last <= datetime.now(timezone.utc):
        raise ValueError('The selected capture must start after the scheduled close and finish before recording')
    baseline_path = ROOT / 'config/final_evaluation.json'
    training_config_path = ROOT / 'config/model_training.json'
    predictions = predict(prices, read_training(training, spec), origin, spec,
                          json.loads(baseline_path.read_text()), json.loads(training_config_path.read_text()))
    now = datetime.now(timezone.utc)
    if now >= deadline or sha256(database) != before:
        raise ValueError('Forecast window closed or warehouse changed during recording')
    path = ledger / f'{origin.date()}.json'
    write_once(path, {'protocol': spec['protocol'], 'protocol_sha256': sha256(PROTOCOL),
                      'warehouse_sha256': before, 'dataset_id': dataset, 'training_sha256': sha256(training),
                      'feature_sql_sha256': sha256(FEATURE_SQL), 'training_config_sha256': sha256(training_config_path),
                      'baseline_config_sha256': sha256(baseline_path), 'recorder_sha256': sha256(Path(__file__)),
                      'runtime': {'python': platform.python_version(),
                                  **{name: version(name) for name in ('numpy', 'pandas', 'scikit-learn', 'duckdb', 'exchange-calendars')}},
                      'origin': str(origin.date()), 'target_end': str(target.date()),
                      'capture_started_at_utc': first.tz_convert('UTC').isoformat(),
                      'capture_finished_at_utc': last.tz_convert('UTC').isoformat(),
                      'recorded_at_utc': now.isoformat(), 'deadline_utc': deadline.isoformat(),
                      'timestamp_basis': 'local_system_clock', 'annualized_variance': predictions})
    return {'record': str(path), 'sha256': sha256(path), 'origin': str(origin.date())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, default=ROOT / 'private/prospective')
    parser.add_argument('--preflight', action='store_true', help='Inspect the next eligible window and local inputs')
    args = parser.parse_args()
    try:
        report = (preflight(args.database, args.training, datetime.now(timezone.utc)) if args.preflight
                  else record(args.database, args.training, args.ledger))
        print(json.dumps(report, indent=2))
    except (ValueError, FileExistsError) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__':
    main()
