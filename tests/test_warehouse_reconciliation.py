"""A second calculation detects corrupted SQL definitions and gap bridging."""
import unittest

import duckdb

from scripts.build_warehouse import load_bundle
from scripts.verify_warehouse import verify
from tests.test_warehouse import fixture


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.connection=duckdb.connect();load_bundle(self.connection,fixture())

    def tearDown(self):self.connection.close()

    def test_all_returns_and_complete_windows_reconcile(self):
        result=verify(self.connection)
        self.assertTrue(result['all_checks_pass'])
        self.assertEqual(result['instruments'][0]['returns'],21)
        self.assertEqual(result['instruments'][0]['complete_20_return_windows'],2)

    def test_missing_price_preserves_both_null_returns_and_window_exclusion(self):
        self.connection.execute("DELETE FROM prices_daily WHERE run_id='yahoo_prices:new' AND session_date='2026-01-10'").fetchall()
        result=verify(self.connection)
        self.assertEqual(result['instruments'][0]['returns'],19)
        self.assertEqual(result['instruments'][0]['complete_20_return_windows'],0)

    def test_wrong_sql_risk_scale_is_detected(self):
        self.connection.execute('CREATE TABLE copied AS SELECT * FROM historical_risk_inputs').fetchall()
        self.connection.execute('CREATE OR REPLACE VIEW historical_risk_inputs AS SELECT * EXCLUDE(trailing_20_ann_volatility), trailing_20_ann_volatility*2 AS trailing_20_ann_volatility FROM copied').fetchall()
        with self.assertRaises(AssertionError):verify(self.connection)


if __name__=='__main__':unittest.main()
