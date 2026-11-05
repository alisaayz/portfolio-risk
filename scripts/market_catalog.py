"""Version and search Nasdaq's current US listing directory; no price acceptance."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile

import duckdb
import pandas as pd
import requests

from scripts.audit_market_data import ROOT, sha256

URL = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
STORE = ROOT / 'data/symbol_directory'
REQUIRED = {'Nasdaq Traded', 'Symbol', 'Security Name', 'Listing Exchange', 'ETF', 'Test Issue'}
NON_STOCK = re.compile(r'\b(warrants?|rights|preferred|debentures|notes|units)\b', re.I)


def parse_directory(raw):
    rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter='|'))
    if not rows or not REQUIRED.issubset(rows[0]):
        raise ValueError('Directory schema differs from expected fields')
    if not rows[-1]['Nasdaq Traded'].startswith('File Creation Time:'):
        raise ValueError('Directory creation-time footer is missing')
    footer = rows.pop()['Nasdaq Traded']
    records = []
    seen = set()
    for row in rows:
        if row['Nasdaq Traded'] != 'Y' or row['Test Issue'] != 'N':
            continue
        symbol = row['Symbol'].strip()
        name = row['Security Name'].strip()
        if not re.fullmatch(r'[A-Z][A-Z0-9.$-]{0,15}', symbol) or symbol in seen or not name:
            raise ValueError('Invalid or duplicate active listing identity')
        seen.add(symbol)
        if row['ETF'] not in {'Y', 'N'}:
            raise ValueError('Unknown ETF classification')
        is_etf = row['ETF'] == 'Y'
        # The directory is broader than common stocks/ETFs. Keep all records, but
        # do not silently offer identifiable preferreds/warrants/rights/notes/units.
        candidate = (is_etf or not NON_STOCK.search(name)) and bool(re.fullmatch(r'[A-Z][A-Z0-9.-]{0,15}', symbol))
        records.append({'symbol': symbol, 'security_name': name,
                        'listing_exchange': row['Listing Exchange'],
                        'directory_type': 'ETF' if is_etf else 'equity_candidate',
                        'eligible_candidate': bool(candidate),
                        'eligibility_note': '' if candidate else 'Outside common-stock/ETF scope',
                        'financial_status': row.get('Financial Status', '').strip(),
                        'provider_symbol': symbol.replace('.', '-'),
                        'calendar': 'XNAS' if row['Listing Exchange'] == 'Q' else 'XNYS'})
    if not records:
        raise ValueError('Directory has no active non-test listings')
    return pd.DataFrame(records).sort_values('symbol').reset_index(drop=True), footer


def build(source, store=STORE):
    raw = source.read_bytes()
    frame, footer = parse_directory(raw)
    recipe = {'catalog_protocol_id': 'US-001', 'source_url': URL,
              'raw_sha256': hashlib.sha256(raw).hexdigest(),
              'creation_time_footer': footer, 'parser_sha256': sha256(Path(__file__))}
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    store.mkdir(parents=True, exist_ok=True)
    destination = store / identity
    staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=store))
    try:
        (staging / 'nasdaqtraded.txt').write_bytes(raw)
        with duckdb.connect() as connection:
            connection.register('records', frame)
            connection.sql('SELECT * FROM records ORDER BY symbol').write_parquet(str(staging / 'catalog.parquet'))
        manifest = {'catalog_id': identity, 'recipe': recipe, 'rows': len(frame),
                    'etf_flagged': int((frame.directory_type == 'ETF').sum()),
                    'eligible_candidates': int(frame.eligible_candidate.sum()),
                    'outputs': {name: sha256(staging / name) for name in ['nasdaqtraded.txt', 'catalog.parquet']}}
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        if destination.exists():
            if json.loads((destination / 'manifest.json').read_text()) != manifest:
                raise ValueError('Repeated catalog build differs')
            for name, digest in manifest['outputs'].items():
                if sha256(destination / name) != digest:
                    raise ValueError('Saved catalog artifact differs')
            shutil.rmtree(staging)
        else:
            staging.rename(destination)
        pointer = store / '.current.pending'
        pointer.write_text(json.dumps({'catalog_id': identity}) + '\n')
        pointer.replace(store / 'current.json')
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return manifest


def load(store=STORE):
    identity = json.loads((store / 'current.json').read_text())['catalog_id']
    if not re.fullmatch('[a-f0-9]{64}', identity):
        raise ValueError('Invalid catalog identity')
    folder = store / identity
    manifest = json.loads((folder / 'manifest.json').read_text())
    if hashlib.sha256(json.dumps(manifest['recipe'], sort_keys=True).encode()).hexdigest() != identity:
        raise ValueError('Catalog identity/recipe mismatch')
    if set(manifest['outputs']) != {'nasdaqtraded.txt', 'catalog.parquet'}:
        raise ValueError('Incomplete catalog inventory')
    for name, digest in manifest['outputs'].items():
        if name not in {'nasdaqtraded.txt', 'catalog.parquet'} or sha256(folder / name) != digest:
            raise ValueError('Catalog artifact hash mismatch')
    return manifest, folder / 'catalog.parquet'


def search(query, store=STORE, limit=25):
    query = str(query).strip()[:100]
    manifest, path = load(store)
    if not query:
        return {'catalog_id': manifest['catalog_id'], 'matches': []}
    with duckdb.connect() as connection:
        frame = connection.execute('''SELECT * FROM read_parquet(?)
            WHERE eligible_candidate AND (starts_with(symbol,upper(?)) OR contains(lower(security_name),lower(?)))
            ORDER BY CASE WHEN symbol=upper(?) THEN 0 WHEN starts_with(symbol,upper(?)) THEN 1 ELSE 2 END,symbol
            LIMIT ?''', [str(path), query, query, query, query, int(limit)]).df()
    return {'catalog_id': manifest['catalog_id'], 'matches': frame.to_dict('records')}


def exact(symbol, store=STORE):
    symbol = str(symbol).upper().strip()
    result = search(symbol, store)
    matches = [row for row in result['matches'] if row['symbol'] == symbol]
    if len(matches) != 1:
        raise ValueError('Choose a current common-stock/ETF candidate from the US directory')
    return result['catalog_id'], matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, help='Replay an existing saved directory without a network request')
    args = parser.parse_args()
    source = args.source
    if source is None:
        response = requests.get(URL, timeout=25)
        response.raise_for_status()
        capture = STORE / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        capture.mkdir(parents=True)
        source = capture / 'nasdaqtraded.txt'
        source.write_bytes(response.content)
        (capture / 'retrieval.json').write_text(json.dumps({'url': URL, 'status': response.status_code,
            'retrieved_at_utc': datetime.now(timezone.utc).isoformat(), 'sha256': sha256(source)}, indent=2) + '\n')
    print(json.dumps(build(source), indent=2))


if __name__ == '__main__':
    main()
