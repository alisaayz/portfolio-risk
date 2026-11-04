"""Chronological fitting, predictor isolation, positive forecasts and selection."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from scripts.build_modeling_dataset import FEATURE_COLUMNS
from scripts.train_risk_model import (
    build_estimator, configuration, equal_instrument_weights, fit_candidate,
    log_event, predict_variance, predictor_matrix, regime_metrics,
    select_candidate, training_slice, validate_configuration,
)
from tests.test_modeling_dataset import protocol


def fixture():
    dates = pd.date_range('2021-01-04', periods=400, freq='B')
    values = np.arange(400) / 400
    frame = pd.DataFrame({name: values * (index + 1) / 100
                          for index, name in enumerate(FEATURE_COLUMNS)})
    frame['instrument_id'] = np.where(np.arange(400) % 2 == 0, 'A', 'B')
    frame['origin_date'] = dates
    frame['target_end_date'] = dates + pd.offsets.BDay(20)
    frame['feature_ready'] = True
    frame['feature_history_ready'] = True
    frame['target_complete'] = True
    frame['target_variance'] = .01 + .08 * values ** 2
    frame['target_volatility'] = np.sqrt(frame.target_variance)
    frame['fold_2023_train'] = True
    frame['fold_2024_train'] = True
    frame['fold_2025_train'] = True
    return frame


class ModelTrainingTests(unittest.TestCase):
    def test_only_explicit_features_enter_predictor_matrix(self):
        frame = fixture()
        before = predictor_matrix(frame)
        frame['target_variance'] = 99999.
        frame['target_end_date'] = pd.Timestamp('2099-01-01')
        frame['instrument_id'] = 'numeric_metadata_must_not_enter'
        frame['accidental_numeric_column'] = -123.
        frame = frame[list(reversed(frame.columns))]
        pd.testing.assert_frame_equal(before, predictor_matrix(frame), check_exact=True)
        self.assertEqual(list(before.columns), FEATURE_COLUMNS)

    def test_nonfinite_missing_and_duplicate_feature_columns_are_rejected(self):
        for value in [np.nan, np.inf, -np.inf]:
            frame = fixture()
            frame.loc[0, FEATURE_COLUMNS[0]] = value
            with self.assertRaises(ValueError):
                predictor_matrix(frame)
        with self.assertRaises(KeyError):
            predictor_matrix(fixture().drop(columns=FEATURE_COLUMNS[0]))
        with self.assertRaises(ValueError):
            predictor_matrix(pd.concat([fixture(), fixture()[[FEATURE_COLUMNS[0]]]], axis=1))

    def test_each_instrument_gets_equal_total_training_weight(self):
        frame = pd.DataFrame({'instrument_id': ['A', 'A', 'A', 'B']})
        weights = equal_instrument_weights(frame)
        np.testing.assert_allclose(weights, [2 / 3, 2 / 3, 2 / 3, 2.])
        self.assertAlmostEqual(weights.mean(), 1.)
        self.assertAlmostEqual(weights[:3].sum(), weights[3])
        with self.assertRaises(ValueError):
            equal_instrument_weights(pd.DataFrame({'instrument_id': []}))

    def test_training_labels_must_finish_before_validation(self):
        frame = fixture()
        selected = training_slice(frame, 2023, protocol())
        self.assertEqual(len(selected), 400)
        frame.loc[0, 'target_end_date'] = pd.Timestamp('2023-01-02')
        with self.assertRaisesRegex(ValueError, 'purge'):
            training_slice(frame, 2023, protocol())

    def test_bad_readiness_or_target_values_block_training(self):
        for column, value in [('feature_ready', False), ('feature_history_ready', False),
                              ('target_complete', False), ('target_variance', -1.),
                              ('target_variance', np.nan)]:
            frame = fixture()
            frame.loc[0, column] = value
            with self.assertRaises(ValueError):
                training_slice(frame, 2023, protocol())
        frame = fixture()
        frame['target_variance'] = 0.
        with self.assertRaises(ValueError):
            training_slice(frame, 2023, protocol())

    def test_final_test_fold_and_duplicate_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            training_slice(fixture(), 2026, protocol())
        with self.assertRaises(ValueError):
            training_slice(pd.concat([fixture(), fixture().iloc[:1]]), 2023, protocol())

    def test_random_validation_early_stopping_is_disabled(self):
        config = configuration()
        estimator = build_estimator(config['candidates'][0], config)
        self.assertIs(estimator.early_stopping, False)
        self.assertIsNone(estimator.validation_fraction)
        self.assertEqual(estimator.loss, 'poisson')
        with self.assertRaises(ValueError):
            build_estimator({'method': 'unregistered', 'max_leaf_nodes': 99}, config)

    def test_fitted_model_predictions_are_positive_and_repeatable(self):
        config = configuration()
        train = training_slice(fixture(), 2023, protocol())
        first = fit_candidate(train, config['candidates'][0], config)
        second = fit_candidate(train, config['candidates'][0], config)
        a = predict_variance(first, train)
        b = predict_variance(second, train)
        np.testing.assert_array_equal(a, b)
        self.assertTrue(np.isfinite(a).all())
        self.assertTrue((a > 0).all())
        self.assertEqual(first.n_iter_, 150)

    def test_excluded_future_outcomes_cannot_change_fitted_predictions(self):
        config = configuration()
        original = fixture()
        future = original.iloc[:20].copy()
        future['origin_date'] = pd.date_range('2023-02-01', periods=20, freq='B')
        future['target_end_date'] = future.origin_date + pd.offsets.BDay(20)
        future['fold_2023_train'] = False
        all_rows = pd.concat([original, future], ignore_index=True)
        before = training_slice(all_rows, 2023, protocol())
        all_rows.loc[all_rows.origin_date.dt.year == 2023, 'target_variance'] = 1e9
        after = training_slice(all_rows, 2023, protocol())
        pd.testing.assert_frame_equal(before, after, check_exact=True)
        a = fit_candidate(before, config['candidates'][0], config)
        b = fit_candidate(after, config['candidates'][0], config)
        np.testing.assert_array_equal(predict_variance(a, original), predict_variance(b, original))

    def test_invalid_model_outputs_cannot_be_reported_as_positive_forecasts(self):
        class InvalidEstimator:
            def __init__(self, value):
                self.value = value
            def predict(self, matrix):
                return np.full(len(matrix), self.value)
        for value in [0., -1., np.nan, np.inf]:
            with self.assertRaises(ValueError):
                predict_variance(InvalidEstimator(value), fixture())

    def test_selection_uses_only_declared_2025_primary_mae(self):
        records = []
        for year, mode, errors in [(2023, 'primary', [0, 2, 3]),
                                    (2025, 'daily', [0, 1, 2]),
                                    (2025, 'primary', [3, 1, 1])]:
            for method, error in zip(['hgb_7', 'hgb_15', 'hgb_31'], errors):
                records.append({'year': year, 'evaluation_mode': mode,
                                'method': method, 'volatility_mae_pp': error})
        metrics = pd.DataFrame(records)
        self.assertEqual(select_candidate(metrics, configuration()), 'hgb_15')
        with self.assertRaises(ValueError):
            select_candidate(metrics.loc[metrics.method != 'hgb_31'], configuration())

    def test_recipe_changes_require_explicit_version_review(self):
        for key, value in [('early_stopping', True), ('final_test_opened', True),
                            ('development_years', [2025, 2026]), ('loss', 'squared_error'),
                            ('max_iter', 1000)]:
            config = copy.deepcopy(configuration())
            config[key] = value
            with self.assertRaises(ValueError):
                validate_configuration(config)

    def test_regimes_use_given_training_threshold_and_are_diagnostic_only(self):
        errors = pd.DataFrame({'year': [2025, 2025], 'evaluation_mode': ['primary'] * 2,
                              'method': ['m'] * 2, 'instrument_id': ['A'] * 2,
                              'target_variance': [.01, .09],
                              'volatility_absolute_error_pp': [1., 5.], 'variance_qlike': [2., 4.]})
        medians = pd.DataFrame({'year': [2025], 'instrument_id': ['A'],
                               'training_median_volatility': [.2]})
        result = regime_metrics(errors, medians).set_index('realized_regime')
        self.assertEqual(result.loc['above_training_median', 'volatility_mae_pp'], 5.)
        self.assertEqual(result.loc['at_or_below_training_median', 'volatility_mae_pp'], 1.)
        self.assertNotIn('realized_regime', FEATURE_COLUMNS)
        with self.assertRaises(ValueError):
            regime_metrics(errors, medians.assign(instrument_id='missing'))

    def test_attempt_log_retains_start_failure_and_completion_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'attempt.jsonl'
            log_event(path, 'fit_started', method='fixture')
            log_event(path, 'failed', exception_type='ValueError', message='fixture failure')
            log_event(path, 'fit_completed', method='fixture')
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([r['event'] for r in records], ['fit_started', 'failed', 'fit_completed'])
            self.assertTrue(all(r['recorded_at_utc'].endswith('+00:00') for r in records))


if __name__ == '__main__':
    unittest.main()
