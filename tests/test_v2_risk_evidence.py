"""Regression checks for the risk evidence and policy decisions in checkpoint 3."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb
import numpy as np
import pandas as pd

from scripts.portfolio_reweight import simple_shift
from scripts.portfolio_risk_evidence import downside_deviation, rebalance, replay
from scripts.replacement_evidence import (block_indices, eligibility, paired_interval,
    qualification, rank_candidates, validate_filters, volume_evidence, window_scores)


class HistoricalEvidenceTests(unittest.TestCase):
    def test_downside_uses_all_returns_in_denominator(self):
        returns = np.array([-.02, .04, 0, -.01])
        self.assertAlmostEqual(downside_deviation(returns), (.0005 * 252 / 4) ** .5)
        self.assertEqual(downside_deviation(np.abs(returns)), 0)

    def test_rebalance_deducts_buy_and_sell_fees_and_balances_ledger(self):
        position, fee, notional, count = rebalance(np.array([.7, .3]), np.array([.6, .4]), .0025)
        self.assertAlmostEqual(fee, .0025 * .2 / (1 - .0025 * .2))
        self.assertAlmostEqual(position.sum() + fee, 1.)
        self.assertAlmostEqual(notional * .0025, fee)
        self.assertEqual(count, 2)
        np.testing.assert_allclose(position / position.sum(), [.6, .4])

    def test_daily_gross_reconciles_and_costs_reduce_returns_on_same_schedule(self):
        returns = np.array([[.10, -.10], [.05, 0], [-.10, .08]])
        weights = np.array([.5, .5])
        daily = [True, True, False]
        gross, base, stress = [replay(returns, weights, daily, bps) for bps in (0, 5, 25)]
        np.testing.assert_allclose(gross['wealth'][1:], np.cumprod(1 + returns @ weights))
        drift = replay(returns, weights, [False] * 3, 0)
        self.assertAlmostEqual(drift['wealth'][-1], np.prod(1 + returns, axis=0) @ weights)
        self.assertGreater(gross['terminal_return'], base['terminal_return'])
        self.assertGreater(base['terminal_return'], stress['terminal_return'])
        self.assertEqual(gross['trades'], stress['trades'])
        self.assertEqual(gross['rebalance_events'], 2)

    def test_simple_rule_respects_locks_bounds_and_target(self):
        covariance = np.diag([.09, .04, .01])
        current = np.array([.30, .50, .20])
        lower, upper = np.array([.30, .10, .0]), np.array([.30, .8, .24])
        adjusted, status = simple_shift(covariance, current, lower, upper, .10, None)
        np.testing.assert_allclose(adjusted, [.30, .46, .24])
        self.assertEqual(status, 'lower_risk')
        mid = (np.sqrt(current @ covariance @ current) + np.sqrt(adjusted @ covariance @ adjusted)) / 2
        closer, status = simple_shift(covariance, current, lower, upper, .10, mid)
        self.assertEqual(status, 'target_met')
        self.assertAlmostEqual(np.sqrt(closer @ covariance @ closer), mid)
        self.assertEqual(closer[0], current[0])


class ReplacementEvidenceTests(unittest.TestCase):
    def test_mixed_and_missing_evidence_change_status(self):
        rng = np.random.default_rng(42)
        matrix = rng.normal(size=(252, 2)) * [.01, .02]
        current, alternative = np.array([1., 0.]), np.array([.5, .5])
        fixed = window_scores(matrix, current, alternative, 1.)
        self.assertEqual(qualification(fixed), 'stable')
        self.assertEqual(qualification(window_scores(matrix, current, alternative, 0.)), 'above')
        fixed[0]['within_target'] = False
        self.assertEqual(qualification(fixed), 'sensitive')
        matrix[0, 1] = np.nan
        incomplete = window_scores(matrix, current, alternative, 1.)
        self.assertEqual(qualification(incomplete), 'incomplete')
        self.assertEqual(len(incomplete), 4)

    def test_pairing_resamples_same_dates_and_ranks_complete_rows_only(self):
        returns = np.random.default_rng(1).normal(0, .01, 126)
        indices = block_indices(126, 10, 400, np.random.default_rng(42))
        self.assertEqual(paired_interval(returns, returns, indices), [0., 0.])
        self.assertTrue(np.all(np.diff(indices[:, :10], axis=1) % 126 == 1))
        def row(symbol, estimates):
            return {'symbol': symbol, 'decision': 'stable',
                    'window_scores': [{'portfolio_volatility': value} for value in estimates]}
        a, b = row('A', [.08, .07] * 3), row('B', [.07, .08] * 3)
        rank_candidates([a, b, {'decision': 'incomplete'}])
        self.assertEqual([score['rank'] for score in a['window_scores']], [2, 1] * 3)

    def test_filters_block_missing_requested_evidence_and_wrong_exposure(self):
        filters = validate_filters({'role': 'equity_etf', 'max_position': .45,
                                    'min_dollar_volume': 1e6, 'max_fund_fee': .002})
        self.assertEqual(len(eligibility(filters, {'kind': 'bond_etf'}, .5, None, None)), 4)
        self.assertEqual(eligibility(filters, {'kind': 'equity_etf'}, .45,
                                     {'median_usd': 1e6}, {'annual_ratio': .002}), [])
        with self.assertRaises(ValueError):
            validate_filters({'min_dollar_volume': float('nan')})

    def test_volume_requires_all_twenty_matching_sessions_and_ignores_later_data(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / 'volume.duckdb'
            days = pd.bdate_range('2025-01-02', periods=21)
            with duckdb.connect(str(database)) as connection:
                connection.execute('CREATE TABLE accepted_prices_daily (instrument_id VARCHAR, session_date DATE, close DOUBLE, volume BIGINT)')
                connection.executemany('INSERT INTO accepted_prices_daily VALUES (?, ?, ?, ?)', [
                    ('A', day.date(), 10, 100 if index < 20 else 10000) for index, day in enumerate(days)
                ] + [('B', day.date(), 10, 100) for day in days[1:]])
            result = volume_evidence(database, ['A', 'B'], days[:20])
            self.assertEqual(set(result), {'A'})
            self.assertEqual(result['A']['median_usd'], 1000.)
            self.assertEqual(result['A']['end'], days[19].date().isoformat())


if __name__ == '__main__':
    unittest.main()
