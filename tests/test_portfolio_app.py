import copy
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

import duckdb
import numpy as np
import pandas as pd

from scripts.portfolio_baseline import analyze, serializable
from scripts.serve_portfolio_app import (
    allowed_request, assess, context, handler_class, historical_scenarios,
    strict_json, validate_request,
)
from tests.test_portfolio_baseline import configuration, database, panels


def payload():
    return {'configuration': configuration(), 'volatility_reference': None}


def registry():
    return {'schema_version': 1, 'scenario_registry_id': 'FIXTURE',
            'convention': 'fixed_weights_daily_rebalanced',
            'scenarios': [{'id': 'fixture', 'name': 'Synthetic window',
                           'start_close': '2026-01-01', 'end_close': '2026-01-05'}]}


class PortfolioApplicationTests(unittest.TestCase):
    def test_application_metrics_match_the_existing_verified_engine(self):
        with database() as connection:
            expected, _ = analyze(connection, configuration())
            actual = assess(connection, payload(), registry())
        self.assertEqual(actual['analysis'], serializable(expected))
        self.assertFalse(actual['model_forecasts_used'])
        self.assertEqual(len(actual['chart_series']), 5)

    def test_reference_is_user_supplied_and_does_not_change_risk_estimates(self):
        with database() as connection:
            empty = assess(connection, payload(), registry())
            request = payload()
            request['volatility_reference'] = 1e-8
            low = assess(connection, request, registry())
            request['volatility_reference'] = 1.
            high = assess(connection, request, registry())
        self.assertIsNone(empty['reference_comparisons'][0]['comparison'])
        self.assertEqual(low['reference_comparisons'][0]['comparison'], 'above_reference')
        self.assertEqual(high['reference_comparisons'][0]['comparison'], 'within_reference')
        self.assertEqual(empty['analysis'], low['analysis'])
        self.assertEqual(low['analysis'], high['analysis'])

    def test_invalid_references_and_oversized_comparisons_are_rejected(self):
        for value in [-1., 0., True, float('nan'), float('inf'), 3.]:
            request = payload()
            request['volatility_reference'] = value
            with self.assertRaises(ValueError):
                validate_request(request)
        request = payload()
        request['configuration']['risk_window_sessions'] = 253
        with self.assertRaises(ValueError):
            validate_request(request)
        request = payload()
        for index in [1, 2]:
            extra = copy.deepcopy(request['configuration']['portfolios'][0])
            extra['id'] = f'extra_{index}'
            request['configuration']['portfolios'].append(extra)
        with self.assertRaises(ValueError):
            validate_request(request)

    def test_scenario_return_and_drawdown_are_anchored_inside_the_window(self):
        result = {'scenarios': [{'id': 'a'}]}
        dates = pd.date_range('2026-01-01', periods=5)
        daily = pd.DataFrame({'a_wealth_index': [4., 1., 1.2, .9, 1.1]}, index=dates)
        spec = registry()
        spec['scenarios'][0]['start_close'] = '2026-01-02'
        actual = historical_scenarios(result, daily, spec)[0]
        self.assertAlmostEqual(actual['replay_return'], .1)
        self.assertAlmostEqual(actual['maximum_drawdown'], -.25)
        self.assertEqual(actual['return_sessions'], 3)

    def test_unavailable_scenarios_do_not_use_later_or_partial_history(self):
        result = {'scenarios': [{'id': 'a'}]}
        daily = pd.DataFrame({'a_wealth_index': [1., .9]}, index=pd.date_range('2026-01-01', periods=2))
        row = historical_scenarios(result, daily, registry())[0]
        self.assertFalse(row['available'])
        self.assertNotIn('replay_return', row)
        self.assertNotIn('maximum_drawdown', row)
        spec = registry()
        spec['scenarios'][0]['end_close'] = '2025-01-01'
        with self.assertRaises(ValueError):
            historical_scenarios(result, daily, spec)

    def test_host_and_origin_policy_restricts_requests_to_the_local_app(self):
        self.assertTrue(allowed_request('127.0.0.1:8765', None, 8765))
        self.assertTrue(allowed_request('localhost:8765', 'http://localhost:8765', 8765, True))
        for host, origin in [('attacker.example:8765', 'http://attacker.example:8765'),
                              ('127.0.0.1:8765', 'https://attacker.example'),
                              ('127.0.0.1:8765', None),
                              ('127.0.0.1:9999', 'http://127.0.0.1:9999')]:
            self.assertFalse(allowed_request(host, origin, 8765, True))

    def test_nonfinite_json_is_rejected_before_analysis(self):
        for value in ['NaN', 'Infinity', '-Infinity']:
            with self.assertRaises(ValueError):
                strict_json('{"value":' + value + '}')
        self.assertEqual(strict_json('{"value":null}'), {'value': None})

    def test_context_reports_observed_coverage_without_downloading(self):
        with database() as connection:
            actual = context(connection)
        self.assertEqual(actual['dataset_id'], 'fixture')
        self.assertEqual(actual['latest_common_close'], '2026-01-05')
        self.assertEqual(actual['price_rows'], 10)
        self.assertFalse(actual['downloaded_on_request'])
        self.assertFalse(actual['personal_inputs_saved'])

    def test_http_analysis_is_local_and_does_not_modify_the_warehouse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.duckdb'
            prices, returns, calendar = panels()
            frames = {'accepted_prices_daily': prices, 'returns_daily': returns,
                      'expected_sessions': calendar, 'active_dataset': pd.DataFrame({'dataset_id': ['fixture']})}
            with duckdb.connect(str(path)) as connection:
                for name, frame in frames.items():
                    connection.register('records', frame)
                    connection.execute(f'CREATE TABLE {name} AS SELECT * FROM records').fetchall()
                    connection.unregister('records')
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_class(path))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_port
                client = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                client.request('POST', '/api/analyze', json.dumps(payload()),
                               {'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{port}'})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                result = json.loads(response.read())
                self.assertTrue(result['analysis']['reconciliations_passed'])
                self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
                client.close()
                client = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                client.request('POST', '/api/analyze', json.dumps(payload()),
                               {'Content-Type': 'application/json', 'Origin': 'https://unrelated.example'})
                response = client.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                client.close()
                client = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                client.request('GET', '/../AGENTS.md')
                response = client.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                client.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
