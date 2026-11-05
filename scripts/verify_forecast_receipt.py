"""Verify a FreeTSA RFC 3161 receipt against an exact PF-002 forecast record."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from scripts.audit_market_data import ROOT, sha256
from scripts.record_prospective_forecast import PROTOCOL, open_window


CERTIFICATE_HASHES = {
    'cacert.pem': '2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438',
    'tsa.crt': '8bfb0305bb64e2571ca507552ef3245cb1c2fee8728e0ff8689225081ea13467',
}


def openssl(binary, *args):
    try:
        result = subprocess.run([binary, 'ts', *args], check=True, capture_output=True, text=True,
                                env={**os.environ, 'LC_ALL': 'C'}, timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise ValueError(f'Timestamp check failed: {detail or error}') from None
    return result.stdout


def signed_timestamp(record, query, receipt, trust, binary='openssl'):
    """Verify the imprint and original nonce, then extract the signed UTC time."""
    with TemporaryDirectory(prefix='riskitnot-tsa-') as folder:
        stage = Path(folder)
        for name, expected in CERTIFICATE_HASHES.items():
            contents = (trust / name).read_bytes()
            if hashlib.sha256(contents).hexdigest() != expected:
                raise ValueError(f'Timestamp trust file fingerprint differs: {name}')
            (stage / name).write_bytes(contents)
        files = {'record': record, 'query': query, 'receipt': receipt}
        for name, data in files.items():
            (stage / name).write_bytes(data)
        empty_store = stage / 'empty-ca-directory'
        empty_store.mkdir()
        response = openssl(binary, '-reply', '-in', stage / 'receipt', '-text')
        algorithm = re.search(r'^Hash Algorithm: (.+)$', response, re.MULTILINE)
        stamp = re.search(r'^Time stamp: (.+) GMT$', response, re.MULTILINE)
        nonce = re.search(r'^Nonce: 0x[0-9a-fA-F]+$', response, re.MULTILINE)
        if not (algorithm and algorithm[1] == 'sha256' and stamp and nonce):
            raise ValueError('Expected a signed SHA-256 UTC timestamp with a nonce')
        value = stamp[1]
        time_format = '%b %d %H:%M:%S.%f %Y' if '.' in value else '%b %d %H:%M:%S %Y'
        signed_at = datetime.strptime(value, time_format).replace(tzinfo=timezone.utc)
        common = ['-in', stage / 'receipt', '-CAfile', stage / 'cacert.pem',
                  '-CApath', empty_store, '-untrusted', stage / 'tsa.crt']
        openssl(binary, '-verify', '-data', stage / 'record', *common)
        openssl(binary, '-verify', '-queryfile', stage / 'query', *common)
    return signed_at


def utc_value(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('Forecast timestamps must include a UTC offset')
    return result.astimezone(timezone.utc)


def check_forecast(record, signed_at, spec, baseline):
    origin, target, close, deadline = open_window(signed_at, spec)
    recorded_at = utc_value(record['recorded_at_utc'])
    capture_start = utc_value(record['capture_started_at_utc'])
    capture_end = utc_value(record['capture_finished_at_utc'])
    if (record['protocol'] != spec['protocol'] or record['protocol_sha256'] != sha256(PROTOCOL)
            or record['training_sha256'] != spec['training_sample_sha256']):
        raise ValueError('Forecast differs from the frozen protocol or training input')
    if (record['origin'] != str(origin.date()) or record['target_end'] != str(target.date())
            or utc_value(record['deadline_utc']) != deadline
            or not close <= capture_start <= capture_end <= recorded_at < deadline
            or signed_at < recorded_at.replace(microsecond=0)):
        raise ValueError('Receipt and forecast timestamps must match the same scheduled window')
    methods = {baseline[key] for key in ('trained_method', 'ewma_method', 'trailing_method')}
    portfolios = {row['id'] for row in spec['portfolio_weights']}
    rows = record['annualized_variance']
    if (len(rows) != len(portfolios) or {row['portfolio_id'] for row in rows} != portfolios
            or any(set(row) != methods | {'portfolio_id'} for row in rows)
            or any(type(row[method]) not in (int, float) or not math.isfinite(row[method])
                   or row[method] < 0 for row in rows for method in methods)):
        raise ValueError('Expected finite nonnegative predictions for all frozen portfolios and methods')
    return str(origin.date())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--query', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--trust-dir', type=Path, required=True)
    parser.add_argument('--openssl', default='openssl')
    args = parser.parse_args()
    try:
        record, query, receipt = (path.read_bytes() for path in (args.record, args.query, args.receipt))
        timestamp = signed_timestamp(record, query, receipt, args.trust_dir, args.openssl)
        spec = json.loads(PROTOCOL.read_text())
        baseline = json.loads((ROOT / 'config/final_evaluation.json').read_text())
        origin = check_forecast(json.loads(record), timestamp, spec, baseline)
        print(json.dumps({'status': 'receipt_verified', 'origin': origin,
                          'signed_at_utc': timestamp.isoformat(),
                          'record_sha256': hashlib.sha256(record).hexdigest(),
                          'receipt_sha256': hashlib.sha256(receipt).hexdigest()}, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f'{error}\n')


if __name__ == '__main__':
    main()
