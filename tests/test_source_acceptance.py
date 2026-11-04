"""Fail-closed source acceptance tests using synthetic comparison evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.build_warehouse import check_acceptance, load_bundle, validated_policy_calendars
from scripts.corporate_action_checks import check_action, reference_configuration, validate_actions
from scripts.cross_validate_sources import websites_for_manifest
from tests.test_warehouse import fixture


class SourceAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT/'config/expanded_source_policy.json').read_text())
        universe = json.loads((ROOT/'config/reference_universe.json').read_text())
        self.manifest = {'universe': universe, 'universe_sha256': self.policy['universe_sha256'],
                         'instruments': {r['symbol']: {'calendar': r['calendar']} for r in universe['instruments']}}
        self.calendars = validated_policy_calendars(self.manifest, self.policy)
        self.comparison = {
            'website_checks': {symbol: {'passed':True, 'compared_dates':5, 'required_dates':5} for symbol in self.calendars},
            'issuer_action_checks': [{'reference_id':r['id'], 'passed':True} for r in reference_configuration()['references']],
            'fred_benchmark_check': {'passed':False, 'required_dates':10, 'compared_dates':10,
                                     'missing_dates':[], 'mismatch_dates':['2020-05-11']}}

    def test_expanded_scope_requires_exact_universe_and_reference_binding(self):
        self.assertEqual(len(self.calendars),16)
        for field in ['universe_sha256','issuer_reference_sha256','universe_id','issuer_reference_set_id']:
            changed=copy.deepcopy(self.policy);changed[field]='changed'
            with self.subTest(field=field),self.assertRaises(ValueError):
                validated_policy_calendars(self.manifest,changed)
        changed=copy.deepcopy(self.manifest);changed['universe']['instruments'].pop()
        with self.assertRaises(ValueError):validated_policy_calendars(changed,self.policy)

    def test_quarantine_or_context_cannot_be_promoted_to_risk_prices(self):
        for index in [-1,-2]:
            changed=copy.deepcopy(self.policy);changed['rules'][index]['purpose']='risk_prices'
            with self.assertRaisesRegex(ValueError,'Unsupported source policy rules'):
                validated_policy_calendars(self.manifest,changed)

    def test_missing_duplicate_or_unknown_rules_are_rejected(self):
        for mutation in ['omit','duplicate','unknown']:
            changed=copy.deepcopy(self.policy)
            if mutation=='omit':changed['rules'].pop(0)
            elif mutation=='duplicate':changed['rules'].append(copy.deepcopy(changed['rules'][0]))
            else:changed['rules'].append({'source_id':'yahoo_prices','entity_id':'OTHER','purpose':'risk_prices'})
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validated_policy_calendars(self.manifest,changed)

    def test_legacy_policy_stays_limited_to_original_scope(self):
        policy=json.loads((ROOT/'config/source_policy.json').read_text())
        manifest={'instruments':{k:self.manifest['instruments'][k] for k in ['AAPL','SPY','BND']}}
        self.assertEqual(set(validated_policy_calendars(manifest,policy)),{'AAPL','SPY','BND'})
        with self.assertRaises(ValueError):validated_policy_calendars(self.manifest,policy)

    def test_every_instrument_must_pass_all_five_quote_checks(self):
        for mutation in ['omit','failed','partial']:
            comparison=copy.deepcopy(self.comparison)
            if mutation=='omit':del comparison['website_checks']['GLD']
            elif mutation=='failed':comparison['website_checks']['GLD']['passed']=False
            else:comparison['website_checks']['GLD']['compared_dates']=4
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'quote acceptance'):
                check_acceptance(comparison,self.calendars,'DS-002')

    def test_empty_missing_duplicate_or_failed_issuer_evidence_rejects_acceptance(self):
        for mutation in ['empty','omit','duplicate','failed']:
            comparison=copy.deepcopy(self.comparison)
            if mutation=='empty':comparison['issuer_action_checks']=[]
            elif mutation=='omit':comparison['issuer_action_checks'].pop()
            elif mutation=='duplicate':comparison['issuer_action_checks'][-1]=copy.deepcopy(comparison['issuer_action_checks'][0])
            else:comparison['issuer_action_checks'][-1]['passed']=False
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'issuer action acceptance'):
                check_acceptance(comparison,self.calendars,'DS-002')

    def test_benchmark_mismatch_is_preserved_but_missing_evidence_blocks(self):
        check_acceptance(self.comparison,self.calendars,'DS-002')
        self.assertFalse(self.comparison['fred_benchmark_check']['passed'])
        changed=copy.deepcopy(self.comparison);changed['fred_benchmark_check']['missing_dates']=['2020-01-02']
        with self.assertRaisesRegex(ValueError,'Benchmark evidence'):check_acceptance(changed,self.calendars,'DS-002')

    def test_existing_instrument_identity_change_rolls_back(self):
        with duckdb.connect() as connection:
            original=fixture();load_bundle(connection,original)
            changed=fixture('changed');changed['frames']['instruments'][0]['calendar_id']='XNYS'
            with self.assertRaisesRegex(ValueError,'instrument has a different'):load_bundle(connection,changed)
            self.assertEqual(connection.execute('SELECT dataset_id FROM active_dataset').fetchall()[0][0],'dataset-new')

    def test_quote_page_mapping_covers_all_instruments_with_correct_type(self):
        urls=websites_for_manifest(self.manifest)
        self.assertEqual(len(urls),16)
        self.assertIn('/stocks/msft/',urls['MSFT']);self.assertIn('/etf/gld/',urls['GLD'])
        changed=copy.deepcopy(self.manifest);del changed['instruments']['GLD']
        with self.assertRaises(ValueError):websites_for_manifest(changed)


class IssuerEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.reference=next(r for r in reference_configuration()['references'] if r['symbol']=='MSFT')
        self.frame=pd.DataFrame({'Dividends':[.91]},index=pd.to_datetime(['2025-11-20']))
        self.html='<p>$0.91 per share. The ex-dividend date will be Nov. 20, 2025.</p>'

    def test_reviewed_issuer_date_and_amount_match(self):
        self.assertTrue(check_action(self.frame,self.html,self.reference)['passed'])

    def test_http_200_maintenance_or_script_only_content_is_not_evidence(self):
        for html in ['<h1>Site maintenance</h1>', '<script>'+self.html+'</script>']:
            result=check_action(self.frame,html,self.reference)
            self.assertFalse(result['passed']);self.assertTrue(result['missing_evidence_text'])

    def test_wrong_amount_or_missing_action_date_fails(self):
        for frame in [self.frame.assign(Dividends=.83),self.frame.iloc[:0]]:
            self.assertFalse(check_action(frame,self.html,self.reference)['passed'])

    def test_changed_issuer_registry_is_rejected_before_replay(self):
        with self.assertRaisesRegex(ValueError,'configuration differs'):
            validate_actions(Path('/nonexistent'),Path('/nonexistent'),{'issuer_reference_sha256':'altered'},None)


if __name__=='__main__':unittest.main()
