from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import duckdb
import numpy as np
import pandas as pd

from scripts.evaluate_final import realized


class FinalEvaluationTests(unittest.TestCase):
    def test_realized_portfolio_uses_the_next_twenty_sessions_and_validates_endpoint(self):
        days = pd.bdate_range('2026-01-02', periods=22)
        path = pd.DataFrame({'ONE': [.20] + [.02] * 20 + [.25],
                             'TWO': [-.20] + [.01] * 20 + [-.25]}, index=days)
        source = path.rename_axis('session_date').reset_index().melt(
            id_vars='session_date', var_name='instrument_id', value_name='simple_return')
        grid = pd.DataFrame({'origin_date': [days[0]], 'target_end_date': [days[20]]})
        demo = {'portfolios': [{'id': 'demo', 'positions': [{'instrument_id': 'ONE', 'weight': .5},
                                                            {'instrument_id': 'TWO', 'weight': .5}]}]}
        with TemporaryDirectory() as temp:
            warehouse = Path(temp) / 'test.duckdb'
            with duckdb.connect(str(warehouse)) as conn:
                conn.register('source', source)
                conn.execute('CREATE TABLE returns_daily AS SELECT * FROM source')
            with patch('scripts.evaluate_final.WAREHOUSE', warehouse):
                values = realized(path, grid, demo).set_index('instrument_id')
                np.testing.assert_allclose(values.loc[['ONE', 'TWO', 'demo'], 'target_variance'],
                                           252 * np.array([.02, .01, .015])**2)
                grid['target_end_date'] = days[21]
                with self.assertRaisesRegex(ValueError, 'incorrect target end'):
                    realized(path, grid, demo)
