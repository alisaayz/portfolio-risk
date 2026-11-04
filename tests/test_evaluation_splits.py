"""Synthetic session fixtures test leakage boundaries, not forecast performance."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts.audit_market_data import ROOT
from scripts.evaluation_splits import build_manifest, split_membership, validate_protocol


class EvaluationSplitTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads((ROOT / 'config/evaluation_protocol.json').read_text())
        self.calendar = pd.date_range('2020-01-01', '2027-03-31', freq='B')
        self.observed = self.calendar[self.calendar <= '2026-11-03']
        self.frame = split_membership(self.calendar, self.observed, self.protocol)

    def test_train_and_validation_targets_never_cross_their_boundaries(self):
        for field, boundary in [('train_eligible', '2025-01-01'), ('validation_eligible', '2026-01-01'), ('final_refit_eligible', '2026-01-01')]:
            selected = self.frame[self.frame[field]]
            self.assertTrue((selected.target_end_date < pd.Timestamp(boundary)).all())
        december = self.frame[self.frame.origin_date.between('2025-12-15', '2025-12-31')]
        self.assertFalse(december.validation_eligible.any())
        self.assertFalse(december.final_refit_eligible.any())

    def test_development_folds_never_use_2026(self):
        test = self.frame[self.frame.partition == 'test']
        for name in self.frame:
            if name.startswith('fold_') or name in ['train_eligible', 'validation_eligible', 'final_refit_eligible']:
                self.assertFalse(test[name].any(), name)
        for year in [2023, 2024, 2025]:
            train = self.frame[self.frame[f'fold_{year}_train']]
            validation = self.frame[self.frame[f'fold_{year}_validation']]
            self.assertLess(train.target_end_date.max(), validation.origin_date.min())
            self.assertTrue((validation.target_end_date < pd.Timestamp(f'{year+1}-01-01')).all())

    def test_targets_span_exactly_twenty_sessions_and_retain_pending_tail(self):
        origins = self.calendar.get_indexer(self.frame.origin_date)
        ends = self.calendar.get_indexer(self.frame.target_end_date)
        self.assertTrue(((ends-origins) == 20).all())
        self.assertEqual(int((~self.frame.target_complete).sum()), 20)
        self.assertFalse(self.frame.tail(20).test_eligible_when_opened.any())

    def test_features_require_full_warmup(self):
        self.assertFalse(self.frame.iloc[:252].feature_history_ready.any())
        self.assertTrue(self.frame.iloc[252:].feature_history_ready.all())

    def test_primary_target_windows_do_not_overlap(self):
        selected = self.frame[self.frame.primary_test_scorable_when_opened]
        self.assertGreater(len(selected), 1)
        self.assertTrue((selected.target_end_date.iloc[:-1].to_numpy() <= selected.origin_date.iloc[1:].to_numpy()).all())

    def test_year_end_test_targets_do_not_extend_into_2027(self):
        observed = self.calendar[self.calendar <= '2027-02-15']
        frame = split_membership(self.calendar, observed, self.protocol)
        crossing = frame[(frame.partition == 'test') & (frame.target_end_date >= '2027-01-01')]
        self.assertEqual(len(crossing), 20)
        self.assertTrue(crossing.target_complete.all())
        self.assertFalse(crossing.test_eligible_when_opened.any())

    def test_missing_duplicate_and_unsorted_sessions_fail(self):
        for observed in [self.observed.delete(100), self.observed.append(self.observed[-1:]), self.observed[::-1]]:
            with self.subTest(length=len(observed)), self.assertRaises(ValueError):
                split_membership(self.calendar, observed, self.protocol)
        with self.assertRaisesRegex(ValueError, 'extend through'):
            split_membership(self.observed, self.observed, self.protocol)

    def test_appending_data_does_not_shift_the_primary_origin_grid(self):
        early = self.calendar[self.calendar <= '2026-06-30']
        frame = split_membership(self.calendar, early, self.protocol)
        pd.testing.assert_series_equal(frame.primary_test_origin, self.frame.iloc[:len(early)].primary_test_origin)

    def test_opening_test_scores_or_altering_protocol_semantics_is_rejected(self):
        for field, value in [('final_test_scores_opened', True), ('development_validation_years', [2024, 2025, 2026]), ('test_start', '2025-01-01'), ('test_retraining', 'monthly'), ('target_horizon_sessions', 10)]:
            changed = copy.deepcopy(self.protocol)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_protocol(changed)

    def test_structurally_failed_snapshots_cannot_produce_split_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path/'manifest.json').write_text('{}')
            with patch('scripts.evaluation_splits.inspect_snapshot', return_value={'structural_checks_pass': False}), self.assertRaisesRegex(ValueError, 'structural'):
                build_manifest(path, self.protocol)


if __name__ == '__main__':
    unittest.main()
