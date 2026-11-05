"""Generate deterministic fictional prices for the standalone application demo."""

import duckdb
import numpy as np
import pandas as pd


DEMO_ID = 'synthetic-demo-v1'
SYMBOLS = ('DEMOA', 'DEMOB', 'DEMOC')


def build_demo(database):
    dates = pd.bdate_range('2024-01-02', periods=320)
    step = np.arange(len(dates) - 1)
    common = np.sin(step * .21)
    prices, returns, sessions = [], [], []
    for index, symbol in enumerate(SYMBOLS):
        daily = .0003 + (.014 - index * .005) * common + .003 * np.cos(step * (.13 + index * .04))
        closes = 100 * np.r_[1, np.cumprod(1 + daily)]
        prices.extend(zip([symbol] * len(dates), dates, closes, closes))
        returns.extend((DEMO_ID, symbol, day, value) for day, value in
                       zip(dates, np.r_[np.nan, closes[1:] / closes[:-1] - 1]))
        sessions.extend((DEMO_ID, symbol, day) for day in dates)
    tables = {
        'active_dataset': pd.DataFrame({'dataset_id': [DEMO_ID]}),
        'accepted_prices_daily': pd.DataFrame(prices, columns=['instrument_id', 'session_date', 'close', 'adjusted_close']),
        'returns_daily': pd.DataFrame(returns, columns=['dataset_id', 'instrument_id', 'session_date', 'simple_return']),
        'expected_sessions': pd.DataFrame(sessions, columns=['dataset_id', 'instrument_id', 'session_date']),
    }
    with duckdb.connect(str(database)) as connection:
        for name, frame in tables.items():
            connection.register('demo_frame', frame)
            connection.execute(f'CREATE TABLE {name} AS SELECT * FROM demo_frame')
            connection.unregister('demo_frame')
