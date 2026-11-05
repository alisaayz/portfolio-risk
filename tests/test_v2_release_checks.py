"""Check the preview's failure boundaries for stored market and forward evidence."""

from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import duckdb

from scripts.audit_market_data import sha256
from scripts.market_provenance import accepted_evidence
from scripts.preview_market_refresh import preview
from scripts.record_prospective_forecast import PROTOCOL, timing, write_once


class ReleaseChecksTests(unittest.TestCase):
    def test_spot_checks_are_bound_to_the_archive_recipe(self):
        with TemporaryDirectory() as directory, duckdb.connect() as connection:
            path = Path(directory) / 'proof.json'
            checks = {'compared': 5, 'required': 5}
            path.write_text(json.dumps({'dataset_id': 'selected', 'primary_capture_id': 'run',
                'external_manifest_sha256': 'verified', 'instruments': {'AAPL': {'quotes': checks, 'issuer': []}}}))
            connection.execute('CREATE TABLE dataset_versions(dataset_id VARCHAR, policy_id VARCHAR, recipe_json VARCHAR, primary_run_id VARCHAR)')
            connection.execute('CREATE TABLE ingestion_runs(run_id VARCHAR, manifest_json VARCHAR)')
            connection.execute('INSERT INTO ingestion_runs VALUES (?, ?)', ['run', '{"retrieved_at_utc":"2026-11-04T00:00:00Z"}'])
            for dataset, external in [('selected', 'verified'), ('selected', 'other')]:
                connection.execute('DELETE FROM dataset_versions')
                connection.execute('INSERT INTO dataset_versions VALUES (?, ?, ?, ?)',
                                   [dataset, 'DS-002', json.dumps({'external_manifest_sha256': external}), 'run'])
                instruments = [{'symbol': 'AAPL', 'start': '2020-01-02', 'end': '2026-11-03', 'sessions': 1719}]
                with patch('scripts.market_provenance.ARCHIVE', path):
                    evidence = accepted_evidence(connection, instruments, dataset)['AAPL']
                self.assertEqual(evidence['spot_checks'], checks if external == 'verified' else None)
                self.assertEqual(evidence['price_status'], 'structurally_checked')

    def test_invalid_candidate_cannot_change_an_active_warehouse(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            database = base / 'warehouse.duckdb'
            with duckdb.connect(str(database)) as connection:
                connection.execute("CREATE TABLE active_dataset AS SELECT 'active' AS dataset_id")
                connection.execute("""CREATE TABLE accepted_prices_daily AS
                    SELECT 'AAPL' AS instrument_id, DATE '2026-11-03' AS session_date""")
                for table in ['data_quality_issues', 'active_quality_issues']:
                    connection.execute(f"CREATE TABLE {table} AS SELECT 'quarantined' AS issue_id")
                connection.execute("CREATE TABLE ingestion_runs AS SELECT 'known' AS run_id, 'verified' AS manifest_sha256")
            before = sha256(database)
            invalid = base / 'failed_capture'
            invalid.mkdir()
            (invalid / 'manifest.json').write_text('<html>temporarily unavailable</html>')
            report = preview(database, invalid, invalid, [], base / 'policy.json')
            self.assertEqual(report['status'], 'blocked')
            self.assertFalse(report['promoted'])
            self.assertEqual(before, sha256(database))

    def test_prospective_schedule_blocks_backfill_and_uses_market_hours(self):
        spec = json.loads(PROTOCOL.read_text())
        for stamp in ['2026-11-06T20:59:59', '2026-11-09T14:30:00']:
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                timing(datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc), spec)
        origin, target, _ = timing(datetime(2026, 11, 6, 21, 1, tzinfo=timezone.utc), spec)
        self.assertEqual(str(origin.date()), '2026-11-06')
        self.assertEqual(str(target.date()), '2026-12-07')

    def test_second_forecast_cannot_replace_first(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'origin.json'
            write_once(path, {'forecast': 1})
            original = sha256(path)
            with self.assertRaises(FileExistsError):
                write_once(path, {'forecast': 2})
            self.assertEqual(sha256(path), original)


if __name__ == '__main__':
    unittest.main()
