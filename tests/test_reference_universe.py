"""Configuration and acquisition tests; all prices in these tests are fixtures."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from scripts.audit_market_data import ROOT, download_snapshot, inspect_snapshot, load_universe


class ReferenceUniverseTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT/'config/reference_universe.json').read_text())

    def load(self, value):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'universe.json'
            path.write_text(json.dumps(value))
            return load_universe(path)

    def test_reference_universe_has_unique_declared_instruments(self):
        result = self.load(self.config)
        self.assertEqual(len(result['instruments']), 16)
        self.assertEqual(len({r['symbol'] for r in result['instruments']}), 16)
        self.assertTrue({'AAPL','SPY','BND'} <= {r['symbol'] for r in result['instruments']})

    def test_duplicate_symbols_and_path_like_symbols_are_rejected(self):
        for symbol in ['AAPL', '../OTHER', 'A/B', '^GSPC']:
            changed = copy.deepcopy(self.config)
            changed['instruments'][1]['symbol'] = symbol
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                self.load(changed)

    def test_unsupported_calendars_currency_and_empty_universe_fail(self):
        changes = []
        for field,value in [('calendar','UNKNOWN'), ('kind',''), ('research_role','')]:
            changed = copy.deepcopy(self.config);changed['instruments'][0][field] = value;changes.append(changed)
        changed = copy.deepcopy(self.config);changed['currency']='EUR';changes.append(changed)
        changed = copy.deepcopy(self.config);changed['instruments']=[];changes.append(changed)
        for changed in changes:
            with self.assertRaises(ValueError):self.load(changed)

    def test_download_uses_only_declared_symbols_and_preserves_universe(self):
        config = copy.deepcopy(self.config);config['instruments']=config['instruments'][:2]
        ticker = Mock()
        ticker.history.return_value = pd.DataFrame({'Close':[100.]},index=pd.DatetimeIndex(['2020-01-02']))
        ticker.get_history_metadata.return_value={'currency':'USD','exchangeTimezoneName':'America/New_York','exchangeName':'NMS'}
        with tempfile.TemporaryDirectory() as directory, patch('scripts.audit_market_data.yf.Ticker',return_value=ticker) as factory, patch('scripts.audit_market_data.yf.set_tz_cache_location'):
            run=Path(directory)/'run'
            result=download_snapshot(run,'2020-01-01','2020-01-03',config)
            self.assertEqual([call.args[0] for call in factory.call_args_list],['AAPL','MSFT'])
            self.assertEqual(result['universe'],config)
            self.assertEqual(set(result['instruments']),{'AAPL','MSFT'})
            self.assertEqual(len(result['universe_sha256']),64)
            self.assertEqual(json.loads((run/'manifest.json').read_text())['universe'],config)

    def test_changed_preserved_universe_is_rejected_before_price_use(self):
        manifest = {'universe': self.config, 'universe_sha256': 'changed'}
        with self.assertRaisesRegex(ValueError, 'universe hash mismatch'):
            inspect_snapshot(Path('/nonexistent'), manifest)

    def test_manifest_cannot_silently_omit_configured_instruments(self):
        manifest = {'universe': self.config, 'universe_sha256': hashlib.sha256(json.dumps(self.config, sort_keys=True).encode()).hexdigest(), 'instruments': {}}
        with self.assertRaisesRegex(ValueError, 'disagree with preserved universe'):
            inspect_snapshot(Path('/nonexistent'), manifest)


if __name__ == '__main__':
    unittest.main()
