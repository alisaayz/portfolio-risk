"""Synthetic regression fixtures; the published report uses real market history."""
import copy
import unittest

import duckdb
import numpy as np
import pandas as pd

from scripts.portfolio_baseline import (analyze, drawdown_summary, prepare_panel,
    publication_directory, resolve_weights, risk_decomposition, serializable, validate_configuration)


def configuration():
    return {"schema_version":1,"is_demo":True,"as_of_date":"2026-01-05","report_currency":"USD",
        "risk_window_sessions":2,"convention":"fixed_weights_daily_rebalanced",
        "portfolios":[{"id":"demo","name":"Synthetic regression fixture","input_type":"weights",
            "positions":[{"instrument_id":"A","weight":.5},{"instrument_id":"B","weight":.5}]}]}


def panels():
    dates=pd.date_range('2026-01-01',periods=5)
    prices=[];returns=[];calendar=[]
    for symbol,base in [('A',100.),('B',200.)]:
        for i,day in enumerate(dates):
            prices.append({'instrument_id':symbol,'session_date':day,'close':base+i,'adjusted_close':(base+i)/10 if symbol=='A' else base+i})
            returns.append({'dataset_id':'fixture','instrument_id':symbol,'session_date':day,'simple_return':None if not i else (base+i)/(base+i-1)-1})
            calendar.append({'dataset_id':'fixture','instrument_id':symbol,'session_date':day})
    return pd.DataFrame(prices),pd.DataFrame(returns),pd.DataFrame(calendar)


def database():
    con=duckdb.connect()
    prices,returns,calendar=panels()
    frames={'accepted_prices_daily':prices,'returns_daily':returns,'expected_sessions':calendar,
            'active_dataset':pd.DataFrame({'dataset_id':['fixture']})}
    for name,frame in frames.items():
        con.register('records',frame)
        con.execute(f'CREATE TABLE {name} AS SELECT * FROM records').fetchall()
        con.unregister('records')
    return con


class PortfolioBaselineTests(unittest.TestCase):
    def test_invalid_inputs_fail_instead_of_being_rescaled_or_silently_dropped(self):
        bad=[]
        for value in [-.1,float('nan'),float('inf'),0,True]:
            config=configuration();config['portfolios'][0]['positions'][0]['weight']=value;bad.append(config)
        config=configuration();config['portfolios'][0]['positions'][0]['weight']=.4;bad.append(config)
        config=configuration();config['report_currency']='CAD';bad.append(config)
        config=configuration();config['portfolios'][0]['positions'][1]['instrument_id']='A';bad.append(config)
        for config in bad:
            with self.subTest(config=config),self.assertRaises(ValueError):validate_configuration(config)

    def test_covariance_volatility_matches_return_series_and_euler_sum(self):
        values=np.array([[.01,.02],[-.02,.01],[.005,-.01],[.015,.03]])
        weights=np.array([.4,.6]);covariance=np.cov(values,rowvar=False,ddof=1)*252
        volatility,contributions,shares=risk_decomposition(covariance,weights)
        self.assertAlmostEqual(volatility,np.std(values@weights,ddof=1)*np.sqrt(252))
        self.assertAlmostEqual(contributions.sum(),volatility)
        self.assertAlmostEqual(shares.sum(),1)

    def test_hedging_contributions_are_not_clipped_and_zero_risk_shares_are_undefined(self):
        covariance=np.array([[.04,-.015],[-.015,.01]])
        _,_,shares=risk_decomposition(covariance,np.array([.1,.9]))
        self.assertLess(shares[0],0);self.assertGreater(shares[1],1);self.assertAlmostEqual(shares.sum(),1)
        volatility,contributions,shares=risk_decomposition(np.zeros((2,2)),np.array([.5,.5]))
        self.assertEqual(volatility,0);np.testing.assert_array_equal(contributions,[0,0])
        self.assertEqual(serializable(shares),[None,None])

    def test_drawdown_includes_initial_capital_before_the_first_loss(self):
        wealth=pd.Series([1,.5,.75],index=pd.date_range('2026-01-01',periods=3))
        result=drawdown_summary(wealth)
        self.assertEqual(result['maximum_drawdown'],-.5)
        self.assertEqual(result['peak_date'],'2026-01-01');self.assertIsNone(result['recovery_date'])

    def test_drawdown_identifies_peak_trough_and_recovery(self):
        wealth=pd.Series([1,1.1,.88,.99,1.1],index=pd.date_range('2026-01-01',periods=5))
        result=drawdown_summary(wealth)
        self.assertAlmostEqual(result['maximum_drawdown'],-.2)
        self.assertEqual((result['peak_date'],result['trough_date'],result['recovery_date']),('2026-01-02','2026-01-03','2026-01-05'))

    def test_as_of_filter_excludes_later_observations(self):
        prices,returns,calendar=panels()
        prices.loc[prices.session_date==pd.Timestamp('2026-01-05'),'adjusted_close']=9999
        adjusted,_,panel,_,_=prepare_panel(prices,returns,calendar,['A','B'],pd.Timestamp('2026-01-04'))
        self.assertEqual(adjusted.index[-1],pd.Timestamp('2026-01-04'))
        self.assertEqual(len(panel),3);self.assertLess(adjusted.to_numpy().max(),9999)

    def test_missing_prices_and_unsupported_instruments_fail(self):
        prices,returns,calendar=panels()
        missing=prices[~((prices.instrument_id=='B')&(prices.session_date==pd.Timestamp('2026-01-03')))]
        with self.assertRaisesRegex(ValueError,'Incomplete common price history'):
            prepare_panel(missing,returns,calendar,['A','B'],pd.Timestamp('2026-01-05'))
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            prepare_panel(prices,returns,calendar,['A','C'],pd.Timestamp('2026-01-05'))

    def test_quantity_valuation_uses_close_and_rejects_historical_share_reconstruction(self):
        config=configuration();portfolio=config['portfolios'][0];portfolio['input_type']='quantities'
        portfolio['positions']=[{'instrument_id':'A','quantity':1},{'instrument_id':'B','quantity':2}]
        with database() as con:
            result,_=analyze(con,config)
        self.assertAlmostEqual(result['scenarios'][0]['weights'][0],104/(104+2*204))
        close=pd.Series({'A':104.,'B':204.},name=pd.Timestamp('2026-01-05'))
        with self.assertRaisesRegex(ValueError,'latest available common close'):
            resolve_weights(portfolio,['A','B'],close,pd.Timestamp('2026-01-04'),pd.Timestamp('2026-01-05'))

    def test_personal_reports_cannot_use_the_demo_publication_route(self):
        config=configuration();config['is_demo']=False
        self.assertIsNone(publication_directory(config,False))
        with self.assertRaisesRegex(ValueError,'Personal reports'):
            publication_directory(config,True)

    def test_insufficient_history_does_not_shrink_the_declared_window(self):
        config=configuration();config['risk_window_sessions']=252
        with database() as con,self.assertRaisesRegex(ValueError,'shorter than the declared risk window'):
            analyze(con,config)


if __name__=='__main__':unittest.main()
