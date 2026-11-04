"""Synthetic fixtures exercise SQL controls; production reports use real snapshots."""
import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from scripts.build_warehouse import TABLES, export_dataset, load_bundle, prepare_bundle


def fixture(dataset="dataset-new", primary="yahoo_prices:new"):
    frames={name:[] for name in TABLES}
    runs=[("yahoo_prices:old","yahoo_prices"),("yahoo_prices:new","yahoo_prices"),("fred:ref","fred"),("yahoo_index:ref","yahoo_index")]
    frames["ingestion_runs"]=[{"run_id":r,"source_id":s,"capture_id":r.split(":")[1],"manifest_sha256":r,"manifest_json":"{}"} for r,s in runs]
    frames["instruments"]=[{"instrument_id":"AAPL","currency":"USD","calendar_id":"XNAS"}]
    for run_id, base in [("yahoo_prices:old",50.0),("yahoo_prices:new",100.0)]:
        for i in range(22):
            frames["prices_daily"].append({"run_id":run_id,"instrument_id":"AAPL","session_date":date(2026,1,1)+timedelta(days=i),
                "open":base+i,"high":base+i+1,"low":base+i-1,"close":base+i,"adjusted_close":base+i,"volume":1000})
    frames["benchmark_observations"]=[{"run_id":r,"series_id":s,"observation_date":date(2026,1,2),"index_level":v,"units":"price_index"}
                                       for r,s,v in [("fred:ref","SP500",105.0),("yahoo_index:ref","^GSPC",100.0)]]
    frames["dataset_versions"]=[{"dataset_id":dataset,"primary_run_id":primary,"policy_id":"DS-001","recipe_json":"{}"}]
    frames["dataset_runs"]=[{"dataset_id":dataset,"run_id":r} for r,_ in runs]
    frames["source_rules"]=[{"dataset_id":dataset,"source_id":s,"entity_id":e,"purpose":p} for s,e,p in
                            [("yahoo_prices","AAPL","risk_prices"),("fred","SP500","context"),("yahoo_index","^GSPC","quarantine")]]
    frames["expected_sessions"]=[{"dataset_id":dataset,"instrument_id":"AAPL","session_date":date(2026,1,1)+timedelta(days=i)} for i in range(22)]
    frames["data_quality_issues"]=[{"dataset_id":dataset,"issue_id":"issue-1","entity_id":"SP500","observation_date":date(2026,1,2),
        "rule_id":"same_index_close_v1","observed_run_id":"yahoo_index:ref","reference_run_id":"fred:ref","observed_value":100.0,
        "reference_value":105.0,"absolute_difference":5.0,"tolerance":0.02,"status":"quarantined","evidence_ref":"fixture.json","resolution_note":"Fixture only"}]
    return {"dataset_id":dataset,"frames":frames,"recipe":{}}


class WarehouseTests(unittest.TestCase):
    def setUp(self):
        self.con=duckdb.connect()
        self.bundle=fixture()
        load_bundle(self.con,self.bundle)

    def tearDown(self):
        self.con.close()

    def test_identical_rerun_does_not_duplicate_rows_or_reset_issue_status(self):
        self.con.execute("UPDATE data_quality_issues SET status='resolved',resolution_note='Test review note'")
        load_bundle(self.con,self.bundle)
        self.assertEqual(self.con.execute("SELECT count(*) FROM prices_daily").fetchall()[0][0],44)
        self.assertEqual(self.con.execute("SELECT count(*) FROM data_quality_issues").fetchall()[0][0],1)
        self.assertEqual(self.con.execute("SELECT status,resolution_note FROM active_quality_issues").fetchall()[0],('resolved','Test review note'))

    def test_explicit_selection_preserves_both_price_versions(self):
        self.assertEqual(self.con.execute("SELECT min(close) FROM accepted_prices_daily").fetchall()[0][0],100)
        load_bundle(self.con,fixture('dataset-old','yahoo_prices:old'))
        self.assertEqual(self.con.execute("SELECT min(close) FROM accepted_prices_daily").fetchall()[0][0],50)
        self.assertEqual(self.con.execute("SELECT count(*) FROM prices_daily").fetchall()[0][0],44)
        self.assertEqual(self.con.execute("SELECT count(*) FROM dataset_versions").fetchall()[0][0],2)

    def test_quarantined_source_is_separate_from_accepted_context_and_risk(self):
        self.assertEqual(self.con.execute("SELECT DISTINCT source_id FROM benchmark_context_daily").fetchall(),[('fred',)])
        self.assertEqual(self.con.execute("SELECT DISTINCT source_id FROM quarantined_benchmark_daily").fetchall(),[('yahoo_index',)])
        self.assertEqual(self.con.execute("SELECT DISTINCT instrument_id FROM accepted_prices_daily").fetchall(),[('AAPL',)])
        self.assertEqual(self.con.execute("SELECT count(*) FROM active_quality_issues").fetchall()[0][0],1)

    def test_constraint_failure_rolls_back_rows_and_active_selection(self):
        bad=fixture('bad-dataset')
        bad['frames']['prices_daily'][0]['volume']=-1
        bad['frames']['prices_daily'][0]['run_id']='yahoo_prices:bad'
        bad['frames']['ingestion_runs'].append({'run_id':'yahoo_prices:bad','source_id':'yahoo_prices','capture_id':'bad','manifest_sha256':'bad','manifest_json':'{}'})
        with self.assertRaises(duckdb.ConstraintException):
            load_bundle(self.con,bad)
        self.assertEqual(self.con.execute("SELECT dataset_id FROM active_dataset").fetchall()[0][0],'dataset-new')
        self.assertEqual(self.con.execute("SELECT count(*) FROM ingestion_runs WHERE run_id='yahoo_prices:bad'").fetchall()[0][0],0)

    def test_changed_manifest_for_existing_capture_is_rejected(self):
        changed=copy.deepcopy(self.bundle)
        changed['frames']['ingestion_runs'][0]['manifest_sha256']='different'
        with self.assertRaisesRegex(ValueError,'different manifest'):
            load_bundle(self.con,changed)
        self.assertEqual(self.con.execute("SELECT count(*) FROM prices_daily").fetchall()[0][0],44)

    def test_sql_calendar_prevents_gap_bridging_and_incomplete_windows(self):
        self.assertEqual(self.con.execute("SELECT count(simple_return),count(trailing_20_ann_volatility) FROM historical_risk_inputs").fetchall()[0],(21,2))
        self.con.execute("DELETE FROM prices_daily WHERE run_id='yahoo_prices:new' AND session_date='2026-01-10'")
        rows=self.con.execute("SELECT simple_return FROM returns_daily WHERE session_date IN ('2026-01-10','2026-01-11')").fetchall()
        self.assertEqual(rows,[(None,),(None,)])
        self.assertEqual(self.con.execute("SELECT count(trailing_20_ann_volatility) FROM historical_risk_inputs").fetchall()[0][0],0)

    def test_parquet_replay_verifies_rows_and_detects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            first=export_dataset(self.con,'dataset-new',root)
            self.assertEqual(first,export_dataset(self.con,'dataset-new',root))
            (root/'dataset-new/prices_daily.parquet').write_bytes(b'corrupted fixture')
            with self.assertRaisesRegex(ValueError,'Parquet cache changed'):
                export_dataset(self.con,'dataset-new',root)

    def test_unknown_policy_cannot_silently_allow_the_comparator(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'manifest.json').write_text('{}')
            policy=path/'policy.json'
            policy.write_text(json.dumps({'policy_id':'DS-001','rules':[]}))
            with self.assertRaisesRegex(ValueError,'Unsupported source policy'):
                prepare_bundle(path,path,[],policy)


if __name__=='__main__':
    unittest.main()
