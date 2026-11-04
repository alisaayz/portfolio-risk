"""Small synthetic regression fixtures test failure detection, not project results."""

from collections.abc import Mapping
import hashlib
import tempfile
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from scripts.audit_market_data import audit_frame, expected_sessions, inspect_snapshot, materialize_metadata


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.DatetimeIndex(["2020-09-01", "2020-09-02", "2020-09-03"])
        self.frame = pd.DataFrame({"Open": [100.] * 3, "High": [102.] * 3,
                                   "Low": [98.] * 3, "Close": [100.] * 3,
                                   "Adj Close": [100.] * 3, "Volume": [1000.] * 3,
                                   "Dividends": [0.] * 3, "Stock Splits": [0.] * 3}, index=self.dates)

    def test_exchange_closure_is_not_a_missing_session(self):
        dates = expected_sessions("2020-07-02", "2020-07-07", "XNYS")
        self.assertEqual(list(dates.strftime("%Y-%m-%d")), ["2020-07-02", "2020-07-06"])

    def test_gap_fails_without_turning_into_one_session_return(self):
        frame = self.frame.drop(self.dates[1])
        frame.loc[self.dates[2], ["Open", "High", "Low", "Close", "Adj Close"]] = [200, 202, 198, 200, 200]
        result = audit_frame(frame, self.dates)
        self.assertEqual(result["missing_sessions"], ["2020-09-02"])
        self.assertTrue(result["errors"])
        self.assertEqual(result["extreme_adjusted_move_dates"], [])

    def test_duplicate_is_rejected_instead_of_removed(self):
        frame = pd.concat([self.frame, self.frame.iloc[[0]]])
        result = audit_frame(frame, self.dates)
        self.assertEqual(result["duplicate_dates"], 1)
        self.assertEqual(result["rows"], 4)
        self.assertNotIn("extreme_adjusted_move_dates", result)

    def test_invalid_values_prevent_return_diagnostics(self):
        frame = self.frame.copy()
        frame.loc[self.dates[1], "Close"] = 0
        frame.loc[self.dates[2], "Volume"] = np.inf
        result = audit_frame(frame, self.dates)
        self.assertEqual(result["nonpositive_price_cells"], 1)
        self.assertEqual(result["nonfinite_cells"], 1)
        self.assertTrue(result["errors"])
        self.assertEqual(result["events"], [])

    def test_adjustment_factor_explains_a_cash_distribution(self):
        frame = self.frame.copy()
        frame.loc[self.dates[0], "Adj Close"] = 97.5
        frame.loc[self.dates[1], "Dividends"] = 2.5
        result = audit_frame(frame, self.dates)
        self.assertEqual(result["dividend_events"], 1)
        self.assertAlmostEqual(result["events"][0]["adjustment_factor_error_bp"], 0, places=8)
        self.assertEqual(result["factor_deviation_over_5bp_dates"], [])

    def test_applying_a_split_again_creates_an_artificial_move(self):
        frame = self.frame.copy()
        frame.loc[self.dates[1], "Stock Splits"] = 4
        event = audit_frame(frame, self.dates)["events"][0]
        self.assertAlmostEqual(event["provider_close_return"], 0)
        self.assertAlmostEqual(event["return_if_split_applied_again"], 3)

    def test_altered_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "AAPL.csv").write_text("altered evidence\n")
            manifest = {"packages": {}, "instruments": {"AAPL": {"status": "downloaded", "csv_sha256": hashlib.sha256(b"original").hexdigest()}}}
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                inspect_snapshot(path, manifest)

    def test_metadata_is_structured_without_lazy_network_access(self):
        class LazyMetadata(Mapping):
            def __iter__(self):
                return iter(["currency", "tradingPeriods"])
            def __len__(self):
                return 2
            def __getitem__(self, key):
                if key == "tradingPeriods":
                    raise AssertionError("Unexpected lazy metadata fetch")
                return "USD"
        self.assertEqual(materialize_metadata(LazyMetadata()), {"currency": "USD"})


if __name__ == "__main__":
    unittest.main()
