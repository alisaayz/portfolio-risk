"""Stage a saved capture in a disposable warehouse and report changes without promotion."""

import argparse
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory

import duckdb

from scripts.audit_market_data import sha256
from scripts.build_warehouse import load_bundle, prepare_bundle
from scripts.verify_warehouse import verify


def profile(connection):
    dataset = connection.execute('SELECT dataset_id FROM active_dataset').fetchall()[0][0]
    prices = connection.execute('''
        SELECT instrument_id, min(session_date), max(session_date), count(*)
        FROM accepted_prices_daily GROUP BY instrument_id ORDER BY instrument_id
    ''').fetchall()
    issues = connection.execute('SELECT issue_id FROM data_quality_issues ORDER BY issue_id').fetchall()
    active = connection.execute('SELECT issue_id FROM active_quality_issues').fetchall()
    runs = connection.execute('SELECT run_id, manifest_sha256 FROM ingestion_runs ORDER BY run_id').fetchall()
    return {'dataset_id': dataset, 'coverage': {symbol: {'start': str(first), 'end': str(last), 'rows': count}
                                                for symbol, first, last, count in prices},
            'retained_issues': set(issues), 'active_issues': len(active), 'runs': set(runs)}


def preview(database, snapshot, external, historical, policy):
    original = sha256(database)
    try:
        with TemporaryDirectory(prefix='riskitnot-refresh-') as folder:
            path = Path(folder) / 'staged.duckdb'
            shutil.copyfile(database, path)
            with duckdb.connect(str(path)) as connection:
                before = profile(connection)
                connection.execute('CREATE TEMP TABLE previous_prices AS SELECT * FROM accepted_prices_daily')
                bundle = prepare_bundle(snapshot, external, historical, policy)
                load_bundle(connection, bundle)
                verify(connection)
                after = profile(connection)
                revised = connection.execute('''
                    SELECT p.instrument_id,
                           count(*) FILTER (WHERE p.close <> n.close) AS closes,
                           count(*) FILTER (WHERE p.adjusted_close <> n.adjusted_close) AS adjusted,
                           count(*) FILTER (WHERE p.volume <> n.volume) AS volume
                    FROM previous_prices p JOIN accepted_prices_daily n USING(instrument_id, session_date)
                    GROUP BY p.instrument_id ORDER BY p.instrument_id
                ''').fetchall()
                missing_sessions = connection.execute('''
                    SELECT count(*) FROM previous_prices p
                    ANTI JOIN accepted_prices_daily n USING(instrument_id, session_date)
                ''').fetchall()[0][0]
                if missing_sessions or not (before['retained_issues'] <= after['retained_issues']
                                            and before['runs'] <= after['runs']):
                    raise ValueError('Staged refresh would drop previously accepted sessions or retained evidence')
                result = {
                    'status': 'unchanged' if before['dataset_id'] == after['dataset_id'] else 'review_required',
                    'before_dataset': before['dataset_id'], 'candidate_dataset': after['dataset_id'],
                    'before_coverage': before['coverage'], 'candidate_coverage': after['coverage'],
                    'active_quarantine_before': before['active_issues'], 'active_quarantine_candidate': after['active_issues'],
                    'prior_evidence_retained': True, 'changed_overlap': [
                        {'symbol': s, 'close': c, 'adjusted_close': a, 'volume': v}
                        for s, c, a, v in revised if c or a or v],
                }
    except (OSError, ValueError, KeyError, AssertionError, duckdb.Error) as error:
        result = {'status': 'blocked', 'reason': str(error) or type(error).__name__}
    finally:
        if sha256(database) != original:
            raise RuntimeError('The active warehouse changed during the dry run')
    return {**result, 'active_warehouse_sha256': original, 'promoted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--external-snapshot', required=True, type=Path)
    parser.add_argument('--historical-snapshot', action='append', type=Path, default=[])
    parser.add_argument('--policy', required=True, type=Path)
    args = parser.parse_args()
    result = preview(args.database, args.snapshot, args.external_snapshot, args.historical_snapshot, args.policy)
    print(json.dumps(result, indent=2))
    return 2 if result['status'] == 'blocked' else 0


if __name__ == '__main__':
    raise SystemExit(main())
