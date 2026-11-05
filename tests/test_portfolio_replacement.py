import unittest
from unittest.mock import patch

import numpy as np

from scripts.portfolio_replacement import replacement_criteria, volatility_band


class PortfolioReplacementTests(unittest.TestCase):
    def test_negative_correlation_can_require_minimum_volatility(self):
        remaining, swap, target, correlation = .12, .20, .10, -.75
        band = volatility_band(remaining, swap, target, correlation)
        self.assertGreater(band['minimum'], 0)
        for value in band.values():
            self.assertAlmostEqual(remaining**2 + (swap * value)**2
                                   + 2 * remaining * swap * value * correlation, target**2)
        self.assertIsNone(volatility_band(remaining, swap, target, .50))

    def test_zero_variance_remainder_and_locked_holding(self):
        report = {
            'symbols': ['DEMO'], 'scenarios': [{'weights': np.array([1.0]), 'annualized_sample_volatility': .2}],
            'annualized_covariance': np.array([[.04]]), 'risk_window_sessions': 252,
            'risk_window_start': '2025-11-03', 'risk_window_end': '2026-11-03',
        }
        config = {'portfolios': [{'input_type': 'weights'}]}
        constraints = {'turnover_limit': 1, 'holdings': {}}
        replacement = {'symbol': 'DEMO', 'weight': 1}
        with patch('scripts.portfolio_replacement.analyze', return_value=(report, None)):
            result = replacement_criteria(None, config, constraints, replacement, .10)
            self.assertEqual(result['bands'], [{'correlation': None, 'volatility': {'minimum': 0, 'maximum': .10}}])
            constraints['holdings']['DEMO'] = {'locked': True}
            with self.assertRaisesRegex(ValueError, 'allows up to 0%'):
                replacement_criteria(None, config, constraints, replacement, .10)


class PortfolioScreenTests(unittest.TestCase):
    def test_screen_uses_matched_dates_and_excludes_current_holdings(self):
        import duckdb
        import pandas as pd
        from scripts.portfolio_replacement import screen_candidates

        dates = pd.date_range('2026-01-02', periods=4)
        returns = {'HELD': [.02, -.02, .01, -.01],
                   'OPPOSITE': [-.02, .02, -.01, .01],
                   'SAME': [.02, -.02, .01, -.01],
                   'GAP': [-.02, .02, None, .01]}
        frame = pd.DataFrame(returns, index=dates).rename_axis('session_date').reset_index().melt(
            id_vars='session_date', var_name='instrument_id', value_name='simple_return')
        report = {'symbols': ['HELD'], 'risk_window_start': str(dates[0].date()),
                  'risk_window_end': str(dates[-1].date()), 'risk_window_sessions': 4}
        remainder = np.array([.5])
        original = np.std(returns['HELD'], ddof=1) * np.sqrt(252)
        criteria = {'remainder_volatility_contribution': original * .5,
                    'replacement_weight': .5, 'target': original * .9}
        universe = {'instruments': [{'symbol': symbol, 'research_role': symbol} for symbol in returns],
                    'universe_id': 'TEST', 'dataset_id': 'test-data', 'policy': 'test'}
        with duckdb.connect() as db:
            db.register('returns_daily', frame)
            screened = screen_candidates(db, report, remainder, criteria, universe)
        self.assertEqual([(row['symbol'], row['status']) for row in screened['candidates']],
                         [('OPPOSITE', 'meets_target'), ('SAME', 'above_target'), ('GAP', 'unavailable')])
        self.assertAlmostEqual(screened['candidates'][0]['portfolio_volatility'], 0.0)
        self.assertAlmostEqual(screened['candidates'][1]['portfolio_volatility'], original)
