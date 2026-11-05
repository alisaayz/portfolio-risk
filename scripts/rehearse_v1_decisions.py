"""Exercise 30 fixed decision paths against the tagged V1 dashboard API."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


V1 = 'd4eba345acf506ff3fb89c8583bc0bb1f5d9b02c'
DATASET = '80b5d80b266b0255f7c8de0310569de02f63a5ee0ff2a54e707ddfa2cd114166'
WAREHOUSE_SHA256 = '6dee162df4f560178d8a5ea55313898aba69e858857192c74425d804e498e404'


def request(base, route, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json', 'Origin': base}
    try:
        with urlopen(Request(base + route, data=data, headers=headers), timeout=8) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        with error:
            return error.code, json.load(error)


def verify_checkout(root):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    if git('rev-parse', 'HEAD') != V1 or git('rev-parse', 'v1.0.0^{commit}') != V1 or git('status', '--porcelain'):
        raise ValueError('Use a clean checkout at the preserved v1.0.0 commit')
    warehouse = root / 'data/warehouse/portfolio-risk.duckdb'
    if hashlib.sha256(warehouse.read_bytes()).hexdigest() != WAREHOUSE_SHA256:
        raise ValueError('The warehouse differs from the archived V1 snapshot')


def wait_for_context(base, server):
    for _ in range(40):
        if server.poll() is not None:
            raise RuntimeError('The V1 rehearsal server did not start')
        try:
            code, context = request(base, '/api/context')
            if code == 200 and context['dataset_id'] == DATASET:
                return context
            raise ValueError('Unexpected V1 dashboard context')
        except URLError:
            time.sleep(.25)
    raise RuntimeError('The V1 rehearsal server did not respond')


def run_case_a(base, config):
    paths = [
        ('case_settings', (252,) * 3, (.085, .09, .10), True, .106, ('target_met',) * 3),
        ('budget_too_small', (252,) * 3, (.02, .05, .08), True, .106, ('target_unreachable',) * 3),
        ('lock_omitted', (252,) * 3, (.05, .075, .10), False, .106, ('target_met',) * 3),
        ('different_window', (63, 126, 126), (.10, .085, .10), True, .106,
         ('already_within_target', 'target_met', 'target_met')),
        ('target_omitted', (252,) * 3, (.02, .05, .08), True, None, ('lower_risk',) * 3),
    ]
    records = []
    for path, windows, budgets, lock, reference, expected in paths:
        for window, budget, expected_status in zip(windows, budgets, expected, strict=True):
            payload = {
                'portfolio': {'configuration': {**config, 'risk_window_sessions': window},
                              'volatility_reference': reference},
                'constraints': {'turnover_limit': budget, 'holdings': {'AAPL': {'locked': lock}}},
            }
            code, result = request(base, '/api/reweight', payload)
            assert code == 200 and result['status'] == expected_status, (path, result)
            weight = next(row['alternative_weight'] for row in result['holdings'] if row['symbol'] == 'AAPL')
            assert result['turnover'] <= budget + 1e-10 and result['risk_window_sessions'] == window
            assert (abs(weight - .30) <= 1e-10) == lock
            if path in {'budget_too_small', 'target_omitted'}:
                assert result['alternative_volatility'] > .106
            if path == 'case_settings':
                assert result['alternative_volatility'] <= .106 + 1e-10
            records.append({
                'case': 'A', 'path': path, 'window': window, 'move_limit': budget, 'reference': reference,
                'aapl_locked': lock, 'response': result['status'], 'estimated_volatility': result['alternative_volatility'],
                'turnover': result['turnover'], 'aapl_weight': weight,
            })
    return records


def run_case_b(base, config, kinds):
    equity_etfs = ('QQQ', 'EFA', 'IWM')
    paths = [
        ('case_settings', 252, .10, equity_etfs, 'above_target'),
        ('target_only_wrong_exposure', 252, .10, ('XOM', 'IEF', 'TLT'), 'meets_target'),
        ('different_window', 63, .10, equity_etfs, 'meets_target'),
        ('target_omitted', 252, None, equity_etfs, 'meets_target'),
    ]
    records = []
    for path, window, reference, symbols, expected in paths:
        for symbol in symbols:
            payload = {
                'portfolio': {'configuration': {**config, 'risk_window_sessions': window},
                              'volatility_reference': reference},
                'constraints': {'turnover_limit': .10, 'holdings': {}},
                'replacement': {'symbol': 'AAPL', 'weight': .10},
            }
            code, result = request(base, '/api/replacement-screen', payload)
            assert code == 200, (path, result)
            candidates = result['screen']['candidates']
            row = next(candidate for candidate in candidates if candidate['symbol'] == symbol)
            assert row['status'] == expected, (path, row)
            if path == 'case_settings':
                assert not any(kinds[c['symbol']] == 'equity_etf' and c['status'] == 'meets_target' for c in candidates)
            if path == 'target_omitted':
                assert result['target_source'] == 'current_estimate' and row['portfolio_volatility'] > .10
            assert (kinds[symbol] != 'equity_etf') == (path == 'target_only_wrong_exposure')
            records.append({
                'case': 'B', 'path': path, 'window': window, 'reference': reference,
                'candidate': symbol, 'candidate_kind': kinds[symbol], 'response': row['status'],
                'estimated_volatility': row['portfolio_volatility'],
            })
    for name, budget, rules in [
        ('locked', .10, {'locked': True}), ('minimum_weight', .10, {'minimum': .25}), ('move_limit', .05, {}),
    ]:
        payload = {
            'portfolio': {'configuration': config, 'volatility_reference': .10},
            'constraints': {'turnover_limit': budget, 'holdings': {'AAPL': rules}},
            'replacement': {'symbol': 'AAPL', 'weight': .10},
        }
        code, result = request(base, '/api/replacement-screen', payload)
        assert code == 422 and 'allows up to' in result['error'], (name, result)
        records.append({'case': 'B', 'path': 'constraint_rejected', 'constraint': name, 'response': code})
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--v1-root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    root = args.v1_root.resolve()
    verify_checkout(root)
    base = f'http://127.0.0.1:{args.port}'
    with subprocess.Popen([str(root / '.venv/bin/python'), '-m', 'scripts.serve_portfolio_app',
                           '--port', str(args.port)], cwd=root, stdout=subprocess.DEVNULL) as server:
        try:
            context = wait_for_context(base, server)
            code, study = request(base, '/api/study')
            assert code == 200 and study['recording'] is False
            config = deepcopy(context['demo_configuration'])
            config['portfolios'] = config['portfolios'][:1]
            registry = json.loads((root / 'config/reference_universe.json').read_text())
            kinds = {row['symbol']: row['kind'] for row in registry['instruments']}
            records = run_case_a(base, config) + run_case_b(base, config, kinds)
            counts = Counter(record['case'] for record in records)
            assert counts == {'A': 15, 'B': 15}
        finally:
            server.terminate()
    verify_checkout(root)
    print(json.dumps({
        'v1_commit': V1, 'dataset_id': DATASET, 'warehouse_sha256': WAREHOUSE_SHA256,
        'evidence_type': 'scripted_api_rehearsal', 'trials': len(records), 'by_case': counts,
        'participant_sessions': 0, 'trials_detail': records,
    }, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
