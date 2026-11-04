"""Train a fixed candidate grid on chronological development folds only.

No final refitting, 2026 forecasts, final-test outcomes, or final scores are
produced. Model artifacts and detailed observations remain local.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import uuid

import duckdb
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from scripts.audit_market_data import ROOT, sha256
from scripts.build_modeling_dataset import FEATURE_COLUMNS
from scripts import evaluate_baselines as baseline
from scripts.evaluation_splits import validate_protocol

KEYS = baseline.KEYS


def configuration() -> dict:
    return json.loads((ROOT / 'config/model_training.json').read_text())


def validate_configuration(config: dict) -> None:
    expected = {
        'training_protocol_id': 'ML-001', 'schema_version': 1,
        'development_years': [2023, 2024, 2025],
        'estimator': 'sklearn.ensemble.HistGradientBoostingRegressor',
        'loss': 'poisson', 'learning_rate': .05, 'max_iter': 150,
        'min_samples_leaf': 100, 'l2_regularization': 1., 'max_bins': 255,
        'early_stopping': False, 'random_state': 42, 'thread_limit': 1,
        'candidates': [{'method': f'hgb_{n}', 'max_leaf_nodes': n} for n in [7, 15, 31]],
        'training_weights': 'equal_total_weight_per_instrument_mean_row_weight_one',
        'preprocessing': 'none_explicit_numeric_feature_whitelist',
        'selection_year': 2025,
        'selection_metric': 'equal_instrument_primary_volatility_mae',
        'selection_tiebreak': 'ascending_method_id',
        'diagnostic_regime': 'above_training_instrument_median_target_volatility',
        'final_refit_performed': False, 'final_test_opened': False,
    }
    if config != expected:
        raise ValueError('Unsupported ML-001 semantics; version a reviewed recipe before changes')


def predictor_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    """Metadata and labels are deliberately excluded even if they are numeric."""
    if frame.columns.duplicated().any():
        raise ValueError('Duplicate input column names')
    matrix = frame.loc[:, FEATURE_COLUMNS].astype('float64').copy()
    if matrix.empty or not np.isfinite(matrix.to_numpy()).all():
        raise ValueError('Predictors must contain nonempty finite feature rows')
    return matrix


def equal_instrument_weights(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty or frame.instrument_id.isna().any():
        raise ValueError('Training requires identified instruments')
    counts = frame.groupby('instrument_id').instrument_id.transform('size')
    return (len(frame) / frame.instrument_id.nunique() / counts).to_numpy(dtype=float)


def training_slice(examples: pd.DataFrame, year: int, protocol: dict) -> pd.DataFrame:
    validate_protocol(protocol)
    if year not in protocol['development_validation_years'] or year >= 2026:
        raise ValueError('Only declared pre-2026 development folds can be trained')
    if examples.duplicated(KEYS).any():
        raise ValueError('Duplicate modeling example keys')
    train = examples.loc[examples[f'fold_{year}_train']].sort_values(KEYS).copy()
    boundary = pd.Timestamp(f'{year}-01-01')
    valid = (
        train.feature_ready & train.feature_history_ready & train.target_complete
        & (train.origin_date >= pd.Timestamp(protocol['train_start']))
        & (train.origin_date < boundary) & (train.target_end_date < boundary)
        & (train.target_end_date > train.origin_date)
    )
    if train.empty or not valid.all():
        raise ValueError('Training membership violates chronological readiness or target purge')
    target = train.target_variance.to_numpy(dtype=float)
    if not np.isfinite(target).all() or (target < 0).any() or not (target > 0).any():
        raise ValueError('Poisson training requires finite nonnegative targets with positive mass')
    predictor_matrix(train)
    return train.reset_index(drop=True)


def build_estimator(candidate: dict, config: dict) -> HistGradientBoostingRegressor:
    validate_configuration(config)
    if candidate not in config['candidates']:
        raise ValueError('Undeclared candidate')
    return HistGradientBoostingRegressor(
        loss=config['loss'], learning_rate=config['learning_rate'],
        max_iter=config['max_iter'], max_leaf_nodes=candidate['max_leaf_nodes'],
        min_samples_leaf=config['min_samples_leaf'],
        l2_regularization=config['l2_regularization'], max_bins=config['max_bins'],
        categorical_features=None, early_stopping=False, validation_fraction=None,
        random_state=config['random_state'],
    )


def fit_candidate(train: pd.DataFrame, candidate: dict, config: dict):
    estimator = build_estimator(candidate, config)
    with threadpool_limits(limits=config['thread_limit']):
        estimator.fit(predictor_matrix(train), train.target_variance.to_numpy(dtype=float),
                      sample_weight=equal_instrument_weights(train))
    if list(estimator.feature_names_in_) != FEATURE_COLUMNS or estimator.do_early_stopping_:
        raise ValueError('Estimator violated feature or early-stopping contract')
    return estimator


def predict_variance(estimator, rows: pd.DataFrame) -> np.ndarray:
    with threadpool_limits(limits=1):
        prediction = estimator.predict(predictor_matrix(rows))
    if not np.isfinite(prediction).all() or (prediction <= 0).any():
        raise ValueError('Log-link model must produce finite strictly positive variance')
    return prediction


def select_candidate(overall: pd.DataFrame, config: dict) -> str:
    methods = {candidate['method'] for candidate in config['candidates']}
    choices = overall.loc[(overall.year == config['selection_year'])
                          & (overall.evaluation_mode == 'primary')
                          & overall.method.isin(methods)]
    if set(choices.method) != methods or choices.method.duplicated().any():
        raise ValueError('Incomplete trained-model candidate comparison')
    if not np.isfinite(choices.volatility_mae_pp).all():
        raise ValueError('Candidate selection requires finite errors')
    return choices.sort_values(['volatility_mae_pp', 'method'], kind='stable').iloc[0].method


def regime_metrics(errors: pd.DataFrame, training_medians: pd.DataFrame) -> pd.DataFrame:
    """Outcome-based diagnostic slices; never available as prediction inputs."""
    frame = errors.merge(training_medians, on=['year', 'instrument_id'],
                         how='left', validate='many_to_one')
    if frame.training_median_volatility.isna().any():
        raise ValueError('Missing training-only diagnostic threshold')
    frame['realized_regime'] = np.where(
        np.sqrt(frame.target_variance) > frame.training_median_volatility,
        'above_training_median', 'at_or_below_training_median')
    per_asset = frame.groupby(['year', 'evaluation_mode', 'method', 'realized_regime',
                               'instrument_id'], sort=True).agg(
        observations=('target_variance', 'size'),
        volatility_mae_pp=('volatility_absolute_error_pp', 'mean'),
        variance_qlike=('variance_qlike', 'mean')).reset_index()
    return per_asset.groupby(['year', 'evaluation_mode', 'method', 'realized_regime'], sort=True).agg(
        instruments=('instrument_id', 'size'), observations=('observations', 'sum'),
        volatility_mae_pp=('volatility_mae_pp', 'mean'),
        variance_qlike=('variance_qlike', 'mean')).reset_index()


def log_event(path: Path | None, event: str, **values) -> None:
    if path is not None:
        with path.open('a') as stream:
            stream.write(json.dumps({'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
                                     'event': event, **values}, allow_nan=False) + '\n')


def evaluate(folder: Path, config: dict, attempt_log: Path | None = None):
    validate_configuration(config)
    manifest, frames = baseline.load_modeling_artifacts(folder)
    protocol = manifest['recipe']['protocol']
    baseline_config = json.loads((ROOT / 'config/forecast_baselines.json').read_text())
    benchmark, benchmark_frames = baseline.evaluate(folder, baseline_config)
    origins = benchmark_frames['evaluation_origins']
    errors = [benchmark_frames['per_origin_errors']]
    predictions, fold_records, median_records, models = [], [], [], {}
    validation_predictors = []
    for year in config['development_years']:
        train = training_slice(frames['development_examples'], year, protocol)
        validation_origins = origins.loc[(origins.year == year)
                                         & (origins.evaluation_mode == 'daily'), KEYS]
        validation = validation_origins.merge(frames['features_daily'], on=KEYS,
                                               how='left', validate='one_to_one').sort_values(KEYS)
        if not (validation.origin_date.dt.year == year).all():
            raise ValueError('Unexpected prediction year')
        validation_predictors.append(validation[KEYS + FEATURE_COLUMNS].copy())
        medians = train.groupby('instrument_id').target_volatility.median()
        for instrument, value in medians.items():
            median_records.append({'year': year, 'instrument_id': instrument,
                                   'training_median_volatility': float(value)})
        for candidate in config['candidates']:
            method = candidate['method']
            log_event(attempt_log, 'fit_started', year=year, candidate=candidate,
                      training_rows=len(train), validation_rows=len(validation))
            model = fit_candidate(train, candidate, config)
            forecast = validation[KEYS].copy()
            forecast['method'] = method
            forecast['predicted_variance'] = predict_variance(model, validation)
            # A repeated fit verifies seed/thread reproducibility on actual observations.
            replay = fit_candidate(train, candidate, config)
            np.testing.assert_array_equal(forecast.predicted_variance,
                                           predict_variance(replay, validation))
            predictions.append(forecast)
            models[f'{year}-{method}'] = model
            fold_records.append({
                'year': year, 'method': method, 'training_rows': len(train),
                'training_instruments': int(train.instrument_id.nunique()),
                'training_origin_start': str(train.origin_date.min().date()),
                'training_origin_end': str(train.origin_date.max().date()),
                'latest_training_target_end': str(train.target_end_date.max().date()),
                'validation_rows': len(validation), 'iterations': int(model.n_iter_),
                'feature_columns': FEATURE_COLUMNS, 'parameters': model.get_params(),
                'repeat_fit_predictions_identical': True,
            })
            log_event(attempt_log, 'fit_completed', year=year, method=method,
                      repeat_fit_predictions_identical=True)
        year_predictions = pd.concat(predictions[-len(config['candidates']):], ignore_index=True)
        for mode in ['primary', 'daily']:
            selected_origins = origins.loc[(origins.year == year) & (origins.evaluation_mode == mode)]
            errors.append(baseline.score_common_origins(
                year_predictions, selected_origins, frames['targets_development'],
                [candidate['method'] for candidate in config['candidates']],
                baseline_config['qlike_prediction_floor']))
    all_errors = pd.concat(errors, ignore_index=True)
    universe = json.loads((ROOT / 'config/reference_universe.json').read_text())
    overall, instruments, groups = baseline.metric_tables(
        all_errors, {row['symbol']: row['kind'] for row in universe['instruments']})
    selected = select_candidate(overall, config)
    medians = pd.DataFrame(median_records)
    regimes = regime_metrics(all_errors, medians)
    recipe = {
        'modeling_dataset_id': manifest['modeling_dataset_id'],
        'modeling_manifest_sha256': sha256(folder / 'manifest.json'),
        'baseline_experiment_id': benchmark['experiment_id'],
        'training_configuration': config, 'evaluation_protocol': protocol,
        'feature_columns': FEATURE_COLUMNS,
        'code_sha256': {name: sha256(ROOT / name) for name in [
            'scripts/train_risk_model.py', 'scripts/evaluate_baselines.py',
            'scripts/build_modeling_dataset.py', 'scripts/evaluation_splits.py']},
        'reference_universe_sha256': sha256(ROOT / 'config/reference_universe.json'),
        'python': platform.python_version(), 'platform': platform.system(),
        'packages': {name: version(name) for name in [
            'numpy', 'pandas', 'duckdb', 'matplotlib', 'scikit-learn', 'scipy',
            'joblib', 'threadpoolctl']},
    }
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    result = {
        'experiment_id': identity, 'recipe': recipe,
        'selected_model': selected, 'selected_ewma': benchmark['selected_ewma'],
        'selection_scope': '2025 primary development MAE; not an unbiased final test',
        'overall_metrics': overall.to_dict('records'), 'fold_records': fold_records,
        'final_refit_performed': False, 'final_test_scores_computed': False,
        'machine_learning_models_trained': len(models),
    }
    log_event(attempt_log, 'evaluation_completed', experiment_id=identity,
              selected_model=selected, final_test_scores_computed=False)
    return result, {
        'model_forecasts': pd.concat(predictions, ignore_index=True),
        'validation_predictors': pd.concat(validation_predictors, ignore_index=True),
        'evaluation_origins': origins, 'per_origin_errors': all_errors,
        'per_instrument_metrics': instruments, 'exposure_group_metrics': groups,
        'realized_regime_metrics': regimes, 'training_regime_thresholds': medians,
    }, models


def write_figures(result: dict, frames: dict, folder: Path) -> None:
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'data/cache/matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['svg.hashsalt'] = 'portfolio-risk-trained-model'
    metrics = pd.DataFrame(result['overall_metrics'])
    selected, ewma = result['selected_model'], result['selected_ewma']
    methods = ['trailing_20', ewma, selected]
    labels = ['Trailing 20', f'EWMA {ewma[-4:]}', f'Selected HGB ({selected[4:]} leaves)']
    colors = ['#284f7d', '#8eb1d4', '#448e7b']
    primary = metrics.loc[metrics.evaluation_mode == 'primary']
    fig, ax = plt.subplots(figsize=(9.4, 4.9), layout='constrained')
    x = np.arange(3)
    for index, (method, label, color) in enumerate(zip(methods, labels, colors)):
        values = primary.loc[primary.method == method].set_index('year').loc[[2023, 2024, 2025], 'volatility_mae_pp']
        bars = ax.bar(x + (index - 1) * .24, values, .24, label=label, color=color)
        ax.bar_label(bars, fmt='%.2f', fontsize=9, padding=3)
    ax.set_xticks(x, ['2023', '2024', '2025'])
    ax.set_ylabel('Annualized-volatility MAE (percentage points)')
    ax.set_ylim(0, float(primary.volatility_mae_pp.max()) * 1.25)
    ax.set_title('Chronological development forecasts\nModel and EWMA chosen using 2025; final 2026 test unopened')
    ax.legend(loc='upper left', frameon=False)
    ax.spines[['right', 'top']].set_visible(False)
    fig.savefig(folder / 'model-development-comparison.png', dpi=150, metadata={'Software': 'portfolio-risk'})
    fig.savefig(folder / 'model-development-comparison.svg', metadata={'Date': None})
    plt.close(fig)
    frame = frames['per_origin_errors']
    frame = frame.loc[(frame.year == 2025) & (frame.evaluation_mode == 'primary') & (frame.method == selected)]
    fig, ax = plt.subplots(figsize=(7.2, 6.1), layout='constrained')
    actual = 100 * np.sqrt(frame.target_variance)
    predicted = 100 * np.sqrt(frame.predicted_variance)
    ax.scatter(actual, predicted, s=21, alpha=.6, color='#448e7b', edgecolors='none')
    limit = max(float(actual.max()), float(predicted.max())) * 1.05
    ax.plot([0, limit], [0, limit], color='#284f7d', linestyle='--', label='Exact agreement')
    ax.set(xlim=(0, limit), ylim=(0, limit),
           xlabel='Realized annualized volatility (%)', ylabel='Predicted annualized volatility (%)',
           title='2025 primary forecasts for selected model\nDevelopment selection sample; 192 correlated instrument/window pairs')
    ax.legend(frameon=False)
    ax.spines[['right', 'top']].set_visible(False)
    fig.savefig(folder / 'model-prediction-diagnostics.png', dpi=150, metadata={'Software': 'portfolio-risk'})
    fig.savefig(folder / 'model-prediction-diagnostics.svg', metadata={'Date': None})
    plt.close(fig)
    for path in folder.glob('*.svg'):
        path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')


def write_report(result: dict, frames: dict, folder: Path) -> None:
    metrics = pd.DataFrame(result['overall_metrics'])
    selected, ewma = result['selected_model'], result['selected_ewma']
    primary = metrics.loc[metrics.evaluation_mode == 'primary']
    table = ['| Year | Method | Pairs | Volatility MAE, pp | Variance QLIKE |',
             '| --- | --- | ---: | ---: | ---: |']
    for row in primary.itertuples():
        table.append(f'| {row.year} | {row.method} | {row.observations} | {row.volatility_mae_pp:.4f} | {row.variance_qlike:.4f} |')
    folds = ['| Validation year | Training rows | Latest training target | Validation rows |',
             '| --- | ---: | --- | ---: |']
    for year in [2023, 2024, 2025]:
        row = next(r for r in result['fold_records'] if r['year'] == year)
        folds.append(f"| {year} | {row['training_rows']} | {row['latest_training_target_end']} | {row['validation_rows']} |")
    current = primary.loc[primary.year == 2025].set_index('method')
    best = current.loc[selected]
    trailing, exponential = current.loc['trailing_20'], current.loc[ewma]
    daily_table = ['| Year | Method | Daily pairs | Volatility MAE, pp | QLIKE |',
                   '| --- | --- | ---: | ---: | ---: |']
    daily = metrics.loc[(metrics.evaluation_mode == 'daily')
                        & metrics.method.isin(['trailing_20', ewma, selected])]
    for row in daily.itertuples():
        daily_table.append(f'| {row.year} | {row.method} | {row.observations} | {row.volatility_mae_pp:.4f} | {row.variance_qlike:.4f} |')
    instrument_table = ['| Instrument | Model MAE, pp | EWMA MAE, pp | Trailing MAE, pp |',
                        '| --- | ---: | ---: | ---: |']
    by_asset = frames['per_instrument_metrics']
    by_asset = by_asset.loc[(by_asset.year == 2025) & (by_asset.evaluation_mode == 'primary')]
    asset_mae = by_asset.pivot(index='instrument_id', columns='method', values='volatility_mae_pp')
    for instrument, row in asset_mae.sort_index().iterrows():
        instrument_table.append(f'| {instrument} | {row[selected]:.4f} | {row[ewma]:.4f} | {row["trailing_20"]:.4f} |')
    regimes = frames['realized_regime_metrics']
    sliced = regimes.loc[(regimes.year == 2025) & (regimes.evaluation_mode == 'primary')
                         & regimes.method.isin(['trailing_20', ewma, selected])]
    regime_table = ['| Realized regime | Method | Instruments | Pairs | MAE, pp | QLIKE |',
                    '| --- | --- | ---: | ---: | ---: | ---: |']
    for row in sliced.itertuples():
        regime_table.append(f'| {row.realized_regime} | {row.method} | {row.instruments} | {row.observations} | {row.volatility_mae_pp:.4f} | {row.variance_qlike:.4f} |')
    text = f'''# Trained risk-model development experiment

Updated November 4, 2026. ML-001 trains pooled histogram gradient-boosted trees on earlier years and evaluates fixed development folds. No final refitting or 2026 predictions, outcomes, or scores are produced.

## Executive result

The selected trained candidate is **{selected}**, chosen by primary 2025 equal-instrument volatility MAE. Its 2025 error is **{best.volatility_mae_pp:.4f} percentage points**, compared with **{trailing.volatility_mae_pp:.4f}** for trailing variance and **{exponential.volatility_mae_pp:.4f}** for selected **{ewma}**. Its variance QLIKE is **{best.variance_qlike:.4f}**, versus **{trailing.variance_qlike:.4f}** and **{exponential.variance_qlike:.4f}**, respectively. Lower is better on these same outcomes. These are development-selection results, not independent final-test evidence or a deployment recommendation.

{chr(10).join(table)}

Every method uses the same twelve primary windows per instrument/year (192 pairs across sixteen instruments). Daily overlapping scores are secondary and retained in the local summary. Methods first average within instruments, then weight instruments equally. All candidate settings remain visible; choosing by 2025 makes that year's selected score optimistic. Earlier-year differences and secondary metrics must be considered before claiming improvement. Instrument pairs share market events and cannot be treated as independent observations.

![Selected model and historical benchmarks across development years](assets/model-development-comparison.svg)

### Secondary daily comparisons

{chr(10).join(daily_table)}

These daily target windows overlap. They provide a sensitivity view and must not replace the declared primary grid after observing the results. The selected candidate and EWMA decay are fixed by the 2025 primary rule when shown in earlier years.

## Training contract

{chr(10).join(folds)}

One model pools the sixteen instruments using the explicit twelve-column price-feature whitelist. Instrument IDs, dates, eligibility flags, target endpoints, and labels are excluded from predictors. Each fold fits only earlier target windows that finish before its validation year. Equal total training weight is assigned to each instrument, with mean row weight one. No scaling, imputation, feature selection, or target transformation is fitted; finite, ready feature rows are required.

Three fixed candidates differ only in maximum leaves (7, 15, 31). All use 150 boosting iterations, learning rate 0.05, minimum 100 observations per leaf, L2 regularization 1, seed 42, and one computational thread. Poisson deviance with a log link gives positive variance estimates for a nonnegative continuous target; it does not assert that volatility is a Poisson count. Random-split early stopping is explicitly disabled. The objective fits variance, while selection measures volatility MAE, so the optimization and reporting metrics differ.

The model is frozen within each validation year. Inputs update after each close without fitting on validation outcomes. Training uses overlapping daily labels, so training-row counts overstate independent market episodes. Repeat fitting of all nine candidate/fold combinations produces identical predictions. This is same-environment determinism, not proof of generalization or cross-platform bitwise equivalence.

## Where predictions fail

![Selected model predicted versus realized volatility in 2025](assets/model-prediction-diagnostics.svg)

The diagonal indicates exact agreement; points below it underestimate realized risk. This plot uses the same 2025 development sample that influenced selection and is not a calibration guarantee. The following slices classify realized outcomes using each instrument's training-only median target volatility. Realized regime is known afterward and is never a model input. A slice can omit an instrument if it has no qualifying outcomes; compare only the same slice across methods.

{chr(10).join(regime_table)}

### 2025 primary errors by instrument

{chr(10).join(instrument_table)}

Each instrument has only twelve primary outcomes. A favorable aggregate can coexist with substantial errors or deterioration for particular assets. This table describes the declared universe and does not justify adding or removing assets after seeing their results.

## Reproduction and limitations

- Experiment: `{result['experiment_id']}`.
- Modeling dataset: `{result['recipe']['modeling_dataset_id']}`.
- Baseline experiment: `{result['recipe']['baseline_experiment_id']}`.
- [ML-001 recipe](../config/model_training.json); [evaluation contract](EVALUATION_PROTOCOL.md).
- Saved artifacts include every candidate/fold model, parameters, training dates, feature order, package/code/data versions, all forecasts, matched origins, errors, exposure-group/regime metrics, and hashes. An append-only local attempt log records starts, completions, and failures. This is file-based tracking; MLflow remains uninstalled.

```bash
.venv/bin/python -m scripts.train_risk_model --modeling-dataset data/modeling/{result['recipe']['modeling_dataset_id']}
.venv/bin/python -m unittest discover -s tests -v
```

Model files stay local. Only models generated in the current run are reloaded for verification; arbitrary downloaded pickle/joblib files are not accepted. The source data contain revised adjusted histories and a small current-survivor universe. Development tuning, correlated assets, limited non-overlapping windows, and absent transaction costs limit conclusions. This experiment forecasts instrument variance, not portfolio covariance or expected investment returns. Portfolio-level forecasting requires a separate correlation estimator and evaluation. News, personal risk preferences, portfolio suggestions, final refitting, and final testing remain subsequent work.

Method references: [scikit-learn estimator documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html) and [model persistence documentation](https://scikit-learn.org/stable/model_persistence.html). Numerical results are generated from this project's saved experiment.
'''
    (folder / 'MODEL_DEVELOPMENT_REPORT.md').write_text(text)


def publish(result: dict, frames: dict, models: dict, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    destination = root / result['experiment_id']
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=root))
    try:
        for name, frame in frames.items():
            with duckdb.connect() as connection:
                connection.register('records', frame)
                connection.sql('SELECT * FROM records').write_parquet(str(staging / (name + '.parquet')), compression='zstd')
        (staging / 'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
        model_folder = staging / 'models'
        model_folder.mkdir()
        # Only reload files created in this run, using the same pinned environment.
        for name, model in sorted(models.items()):
            path = model_folder / (name + '.joblib')
            joblib.dump(model, path, compress=3, protocol=5)
            restored = joblib.load(path)
            year, method = name.split('-', 1)
            probes = frames['validation_predictors']
            probes = probes.loc[probes.origin_date.dt.year == int(year)].sort_values(KEYS)
            expected = frames['model_forecasts']
            expected = expected.loc[(expected.origin_date.dt.year == int(year))
                                    & (expected.method == method)].sort_values(KEYS)
            np.testing.assert_array_equal(predict_variance(model, probes),
                                           predict_variance(restored, probes))
            np.testing.assert_array_equal(expected.predicted_variance,
                                           predict_variance(restored, probes))
        assets = staging / 'assets'
        assets.mkdir()
        write_figures(result, frames, assets)
        write_report(result, frames, staging)
        outputs = {str(path.relative_to(staging)): sha256(path)
                   for path in sorted(staging.rglob('*')) if path.is_file()}
        manifest = {'experiment_id': result['experiment_id'], 'outputs': outputs}
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        if destination.exists():
            existing = json.loads((destination / 'manifest.json').read_text())
            if existing != manifest:
                raise ValueError('Repeated trained experiment differs from saved output hashes')
            for name, digest in outputs.items():
                if sha256(destination / name) != digest:
                    raise ValueError('Saved trained experiment artifact differs')
            shutil.rmtree(staging)
        else:
            staging.rename(destination)
        shutil.copy2(destination / 'MODEL_DEVELOPMENT_REPORT.md', ROOT / 'docs/MODEL_DEVELOPMENT_REPORT.md')
        for path in (destination / 'assets').glob('*.svg'):
            shutil.copy2(path, ROOT / 'docs/assets' / path.name)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modeling-dataset', type=Path, required=True)
    args = parser.parse_args()
    config = configuration()
    attempt_folder = ROOT / 'data/experiments/training_attempts'
    attempt_folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    attempt_log = attempt_folder / f'{timestamp}-{uuid.uuid4().hex[:8]}.jsonl'
    log_event(attempt_log, 'experiment_started', configuration=config)
    try:
        result, frames, models = evaluate(args.modeling_dataset, config, attempt_log)
        publish(result, frames, models, ROOT / 'data/experiments/trained_models')
        log_event(attempt_log, 'published', experiment_id=result['experiment_id'])
    except Exception as error:
        log_event(attempt_log, 'failed', exception_type=type(error).__name__, message=str(error))
        raise
    print(json.dumps({'experiment_id': result['experiment_id'],
                      'selected_model': result['selected_model'],
                      'models_trained': result['machine_learning_models_trained'],
                      'primary_metrics': [row for row in result['overall_metrics']
                                          if row['evaluation_mode'] == 'primary'],
                      'final_test_scores_computed': False}, indent=2))


if __name__ == '__main__':
    main()
