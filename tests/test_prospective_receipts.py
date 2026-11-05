"""Check admission rules independently of any network timestamp service."""

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_market_data import ROOT, sha256
from scripts.record_prospective_forecast import PROTOCOL, capture_times
from scripts.verify_forecast_receipt import check_forecast, signed_timestamp


class ProspectiveReceiptTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads(PROTOCOL.read_text())
        self.baseline = json.loads((ROOT / 'config/final_evaluation.json').read_text())
        self.record = {
            'protocol': self.spec['protocol'], 'protocol_sha256': sha256(PROTOCOL),
            'training_sha256': self.spec['training_sample_sha256'],
            'origin': '2026-11-06', 'target_end': '2026-12-07',
            'capture_started_at_utc': '2026-11-06T21:01:00+00:00',
            'capture_finished_at_utc': '2026-11-06T21:02:00+00:00',
            'recorded_at_utc': '2026-11-06T21:03:00.5+00:00',
            'deadline_utc': '2026-11-09T14:30:00+00:00',
            'annualized_variance': [{'portfolio_id': row['id'], 'hgb_7': .04,
                                     'ewma_0.90': .03, 'trailing_20': .04}
                                    for row in self.spec['portfolio_weights']],
        }

    def check(self, time, **changes):
        return check_forecast(self.record | changes, datetime.fromisoformat(time), self.spec, self.baseline)

    def test_valid_window_accepts_same_second_as_local_record(self):
        self.assertEqual(self.check('2026-11-06T21:03:00+00:00'), '2026-11-06')

    def test_rejects_early_and_late_receipts_and_capture(self):
        for stamp in ['2026-11-06T21:02:59+00:00', '2026-11-09T14:30:00+00:00']:
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                self.check(stamp)
        with self.assertRaises(ValueError):
            self.check('2026-11-06T21:04:00+00:00', capture_started_at_utc='2026-11-06T20:59:59+00:00')

    def test_rejects_incomplete_forecast_and_wrong_protocol(self):
        stamp = '2026-11-06T21:04:00+00:00'
        for changes in [{'annualized_variance': self.record['annualized_variance'][:-1]},
                        {'training_sha256': 'wrong'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.check(stamp, **changes)

    def test_rejects_unpinned_certificate_before_verification(self):
        with TemporaryDirectory() as folder:
            trust = Path(folder)
            (trust / 'cacert.pem').write_text('unexpected certificate')
            with self.assertRaisesRegex(ValueError, 'fingerprint differs'):
                signed_timestamp(b'forecast', b'query', b'receipt', trust)

    def test_capture_checks_use_all_instrument_retrieval_times(self):
        manifest = {'retrieved_at_utc': '2026-11-06T21:01:00Z', 'instruments': {
            'AAPL': {'retrieved_at_utc': '2026-11-06T21:02:00Z'},
            'SPY': {'retrieved_at_utc': '2026-11-06T21:03:00Z'},
        }}
        _, end = capture_times(manifest)
        self.assertEqual(end.isoformat(), '2026-11-06T21:03:00+00:00')
        manifest['instruments']['SPY']['retrieved_at_utc'] = '2026-11-06T21:00:59Z'
        with self.assertRaises(ValueError):
            capture_times(manifest)


if __name__ == '__main__':
    unittest.main()
