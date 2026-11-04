"""Independently reconcile every SQL return and historical RMS window with NumPy."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import numpy as np

from scripts.audit_market_data import ROOT, sha256


def verify(connection) -> dict:
    dataset=connection.execute('SELECT dataset_id FROM active_dataset').fetchall()[0][0]
    prices=connection.execute('SELECT instrument_id,session_date,adjusted_close FROM accepted_prices_daily ORDER BY instrument_id,session_date').df()
    sql=connection.execute('SELECT instrument_id,session_date,simple_return,trailing_20_ann_volatility FROM historical_risk_inputs ORDER BY instrument_id,session_date').df()
    results=[]
    for symbol in sorted(sql.instrument_id.unique()):
        source=prices[prices.instrument_id==symbol].set_index('session_date').adjusted_close
        computed=sql[sql.instrument_id==symbol].set_index('session_date')
        values=source.reindex(computed.index).to_numpy(dtype=float)
        expected=np.r_[np.nan,values[1:]/values[:-1]-1]
        rms=np.full(len(expected),np.nan)
        for offset in range(20,len(expected)):
            window=expected[offset-19:offset+1]
            if np.isfinite(window).all():rms[offset]=np.sqrt(252*np.sum(window**2)/20)
        np.testing.assert_allclose(computed.simple_return.to_numpy(),expected,rtol=0,atol=1e-12,equal_nan=True)
        np.testing.assert_allclose(computed.trailing_20_ann_volatility.to_numpy(),rms,rtol=0,atol=1e-12,equal_nan=True)
        results.append({'instrument':symbol,'sessions':len(values),'returns':int(np.isfinite(expected).sum()),'complete_20_return_windows':int(np.isfinite(rms).sum())})
    if not results or set(prices.instrument_id)!=set(sql.instrument_id):
        raise ValueError('Incomplete instrument coverage in historical SQL inputs')
    return {'dataset_id':dataset,'verification_script_sha256':sha256(Path(__file__)),'all_checks_pass':True,'instruments':results}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'data/warehouse/portfolio-risk.duckdb')
    args=parser.parse_args()
    with duckdb.connect(str(args.database),read_only=True) as connection:result=verify(connection)
    (args.database.parent/'reconciliation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
