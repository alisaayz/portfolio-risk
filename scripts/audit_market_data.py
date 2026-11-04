"""Download a small, versioned market-data sample and audit it without filling gaps.

Online: python scripts/audit_market_data.py --end 2026-11-04
Offline: python scripts/audit_market_data.py --snapshot data/audit/<run-id>
The end date is exclusive. Downloaded prices and detailed evidence remain local.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import sys

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
CALENDARS = {"AAPL": "XNAS", "SPY": "XNYS", "BND": "XNAS"}
REQUIRED = ["Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"]
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close"]
HISTORY_SETTINGS = {
    "interval": "1d", "actions": True, "auto_adjust": False,
    "back_adjust": False, "repair": False, "keepna": True,
    "prepost": False, "rounding": False, "timeout": 30,
}


def dump_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_metadata(metadata) -> dict:
    """Convert the library's lazy Mapping without fetching intraday tradingPeriods."""
    return {key: metadata[key] for key in metadata if key != "tradingPeriods"}


def expected_sessions(start: str, end: str, calendar: str) -> pd.DatetimeIndex:
    start_day, end_day = pd.Timestamp(start), pd.Timestamp(end)
    if start_day >= end_day:
        raise ValueError("start must precede the exclusive end date")
    exchange = xcals.get_calendar(calendar, start=start_day - pd.Timedelta(days=10),
                                  end=end_day + pd.Timedelta(days=10))
    sessions = exchange.sessions_in_range(start_day, end_day - pd.Timedelta(days=1))
    return sessions.tz_localize(None) if sessions.tz is not None else sessions


def audit_frame(frame: pd.DataFrame, expected: pd.DatetimeIndex) -> dict:
    """Inspect provider rows; do not remove duplicates, fill values, or repair prices."""
    errors, warnings = [], []
    result = {"rows": len(frame), "expected_sessions": len(expected), "errors": errors,
              "warnings": warnings, "columns": list(frame.columns), "events": []}
    missing_columns = sorted(set(REQUIRED) - set(frame.columns))
    result["missing_columns"] = missing_columns
    if frame.empty or missing_columns:
        errors.append("Empty response" if frame.empty else f"Missing required fields: {missing_columns}")
        return result

    dates = pd.DatetimeIndex(frame.index)
    result["index_timezone"] = str(dates.tz) if dates.tz is not None else None
    if dates.tz is not None:
        dates = dates.tz_convert("America/New_York").tz_localize(None)
    dates = dates.normalize()
    observed = dates.unique().sort_values()
    result.update(first_session=str(observed.min().date()), last_session=str(observed.max().date()),
                  unique_sessions=len(observed), duplicate_dates=int(dates.duplicated().sum()),
                  chronological=bool(dates.is_monotonic_increasing),
                  missing_sessions=[str(d.date()) for d in expected.difference(observed)],
                  unexpected_sessions=[str(d.date()) for d in observed.difference(expected)])
    for key in ["duplicate_dates", "missing_sessions", "unexpected_sessions"]:
        if result[key]:
            errors.append(f"{key}: {len(result[key]) if isinstance(result[key], list) else result[key]}")
    if not result["chronological"]:
        warnings.append("Provider rows were not chronological; diagnostics use sorted dates")

    numeric = frame[REQUIRED].apply(pd.to_numeric, errors="coerce")
    numeric.index = dates
    result["missing_cells"] = {c: int(numeric[c].isna().sum()) for c in REQUIRED}
    result["nonfinite_cells"] = int((~np.isfinite(numeric.to_numpy(dtype=float))).sum())
    result["nonpositive_price_cells"] = int((numeric[PRICE_COLUMNS] <= 0).sum().sum())
    result["negative_volume_rows"] = int((numeric["Volume"] < 0).sum())
    result["zero_volume_rows"] = int((numeric["Volume"] == 0).sum())
    result["negative_action_rows"] = int(((numeric["Dividends"] < 0) | (numeric["Stock Splits"] < 0)).sum())
    result["ohlc_inconsistent_rows"] = int(((numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1))
                                            | (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1))).sum())
    for key in ["nonfinite_cells", "nonpositive_price_cells", "negative_volume_rows",
                "negative_action_rows", "ohlc_inconsistent_rows"]:
        if result[key]:
            errors.append(f"{key}: {result[key]}")
    if result["zero_volume_rows"]:
        warnings.append(f"Zero-volume rows require review: {result['zero_volume_rows']}")
    result["dividend_events"] = int((numeric["Dividends"] > 0).sum())
    result["split_events"] = int((numeric["Stock Splits"] > 0).sum())
    if result["duplicate_dates"] or result["nonfinite_cells"] or result["nonpositive_price_cells"]:
        warnings.append("Return and adjustment diagnostics skipped because required values are invalid")
        return result

    ordered = numeric.sort_index().reindex(expected)
    close, adjusted = ordered["Close"], ordered["Adj Close"]
    previous = close.shift(1)
    # No forward-fill: a missing session also makes the next one-session return unavailable.
    price_return = close.pct_change(fill_method=None)
    adjusted_return = adjusted.pct_change(fill_method=None)
    factor = adjusted / close
    factor_jump = factor / factor.shift(1)
    dividend = ordered["Dividends"]
    eligible_dividend = (dividend > 0) & (dividend < previous)
    expected_jump = pd.Series(1.0, index=expected)
    expected_jump.loc[eligible_dividend] = 1 / (1 - dividend.loc[eligible_dividend] / previous.loc[eligible_dividend])
    factor_error_bp = (factor_jump / expected_jump - 1) * 10_000
    result["factor_deviation_over_5bp_dates"] = [str(d.date()) for d in expected[factor_error_bp.abs().gt(5)]]
    result["extreme_adjusted_move_dates"] = [str(d.date()) for d in expected[adjusted_return.abs().gt(0.20)]]
    for key in ["factor_deviation_over_5bp_dates", "extreme_adjusted_move_dates"]:
        if result[key]:
            warnings.append(f"{key}: {len(result[key])}; inspect local diagnostics")

    event_mask = (dividend > 0) | (ordered["Stock Splits"] > 0)
    for date in expected[event_mask.fillna(False)]:
        event = {"date": str(date.date()), "dividend": float(dividend.loc[date]),
                 "split_ratio": float(ordered.loc[date, "Stock Splits"])}
        for name, series in {"provider_close_return": price_return, "adjusted_return": adjusted_return,
                             "adjustment_factor_error_bp": factor_error_bp}.items():
            value = series.loc[date]
            event[name] = float(value) if pd.notna(value) and np.isfinite(value) else None
        if event["split_ratio"] > 0 and pd.notna(previous.loc[date]):
            event["return_if_split_applied_again"] = float(close.loc[date] * event["split_ratio"] / previous.loc[date] - 1)
        result["events"].append(event)
    return result


def load_universe(path: Path) -> dict:
    universe = json.loads(path.read_text())
    if universe.get("schema_version") != 1 or universe.get("currency") != "USD":
        raise ValueError("Require a version-1 USD research universe")
    if not re.fullmatch(r"[A-Z0-9_-]+", universe.get("universe_id", "")):
        raise ValueError("Require a simple universe identity")
    records = universe.get("instruments", [])
    if not records:
        raise ValueError("Universe must contain instruments")
    symbols = set()
    for record in records:
        symbol = record.get("symbol", "")
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", symbol) or symbol in symbols:
            raise ValueError("Require unique, safe instrument symbols")
        symbols.add(symbol)
        if record.get("calendar") not in {"XNAS", "XNYS"}:
            raise ValueError("Unsupported daily-session reference calendar")
        if not record.get("research_role") or not record.get("kind"):
            raise ValueError("Record instrument classification and selection purpose")
    return universe


def download_snapshot(run: Path, start: str, end: str, universe: dict | None = None) -> dict:
    run.mkdir(parents=True, exist_ok=False)
    yf.set_tz_cache_location(str(ROOT / "data/cache/yfinance"))
    yf.config.debug.hide_exceptions = False
    manifest = {"schema_version": 1, "run_id": run.name,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": "Yahoo Finance via yfinance", "start_inclusive": start, "end_exclusive": end,
                "python": platform.python_version(), "script_sha256": sha256(Path(__file__)),
                "packages": {name: version(name) for name in ["yfinance", "pandas", "exchange-calendars", "matplotlib", "pip"]},
                "request_settings": HISTORY_SETTINGS, "instruments": {}}
    calendars = CALENDARS if universe is None else {r["symbol"]: r["calendar"] for r in universe["instruments"]}
    if universe is not None:
        manifest["universe"] = universe
        manifest["universe_sha256"] = hashlib.sha256(json.dumps(universe, sort_keys=True).encode()).hexdigest()
    for symbol, calendar in calendars.items():
        record = {"calendar": calendar, "status": "failed"}
        try:
            ticker = yf.Ticker(symbol)
            frame = ticker.history(start=start, end=end, **HISTORY_SETTINGS)
            # This is preserved library output, not an original HTTP payload.
            frame.to_csv(run / f"{symbol}.csv", index_label="provider_timestamp")
            record.update(status="downloaded", rows=len(frame),
                          retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
                          index_timezone=str(frame.index.tz) if isinstance(frame.index, pd.DatetimeIndex) and frame.index.tz else None,
                          csv_sha256=sha256(run / f"{symbol}.csv"))
            try:
                metadata = materialize_metadata(ticker.get_history_metadata(repair=False))
                dump_json(run / f"{symbol}.metadata.json", metadata)
                record["metadata_scope"] = "Library metadata excluding lazy intraday tradingPeriods"
                record["metadata_sha256"] = sha256(run / f"{symbol}.metadata.json")
                record["currency"] = metadata.get("currency")
                record["exchange_timezone"] = metadata.get("exchangeTimezoneName")
                record["provider_exchange"] = metadata.get("exchangeName")
            except Exception as exc:
                record["metadata_error"] = f"{type(exc).__name__}: {exc}"
            print(f"{symbol}: saved {len(frame)} provider rows", flush=True)
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            print(f"{symbol}: download failed ({type(exc).__name__})", flush=True)
        manifest["instruments"][symbol] = record
        dump_json(run / "manifest.json", manifest)
    return manifest


def inspect_snapshot(run: Path, manifest: dict) -> dict:
    if "universe" in manifest:
        universe = manifest["universe"]
        digest = hashlib.sha256(json.dumps(universe, sort_keys=True).encode()).hexdigest()
        if digest != manifest.get("universe_sha256"):
            raise ValueError("Preserved universe hash mismatch")
        configured = {r["symbol"]: r["calendar"] for r in universe["instruments"]}
        recorded = {symbol: record["calendar"] for symbol, record in manifest["instruments"].items()}
        if configured != recorded or len(configured) != len(universe["instruments"]):
            raise ValueError("Snapshot instruments/calendars disagree with preserved universe")
    for package, recorded_version in manifest["packages"].items():
        if package != "pip" and version(package) != recorded_version:
            raise ValueError(f"Environment differs for {package}; install the recorded requirements before replay")
    results = {}
    for symbol, record in manifest["instruments"].items():
        if record["status"] != "downloaded":
            results[symbol] = {"rows": 0, "errors": [record.get("error", "Download failed")], "warnings": []}
            continue
        path = run / f"{symbol}.csv"
        if sha256(path) != record["csv_sha256"]:
            raise ValueError(f"Snapshot hash mismatch for {symbol}; do not overwrite or use altered evidence")
        if record.get("metadata_sha256") and sha256(run / f"{symbol}.metadata.json") != record["metadata_sha256"]:
            raise ValueError(f"Metadata hash mismatch for {symbol}")
        frame = pd.read_csv(path, index_col=0)
        if record["index_timezone"]:
            frame.index = pd.to_datetime(frame.index, utc=True).tz_convert(record["index_timezone"])
        else:
            frame.index = pd.to_datetime(frame.index)
        sessions = expected_sessions(manifest["start_inclusive"], manifest["end_exclusive"], record["calendar"])
        result = audit_frame(frame, sessions)
        if record.get("currency") != "USD":
            result["errors"].append("USD currency not verified from provider metadata")
        if record.get("metadata_error"):
            result["warnings"].append("Provider metadata retrieval failed")
        results[symbol] = result
    return {"run_id": manifest["run_id"], "audit_script_sha256": sha256(Path(__file__)), "results": results,
            "structural_checks_pass": all(not result["errors"] for result in results.values()),
            "review_flags": sum(len(result["warnings"]) for result in results.values())}


def write_figure(audit: dict, destination: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data/cache/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["svg.hashsalt"] = "portfolio-risk-audit"
    symbols = list(audit["results"])
    observed = [audit["results"][s].get("unique_sessions", 0) for s in symbols]
    missing = [len(audit["results"][s].get("missing_sessions", [])) for s in symbols]
    expected = [audit["results"][s].get("expected_sessions", 0) for s in symbols]
    fig, ax = plt.subplots(figsize=(9, max(3.8, .43*len(symbols)+1.5)), layout="constrained")
    fig.set_facecolor("#f4f7fb")
    ax.set_facecolor("#f4f7fb")
    ax.barh(symbols, observed, color="#284f7d", label="Observed sessions")
    ax.barh(symbols, missing, left=observed, color="#d77b43", label="Missing expected sessions")
    for i, (present, total) in enumerate(zip(observed, expected)):
        ax.text(max(expected + [1]) * 0.015, i, f"{present:,} observed / {total:,} expected", va="center", color="white", fontsize=11)
    ax.set_title("Market-data coverage audit", loc="left", weight="bold", pad=18, color="#172b46")
    ax.set_xlabel("Trading sessions in the requested date range")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=2, frameon=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, metadata={"Date": None})
    destination.write_text("\n".join(line.rstrip() for line in destination.read_text().splitlines()) + "\n")
    fig.savefig(destination.with_suffix(".png"), dpi=160)
    plt.close(fig)


def write_report(audit: dict, manifest: dict, destination: Path, figure: Path) -> None:
    rows = []
    for symbol, result in audit["results"].items():
        rows.append(f"| {symbol} | {result['rows']:,} | {result.get('expected_sessions', '—')} | "
                    f"{len(result.get('missing_sessions', []))} | {result.get('duplicate_dates', '—')} | "
                    f"{result.get('nonpositive_price_cells', '—')} | {result.get('dividend_events', '—')} | "
                    f"{result.get('split_events', '—')} | {'Pass' if not result['errors'] else 'Fail'} |")
    decision = ("The sample passes the implemented structural checks. It is suitable for the next prototype stage, subject to the adjustment review and limitations below."
                if audit["structural_checks_pass"] else
                "The sample does not pass the implemented structural checks. Resolve the listed failures before using it for portfolio calculations or model training.")
    detail = []
    for symbol, result in audit["results"].items():
        record = manifest["instruments"][symbol]
        detail.append(f"### {symbol}\n\n- Observed range: {result.get('first_session', 'unavailable')} to {result.get('last_session', 'unavailable')}.\n"
                      f"- Reference calendar: `{record['calendar']}`; provider exchange: `{record.get('provider_exchange', 'unverified')}`.\n"
                      f"- Currency: `{record.get('currency', 'unverified')}`.\n"
                      f"- Non-finite numeric cells: {result.get('nonfinite_cells', 'not assessed')}; inconsistent OHLC rows: {result.get('ohlc_inconsistent_rows', 'not assessed')}.\n"
                      f"- Errors: {'; '.join(result['errors']) or 'None detected'}.\n"
                      f"- Review flags: {'; '.join(result['warnings']) or 'None raised by the implemented thresholds'}.\n")
    relative_figure = os.path.relpath(figure, destination.parent)
    apple_events = audit["results"].get("AAPL", {}).get("events", [])
    split = next((e for e in apple_events if e["date"] == "2020-08-31" and e["split_ratio"] == 4), None)
    cash = next((e for e in apple_events if e["date"] == "2020-08-07"), None)
    action_review = "The specific Apple reference events were unavailable in this snapshot; no independent event match is claimed."
    if split and cash:
        action_review = (f"Apple's issuer announcement specifies a four-for-one split with split-adjusted trading beginning August 31, 2020; this matches the provider event. "
                         f"The observed provider-close return around that event is {split['provider_close_return']:.2%}. Applying the split ratio again would instead produce {split['return_if_split_applied_again']:.2%}, demonstrating the double-adjustment error. "
                         f"The announcement also specifies a pre-split dividend of $0.82; the provider reports ${cash['dividend']:.3f} on August 7, consistent with $0.82 divided by four. "
                         "This cross-check covers the split date/ratio and dividend amount basis, not an independently verified ex-dividend date or all ETF distributions. "
                         "[Apple issuer announcement](https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/).")
    universe_argument = " --universe config/reference_universe.json" if "universe" in manifest else ""
    text = f"""# Market-data audit

## Executive finding

{decision}

This report is generated from saved provider-library output. It records data availability and internal consistency, not an independent certification of price accuracy. No model has been trained.

External source agreement for the original AAPL/SPY/BND sample is assessed separately in [cross-source validation](CROSS_SOURCE_VALIDATION.md). Those spot checks do not validate additional instruments or fresh captures. A structural pass here does not grant SQL acceptance, close source discrepancies, or authorize automatic correction of source values.

## Run and source

- Run: `{manifest['run_id']}`.
- Retrieval time: `{manifest['retrieved_at_utc']}`.
- Requested dates: **{manifest['start_inclusive']} inclusive to {manifest['end_exclusive']} exclusive**.
- Source: Yahoo Finance through yfinance {manifest['packages']['yfinance']}.
- Environment: Python {manifest['python']}; pandas {manifest['packages']['pandas']}; exchange-calendars {manifest['packages']['exchange-calendars']}.
- Snapshot settings: daily, corporate actions enabled, automatic/back adjustment disabled, repair disabled, missing rows retained, no rounding.
- Code provenance: the manifest records the download script hash when available; detailed audit JSON records the current audit script hash. Replay checks package versions and saved file hashes.
- Evidence: local `data/audit/{manifest['run_id']}/`, including manifest, CSV hashes, metadata, and detailed audit JSON. These files are excluded from version control.

## Coverage and structural checks

![Observed and missing expected trading sessions by instrument]({relative_figure})

| Instrument | Rows | Expected sessions | Missing sessions | Duplicate dates | Nonpositive price cells | Dividend events | Split events | Structural result |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{chr(10).join(rows)}

{chr(10).join(detail)}
## Adjustment diagnostics

The local audit JSON records every returned dividend and split event with surrounding close/adjusted-close returns. Dividend checks compare changes in the adjusted-close/close factor with the convention `1 / (1 - dividend / previous_close)`. Deviations above five basis points are review flags, not automatic price corrections. This checks consistency with a convention; it is not an independent reconstruction of total returns.

The provider's Close field must not be assumed to be an original, split-unadjusted quote. Split-event diagnostics also calculate the hypothetical return produced by applying the reported split ratio again. A large artificial move in that diagnostic is evidence against double-adjusting the returned series. A split on the first observed session cannot be reconciled without an earlier observation.

### Selected issuer cross-check

{action_review}

Adjusted-return moves above 20% are flagged for investigation. The script does not fill missing sessions, repair outliers, or remove duplicates. One-session return diagnostics use the full expected session index, so a gap cannot silently become a multi-session return.

## Limitations and next decision

- A single source can be internally consistent and still contain errors. Independent checks around selected corporate actions remain necessary before treating adjustments as verified.
- `XNAS` and `XNYS` are configured daily-session references. NYSE Arca-listed instruments use XNYS as a U.S. daily-session reference rather than a venue-specific calendar. Exchange-calendar definitions can change and are versioned with this run.
- Saved CSVs preserve yfinance's output, not the original HTTP response. The library may process observations before returning them even with the explicit settings above.
- Today's adjusted histories can be revised and do not establish what was known at every historical forecast date. A fresh download need not match an earlier snapshot; offline replay verifies and reuses saved evidence.
- This audit does not establish production availability, redistribution rights, full instrument-universe suitability, or model accuracy. Downloaded prices remain local; the public report contains summary counts and methods.
- Next: resolve failures/review flags and independently inspect selected quotes/actions before expanding SQL acceptance rules. The original three-instrument SQL layer remains a separate verified milestone.

## Reproduction

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/audit_market_data.py --start {manifest['start_inclusive']} --end {manifest['end_exclusive']}{universe_argument}
# Re-audit the original local snapshot without downloading again:
.venv/bin/python scripts/audit_market_data.py --snapshot data/audit/{manifest['run_id']}
```

Source references: [yfinance](https://github.com/ranaroussi/yfinance), [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars).
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", help="Exclusive end date; required for a new download")
    parser.add_argument("--snapshot", type=Path, help="Existing run folder for verified offline replay")
    parser.add_argument("--universe", type=Path, help="Explicit research universe; original three-instrument default is unchanged")
    args = parser.parse_args()
    if args.snapshot and args.universe:
        parser.error("offline replay uses the universe preserved in the manifest")
    if args.snapshot:
        run = args.snapshot.resolve()
        manifest = json.loads((run / "manifest.json").read_text())
    else:
        if not args.end:
            parser.error("provide --end YYYY-MM-DD; dates are never inferred from the machine clock")
        universe = load_universe(args.universe) if args.universe else None
        calendars = CALENDARS if universe is None else {r["symbol"]: r["calendar"] for r in universe["instruments"]}
        for calendar in set(calendars.values()):
            expected_sessions(args.start, args.end, calendar)
        run = ROOT / "data/audit" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        manifest = download_snapshot(run, args.start, args.end, universe)
    audit = inspect_snapshot(run, manifest)
    dump_json(run / "audit.json", audit)
    expanded = "universe" in manifest
    figure = ROOT / ("docs/assets/universe-coverage.svg" if expanded else "docs/assets/data-audit-summary.svg")
    report = ROOT / ("docs/UNIVERSE_AUDIT.md" if expanded else "docs/DATA_AUDIT.md")
    write_figure(audit, figure)
    write_report(audit, manifest, report, figure)
    print(json.dumps({"run_id": run.name, "structural_checks_pass": audit["structural_checks_pass"],
                      "review_flags": audit["review_flags"],
                      "report": str(report.relative_to(ROOT))}, indent=2))
    return 0 if audit["structural_checks_pass"] else 2


if __name__ == "__main__":
    sys.exit(main())
