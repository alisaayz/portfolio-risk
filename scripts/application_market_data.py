"""On-demand AP-001 price evidence, separate from the frozen research warehouse."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import tempfile

import duckdb
import pandas as pd
import yfinance as yf

from scripts.audit_market_data import (
    ROOT, HISTORY_SETTINGS, audit_frame, expected_sessions, materialize_metadata, sha256,
)
from scripts import market_catalog

STORE = ROOT / 'data/application_market'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def request_recipe(symbol, end, catalog_store=market_catalog.STORE):
    catalog_id, record = market_catalog.exact(symbol, catalog_store)
    policy_path = ROOT / 'config/application_source_policy.json'
    recipe = {'application_source_policy': 'AP-001', 'catalog_id': catalog_id,
              'policy_sha256': sha256(policy_path),
              'instrument': record, 'start_inclusive': '2020-01-01',
              'end_exclusive': str(pd.Timestamp(end).date()), 'settings': HISTORY_SETTINGS,
              'yfinance_version': version('yfinance'), 'audit_code_sha256': sha256(ROOT / 'scripts/audit_market_data.py'),
              'loader_code_sha256': sha256(Path(__file__))}
    return recipe


def check_download(frame, metadata, recipe):
    instrument = recipe['instrument']
    expected_type = 'ETF' if instrument['directory_type'] == 'ETF' else 'EQUITY'
    if metadata.get('symbol') != instrument['provider_symbol']:
        raise ValueError('Provider returned a different symbol identity')
    if metadata.get('currency') != 'USD' or metadata.get('instrumentType') != expected_type:
        raise ValueError('Provider currency/instrument type does not match the requested US stock/ETF')
    if metadata.get('exchangeTimezoneName') != 'America/New_York':
        raise ValueError('Unsupported exchange timezone')
    if frame.empty or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError('Missing daily history or exchange-timezone information')
    first_trade = metadata.get('firstTradeDate')
    if first_trade is None:
        raise ValueError('Provider first-trade metadata is needed to check requested coverage')
    start = max(pd.Timestamp(recipe['start_inclusive']), pd.Timestamp(first_trade).tz_localize(None).normalize())
    expected = expected_sessions(str(start.date()), recipe['end_exclusive'], instrument['calendar'])
    if expected.empty:
        raise ValueError('No completed sessions available before the saved snapshot cutoff')
    audit = audit_frame(frame, expected)
    if audit['errors']:
        raise ValueError('Structural audit failed: ' + '; '.join(audit['errors']))
    if audit.get('factor_deviation_over_5bp_dates'):
        raise ValueError('Adjusted-price behavior requires review before analytical use')
    # Large real price moves and zero volumes remain visible warnings, not repairs.
    return audit


def read(symbol, end, store=STORE, catalog_store=market_catalog.STORE):
    recipe = request_recipe(symbol, end, catalog_store)
    folder = store / digest(recipe)
    if not folder.is_dir():
        raise FileNotFoundError('Price history has not been loaded and audited for this symbol/cutoff')
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest['recipe'] != recipe or manifest['status'] != 'structurally_audited':
        raise ValueError('On-demand source recipe/status differs')
    if set(manifest['outputs']) != {'history.csv', 'metadata.json', 'audit.json'}:
        raise ValueError('Incomplete on-demand evidence inventory')
    for name, recorded in manifest['outputs'].items():
        if sha256(folder / name) != recorded:
            raise ValueError('On-demand evidence hash mismatch')
    if digest({'recipe': recipe, 'outputs': manifest['outputs']}) != manifest['cache_id']:
        raise ValueError('On-demand evidence identity mismatch')
    frame = pd.read_csv(folder / 'history.csv', index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert('America/New_York')
    metadata = json.loads((folder / 'metadata.json').read_text())
    audit = check_download(frame, metadata, recipe)
    saved = json.loads((folder / 'audit.json').read_text())
    if audit != saved:
        raise ValueError('Replayed structural audit differs from saved evidence')
    return manifest, frame


def acquire(symbol, end, store=STORE, catalog_store=market_catalog.STORE):
    try:
        manifest, _ = read(symbol, end, store, catalog_store)
        return manifest
    except FileNotFoundError:
        pass
    recipe = request_recipe(symbol, end, catalog_store)
    key = digest(recipe)
    store.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=store))
    try:
        yf.set_tz_cache_location(str(ROOT / 'data/cache/yfinance'))
        yf.config.debug.hide_exceptions = False
        ticker = yf.Ticker(recipe['instrument']['provider_symbol'])
        frame = ticker.history(start=recipe['start_inclusive'], end=recipe['end_exclusive'], **HISTORY_SETTINGS)
        frame.to_csv(staging / 'history.csv', index_label='provider_timestamp')
        metadata = materialize_metadata(ticker.get_history_metadata(repair=False))
        (staging / 'metadata.json').write_text(json.dumps(metadata, indent=2, default=str, allow_nan=False) + '\n')
        # Re-read preserved output, so audit replay sees the same stored precision.
        saved = pd.read_csv(staging / 'history.csv', index_col=0)
        saved.index = pd.to_datetime(saved.index, utc=True).tz_convert('America/New_York')
        audit = check_download(saved, metadata, recipe)
        (staging / 'audit.json').write_text(json.dumps(audit, indent=2, allow_nan=False) + '\n')
        outputs = {name: sha256(staging / name) for name in ['history.csv', 'metadata.json', 'audit.json']}
        manifest = {'cache_id': digest({'recipe': recipe, 'outputs': outputs}),
                    'recipe': recipe, 'status': 'structurally_audited', 'outputs': outputs,
                    'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                    'independently_crosschecked': False,
                    'coverage_start': audit['first_session'], 'coverage_end': audit['last_session'],
                    'rows': len(saved), 'warnings': audit['warnings'],
                    'coverage_basis': 'Provider first-trade metadata and complete configured exchange sessions'}
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n')
        destination = store / key
        if destination.exists():
            raise ValueError('An existing capture must not be overwritten')
        staging.rename(destination)
        read(symbol, end, store, catalog_store)
        return manifest
    except Exception as error:
        if staging.exists():
            (staging / 'failure.json').write_text(json.dumps({'recipe': recipe, 'status': 'failed',
                'exception_type': type(error).__name__, 'message': str(error),
                'recorded_at_utc': datetime.now(timezone.utc).isoformat()}, indent=2) + '\n')
            failed = store / 'failed'
            failed.mkdir(exist_ok=True)
            staging.rename(failed / staging.name.replace('.pending-', 'capture-'))
        raise


def as_tables(symbol, manifest, frame, dataset):
    dates = frame.index.tz_convert('America/New_York').tz_localize(None).normalize()
    prices = pd.DataFrame({'instrument_id': symbol, 'session_date': dates,
                           'close': frame.Close.to_numpy(), 'adjusted_close': frame['Adj Close'].to_numpy()})
    prices = prices.sort_values('session_date').reset_index(drop=True)
    returns = prices[['instrument_id', 'session_date']].copy()
    returns['dataset_id'] = dataset
    returns['simple_return'] = prices.adjusted_close.pct_change(fill_method=None)
    calendar = returns[['dataset_id', 'instrument_id', 'session_date']].copy()
    return prices, returns, calendar


def application_connection(base_database, symbols, store=STORE, catalog_store=market_catalog.STORE):
    """Use the base read-only DB, or a separate in-memory analytical composition."""
    base = duckdb.connect(str(base_database), read_only=True)
    try:
        present = {row[0] for row in base.execute('SELECT DISTINCT instrument_id FROM accepted_prices_daily').fetchall()}
        missing = sorted(set(symbols) - present)
        base_dataset = base.execute('SELECT dataset_id FROM active_dataset').fetchall()[0][0]
        end = str((pd.Timestamp(base.execute('SELECT min(last_date) FROM (SELECT max(session_date) last_date FROM accepted_prices_daily GROUP BY instrument_id)').fetchall()[0][0]) + pd.Timedelta(days=1)).date())
        sources = [{'symbol': symbol, 'policy': 'DS-002', 'independently_crosschecked': True}
                   for symbol in sorted(set(symbols) & present)]
        if not missing:
            return base, sources
        additions = [(symbol, *read(symbol, end, store, catalog_store)) for symbol in missing]
        recipe = {'application_source_policy': 'AP-001', 'base_dataset_id': base_dataset,
                  'additional_captures': {symbol: manifest['cache_id'] for symbol, manifest, _ in additions},
                  'composition_code_sha256': sha256(Path(__file__))}
        dataset = digest(recipe)
        price = base.execute('SELECT instrument_id,session_date,close,adjusted_close FROM accepted_prices_daily').df()
        returns = base.execute('SELECT * FROM returns_daily').df()
        calendar = base.execute('SELECT e.* FROM expected_sessions e JOIN active_dataset a USING(dataset_id)').df()
        returns = returns[['dataset_id', 'instrument_id', 'session_date', 'simple_return']]
        calendar = calendar[['dataset_id', 'instrument_id', 'session_date']]
        returns['dataset_id'] = dataset
        calendar['dataset_id'] = dataset
        price_frames, return_frames, calendar_frames = [price], [returns], [calendar]
        for symbol, manifest, frame in additions:
            p, r, c = as_tables(symbol, manifest, frame, dataset)
            price_frames.append(p); return_frames.append(r); calendar_frames.append(c)
            sources.append({'symbol': symbol, 'policy': 'AP-001', 'cache_id': manifest['cache_id'],
                            'independently_crosschecked': False, 'warnings': manifest['warnings'],
                            'coverage_start': manifest['coverage_start'], 'coverage_end': manifest['coverage_end']})
        connection = duckdb.connect()
        tables = {'accepted_prices_daily': pd.concat(price_frames, ignore_index=True),
                  'returns_daily': pd.concat(return_frames, ignore_index=True),
                  'expected_sessions': pd.concat(calendar_frames, ignore_index=True),
                  'active_dataset': pd.DataFrame({'dataset_id': [dataset]})}
        try:
            for name, frame in tables.items():
                connection.register('records', frame)
                connection.execute(f'CREATE TABLE {name} AS SELECT * FROM records').fetchall()
                connection.unregister('records')
        except Exception:
            connection.close()
            raise
        return connection, sources
    except Exception:
        base.close()
        raise
    finally:
        if 'missing' in locals() and missing:
            base.close()
