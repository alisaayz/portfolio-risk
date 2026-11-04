"""Regression fixtures for source alignment and precision; no project data is simulated."""
import unittest
import pandas as pd
from scripts.cross_validate_sources import compare_values


class SourceComparisonTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.date_range("2026-11-02", periods=2)

    def test_published_precision_does_not_hide_a_material_difference(self):
        provider = pd.Series([3348.419922, 4442.410156], index=self.dates)
        reference = pd.Series([3348.44, 4447.70], index=self.dates)
        result = compare_values(provider, reference, self.dates, 0.02)
        self.assertEqual(len(result["native_float_mismatch_dates"]), 2)
        self.assertEqual(result["mismatch_dates"], ["2026-11-03"])
        self.assertEqual(result["max_absolute_difference"], 5.29)
        self.assertFalse(result["passed"])

    def test_missing_reference_day_fails_instead_of_being_dropped(self):
        provider = pd.Series([100., 101.], index=self.dates)
        reference = provider.iloc[:1]
        result = compare_values(provider, reference, self.dates, 0.01)
        self.assertEqual(result["compared_dates"], 1)
        self.assertEqual(result["missing_dates"], ["2026-11-03"])
        self.assertFalse(result["passed"])

    def test_duplicate_reference_dates_cannot_multiply_the_join(self):
        provider = pd.Series([100., 101.], index=self.dates)
        reference = pd.concat([provider, provider.iloc[:1]])
        with self.assertRaisesRegex(ValueError, "Duplicate dates"):
            compare_values(provider, reference, self.dates, 0.01)

    def test_live_next_day_quote_is_excluded_from_completed_session_checks(self):
        provider = pd.Series([100., 101.], index=self.dates)
        reference = pd.Series([999., 101., 100.], index=pd.to_datetime(["2026-11-04", "2026-11-03", "2026-11-02"]))
        result = compare_values(provider, reference, self.dates, 0.01)
        self.assertTrue(result["passed"])
        self.assertEqual(result["compared_dates"], 2)


if __name__ == "__main__":
    unittest.main()
