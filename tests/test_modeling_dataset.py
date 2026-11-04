"""Synthetic price paths exercise numerical alignment and causal feature timing."""
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT
from scripts.build_modeling_dataset import (FEATURE_COLUMNS, KEYS, assemble, export,
    read_market_inputs, reconcile, sql_tables)
from scripts.evaluation_splits import split_membership


def prices(periods=560, constant=False):
    dates=pd.date_range('2024-01-02',periods=periods,freq='B')
    records=[]
    for symbol,phase in [('A',0),('B',3)]:
        changes=.004*np.sin((np.arange(periods)+phase)/9)+.002*np.cos(np.arange(periods)/11)
        values=np.full(periods,100.) if constant else 100*np.cumprod(1+changes)
        records.extend({'dataset_id':'fixture','instrument_id':symbol,'session_date':day,'adjusted_close':value}
                       for day,value in zip(dates,values))
    return pd.DataFrame(records)


def protocol():return json.loads((ROOT/'config/evaluation_protocol.json').read_text())


def membership(frame):
    frames=[]
    for symbol,group in frame.groupby('instrument_id',sort=True):
        observed=pd.DatetimeIndex(group.session_date)
        calendar=pd.date_range(observed[0],'2027-04-01',freq='B')
        result=split_membership(calendar,observed,protocol())
        result.insert(0,'instrument_id',symbol);result.insert(0,'dataset_id','fixture');frames.append(result)
    return pd.concat(frames,ignore_index=True)


class ModelingDatasetTests(unittest.TestCase):
    def test_every_feature_and_development_target_matches_independent_reference(self):
        source=prices();features,targets=sql_tables(source,protocol())
        result=reconcile(source,features,targets,protocol())
        self.assertTrue(result['all_checks_pass'])
        self.assertEqual(result['feature_cells_compared'],len(source)*12)

    def test_future_price_changes_cannot_change_earlier_features(self):
        source=prices();before,_=sql_tables(source,protocol())
        cutoff=source.session_date.sort_values().unique()[300]
        changed=source.copy();mask=(changed.instrument_id=='A')&(changed.session_date>cutoff)
        changed.loc[mask,'adjusted_close']*=np.linspace(1.3,2.1,int(mask.sum()))
        after,_=sql_tables(changed,protocol())
        selected=(before.origin_date<=cutoff)|(before.instrument_id=='B')
        pd.testing.assert_frame_equal(before.loc[selected],after.loc[selected],check_exact=True)

    def test_appending_observations_does_not_change_existing_features(self):
        source=prices();prefix=source[source.session_date<=source.session_date.unique()[320]]
        before,_=sql_tables(prefix,protocol());after,_=sql_tables(source,protocol())
        pd.testing.assert_frame_equal(before.reset_index(drop=True),after[after.origin_date<=prefix.session_date.max()].reset_index(drop=True),check_exact=True)

    def test_target_excludes_origin_return_and_spans_exactly_twenty_later_returns(self):
        source=prices();features,targets=sql_tables(source,protocol())
        a=source[source.instrument_id=='A'].reset_index(drop=True);offset=270
        returns=a.adjusted_close.to_numpy()[1:]/a.adjusted_close.to_numpy()[:-1]-1
        expected=252*np.sum(returns[offset:offset+20]**2)/20
        actual=targets[(targets.instrument_id=='A')&(targets.origin_date==a.session_date.iloc[offset])].iloc[0]
        self.assertAlmostEqual(actual.target_variance,expected,places=13)
        self.assertEqual(actual.observed_target_end,a.session_date.iloc[offset+20])
        alternate=252*np.sum(returns[offset-1:offset+19]**2)/20
        self.assertGreater(abs(actual.target_variance-alternate),1e-8)

    def test_2026_price_mutation_cannot_change_any_development_target(self):
        source=prices();_,before=sql_tables(source,protocol())
        source.loc[source.session_date>='2026-01-01','adjusted_close']*=3
        _,after=sql_tables(source,protocol())
        pd.testing.assert_frame_equal(before,after,check_exact=True)
        self.assertTrue((after.origin_date<'2026-01-01').all())

    def test_missing_session_price_is_not_filled_or_bridged(self):
        source=prices();a=source[source.instrument_id=='A'];missing=a.index[280]
        source.loc[missing,'adjusted_close']=np.nan
        features,targets=sql_tables(source,protocol());reconcile(source,features,targets,protocol())
        selected=features[features.instrument_id=='A'].reset_index(drop=True)
        self.assertTrue(selected.loc[280:281,'return_1'].isna().all())
        self.assertTrue(selected.loc[280:285,'return_5'].isna().all())
        self.assertFalse(selected.loc[280:531,'feature_ready'].any())

    def test_targets_and_metadata_are_not_predictors_and_final_test_values_stay_uncomputed(self):
        source=prices();features,raw=sql_tables(source,protocol())
        targets,development=assemble(features,raw,membership(source),protocol())
        self.assertEqual(set(features)-set(KEYS)-{'feature_ready'},set(FEATURE_COLUMNS))
        self.assertTrue(targets.loc[targets.origin_date>='2026-01-01','target_variance'].isna().all())
        self.assertTrue((development.origin_date<'2026-01-01').all())
        crossing=targets[(targets.origin_date<'2026-01-01')&(targets.target_end_date>='2026-01-01')]
        self.assertEqual(len(crossing),40)
        self.assertTrue(crossing.target_variance.isna().all())
        self.assertTrue((crossing.target_status=='crosses_test_boundary').all())

    def test_shifted_forward_endpoint_is_detected(self):
        source=prices();features,raw=sql_tables(source,protocol())
        raw.loc[raw.target_variance.notna(),'observed_target_end']+=pd.Timedelta(days=1)
        with self.assertRaises(AssertionError):assemble(features,raw,membership(source),protocol())

    def test_zero_returns_have_zero_risk_features_without_nonfinite_values(self):
        source=prices(constant=True);features,targets=sql_tables(source,protocol())
        ready=features[features.feature_ready]
        np.testing.assert_array_equal(ready[FEATURE_COLUMNS].to_numpy(),np.zeros((len(ready),12)))
        self.assertEqual(int(features.groupby('instrument_id').feature_ready.sum().iloc[0]),560-252)

    def test_duplicate_keys_are_rejected(self):
        source=prices();source=pd.concat([source,source.iloc[:1]],ignore_index=True)
        with self.assertRaisesRegex(ValueError,'Duplicate'):sql_tables(source,protocol())

    def test_corrupt_feature_values_fail_independent_reconciliation(self):
        source=prices();features,targets=sql_tables(source,protocol())
        features.loc[features.feature_ready,'variance_20']*=2
        with self.assertRaises(AssertionError):reconcile(source,features,targets,protocol())

    def test_parquet_and_database_corruption_are_detected_on_replay(self):
        frame=pd.DataFrame({'value':[1.,2.]})
        result={'modeling_dataset_id':'fixture','recipe':{'fixture':True}}
        frames={'features_daily':frame,'development_examples':frame.assign(train_eligible=[True,False],validation_eligible=[False,True],final_refit_eligible=[True,True])}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first=export(result,frames,root)
            self.assertEqual(first,export(result,frames,root))
            database=root/'fixture/modeling.duckdb';original=database.read_bytes();database.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'database hash'):export(result,frames,root)
            database.write_bytes(original)
            (root/'fixture/features_daily.parquet').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'export hash'):export(result,frames,root)


if __name__=='__main__':unittest.main()
