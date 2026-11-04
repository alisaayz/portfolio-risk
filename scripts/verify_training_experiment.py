"""Independently verify saved development predictions and scores without loading models."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import sha256


def verify(folder: Path) -> dict:
    manifest = json.loads((folder / 'manifest.json').read_text())
    summary = json.loads((folder / 'summary.json').read_text())
    identity = hashlib.sha256(json.dumps(summary['recipe'], sort_keys=True).encode()).hexdigest()
    if folder.name != identity or manifest['experiment_id'] != identity or summary['experiment_id'] != identity:
        raise ValueError('Experiment identity mismatch')
    actual_files = {str(p.relative_to(folder)) for p in folder.rglob('*')
                    if p.is_file() and p != folder / 'manifest.json'}
    if actual_files != set(manifest['outputs']):
        raise ValueError('Artifact inventory mismatch')
    for name, digest in manifest['outputs'].items():
        path = folder / name
        if path.is_symlink() or sha256(path) != digest:
            raise ValueError(f'Artifact hash mismatch: {name}')
    if summary['final_refit_performed'] or summary['final_test_scores_computed']:
        raise ValueError('Final refit/test must remain reserved')
    with duckdb.connect() as connection:
        errors = connection.execute('SELECT * FROM read_parquet(?)', [str(folder / 'per_origin_errors.parquet')]).df()
        forecasts = connection.execute('SELECT * FROM read_parquet(?)', [str(folder / 'model_forecasts.parquet')]).df()
        origins = connection.execute('SELECT * FROM read_parquet(?)', [str(folder / 'evaluation_origins.parquet')]).df()
    for frame in [errors, forecasts, origins]:
        if frame.empty or (frame.origin_date >= pd.Timestamp('2026-01-01')).any():
            raise ValueError('Empty or final-test forecast/evaluation rows')
        if 'target_end_date' in frame and (frame.target_end_date >= pd.Timestamp('2026-01-01')).any():
            raise ValueError('Target crosses final-test boundary')
    keys = ['year', 'evaluation_mode', 'method', 'instrument_id', 'origin_date']
    if errors.duplicated(keys).any():
        raise ValueError('Duplicate per-origin errors')
    expected_methods = {'trailing_20', 'ewma_0.90', 'ewma_0.94', 'ewma_0.97',
                        *[row['method'] for row in summary['recipe']['training_configuration']['candidates']]}
    if set(errors.method) != expected_methods:
        raise ValueError('Missing candidate scores')
    checked_scores = 0
    for year in [2023, 2024, 2025]:
        for mode in ['primary', 'daily']:
            selected = errors.loc[(errors.year == year) & (errors.evaluation_mode == mode)]
            reference_keys = None
            for method in sorted(expected_methods):
                rows = selected.loc[selected.method == method].sort_values(['instrument_id', 'origin_date'])
                current_keys = list(zip(rows.instrument_id, rows.origin_date))
                if reference_keys is None:
                    reference_keys = current_keys
                if current_keys != reference_keys:
                    raise ValueError('Methods use different forecast origins')
                predicted, realized = rows.predicted_variance.to_numpy(), rows.target_variance.to_numpy()
                if not np.isfinite(predicted).all() or not np.isfinite(realized).all() or (predicted < 0).any() or (realized < 0).any():
                    raise ValueError('Invalid variance observations')
                # EV-001 fixes the floor at 1e-12; no evaluator metric helper is called.
                safe = np.maximum(predicted, 1e-12)
                mae = np.abs(np.sqrt(predicted) - np.sqrt(realized)) * 100
                qlike = np.log(safe) + realized / safe
                np.testing.assert_allclose(mae, rows.volatility_absolute_error_pp, rtol=0, atol=1e-12)
                np.testing.assert_allclose(qlike, rows.variance_qlike, rtol=0, atol=1e-12)
                instruments = sorted(set(rows.instrument_id))
                instrument_mae = [float(mae[(rows.instrument_id == symbol).to_numpy()].mean()) for symbol in instruments]
                instrument_qlike = [float(qlike[(rows.instrument_id == symbol).to_numpy()].mean()) for symbol in instruments]
                recorded = [r for r in summary['overall_metrics'] if r['year'] == year
                            and r['evaluation_mode'] == mode and r['method'] == method]
                if len(recorded) != 1:
                    raise ValueError('Missing or duplicate summary metric')
                np.testing.assert_allclose([np.mean(instrument_mae), np.mean(instrument_qlike)],
                                           [recorded[0]['volatility_mae_pp'], recorded[0]['variance_qlike']],
                                           rtol=0, atol=1e-12)
                if recorded[0]['observations'] != len(rows):
                    raise ValueError('Summary count mismatch')
                if recorded[0]['prediction_floors'] != int((predicted < 1e-12).sum()):
                    raise ValueError('Prediction floor count mismatch')
                checked_scores += 1
    for record in summary['fold_records']:
        if pd.Timestamp(record['latest_training_target_end']) >= pd.Timestamp(f"{record['year']}-01-01"):
            raise ValueError('Training target overlaps validation')
        if not record['repeat_fit_predictions_identical']:
            raise ValueError('Repeated fits did not reconcile')
    config = summary['recipe']['training_configuration']
    choices = [r for r in summary['overall_metrics'] if r['year'] == 2025 and r['evaluation_mode'] == 'primary'
               and r['method'] in {c['method'] for c in config['candidates']}]
    selected = min(choices, key=lambda r: (r['volatility_mae_pp'], r['method']))['method']
    if selected != summary['selected_model']:
        raise ValueError('Selected candidate differs from declared rule')
    return {'experiment_id': identity, 'artifact_files_verified': len(actual_files),
            'per_origin_errors_verified': len(errors), 'aggregate_scores_verified': checked_scores,
            'trained_forecast_rows': len(forecasts), 'final_test_scores_computed': False,
            'all_checks_pass': True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.experiment), indent=2))


if __name__ == '__main__':
    main()
