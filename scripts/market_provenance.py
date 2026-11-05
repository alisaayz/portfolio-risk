"""Report the scope of the evidence behind local instrument prices."""

from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import duckdb

from scripts.audit_market_data import ROOT, sha256


ARCHIVE = ROOT / 'config/archived_price_checks.json'


def snapshot_age(end):
    return max(0, (datetime.now(ZoneInfo('America/New_York')).date() - date.fromisoformat(end)).days)


def unavailable(symbol, status='directory_only'):
    return {'symbol': symbol, 'price_status': status, 'screen_member': False}


def on_demand(symbol, manifest):
    return {'symbol': symbol, 'policy': 'AP-001', 'price_status': 'structurally_checked',
            'coverage_start': manifest['coverage_start'], 'coverage_end': manifest['coverage_end'],
            'sessions': manifest['rows'], 'primary_source': 'Yahoo Finance',
            'primary_capture_id': manifest['cache_id'], 'checked_at': manifest['retrieved_at_utc'],
            'spot_checks': None, 'issuer_checks': [], 'screen_member': False,
            'warnings': manifest['warnings']}


def accepted_evidence(connection, instruments, dataset, screen_universe=None):
    tables = {row[0] for row in connection.execute('SHOW TABLES').fetchall()}
    identified = {'ingestion_runs', 'dataset_versions'} <= tables
    archive = json.loads(ARCHIVE.read_text()) if identified else None
    primary = None
    if identified:
        policy, recipe, run, manifest = connection.execute('''
            SELECT d.policy_id, d.recipe_json, r.run_id, r.manifest_json
            FROM dataset_versions d JOIN ingestion_runs r ON d.primary_run_id = r.run_id
            WHERE d.dataset_id = ?
        ''', [dataset]).fetchall()[0]
        primary = {'policy': policy, 'primary_source': 'Yahoo Finance',
                   'primary_capture_id': run, 'checked_at': json.loads(manifest)['retrieved_at_utc']}
        if (archive['dataset_id'] != dataset or archive['primary_capture_id'] != run
                or archive['external_manifest_sha256'] != json.loads(recipe)['external_manifest_sha256']):
            archive = None
    members = {row['symbol'] for row in screen_universe['instruments']} if screen_universe else set()
    result = {}
    for row in instruments:
        symbol = row['symbol']
        checks = archive['instruments'].get(symbol) if archive else None
        result[symbol] = {
            'symbol': symbol, 'price_status': 'structurally_checked' if primary else 'price_available',
            'coverage_start': row['start'], 'coverage_end': row['end'], 'sessions': row['sessions'],
            'spot_checks': checks['quotes'] if checks else None,
            'issuer_checks': checks['issuer'] if checks else [],
            'screen_member': symbol in members, **(primary or {}),
        }
    return result


def make_archived_summary(database, primary, external):
    """Recompute the published metadata from hash-bound local audit inputs."""
    from scripts.build_warehouse import check_acceptance
    from scripts.cross_validate_sources import load_prices, validate

    with duckdb.connect(str(database), read_only=True) as connection:
        dataset, policy, recipe, run = connection.execute('''
            SELECT dataset_id, policy_id, recipe_json, primary_run_id
            FROM active_dataset JOIN dataset_versions USING(dataset_id)
        ''').fetchall()[0]
    recipe = json.loads(recipe)
    for folder, key in [(primary, 'primary_manifest_sha256'), (external, 'external_manifest_sha256')]:
        if sha256(folder / 'manifest.json') != recipe[key]:
            raise ValueError(f'{key} differs from the selected warehouse recipe')
    manifest = json.loads((external / 'manifest.json').read_text())
    comparison = validate(external, primary, manifest)
    check_acceptance(comparison, comparison['website_checks'], policy)
    evidence = {}
    for symbol, row in sorted(comparison['website_checks'].items()):
        dates = load_prices(primary / f'{symbol}.csv').index[-row['required_dates']:]
        evidence[symbol] = {
            'quotes': {'source': 'Stock Analysis', 'source_url': row['source_url'],
                       'capture_id': comparison['run_id'], 'compared': row['compared_dates'],
                       'required': row['required_dates'], 'missing': row['missing_dates'],
                       'mismatches': row['mismatch_dates'],
                       'sessions': [str(day.date()) for day in dates],
                       'retrieved_at': manifest['sources'][symbol]['retrieved_at_utc'],
                       'upstream_independence': 'unverified'},
            'issuer': [{key: action[key] for key in ('reference_id', 'provider_date', 'scope', 'source_url')}
                       for action in comparison['issuer_action_checks'] if action['symbol'] == symbol and action['passed']],
        }
    return {'dataset_id': dataset, 'primary_capture_id': run,
            'external_manifest_sha256': recipe['external_manifest_sha256'],
            'instruments': evidence}


if __name__ == '__main__':
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--primary', type=Path, required=True)
    parser.add_argument('--external', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(make_archived_summary(args.database, args.primary, args.external), indent=2))
