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
