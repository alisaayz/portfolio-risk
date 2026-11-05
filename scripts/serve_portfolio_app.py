"""Local portfolio comparison application using the reconciled historical engine.

The service binds only to 127.0.0.1, keeps inputs in memory, and reads the market
warehouse without changing it. It does not serve trained-model forecasts.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re

import duckdb
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.portfolio_baseline import analyze, drawdown_summary, serializable, validate_configuration

ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
MAX_BODY_BYTES = 65536


def validate_request(payload):
    if not isinstance(payload, dict) or set(payload) != {'configuration', 'volatility_reference'}:
        raise ValueError('Provide a portfolio configuration and optional volatility reference')
    config = payload['configuration']
    if not isinstance(config, dict):
        raise ValueError('Portfolio configuration must be an object')
    validate_configuration(config)
    if not 1 <= len(config['portfolios']) <= 2:
        raise ValueError('Compare one or two portfolios')
    if not 2 <= config['risk_window_sessions'] <= 252:
        raise ValueError('Risk window must contain 2 to 252 sessions')
    for portfolio in config['portfolios']:
        if len(portfolio['name']) > 80 or len(portfolio['positions']) > 16:
            raise ValueError('Use names of at most 80 characters and at most sixteen positions')
        for position in portfolio['positions']:
            if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}', position['instrument_id']):
                raise ValueError('Invalid instrument symbol')
    limit = payload['volatility_reference']
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, float))
                              or not math.isfinite(limit) or not 0 < limit <= 2):
        raise ValueError('Volatility reference must be above zero and at most 200%')
    return config, limit


def historical_scenarios(result, daily, registry):
    if registry.get('schema_version') != 1 or registry.get('convention') != 'fixed_weights_daily_rebalanced':
        raise ValueError('Unsupported historical scenario convention')
    records = []
    for scenario in registry['scenarios']:
        start, end = pd.Timestamp(scenario['start_close']), pd.Timestamp(scenario['end_close'])
        if start >= end:
            raise ValueError('Scenario endpoints must be ordered')
        for portfolio in result['scenarios']:
            row = {'scenario_id': scenario['id'], 'name': scenario['name'],
                   'portfolio_id': portfolio['id'], 'start_close': str(start.date()),
                   'end_close': str(end.date())}
            if start not in daily.index or end not in daily.index:
                records.append({**row, 'available': False,
                                'reason': 'The complete window is outside this portfolio snapshot history'})
                continue
            wealth = daily.loc[start:end, portfolio['id'] + '_wealth_index']
            normalized = wealth / float(wealth.iloc[0])
            records.append({**row, 'available': True,
                            'replay_return': float(normalized.iloc[-1] - 1),
                            'maximum_drawdown': drawdown_summary(normalized)['maximum_drawdown'],
                            'return_sessions': len(normalized) - 1})
    return records


def assess(connection, payload, registry=None):
    config, reference = validate_request(payload)
    result, daily = analyze(connection, config)
    if registry is None:
        registry = json.loads((ROOT / 'config/stress_scenarios.json').read_text())
    assessment = []
    for portfolio in result['scenarios']:
        measured = portfolio['annualized_sample_volatility']
        assessment.append({'portfolio_id': portfolio['id'],
                           'annualized_sample_volatility': measured,
                           'volatility_reference': reference,
                           'comparison': None if reference is None else
                               ('above_reference' if measured > reference else 'within_reference')})
    series = [{'date': str(day.date()), **{column: float(value) for column, value in row.items()}}
              for day, row in daily.iterrows()]
    return serializable({
        'analysis': result, 'reference_comparisons': assessment,
        'historical_scenarios': historical_scenarios(result, daily, registry),
        'chart_series': series, 'is_demo': config['is_demo'],
        'method': 'historical_sample_covariance', 'model_forecasts_used': False,
        'scenario_registry_id': registry['scenario_registry_id'],
        'scenario_registry_sha256': hashlib.sha256(json.dumps(registry, sort_keys=True).encode()).hexdigest(),
        'application_sha256': sha256(Path(__file__)),
    })


def context(connection):
    dataset = connection.execute('SELECT dataset_id FROM active_dataset').fetchall()[0][0]
    rows = connection.execute('''SELECT instrument_id, min(session_date), max(session_date), count(*)
                                 FROM accepted_prices_daily GROUP BY instrument_id ORDER BY instrument_id''').fetchall()
    if not rows:
        raise ValueError('No accepted market observations are available')
    registry = json.loads((ROOT / 'config/reference_universe.json').read_text())
    labels = {row['symbol']: row['research_role'] for row in registry['instruments']}
    latest_common = min(row[2] for row in rows)
    date_string = lambda value: str(pd.Timestamp(value).date())
    demo = json.loads((ROOT / 'config/demo_portfolios.json').read_text())
    demo['as_of_date'] = date_string(latest_common)
    tables = {row[0] for row in connection.execute('SHOW TABLES').fetchall()}
    issues = []
    if 'active_quality_issues' in tables:
        issues = [{'entity': row[0], 'date': str(row[1]), 'status': row[2]}
                  for row in connection.execute('SELECT entity_id,observation_date,status FROM active_quality_issues ORDER BY observation_date').fetchall()]
    return {'dataset_id': dataset, 'latest_common_close': date_string(latest_common),
            'earliest_common_close': date_string(max(row[1] for row in rows)),
            'instruments': [{'symbol': row[0], 'label': labels.get(row[0], row[0]),
                             'start': date_string(row[1]), 'end': date_string(row[2]), 'sessions': row[3]} for row in rows],
            'price_rows': sum(row[3] for row in rows), 'source_issues': issues,
            'demo_configuration': demo, 'currency': 'USD',
            'source': 'Saved Yahoo Finance history through yfinance; accepted under a versioned source policy',
            'downloaded_on_request': False, 'personal_inputs_saved': False,
            'final_test_scores_opened': False}


def strict_json(body):
    def reject_constant(value):
        raise ValueError(f'Nonfinite JSON value is not allowed: {value}')
    return json.loads(body, parse_constant=reject_constant)


def allowed_request(host, origin, port, require_origin=False):
    allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
    if host not in allowed:
        return False
    return (not require_origin and origin is None) or origin == f'http://{host}'


def handler_class(database):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'PortfolioRiskLocal/1.0'

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *args):
            # Keep portfolio inputs and query strings out of request logs.
            pass

        def send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status, value):
            self.send_bytes(status, json.dumps(value, allow_nan=False).encode(), 'application/json; charset=utf-8')

        def request_allowed(self, require_origin=False):
            return allowed_request(self.headers.get('Host'), self.headers.get('Origin'),
                                   self.server.server_port, require_origin)

        def do_GET(self):
            if not self.request_allowed():
                self.send_json(403, {'error': 'Use this application from its local address'})
                return
            if self.path in ASSETS:
                name, content_type = ASSETS[self.path]
                self.send_bytes(200, (ROOT / 'app' / name).read_bytes(), content_type)
                return
            if self.path != '/api/context':
                self.send_json(404, {'error': 'Not found'})
                return
            try:
                with duckdb.connect(str(database), read_only=True) as connection:
                    value = context(connection)
                self.send_json(200, value)
            except (duckdb.Error, ValueError, IndexError):
                self.send_json(503, {'error': 'Accepted local data is unavailable. Build the warehouse before starting the application.'})

        def do_POST(self):
            if not self.request_allowed(require_origin=True):
                self.send_json(403, {'error': 'Analysis requests must come from this local application'})
                return
            if self.path != '/api/analyze':
                self.send_json(404, {'error': 'Not found'})
                return
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError('Send application/json')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= MAX_BODY_BYTES:
                    raise ValueError('Request is empty or too large')
                payload = strict_json(self.rfile.read(length))
                with duckdb.connect(str(database), read_only=True) as connection:
                    value = assess(connection, payload)
                self.send_json(200, value)
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                self.send_json(422, {'error': str(error) or 'Invalid portfolio inputs'})
            except (duckdb.Error, AssertionError):
                self.send_json(503, {'error': 'Analysis could not complete its data and numerical checks'})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/warehouse/portfolio-risk.duckdb')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('Build the local market warehouse first')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_class(args.database))
    print(f'Portfolio Risk is available at http://127.0.0.1:{server.server_port}', flush=True)
    print('Analysis uses the saved warehouse. Inputs remain in memory; stop with Ctrl+C.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
