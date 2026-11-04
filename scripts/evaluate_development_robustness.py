"""Sensitivity of fixed development predictions to grid phase and asset aggregation."""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.evaluate_baselines import load_modeling_artifacts, metric_tables
from scripts.verify_training_experiment import verify

KEYS = ['instrument_id', 'origin_date']


def validate_configuration(config):
    expected = {
        'robustness_protocol_id': 'RB-001', 'schema_version': 1,
        'development_years': [2023, 2024, 2025], 'grid_offsets_sessions': [0, 5, 10, 15],
        'stride_sessions': 20, 'models_refitted': False, 'candidate_selection_changed': False,
        'leave_one_instrument_out': 'aggregation_only_not_refitting', 'final_test_opened': False,
    }
    if config != expected:
        raise ValueError('Unsupported RB-001 sensitivity contract')


def phase_origins(membership, year, offset, config):
    validate_configuration(config)
    if year not in config['development_years'] or offset not in config['grid_offsets_sessions']:
        raise ValueError('Only declared development phases are allowed')
    if membership.duplicated(KEYS).any():
        raise ValueError('Duplicate membership keys')
    frame = membership.loc[(membership.origin_date.dt.year == year)
                           & membership.feature_history_ready].sort_values(KEYS).copy()
    position = frame.groupby('instrument_id').cumcount()
    selected = (position >= offset) & ((position - offset) % config['stride_sessions'] == 0)
    frame = frame.loc[selected & frame[f'fold_{year}_validation'], KEYS + ['target_end_date']]
    if frame.empty or (frame.target_end_date >= pd.Timestamp(f'{year+1}-01-01')).any():
        raise ValueError('Invalid phase outcome boundaries')
    for _, group in frame.groupby('instrument_id'):
        if not (group.target_end_date.iloc[:-1].to_numpy() <= group.origin_date.iloc[1:].to_numpy()).all():
            raise ValueError('Phase outcomes overlap')
    return frame.reset_index(drop=True)


def match_errors(daily_errors, origins):
    keys = KEYS + ['target_end_date']
    if origins.duplicated(KEYS).any():
        raise ValueError('Duplicate phase origins')
    methods = sorted(daily_errors.method.unique())
    frames = []
    for method in methods:
        source = daily_errors.loc[daily_errors.method == method]
        if source.duplicated(KEYS).any():
            raise ValueError('Duplicate daily prediction keys')
        selected = origins.merge(source, on=keys, how='left', validate='one_to_one')
        if selected.method.isna().any():
            raise ValueError('Missing phase forecast; comparison cannot shrink the sample')
        frames.append(selected)
    return pd.concat(frames, ignore_index=True)


def leave_one_out(instrument_metrics):
    """Remove one instrument from aggregation only; keep every trained model fixed."""
    records = []
    for (year, mode, method), group in instrument_metrics.groupby(['year', 'evaluation_mode', 'method'], sort=True):
        if group.instrument_id.duplicated().any() or len(group) < 2:
            raise ValueError('Need unique metrics for at least two instruments')
        for excluded in sorted(group.instrument_id):
            remaining = group.loc[group.instrument_id != excluded]
            records.append({'year': int(year), 'evaluation_mode': mode, 'method': method,
                            'excluded_instrument': excluded, 'instruments': len(remaining),
                            'volatility_mae_pp': float(remaining.volatility_mae_pp.mean()),
                            'variance_qlike': float(remaining.variance_qlike.mean())})
    return pd.DataFrame(records)


def evaluate(experiment, modeling, config):
    validate_configuration(config)
    verified = verify(experiment)
    summary = json.loads((experiment / 'summary.json').read_text())
    manifest, data = load_modeling_artifacts(modeling)
    if manifest['modeling_dataset_id'] != summary['recipe']['modeling_dataset_id']:
        raise ValueError('Sensitivity uses a different modeling dataset')
    with duckdb.connect() as connection:
        errors = connection.execute('SELECT * FROM read_parquet(?)', [str(experiment / 'per_origin_errors.parquet')]).df()
        instruments = connection.execute('SELECT * FROM read_parquet(?)', [str(experiment / 'per_instrument_metrics.parquet')]).df()
    universe = json.loads((ROOT / 'config/reference_universe.json').read_text())
    kinds = {record['symbol']: record['kind'] for record in universe['instruments']}
    scores, selected_rows = [], []
    for year in config['development_years']:
        daily = errors.loc[(errors.year == year) & (errors.evaluation_mode == 'daily')]
        for offset in config['grid_offsets_sessions']:
            origins = phase_origins(data['split_membership'], year, offset, config)
            selected = match_errors(daily, origins)
            if offset == 0:
                original = errors.loc[(errors.year == year) & (errors.evaluation_mode == 'primary')]
                columns = KEYS + ['method', 'predicted_variance', 'target_variance',
                                   'volatility_absolute_error_pp', 'variance_qlike']
                order = ['method', *KEYS]
                pd.testing.assert_frame_equal(selected[columns].sort_values(order).reset_index(drop=True),
                                               original[columns].sort_values(order).reset_index(drop=True), check_exact=True)
            selected['evaluation_mode'] = f'offset_{offset:02d}'
            selected['grid_offset_sessions'] = offset
            overall, _, _ = metric_tables(selected, kinds)
            overall['grid_offset_sessions'] = offset
            scores.append(overall)
            selected_rows.append(selected)
    phase_scores = pd.concat(scores, ignore_index=True)
    omission = leave_one_out(instruments.loc[instruments.evaluation_mode == 'primary'])
    recipe = {
        'training_experiment_id': verified['experiment_id'],
        'training_manifest_sha256': sha256(experiment / 'manifest.json'),
        'modeling_dataset_id': manifest['modeling_dataset_id'],
        'configuration': config, 'script_sha256': sha256(Path(__file__)),
        'metric_code_sha256': sha256(ROOT / 'scripts/evaluate_baselines.py'),
        'python': platform.python_version(), 'platform': platform.system(),
        'packages': {name: version(name) for name in ['numpy', 'pandas', 'duckdb', 'matplotlib']},
    }
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    result = {'robustness_id': identity, 'recipe': recipe,
              'selected_model_unchanged': summary['selected_model'],
              'selected_ewma_unchanged': summary['selected_ewma'],
              'phase_metrics': phase_scores.to_dict('records'),
              'models_refitted': False, 'final_test_scores_computed': False,
              'offset_zero_exactly_matches_primary': True}
    return result, {'phase_metrics': phase_scores,
                    'phase_errors': pd.concat(selected_rows, ignore_index=True),
                    'leave_one_instrument_out_metrics': omission}


def write_outputs(result, frames, folder):
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'data/cache/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['svg.hashsalt'] = 'portfolio-risk-development-robustness'
    selected, ewma = result['selected_model_unchanged'], result['selected_ewma_unchanged']
    methods = ['trailing_20', ewma, selected]
    phases = frames['phase_metrics']
    table = ['| Year | Offset, sessions | Method | Pairs | Volatility MAE, pp | QLIKE |',
             '| --- | ---: | --- | ---: | ---: | ---: |']
    shown = phases.loc[phases.method.isin(methods)]
    current = shown.loc[shown.year == 2025].pivot(index='grid_offset_sessions', columns='method', values='volatility_mae_pp')
    ewma_wins = int((current[selected] < current[ewma]).sum())
    trailing_wins = int((current[selected] < current['trailing_20']).sum())
    for row in shown.itertuples():
        table.append(f'| {row.year} | {row.grid_offset_sessions} | {row.method} | {row.observations} | {row.volatility_mae_pp:.4f} | {row.variance_qlike:.4f} |')
    fig, ax = plt.subplots(figsize=(9.1, 4.8), layout='constrained')
    for method, label, color in zip(methods, ['Trailing 20', f'EWMA {ewma[-4:]}', 'Selected HGB'], ['#284f7d', '#8eb1d4', '#448e7b']):
        values = phases.loc[(phases.year == 2025) & (phases.method == method)].sort_values('grid_offset_sessions')
        ax.plot(values.grid_offset_sessions, values.volatility_mae_pp, marker='o', label=label, color=color)
    ax.set_xticks([0, 5, 10, 15])
    ax.set(xlabel='Grid offset from first ready origin (sessions)',
           ylabel='Annualized-volatility MAE (percentage points)',
           title='2025 development sensitivity to forecast dates\nFixed selected models; no refitting or reselection')
    ax.spines[['right', 'top']].set_visible(False)
    ax.legend(frameon=False)
    assets = folder / 'assets'
    assets.mkdir()
    fig.savefig(assets / 'development-grid-sensitivity.svg', metadata={'Date': None})
    fig.savefig(assets / 'development-grid-sensitivity.png', dpi=150, metadata={'Software': 'portfolio-risk'})
    plt.close(fig)
    svg = assets / 'development-grid-sensitivity.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    omission = frames['leave_one_instrument_out_metrics']
    omitted_table = ['| Year | Method | Lowest omission MAE, pp | Highest omission MAE, pp |',
                     '| --- | --- | ---: | ---: |']
    for (year, method), group in omission.loc[omission.method.isin(methods)].groupby(['year', 'method'], sort=True):
        omitted_table.append(f'| {year} | {method} | {group.volatility_mae_pp.min():.4f} | {group.volatility_mae_pp.max():.4f} |')
    text = f'''# Development robustness review

Updated November 4, 2026. RB-001 examines the existing saved forecasts after ML-001 development selection. It does not refit models, add candidates, change the primary grid, or open 2026 outcomes. Results are diagnostic development evidence.

In 2025, the fixed selected model has lower volatility MAE than selected EWMA in **{ewma_wins} of four phases**, and lower MAE than trailing variance in **{trailing_wins} of four phases**. The model-versus-EWMA ranking therefore depends on forecast dates. These counts are descriptive and dependent, not a probability of future superiority. Keep the original primary result and this sensitivity evidence together.

## Why forecast dates matter

The declared primary grid samples every twenty sessions. Four phase offsets (0, 5, 10, 15) test whether a different starting date changes the observed comparison. Each phase has non-overlapping target windows within an instrument. Phases overlap one another and share market events; they are not independent replications, confidence intervals, or a basis for selecting a more favorable test grid.

Offset zero exactly reproduces the original primary predictions, targets, and errors. The same fixed models and EWMA decay selected using 2025 remain in every comparison. All seven original candidates remain in the local record; the public table focuses on the selected model and two benchmark families.

![Development errors under four fixed grid offsets](assets/development-grid-sensitivity.svg)

{chr(10).join(table)}

## Sensitivity to instrument aggregation

Leave-one-instrument-out results remove an asset only from score aggregation. They do not retrain a model without it and do not estimate generalization to an unseen company. The universe and all fitted models remain unchanged. Ranges below are descriptive minima/maxima across sixteen omissions, not uncertainty intervals.

{chr(10).join(omitted_table)}

## Evidence and reproduction

- Robustness run: `{result['robustness_id']}`.
- Training experiment: `{result['recipe']['training_experiment_id']}`.
- [RB-001 configuration](../config/development_robustness.json); [trained-model report](MODEL_DEVELOPMENT_REPORT.md).
- Source experiment identity/hashes and all original saved scores pass the independent verifier before use. Model and data identity are matched. Missing phase forecasts block comparison. All scores average instruments equally.

```bash
.venv/bin/python -m scripts.evaluate_development_robustness --experiment data/experiments/trained_models/{result['recipe']['training_experiment_id']} --modeling-dataset data/modeling/{result['recipe']['modeling_dataset_id']}
```

Do not change selection or the final-test grid after observing these diagnostics. A robust conclusion must account for changes across years, metrics, assets, and phases. This remains a small revised-history research dataset; no final-test or live performance claim is established.
'''
    (folder / 'DEVELOPMENT_ROBUSTNESS.md').write_text(text)


def publish(result, frames, root):
    root.mkdir(parents=True, exist_ok=True)
    destination = root / result['robustness_id']
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=root))
    try:
        for name, frame in frames.items():
            with duckdb.connect() as connection:
                connection.register('records', frame)
                connection.sql('SELECT * FROM records').write_parquet(str(staging / (name + '.parquet')), compression='zstd')
        (staging / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        write_outputs(result, frames, staging)
        manifest = {'robustness_id': result['robustness_id'], 'outputs': {
            str(p.relative_to(staging)): sha256(p) for p in sorted(staging.rglob('*')) if p.is_file()}}
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        if destination.exists():
            if json.loads((destination / 'manifest.json').read_text()) != manifest:
                raise ValueError('Repeated robustness artifact differs')
            for name, digest in manifest['outputs'].items():
                if sha256(destination / name) != digest:
                    raise ValueError('Saved robustness artifact differs')
            shutil.rmtree(staging)
        else:
            staging.rename(destination)
        shutil.copy2(destination / 'DEVELOPMENT_ROBUSTNESS.md', ROOT / 'docs/DEVELOPMENT_ROBUSTNESS.md')
        shutil.copy2(destination / 'assets/development-grid-sensitivity.svg', ROOT / 'docs/assets/development-grid-sensitivity.svg')
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--modeling-dataset', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / 'config/development_robustness.json').read_text())
    result, frames = evaluate(args.experiment, args.modeling_dataset, config)
    publish(result, frames, ROOT / 'data/experiments/robustness')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
