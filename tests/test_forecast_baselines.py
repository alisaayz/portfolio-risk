"""Synthetic forecast errors and price paths test timing and fair comparisons."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT
from scripts.build_modeling_dataset import sql_tables
from scripts.evaluate_baselines import (evaluation_origins,ewma_variance,generate_forecasts,
    load_modeling_artifacts,metric_tables,score_common_origins,select_ewma,validate_configuration)
from tests.test_modeling_dataset import prices,protocol


def configuration():return json.loads((ROOT/'config/forecast_baselines.json').read_text())


def score_fixture():
    days=pd.to_datetime(['2025-01-02','2025-01-30'])
    origins=pd.DataFrame({'instrument_id':['A','A'],'origin_date':days,
                         'target_end_date':pd.to_datetime(['2025-01-29','2025-02-27']),
                         'year':[2025,2025],'evaluation_mode':['primary','primary']})
    targets=origins[['instrument_id','origin_date']].assign(target_variance=[.09,.04])
    predictions=origins[['instrument_id','origin_date']].assign(method='fixture',predicted_variance=[.04,.09])
    return predictions,origins,targets


class ForecastBaselineTests(unittest.TestCase):
    def test_recursive_ewma_matches_known_weighted_values(self):
        values,counts=ewma_variance([1.,4.,9.],.5)
        np.testing.assert_array_equal(values,[1.,2.5,5.75])
        np.testing.assert_array_equal(counts,[1,2,3])

    def test_ewma_resets_on_missing_data_instead_of_carrying_state(self):
        values,counts=ewma_variance([1.,4.,np.nan,9.,1.],.5)
        np.testing.assert_allclose(values,[1.,2.5,np.nan,9.,5.],equal_nan=True)
        np.testing.assert_array_equal(counts,[1,2,0,1,2])
        for decay in [0,1,float('nan')]:
            with self.assertRaises(ValueError):ewma_variance([1.],decay)
        for values in [[-1.],[float('inf')]]:
            with self.assertRaises(ValueError):ewma_variance(values,.94)

    def test_future_changes_preserve_earlier_forecasts_and_other_instruments(self):
        source=prices();features,_=sql_tables(source,protocol())
        before=generate_forecasts(features,configuration(),protocol())
        cutoff=pd.Timestamp('2025-04-01');changed=features.copy()
        mask=(changed.instrument_id=='A')&(changed.origin_date>cutoff)
        changed.loc[mask,'return_1']*=4;changed.loc[mask,'variance_20']*=3
        after=generate_forecasts(changed,configuration(),protocol())
        selected=(before.origin_date<=cutoff)|(before.instrument_id=='B')
        pd.testing.assert_frame_equal(before.loc[selected],after.loc[selected],check_exact=True)
        self.assertTrue((before.origin_date<'2026-01-01').all())

    def test_common_origin_scoring_matches_hand_calculation(self):
        predictions,origins,targets=score_fixture()
        result=score_common_origins(predictions,origins,targets,['fixture'],1e-12)
        np.testing.assert_allclose(result.volatility_absolute_error_pp,[10.,10.],rtol=0,atol=1e-12)
        np.testing.assert_allclose(result.variance_qlike,[math.log(.04)+.09/.04,math.log(.09)+.04/.09],rtol=0,atol=1e-12)

    def test_missing_negative_and_nonfinite_predictions_block_comparison(self):
        predictions,origins,targets=score_fixture()
        for value in [-.01,np.nan,np.inf]:
            changed=predictions.copy();changed.loc[0,'predicted_variance']=value
            with self.assertRaisesRegex(ValueError,'Missing, nonfinite, or negative'):
                score_common_origins(changed,origins,targets,['fixture'],1e-12)
        with self.assertRaises(ValueError):score_common_origins(predictions.iloc[:1],origins,targets,['fixture'],1e-12)
        with self.assertRaises(ValueError):score_common_origins(predictions,origins,targets,['fixture','omitted_method'],1e-12)

    def test_zero_forecasts_use_explicit_qlike_floor_without_distorting_mae(self):
        predictions,origins,targets=score_fixture()
        predictions['predicted_variance']=0.;targets['target_variance']=0.
        result=score_common_origins(predictions,origins,targets,['fixture'],1e-12)
        self.assertTrue(result.prediction_floored.all())
        np.testing.assert_array_equal(result.volatility_absolute_error_pp,[0.,0.])
        np.testing.assert_allclose(result.variance_qlike,math.log(1e-12))

    def test_final_test_origins_and_boundary_crossing_targets_cannot_be_scored(self):
        predictions,origins,targets=score_fixture()
        for column in ['origin_date','target_end_date']:
            changed=origins.copy();changed.loc[0,column]=pd.Timestamp('2026-01-02')
            with self.assertRaisesRegex(ValueError,'Final-test scores are reserved'):
                score_common_origins(predictions,changed,targets,['fixture'],1e-12)

    def test_primary_grid_is_anchored_before_eligibility_filtering_and_does_not_overlap(self):
        days=pd.date_range('2025-01-02',periods=120,freq='B')
        frame=pd.DataFrame({'instrument_id':'A','origin_date':days[:100],
            'target_end_date':days[20:120],'feature_history_ready':True,'fold_2025_validation':[False]+[True]*79+[False]*20})
        selected=evaluation_origins(frame,2025,'primary',configuration())
        self.assertEqual(list(selected.origin_date),list(days[[20,40,60]]))
        self.assertTrue((selected.target_end_date.iloc[:-1].to_numpy()<=selected.origin_date.iloc[1:].to_numpy()).all())
        with self.assertRaises(ValueError):evaluation_origins(frame,2026,'primary',configuration())

    def test_equal_instrument_metric_is_not_a_pooled_row_average(self):
        errors=pd.DataFrame({'year':[2025]*3,'evaluation_mode':['primary']*3,'method':['fixture']*3,
            'instrument_id':['A','A','B'],'target_variance':[.1]*3,'volatility_absolute_error_pp':[0.,2.,10.],
            'variance_qlike':[0.,2.,10.],'prediction_floored':[False]*3})
        overall,_,_=metric_tables(errors,{'A':'stock','B':'bond_etf'})
        self.assertEqual(overall.volatility_mae_pp.iloc[0],5.5)
        self.assertNotEqual(overall.volatility_mae_pp.iloc[0],4.)

    def test_ewma_selection_uses_2025_primary_mae_with_fixed_tiebreak(self):
        rows=[]
        for year,mode,values in [(2023,'primary',[9.,8.,0.]),(2025,'daily',[3.,2.,0.]),(2025,'primary',[1.,1.,2.])]:
            for method,value in zip(['ewma_0.90','ewma_0.94','ewma_0.97'],values):
                rows.append({'year':year,'evaluation_mode':mode,'method':method,'volatility_mae_pp':value})
        self.assertEqual(select_ewma(pd.DataFrame(rows),configuration()),'ewma_0.90')

    def test_configuration_changes_cannot_silently_change_the_experiment(self):
        for key,value in [('development_years',[2025,2026]),('primary_stride_sessions',1),('qlike_prediction_floor',.01),('ewma_decays',[.99])]:
            changed=copy.deepcopy(configuration());changed[key]=value
            with self.assertRaises(ValueError):validate_configuration(changed)

    def test_modified_modeling_recipe_or_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            (path/'manifest.json').write_text(json.dumps({'modeling_dataset_id':'altered','recipe':{}}))
            with self.assertRaisesRegex(ValueError,'identity/recipe differs'):load_modeling_artifacts(path)


if __name__=='__main__':unittest.main()
