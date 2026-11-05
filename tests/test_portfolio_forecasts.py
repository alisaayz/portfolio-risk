import unittest

import numpy as np
import pandas as pd

from scripts.evaluate_portfolio_forecasts import YEARS, evaluate


class PortfolioForecastTests(unittest.TestCase):
    def test_future_return_changes_outcome_but_not_forecast_at_same_origin(self):
        dates = pd.bdate_range('2022-01-01', '2025-12-31')
        returns = np.random.default_rng(9).normal(0, .01, (len(dates), 2))
        panel = pd.DataFrame(returns, index=dates, columns=['ONE', 'TWO'])
        portfolio = {'id': 'demo', 'positions': [{'instrument_id': symbol, 'weight': .5}
                                                 for symbol in panel]}
        locations = [location for year in YEARS
                     for location in np.flatnonzero(dates.year == year)[:240:20]]

        def make_scores():
            rows = []
            for location in locations:
                history = panel.iloc[location - 19:location + 1]
                future = panel.iloc[location + 1:location + 21]
                for symbol in panel:
                    for method in ['trailing_20', 'ewma', 'model']:
                        forecast = 252 * (history[symbol]**2).mean() if method == 'trailing_20' else .04
                        rows.append({'year': dates[location].year, 'origin_date': dates[location],
                                     'target_end_date': dates[location + 20], 'method': method,
                                     'instrument_id': symbol, 'predicted_variance': forecast,
                                     'target_variance': 252 * (future[symbol]**2).mean()})
            return evaluate(panel, pd.DataFrame(rows), [portfolio], 'model', 'ewma')

        origin = dates[locations[0]]
        before = make_scores().loc[lambda frame: frame.origin_date == origin]
        panel.iloc[locations[0] + 1] += .10
        after = make_scores().loc[lambda frame: frame.origin_date == origin]
        np.testing.assert_array_equal(before.predicted_variance, after.predicted_variance)
        self.assertTrue((after.target_variance.to_numpy() > before.target_variance.to_numpy()).all())
