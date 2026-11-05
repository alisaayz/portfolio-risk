"""Evaluate PF-002 once the final scheduled outcome has closed."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import duckdb
import exchange_calendars as xcals
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.record_prospective_forecast import (
    FEATURE_SQL, PROTOCOL, accepted_prices, capture_times, schedule, write_once,
)
from scripts.replacement_evidence import block_indices
from scripts.verify_forecast_receipt import check_forecast, signed_timestamp


BASELINE = ROOT / 'config/final_evaluation.json'
TRAINING_CONFIG = ROOT / 'config/model_training.json'
SCORE_FIELDS = {'origin', 'forecast', 'request', 'receipt', 'trust_dir', 'outcome_database', 'outcome_sha256'}


def order_evidence(manifest, slots, protocol):
    rows = manifest['slots']
    if manifest['protocol'] != protocol or not isinstance(rows, list):
        raise ValueError('Use a PF-002 evidence manifest with a list of scheduled slots')
    by_origin = {row['origin']: row for row in rows}
    if len(rows) != len(slots) or set(by_origin) != set(slots):
        raise ValueError('List every scheduled origin exactly once, including skipped origins')
    for row in rows:
        if set(row) == {'origin', 'missing_reason'}:
            if not isinstance(row['missing_reason'], str) or not row['missing_reason'].strip():
                raise ValueError('A skipped origin requires a nonempty reason')
        elif set(row) != SCORE_FIELDS or any(not isinstance(value, str) or not value for value in row.values()):
            raise ValueError('A scored origin requires a forecast, query, receipt, trust files and hashed outcome warehouse')
    return [by_origin[origin] for origin in slots]


def verify_entry(root, entry, spec, baseline, openssl):
    forecast, query, receipt = ((root / entry[key]).read_bytes() for key in ('forecast', 'request', 'receipt'))
    stamp = signed_timestamp(forecast, query, receipt, root / entry['trust_dir'], openssl)
    record = json.loads(forecast)
    if check_forecast(record, stamp, spec, baseline) != entry['origin']:
        raise ValueError('Timestamped forecast does not match its evidence slot')
    bindings = {'feature_sql_sha256': FEATURE_SQL, 'training_config_sha256': TRAINING_CONFIG,
                'baseline_config_sha256': BASELINE,
                'recorder_sha256': ROOT / 'scripts/record_prospective_forecast.py'}
    if any(record.get(key) != sha256(path) for key, path in bindings.items()):
        raise ValueError('Timestamped forecast recipe differs from the frozen feature or model settings')
    return record, {'forecast_sha256': hashlib.sha256(forecast).hexdigest(),
                    'forecast_dataset_id': record['dataset_id'],
                    'forecast_warehouse_sha256': record['warehouse_sha256'],
                    'receipt_sha256': hashlib.sha256(receipt).hexdigest(),
                    'signed_at_utc': stamp.isoformat()}


def realized_window(prices, sessions, portfolios):
    window = prices.loc[prices.session_date.between(sessions[0], sessions[-1])]
    panel = window.pivot(index='session_date', columns='instrument_id', values='adjusted_close').sort_index()
    if (not panel.index.equals(sessions) or not np.isfinite(panel.to_numpy()).all()
            or (panel <= 0).any().any()):
        raise ValueError('Outcome requires the exact origin close and all following scheduled sessions')
    returns = panel.pct_change(fill_method=None).iloc[1:]
    if not np.isfinite(returns.to_numpy()).all():
        raise ValueError('Outcome contains a nonfinite return')
    results = []
    for portfolio in portfolios:
        positions = portfolio['positions']
        weighted = returns[list(positions)].to_numpy() @ np.array(list(positions.values()))
        results.append((252 * np.mean(weighted ** 2), 252 * np.mean(np.minimum(weighted, 0) ** 2)))
    return np.array(results)


def read_outcome(database, digest, sessions, close, now, portfolios):
    if sha256(database) != digest:
        raise ValueError('Outcome warehouse differs from its pinned checksum')
    dataset, manifest, prices = accepted_prices(database)
    if not prices.groupby('instrument_id').session_date.max().eq(sessions[-1]).all():
        raise ValueError('Outcome warehouse must end on the target session for every instrument')
    first, last = capture_times(manifest)
    if not close <= first <= last <= now:
        raise ValueError('Outcome capture must start at or after the target close and finish before scoring')
    values = realized_window(prices, sessions, portfolios)
    if sha256(database) != digest:
        raise ValueError('Outcome warehouse changed during scoring')
    return values, dataset


def summarize(predictions, outcomes, portfolios, methods, spec, floor):
    # Missing slots have a NaN row. Keep them in the calendar for paired resampling.
    matched = np.isfinite(outcomes[:, 0, 0])
    variance = outcomes[matched, :, 0, None]
    forecasts = predictions[matched]
    safe = np.maximum(forecasts, floor)
    error = 100 * (np.sqrt(forecasts) - np.sqrt(variance))
    absolute = np.abs(error)
    mae = absolute.mean(axis=0)
    qlike = (np.log(safe) + variance / safe).mean(axis=0)
    tail_count = (len(error) + 4) // 5
    # Stable sort breaks ties by earliest scheduled origin.
    tail = np.argsort(-outcomes[matched, :, 1], axis=0, kind='stable')[:tail_count]
    tail_error = np.take_along_axis(absolute, tail[:, :, None], axis=0).mean(axis=0)

    by_portfolio = {}
    for i, portfolio in enumerate(portfolios):
        by_portfolio[portfolio['id']] = {
            method: {'mae_pp': float(mae[i, j]), 'qlike': float(qlike[i, j]),
                     'mean_signed_error_pp': float(error[:, i, j].mean()),
                     'understatements_at_least_five_pp': int((error[:, i, j] <= -5).sum()),
                     'prediction_floor_count': int((forecasts[:, i, j] < floor).sum()),
                     'high_downside_mae_pp': float(tail_error[i, j]), 'high_downside_origins': tail_count}
            for j, method in enumerate(methods)
        }

    losses = absolute.mean(axis=1)
    differences = np.full((len(matched), len(methods) - 1), np.nan)
    differences[matched] = losses[:, :1] - losses[:, 1:]
    point = differences[matched].mean(axis=0)
    bounds = {}
    for block in [spec['primary_block_origins'], *spec['sensitivity_block_origins']]:
        indices = block_indices(len(matched), block, spec['bootstrap_draws'],
                                np.random.default_rng(spec['bootstrap_seed']))
        samples = differences[indices]
        counts = matched[indices].sum(axis=1)
        if (counts == 0).any():
            raise ValueError('A paired bootstrap draw has no matched origins')
        means = np.nansum(samples, axis=1) / counts[:, None]
        bounds[str(block)] = np.quantile(means, .975, axis=0)
    primary = bounds[str(spec['primary_block_origins'])]
    advances = (np.all(point <= -spec['minimum_improvement_pp']) and np.all(primary < 0)
                and np.all(mae[:, :1] <= mae[:, 1:]))
    return {'by_portfolio': by_portfolio,
            'pooled_mae_pp': {method: float(value) for method, value in zip(methods, mae.mean(axis=0))},
            'model_minus_baselines': {
                method: {'mae_difference_pp': float(point[j]),
                         'upper_bounds_97_5_pp': {block: float(values[j]) for block, values in bounds.items()}}
                for j, method in enumerate(methods[1:])},
            'advance_to_dashboard_experiment': bool(advances)}


def evaluate(manifest_path, now, spec, baseline, openssl='openssl'):
    slots = list(schedule(spec))
    calendar = xcals.get_calendar(spec['calendar'], start=slots[0][0],
                                  end=slots[-1][1] + pd.Timedelta(days=7))
    final_close = calendar.session_close(slots[-1][1])
    if now < final_close:
        raise ValueError(f'The final scheduled outcome has not closed ({final_close.isoformat()})')

    contents = manifest_path.read_bytes()
    dates = [str(origin.date()) for origin, _, _, _ in slots]
    entries = order_evidence(json.loads(contents), dates, spec['protocol'])
    records, ledger = {}, []
    for index, entry in enumerate(entries):
        origin = entry['origin']
        if 'missing_reason' in entry:
            ledger.append({'origin': origin, 'status': 'skipped', 'reason': entry['missing_reason']})
        else:
            records[index], proof = verify_entry(manifest_path.parent, entry, spec, baseline, openssl)
            ledger.append({'origin': origin, 'status': 'receipt_verified', **proof})

    result = {'protocol': spec['protocol'], 'protocol_sha256': sha256(PROTOCOL),
              'scorer_sha256': sha256(Path(__file__)), 'scored_at_utc': now.isoformat(),
              'evidence_manifest_sha256': hashlib.sha256(contents).hexdigest(),
              'scheduled_origins': len(slots), 'verified_receipts': len(records),
              'minimum_completed_origins': spec['minimum_completed_origins'], 'slots': ledger}
    if len(records) < spec['minimum_completed_origins']:
        return {**result, 'status': 'insufficient_evidence', 'scored_origins': 0}

    methods = [baseline[key] for key in ('trained_method', 'ewma_method', 'trailing_method')]
    portfolios = spec['portfolio_weights']
    predictions = np.full((len(slots), len(portfolios), len(methods)), np.nan)
    outcomes = np.full((len(slots), len(portfolios), 2), np.nan)
    for index, record in records.items():
        origin, target, _, _ = slots[index]
        sessions = calendar.sessions_in_range(origin, target)
        if len(sessions) != spec['horizon_sessions'] + 1:
            raise ValueError('Outcome calendar differs from the frozen horizon')
        entry = entries[index]
        outcomes[index], dataset = read_outcome(manifest_path.parent / entry['outcome_database'],
                                                entry['outcome_sha256'], sessions, calendar.session_close(target),
                                                now, portfolios)
        forecast = {row['portfolio_id']: row for row in record['annualized_variance']}
        predictions[index] = [[forecast[portfolio['id']][method] for method in methods] for portfolio in portfolios]
        ledger[index].update(status='scored', target_end=str(target.date()), outcome_dataset_id=dataset,
                             outcome_sha256=entry['outcome_sha256'])

    scores = summarize(predictions, outcomes, portfolios, methods, spec, baseline['qlike_floor'])
    return {**result, 'status': 'scored', 'scored_origins': len(records), **scores}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'private/prospective/PF-002-results.json')
    parser.add_argument('--openssl', default='openssl')
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise FileExistsError('The final score report already exists')
        spec = json.loads(PROTOCOL.read_text())
        baseline = json.loads(BASELINE.read_text())
        result = evaluate(args.evidence, datetime.now(timezone.utc), spec, baseline, args.openssl)
        write_once(args.output, result)
        print(f'{result["status"]}: {args.output}')
    except (ValueError, OSError, KeyError, TypeError, duckdb.Error) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__':
    main()
