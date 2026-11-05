import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import duckdb
import numpy as np
import pandas as pd

from scripts import market_catalog as catalog
from scripts import application_market_data as market
from scripts.audit_market_data import expected_sessions
from scripts.portfolio_baseline import analyze

HEADER = 'Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|NASDAQ Symbol|NextShares\n'
FOOTER = 'File Creation Time: 1104202621:33|||||||||||\n'


def directory_bytes():
    return (HEADER + 'Y|META|Meta Platforms Common Stock|Q|Q|N|100|N|N||META|N\n'
            + 'Y|VOO|Vanguard ETF units|P||Y|100|N|||VOO|N\n'
            + 'Y|BRK.B|Berkshire Class B Common Stock|N||N|100|N|||BRK.B|N\n'
            + 'Y|PREF$A|Example Preferred Stock|N||N|100|N|||PREF$A|N\n'
            + 'Y|TEST|Testing security|Q|Q|N|100|Y|N||TEST|N\n' + FOOTER).encode()


def build_catalog(folder):
    source = folder / 'source.txt'
    source.write_bytes(directory_bytes())
    store = folder / 'catalog'
    catalog.build(source, store)
    return store


def price_fixture():
    dates = expected_sessions('2020-01-01', '2020-01-10', 'XNAS').tz_localize('America/New_York')
    values = np.arange(len(dates), dtype=float) + 100
    return pd.DataFrame({'Open': values, 'High': values + 1, 'Low': values - 1,
                         'Close': values, 'Adj Close': values, 'Volume': 1000,
                         'Dividends': 0., 'Stock Splits': 0.}, index=dates)


def metadata():
    return {'symbol': 'META', 'currency': 'USD', 'instrumentType': 'EQUITY',
            'exchangeTimezoneName': 'America/New_York', 'exchangeName': 'NMS',
            'firstTradeDate': '2000-01-01 09:30:00-05:00'}


def ticker_mock():
    ticker = MagicMock()
    ticker.history.return_value = price_fixture()
    ticker.get_history_metadata.return_value = metadata()
    return ticker


class MarketCatalogTests(unittest.TestCase):
    def test_test_issues_excluded_and_non_stock_rows_preserved_but_not_eligible(self):
        frame, footer = catalog.parse_directory(directory_bytes())
        self.assertNotIn('TEST', set(frame.symbol))
        self.assertEqual(len(frame), 4)
        self.assertFalse(frame.set_index('symbol').loc['PREF$A', 'eligible_candidate'])
        self.assertTrue(frame.set_index('symbol').loc['VOO', 'eligible_candidate'])
        self.assertEqual(frame.set_index('symbol').loc['BRK.B', 'provider_symbol'], 'BRK-B')
        self.assertTrue(footer.startswith('File Creation Time:'))

    def test_missing_footer_duplicate_symbols_and_bad_flags_are_rejected(self):
        for raw in [directory_bytes().replace(FOOTER.encode(), b''),
                    directory_bytes().replace(FOOTER.encode(), b'Y|META|Duplicate|Q|Q|N|100|N|N||META|N\n' + FOOTER.encode()),
                    directory_bytes().replace(b'P||Y|100', b'P||X|100')]:
            with self.assertRaises(ValueError):
                catalog.parse_directory(raw)

    def test_search_ranks_exact_symbol_and_supports_company_names_and_class_shares(self):
        with tempfile.TemporaryDirectory() as directory:
            store = build_catalog(Path(directory))
            self.assertEqual(catalog.search('META', store)['matches'][0]['symbol'], 'META')
            self.assertEqual(catalog.search('Berkshire', store)['matches'][0]['symbol'], 'BRK.B')
            self.assertEqual(catalog.exact('brk.b', store)[1]['provider_symbol'], 'BRK-B')
            self.assertFalse(catalog.search("' OR 1=1 --", store)['matches'])
            with self.assertRaises(ValueError):
                catalog.exact('PREF$A', store)

    def test_replay_preserves_identity_and_detects_artifact_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            store = build_catalog(folder)
            before, path = catalog.load(store)
            again = catalog.build(folder / 'source.txt', store)
            self.assertEqual(before, again)
            path.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'hash'):
                catalog.load(store)


class ApplicationMarketDataTests(unittest.TestCase):
    def test_successful_capture_replays_without_another_provider_request(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); store = build_catalog(folder)
            with patch.object(market.yf, 'Ticker', return_value=ticker_mock()) as provider:
                first = market.acquire('META', '2020-01-10', folder / 'prices', store)
                again = market.acquire('META', '2020-01-10', folder / 'prices', store)
                self.assertEqual(first, again)
                self.assertEqual(provider.call_count, 1)
            self.assertFalse(first['independently_crosschecked'])
            self.assertEqual(first['rows'], len(price_fixture()))

    def test_wrong_symbol_currency_type_and_timezone_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = build_catalog(Path(directory)); recipe = market.request_recipe('META', '2020-01-10', store)
            for key, value in [('symbol', 'OTHER'), ('currency', 'CAD'),
                                ('instrumentType', 'OPTION'), ('exchangeTimezoneName', 'Europe/London')]:
                meta = metadata(); meta[key] = value
                with self.assertRaises(ValueError):
                    market.check_download(price_fixture(), meta, recipe)

    def test_missing_sessions_and_adjustment_deviations_cannot_enter_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            store = build_catalog(Path(directory)); recipe = market.request_recipe('META', '2020-01-10', store)
            with self.assertRaises(ValueError):
                market.check_download(price_fixture().iloc[1:], metadata(), recipe)
            frame = price_fixture(); frame.iloc[3, frame.columns.get_loc('Adj Close')] *= 1.05
            with self.assertRaisesRegex(ValueError, 'Adjusted-price'):
                market.check_download(frame, metadata(), recipe)

    def test_new_listing_coverage_uses_provider_first_trade_date_explicitly(self):
        with tempfile.TemporaryDirectory() as directory:
            store = build_catalog(Path(directory)); recipe = market.request_recipe('META', '2020-01-10', store)
            frame = price_fixture().iloc[2:]; meta = metadata()
            meta['firstTradeDate'] = str(frame.index[0])
            audit = market.check_download(frame, meta, recipe)
            self.assertEqual(audit['first_session'], '2020-01-06')
            self.assertEqual(audit['missing_sessions'], [])

    def test_real_price_moves_remain_warnings_without_silently_repairing_prices(self):
        with tempfile.TemporaryDirectory() as directory:
            store = build_catalog(Path(directory)); recipe = market.request_recipe('META', '2020-01-10', store)
            frame = price_fixture()
            frame.loc[frame.index[3]:, ['Open', 'High', 'Low', 'Close', 'Adj Close']] *= 1.4
            before = frame.copy(deep=True)
            audit = market.check_download(frame, metadata(), recipe)
            self.assertTrue(audit['extreme_adjusted_move_dates'])
            pd.testing.assert_frame_equal(frame, before)

    def test_failed_capture_is_preserved_and_not_published_as_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); store = build_catalog(folder); provider = ticker_mock()
            provider.get_history_metadata.return_value = {**metadata(), 'currency': 'CAD'}
            with patch.object(market.yf, 'Ticker', return_value=provider):
                with self.assertRaises(ValueError):
                    market.acquire('META', '2020-01-10', folder / 'prices', store)
            self.assertEqual(len(list((folder / 'prices/failed').glob('*/failure.json'))), 1)
            with self.assertRaises(FileNotFoundError):
                market.read('META', '2020-01-10', folder / 'prices', store)

    def test_cached_evidence_tampering_is_rejected_without_refetching(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); store = build_catalog(folder)
            with patch.object(market.yf, 'Ticker', return_value=ticker_mock()):
                market.acquire('META', '2020-01-10', folder / 'prices', store)
            path = next((folder / 'prices').glob('*/history.csv'))
            path.write_bytes(path.read_bytes() + b'\n')
            with self.assertRaisesRegex(ValueError, 'hash'):
                market.read('META', '2020-01-10', folder / 'prices', store)

    def test_new_stock_composition_is_separate_and_preserves_base_database(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); store = build_catalog(folder); prices_store = folder / 'prices'
            with patch.object(market.yf, 'Ticker', return_value=ticker_mock()):
                manifest = market.acquire('META', '2020-01-10', prices_store, store)
            p, r, c = market.as_tables('A', manifest, price_fixture(), 'base')
            database = folder / 'base.duckdb'
            with duckdb.connect(str(database)) as connection:
                for name, frame in {'accepted_prices_daily': p, 'returns_daily': r,
                                     'expected_sessions': c, 'active_dataset': pd.DataFrame({'dataset_id': ['base']})}.items():
                    connection.register('records', frame)
                    connection.execute(f'CREATE TABLE {name} AS SELECT * FROM records').fetchall()
                    connection.unregister('records')
            before = hashlib.sha256(database.read_bytes()).hexdigest()
            connection, sources = market.application_connection(database, ['A', 'META'], prices_store, store)
            config = {'schema_version': 1, 'is_demo': True, 'as_of_date': '2020-01-09', 'report_currency': 'USD',
                      'risk_window_sessions': 2, 'convention': 'fixed_weights_daily_rebalanced',
                      'portfolios': [{'id': 'fixture', 'name': 'Fixture', 'input_type': 'weights',
                                      'positions': [{'instrument_id': 'A', 'weight': .5}, {'instrument_id': 'META', 'weight': .5}]}]}
            with connection:
                result, _ = analyze(connection, config)
            self.assertNotEqual(result['recipe']['dataset_id'], 'base')
            self.assertTrue(result['reconciliations_passed'])
            self.assertEqual(next(s for s in sources if s['symbol'] == 'META')['policy'], 'AP-001')
            self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
