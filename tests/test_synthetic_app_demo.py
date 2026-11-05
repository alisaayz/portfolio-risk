"""Exercise the standalone demo through the local application API."""

from contextlib import contextmanager
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.serve_portfolio_app import handler_class
from scripts.synthetic_app_demo import DEMO_ID, SYMBOLS, build_demo


@contextmanager
def demo_server(database):
    with ThreadingHTTPServer(('127.0.0.1', 0), handler_class(database, synthetic=True)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'

        def call(path, payload=None):
            request = Request(origin + path) if payload is None else Request(
                origin + path, data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json', 'Origin': origin})
            with urlopen(request, timeout=5) as response:
                return json.load(response)

        try:
            yield call
        finally:
            server.shutdown()
            thread.join(timeout=5)


class SyntheticApplicationTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.database = Path(directory) / 'synthetic.duckdb'
        build_demo(self.database)
        self.call = self.enterContext(demo_server(self.database))
        self.context = self.call('/api/context')
        self.payload = {'configuration': self.context['demo_configuration'], 'volatility_reference': None}

    def test_standalone_analysis_and_comparison_use_the_same_synthetic_database(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.assertEqual(self.context['dataset_id'], DEMO_ID)
        self.assertEqual(self.context['data_mode'], 'synthetic')
        self.assertEqual(self.context['price_rows'], 960)
        self.assertEqual([item['symbol'] for item in self.context['instruments']], list(SYMBOLS))
        result = self.call('/api/analyze', self.payload)
        self.assertEqual(result['data_mode'], 'synthetic')
        self.assertEqual({row['policy'] for row in result['source_validation']}, {'synthetic_demo'})
        self.assertEqual(result['historical_scenarios'], [])
        self.assertTrue(result['analysis']['reconciliations_passed'])
        constraints = {'turnover_limit': .1, 'holdings': {'DEMOA': {'minimum': 0, 'maximum': 1, 'locked': True}}}
        adjustment = self.call('/api/reweight', {'portfolio': self.payload, 'constraints': constraints})
        self.assertAlmostEqual(adjustment['holdings'][0]['alternative_weight'], .3)
        self.assertLessEqual(adjustment['turnover'], .1 + 1e-10)
        self.assertLess(adjustment['alternative_volatility'], adjustment['current_volatility'])
        self.payload['configuration']['portfolios'].append({
            'id': 'alt', 'name': 'Alternative', 'input_type': 'weights',
            'positions': [{'instrument_id': row['symbol'], 'weight': row['alternative_weight']}
                          for row in adjustment['holdings'] if row['alternative_weight'] > 0],
        })
        compared = self.call('/api/analyze', self.payload)
        self.assertEqual(len(compared['analysis']['scenarios']), 2)
        self.assertAlmostEqual(compared['analysis']['scenarios'][1]['annualized_sample_volatility'],
                               adjustment['alternative_volatility'])
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).hexdigest())

    def test_demo_rejects_real_symbols_and_unavailable_routes(self):
        for path in ('/api/instruments/load', '/api/replacement-screen', '/api/study/start'):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                self.call(path, {})
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        self.payload['configuration']['portfolios'][0]['positions'][0]['instrument_id'] = 'AAPL'
        with self.assertRaises(HTTPError) as error:
            self.call('/api/analyze', self.payload)
        self.assertEqual(error.exception.code, 422)
        error.exception.close()


if __name__ == '__main__':
    unittest.main()
