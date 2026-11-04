"""Compare saved quotes with another website and an S&P 500 benchmark with FRED.

FRED SP500 is compared with Yahoo ^GSPC, never with an ETF's dollar price.
Downloaded FRED observations and website tables remain local.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
from io import StringIO
import json
from pathlib import Path
import sys

import pandas as pd
import requests
import yfinance as yf

from scripts.audit_market_data import HISTORY_SETTINGS, ROOT, dump_json, expected_sessions, sha256

WEBSITES = {
    "AAPL": "https://stockanalysis.com/stocks/aapl/history/",
    "SPY": "https://stockanalysis.com/etf/spy/history/",
    "BND": "https://stockanalysis.com/etf/bnd/history/",
}


def load_prices(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert("America/New_York").tz_localize(None).normalize()
    if frame.index.has_duplicates:
        raise ValueError("Duplicate provider dates cannot be used in a cross-source comparison")
    return frame.sort_index()


def compare_values(left: pd.Series, right: pd.Series, required_dates: pd.DatetimeIndex,
                   tolerance: float) -> dict:
    if left.index.has_duplicates or right.index.has_duplicates:
        raise ValueError("Duplicate dates in external comparison")
    pairs = pd.concat([left.rename("provider"), right.rename("reference")], axis=1, sort=True).reindex(required_dates)
    pairs = pairs.apply(pd.to_numeric, errors="coerce")
    available = pairs.notna().all(axis=1)
    native_difference = (pairs.loc[available, "provider"] - pairs.loc[available, "reference"]).abs()
    # Reference tables publish cents / hundredths of an index point. Compare that
    # precision explicitly; float32 storage can otherwise push 0.02 just above 0.02.
    published = pairs.loc[available].round(2)
    differences = (published["provider"] - published["reference"]).abs().round(2)
    return {"required_dates": len(required_dates), "compared_dates": int(available.sum()),
            "missing_dates": [str(d.date()) for d in pairs.index[~available]],
            "mismatch_dates": [str(d.date()) for d in differences.index[differences > tolerance]],
            "mismatch_absolute_differences": {str(d.date()): float(value) for d, value in differences.items() if value > tolerance},
            "native_float_mismatch_dates": [str(d.date()) for d in native_difference.index[native_difference > tolerance]],
            "published_decimal_precision": 2,
            "max_native_float_difference": float(native_difference.max()) if len(native_difference) else None,
            "max_absolute_difference": float(differences.max()) if len(differences) else None,
            "tolerance": tolerance,
            "passed": bool(len(required_dates) > 0 and available.all() and (differences <= tolerance).all())}


def fetch_file(session: requests.Session, url: str, path: Path, record: dict, params=None) -> None:
    response = session.get(url, params=params, timeout=30)
    record.update(url=response.url, http_status=response.status_code,
                  retrieved_at_utc=datetime.now(timezone.utc).isoformat())
    response.raise_for_status()
    path.write_bytes(response.content)
    record.update(file=path.name, sha256=sha256(path), status="downloaded")


def acquire(run: Path, base_run: Path) -> dict:
    base = json.loads((base_run / "manifest.json").read_text())
    for package, recorded in base["packages"].items():
        if package != "pip" and version(package) != recorded:
            raise ValueError(f"Baseline package version differs for {package}")
    run.mkdir(parents=True, exist_ok=False)
    manifest = {"run_id": run.name, "base_run_id": base_run.name,
                "base_manifest_sha256": sha256(base_run / "manifest.json"),
                "start_inclusive": base["start_inclusive"], "end_exclusive": base["end_exclusive"],
                "script_sha256": sha256(Path(__file__)),
                "packages": {p: version(p) for p in ["pandas", "requests", "yfinance", "exchange-calendars"]}, "sources": {}}
    session = requests.Session()
    session.headers["User-Agent"] = "PortfolioRiskResearchAudit/0.1"
    tasks = [("FRED_SP500", "https://fred.stlouisfed.org/graph/fredgraph.csv", "FRED_SP500.csv",
              {"id": "SP500", "cosd": base["start_inclusive"],
               "coed": str((pd.Timestamp(base["end_exclusive"]) - pd.Timedelta(days=1)).date())})]
    tasks += [(symbol, url, f"{symbol}.html", None) for symbol, url in WEBSITES.items()]
    for name, url, filename, params in tasks:
        record = {"status": "failed", "url": url}
        try:
            fetch_file(session, url, run / filename, record, params)
            print(f"{name}: saved reference response", flush=True)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            print(f"{name}: unavailable ({type(exc).__name__})", flush=True)
        manifest["sources"][name] = record
        dump_json(run / "manifest.json", manifest)
    record = {"status": "failed", "symbol": "^GSPC"}
    try:
        yf.set_tz_cache_location(str(ROOT / "data/cache/yfinance"))
        yf.config.debug.hide_exceptions = False
        frame = yf.Ticker("^GSPC").history(start=base["start_inclusive"], end=base["end_exclusive"], **HISTORY_SETTINGS)
        if frame.empty:
            raise ValueError("Empty benchmark history")
        frame.to_csv(run / "YAHOO_GSPC.csv", index_label="provider_timestamp")
        record.update(status="downloaded", file="YAHOO_GSPC.csv", sha256=sha256(run / "YAHOO_GSPC.csv"),
                      retrieved_at_utc=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    manifest["sources"]["YAHOO_GSPC"] = record
    dump_json(run / "manifest.json", manifest)
    return manifest


def validate(run: Path, base_run: Path, manifest: dict) -> dict:
    if sha256(base_run / "manifest.json") != manifest["base_manifest_sha256"]:
        raise ValueError("Baseline manifest changed")
    base = json.loads((base_run / "manifest.json").read_text())
    for package, recorded in base["packages"].items():
        if package != "pip" and version(package) != recorded:
            raise ValueError(f"Baseline package version differs for {package}")
    for package, recorded in manifest["packages"].items():
        if version(package) != recorded:
            raise ValueError(f"Package version differs for {package}")
    for name, record in manifest["sources"].items():
        if record["status"] == "downloaded" and sha256(run / record["file"]) != record["sha256"]:
            raise ValueError(f"Reference snapshot changed: {name}")
    results = {}
    for symbol in WEBSITES:
        result = {"passed": False}
        try:
            if manifest["sources"][symbol]["status"] != "downloaded":
                raise ValueError("Reference website was unavailable")
            if sha256(base_run / f"{symbol}.csv") != base["instruments"][symbol]["csv_sha256"]:
                raise ValueError("Baseline price snapshot changed")
            provider = load_prices(base_run / f"{symbol}.csv")
            tables = pd.read_html(StringIO((run / f"{symbol}.html").read_text()))
            table = next(t for t in tables if "Date" in t.columns and "Close" in t.columns)
            table.index = pd.to_datetime(table["Date"], errors="coerce")
            if table.index.isna().any():
                raise ValueError("Unparseable website dates")
            website_close = pd.to_numeric(table["Close"].astype(str).str.replace(",", ""), errors="coerce")
            required = provider.index[-5:]
            result = compare_values(provider["Close"], website_close, required, 0.01)
            result.update(comparison="Daily Close in USD, latest five completed sessions in the baseline", source_url=WEBSITES[symbol])
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        results[symbol] = result
    benchmark = {"passed": False}
    try:
        for source in ["FRED_SP500", "YAHOO_GSPC"]:
            if manifest["sources"][source]["status"] != "downloaded":
                raise ValueError(f"{source} unavailable")
        fred = pd.read_csv(run / "FRED_SP500.csv")
        date_column = next(c for c in fred.columns if c.lower() in {"date", "observation_date"})
        fred.index = pd.to_datetime(fred[date_column])
        reference = pd.to_numeric(fred["SP500"], errors="coerce")
        yahoo = load_prices(run / "YAHOO_GSPC.csv")
        required = expected_sessions(manifest["start_inclusive"], manifest["end_exclusive"], "XNYS")
        benchmark = compare_values(yahoo["Close"], reference, required, 0.02)
        benchmark["comparison"] = "S&P 500 daily closing price index: FRED SP500 versus Yahoo ^GSPC"
    except Exception as exc:
        benchmark["error"] = f"{type(exc).__name__}: {exc}"
    targeted = None
    if (run / "targeted_recheck.json").exists():
        metadata = json.loads((run / "targeted_recheck.json").read_text())
        path = run / "YAHOO_GSPC_targeted_recheck.csv"
        if sha256(path) != metadata["sha256"]:
            raise ValueError("Targeted recheck hash mismatch")
        original = load_prices(run / "YAHOO_GSPC.csv")["Close"]
        recheck = load_prices(path)["Close"]
        targeted = compare_values(original, recheck, recheck.index, 0.0)
    return {"run_id": run.name, "base_run_id": base_run.name,
            "audit_script_sha256": sha256(Path(__file__)), "website_checks": results,
            "fred_benchmark_check": benchmark, "targeted_yahoo_recheck": targeted,
            "all_checks_pass": all(r["passed"] for r in [*results.values(), benchmark])}


def report(result: dict, manifest: dict) -> None:
    table = []
    for name, check in [*result["website_checks"].items(), ("S&P 500 benchmark", result["fred_benchmark_check"])]:
        largest = check.get("max_absolute_difference")
        largest_text = f"{largest:.2f}" if largest is not None else "unavailable"
        table.append(f"| {name} | {check.get('compared_dates', 0)} / {check.get('required_dates', 'unavailable')} | "
                     f"{len(check.get('mismatch_dates', []))} | {largest_text} | "
                     f"{'Pass' if check['passed'] else ('Mismatch' if check.get('mismatch_dates') else 'Fail / unavailable')} |")
    outcome = "All implemented comparisons passed." if result["all_checks_pass"] else "At least one comparison failed or was unavailable; see local evidence before accepting the source."
    errors = [f"- {name}: {check['error']}" for name, check in [*result["website_checks"].items(), ("FRED", result["fred_benchmark_check"])] if check.get("error")]
    benchmark = result["fred_benchmark_check"]
    discrepancy_rows = "\n".join(f"| {date} | {difference:.2f} | Unresolved; original observations retained |"
                                  for date, difference in benchmark.get("mismatch_absolute_differences", {}).items())
    discrepancy_detail = ("\n## Benchmark exceptions\n\n| Date | Absolute difference in index points | Disposition |\n| --- | ---: | --- |\n"
                          + discrepancy_rows + "\n\n" if discrepancy_rows else "")
    if result.get("targeted_yahoo_recheck"):
        discrepancy_detail += ("A separate Yahoo request for August 10–12, 2021 reproduced the original Yahoo values, including the largest discrepancy on August 11. This rules out a one-off full-window response difference in this capture; the discrepancy's cause remains unresolved. The recheck and its hash are retained locally.\n\n")
    text = f"""# Cross-source validation

Updated November 4, 2026. {outcome}

## Scope and source lineage

- **Yahoo Finance via yfinance:** the original AAPL, SPY, and BND acquisition; baseline run `{result['base_run_id']}`.
- **Stock Analysis:** a separate website used to spot-check the daily Close for the last five completed sessions in each baseline series. Comparisons use the same dates, USD, and price field. Intraday observations on November 4 are excluded. The website's upstream vendor independence is not established.
- **FRED:** its SP500 series is compared with Yahoo's **^GSPC**, which represents the same S&P 500 closing price index. FRED SP500 is **not** compared directly with SPY's dollar price, and does not validate individual AAPL, SPY, or BND quotes.
- **Apple:** an issuer announcement cross-checks a split and dividend amount in the [primary data audit](DATA_AUDIT.md).

## Observed comparisons

| Series | Dates compared / required | Mismatches beyond tolerance | Maximum absolute difference | Result |
| --- | ---: | ---: | ---: | --- |
{chr(10).join(table)}

Stock/ETF quote differences are in USD; tolerance is **$0.01**. Index differences are in index points; tolerance is **0.02 index points**. Values are compared at the reference tables' published two-decimal precision. Native floating-point differences are also preserved in local evidence: a 0.02 difference can otherwise appear as 0.020078 after float storage and trigger a spurious boundary flag. The tolerance is unchanged. Missing dates fail a comparison rather than being forward-filled. Website checks cover five dates per instrument; the FRED comparison covers the requested benchmark history.

{chr(10).join(errors)}

{discrepancy_detail}
No exception is automatically repaired or accepted. Keep Yahoo ^GSPC out of model features and benchmark calculations until a documented source-selection or reconciliation decision is made. These benchmark exceptions do not establish that the three stock/ETF histories are erroneous; those series have separate, limited spot checks.

The [source policy](DATA_SOURCE_POLICY.md) selects a preferred context source and quarantines the discrepant comparator. It does not resolve the underlying price disagreement or change this validator's outcome.

```mermaid
flowchart LR
    P[S&P index publisher] --> F[FRED SP500]
    P --> Y[Yahoo GSPC]
    F --> C[Same-index reconciliation]
    Y --> C
    A[Yahoo stock and ETF histories] --> S[Five-date quote checks]
    B[Stock Analysis website] --> S
```

## Evidence and reproduction

- External capture: `{result['run_id']}`; requested window: {manifest['start_inclusive']} inclusive to {manifest['end_exclusive']} exclusive.
- Local `data/validation/{result['run_id']}/` contains website HTML, FRED CSV, benchmark history, HTTP/retrieval metadata, hashes, and detailed comparison JSON. These downloaded sources are excluded from Git.
- The baseline manifest, downloaded file hashes, and package versions are verified before comparison.

```bash
.venv/bin/python -m scripts.cross_validate_sources --snapshot data/audit/{result['base_run_id']}
# Reuse this external capture without downloading again:
.venv/bin/python -m scripts.cross_validate_sources --snapshot data/audit/{result['base_run_id']} --external-snapshot data/validation/{result['run_id']}
```

## Interpretation and limitations

Agreement between websites checks acquisition, date alignment, field interpretation, and selected quote consistency. It does not establish independent price discovery or prove the full history is error-free. Both FRED and Yahoo distribute the S&P 500 index from its originating publisher; their delivery paths differ, but underlying index lineage is shared.

FRED SP500 is a price index without dividends, not a total-return series. Its values must not be substituted for an ETF's adjusted prices. FRED's notes describe history limits, revisions, and source-specific reuse restrictions; downloaded observations are retained locally. The public report presents comparison statistics rather than republishing the series.

Direct Yahoo Finance history pages returned HTTP 429 during the initial web check, so a direct-page validation is not claimed. Stock Analysis supplies the separate website spot check instead. No access warning or rate limit was bypassed.

Sources: [FRED series and notes](https://fred.stlouisfed.org/series/SP500), [AAPL history](https://stockanalysis.com/stocks/aapl/history/), [SPY history](https://stockanalysis.com/etf/spy/history/), [BND history](https://stockanalysis.com/etf/bnd/history/).
"""
    (ROOT / "docs/CROSS_SOURCE_VALIDATION.md").write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="Baseline price snapshot")
    parser.add_argument("--external-snapshot", type=Path, help="Saved external capture for offline comparison")
    args = parser.parse_args()
    base_run = args.snapshot.resolve()
    if args.external_snapshot:
        run = args.external_snapshot.resolve()
        manifest = json.loads((run / "manifest.json").read_text())
    else:
        run = ROOT / "data/validation" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        manifest = acquire(run, base_run)
    result = validate(run, base_run, manifest)
    dump_json(run / "comparison.json", result)
    report(result, manifest)
    print(json.dumps(result, indent=2))
    return 0 if result["all_checks_pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
