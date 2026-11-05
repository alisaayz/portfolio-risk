import unittest

import numpy as np

from scripts.portfolio_reweight import bounds_for_holdings, propose


class PortfolioReweightTests(unittest.TestCase):
    def test_known_optimum_keeps_locked_position_and_respects_move_limit(self):
        covariance = np.diag([.09, .01, .04])
        current = np.array([.5, .3, .2])
        lower, upper, limit = bounds_for_holdings({
            'turnover_limit': .10,
            'holdings': {'C': {'locked': True}, 'B': {'maximum': .39}},
        }, ['A', 'B', 'C'], current)
        weights, status = propose(covariance, current, lower, upper, limit, .10)
        np.testing.assert_allclose(weights, [.41, .39, .20], atol=1e-10)
        self.assertEqual(status, 'target_unreachable')

    def test_target_on_path_uses_less_than_full_budget(self):
        covariance = np.diag([.09, .01])
        current = np.array([.7, .3])
        lower, upper = np.zeros(2), np.ones(2)
        weights, status = propose(covariance, current, lower, upper, .20, .18)
        self.assertEqual(status, 'target_met')
        self.assertAlmostEqual(np.sqrt(weights @ covariance @ weights), .18)
        self.assertLess(np.abs(weights-current).sum()/2, .20)
        same, status = propose(covariance, current, lower, upper, .20, .25)
        np.testing.assert_array_equal(same, current)
        self.assertEqual(status, 'already_within_target')

    def test_all_positions_locked_and_bounds_cannot_force_trades(self):
        current = np.array([.4, .6])
        same, status = propose(np.diag([.09, .01]), current, current, current, .10, None)
        np.testing.assert_array_equal(same, current)
        self.assertEqual(status, 'no_improvement')
        with self.assertRaisesRegex(ValueError, 'include its current weight'):
            bounds_for_holdings({'turnover_limit': .1, 'holdings': {'A': {'minimum': .5}}},
                                ['A', 'B'], current)
