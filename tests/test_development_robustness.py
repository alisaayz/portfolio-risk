import copy
import json
import unittest

import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT
from scripts.evaluate_baselines import evaluation_origins
from scripts.evaluate_development_robustness import (
    leave_one_out, match_errors, phase_origins, validate_configuration,
)
from tests.test_forecast_baselines import configuration as baseline_configuration


def configuration():
    return json.loads((ROOT / 'config/development_robustness.json').read_text())


def membership():
    days = pd.date_range('2025-01-02', periods=120, freq='B')
    return pd.DataFrame({'instrument_id': 'A', 'origin_date': days[:100],
                         'target_end_date': days[20:120], 'feature_history_ready': True,
                         'fold_2025_validation': [False] + [True] * 79 + [False] * 20})


class DevelopmentRobustnessTests(unittest.TestCase):
    def test_offset_zero_matches_declared_baseline_primary_grid(self):
        frame = membership()
        expected = evaluation_origins(frame, 2025, 'primary', baseline_configuration())
        actual = phase_origins(frame, 2025, 0, configuration())
        pd.testing.assert_frame_equal(actual, expected[list(actual.columns)])

    def test_phase_is_anchored_before_availability_filtering(self):
        frame = membership()
        result = phase_origins(frame, 2025, 5, configuration())
        self.assertEqual(list(result.origin_date), list(frame.origin_date.iloc[[5, 25, 45, 65]]))
        self.assertTrue((result.target_end_date.iloc[:-1].to_numpy() <= result.origin_date.iloc[1:].to_numpy()).all())

    def test_reserved_year_and_undeclared_offsets_are_rejected(self):
        for year, offset in [(2026, 0), (2025, 1), (2025, 20)]:
            with self.assertRaises(ValueError):
                phase_origins(membership(), year, offset, configuration())
        frame = membership()
        frame.loc[20, 'target_end_date'] = pd.Timestamp('2026-01-02')
        with self.assertRaises(ValueError):
            phase_origins(frame, 2025, 0, configuration())

    def test_missing_phase_forecasts_cannot_shrink_the_comparison(self):
        origins = phase_origins(membership(), 2025, 5, configuration())
        source = pd.concat([origins.assign(method='a'), origins.assign(method='b')])
        self.assertEqual(len(match_errors(source, origins)), 2 * len(origins))
        with self.assertRaises(ValueError):
            match_errors(source.iloc[:-1], origins)
        with self.assertRaises(ValueError):
            match_errors(pd.concat([source, source.iloc[:1]]), origins)

    def test_leave_one_out_changes_aggregation_only(self):
        metrics = pd.DataFrame({'year': [2025] * 3, 'evaluation_mode': ['primary'] * 3,
                                'method': ['fixed'] * 3, 'instrument_id': ['A', 'B', 'C'],
                                'volatility_mae_pp': [1., 3., 8.], 'variance_qlike': [2., 4., 9.]})
        before = metrics.copy(deep=True)
        result = leave_one_out(metrics).set_index('excluded_instrument')
        self.assertEqual(result.loc['A', 'volatility_mae_pp'], 5.5)
        self.assertEqual(result.loc['C', 'volatility_mae_pp'], 2.)
        self.assertTrue((result.instruments == 2).all())
        pd.testing.assert_frame_equal(before, metrics)

    def test_cannot_silently_refit_or_reselect_under_diagnostic_protocol(self):
        for key, value in [('models_refitted', True), ('candidate_selection_changed', True),
                            ('final_test_opened', True), ('grid_offsets_sessions', [0, 1, 2])]:
            config = copy.deepcopy(configuration())
            config[key] = value
            with self.assertRaises(ValueError):
                validate_configuration(config)


if __name__ == '__main__':
    unittest.main()
