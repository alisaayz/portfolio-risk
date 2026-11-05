"""Test PF-002 scoring boundaries and the paired decision rule."""

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts.record_prospective_forecast import PROTOCOL, schedule
from scripts.score_prospective_forecasts import (
    BASELINE, evaluate, order_evidence, realized_window, summarize,
)


class ProspectiveScoringTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(PROTOCOL.read_text())
        self.baseline = json.loads(BASELINE.read_text())

    def test_realized_target_excludes_origin_return_and_rejects_missing_close(self):
        dates = pd.date_range('2027-01-04', periods=3)
        prices = pd.DataFrame({'instrument_id': 'A', 'session_date': dates, 'adjusted_close': [100, 90, 108]})
        weights = [{'id': 'one', 'positions': {'A': 1}}]
        actual = realized_window(prices, dates, weights)
        np.testing.assert_allclose(actual, [[252 * (.01 + .04) / 2, 252 * .01 / 2]])
        with self.assertRaisesRegex(ValueError, 'exact origin close'):
            realized_window(prices.drop(index=1), dates, weights)

    def test_evidence_requires_every_origin_and_a_reason_for_skips(self):
        slots = ['2026-11-06', '2026-12-07']
        rows = [{'origin': origin, 'missing_reason': 'No eligible capture'} for origin in reversed(slots)]
        manifest = {'protocol': 'PF-002', 'slots': rows}
        self.assertEqual([row['origin'] for row in order_evidence(manifest, slots, 'PF-002')], slots)
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            order_evidence({**manifest, 'slots': [rows[0], rows[0]]}, slots, 'PF-002')
        rows[0]['missing_reason'] = ' '
        with self.assertRaisesRegex(ValueError, 'nonempty reason'):
            order_evidence(manifest, slots, 'PF-002')

    def test_early_scoring_stops_before_reading_the_manifest(self):
        with self.assertRaisesRegex(ValueError, 'final scheduled outcome has not closed'):
            evaluate(Path('missing-manifest.json'), datetime(2026, 11, 5, tzinfo=timezone.utc),
                     self.spec, self.baseline)

    def test_insufficient_receipts_never_open_outcomes(self):
        slots = list(schedule(self.spec))
        rows = [{'origin': str(origin.date()), 'missing_reason': 'No eligible capture'}
                for origin, _, _, _ in slots]
        with TemporaryDirectory() as folder, patch('scripts.score_prospective_forecasts.read_outcome') as read:
            manifest = Path(folder) / 'manifest.json'
            manifest.write_text(json.dumps({'protocol': 'PF-002', 'slots': rows}))
            result = evaluate(manifest, datetime(2034, 1, 1, tzinfo=timezone.utc), self.spec, self.baseline)
        read.assert_not_called()
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['scored_origins'], 0)
        self.assertEqual(len(result['slots']), 72)
        self.assertNotIn('pooled_mae_pp', result)

    def test_paired_scoring_keeps_missing_slots_and_applies_portfolio_guard(self):
        portfolios = self.spec['portfolio_weights']
        methods = ['model', 'ewma', 'trailing']
        outcomes = np.full((72, 4, 2), np.nan)
        forecasts = np.full((72, 4, 3), np.nan)
        matched = np.arange(72) % 6 != 0
        outcomes[matched] = [.01, .003]
        forecasts[matched] = [.01, .0144, .0169]

        result = summarize(forecasts, outcomes, portfolios, methods, self.spec, 1e-12)
        self.assertTrue(result['advance_to_dashboard_experiment'])
        self.assertAlmostEqual(result['pooled_mae_pp']['ewma'], 2)
        interval = result['model_minus_baselines']['ewma']
        self.assertEqual(set(interval['upper_bounds_97_5_pp']), {'2', '3', '6'})
        self.assertAlmostEqual(interval['upper_bounds_97_5_pp']['3'], -2)
        self.assertEqual(result['by_portfolio']['equity_heavy']['model']['high_downside_origins'], 12)

        forecasts[matched, 0, 0] = .0025
        weaker = summarize(forecasts, outcomes, portfolios, methods, self.spec, 1e-12)
        self.assertLess(weaker['model_minus_baselines']['ewma']['mae_difference_pp'], -.5)
        self.assertFalse(weaker['advance_to_dashboard_experiment'])
        self.assertEqual(weaker['by_portfolio']['equity_heavy']['model']['understatements_at_least_five_pp'], 60)


if __name__ == '__main__':
    unittest.main()
