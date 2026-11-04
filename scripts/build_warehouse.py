"""Build a versioned DuckDB warehouse from verified local evidence; no downloads.

Run from the repository root with python -m scripts.build_warehouse --help.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import duckdb
import pandas as pd

from scripts.audit_market_data import ROOT, CALENDARS, expected_sessions, inspect_snapshot, sha256
from scripts.cross_validate_sources import load_prices, validate

SQL = ROOT / "sql"
TABLES = {"ingestion_runs", "instruments", "prices_daily", "corporate_actions", "benchmark_observations",
          "dataset_versions", "dataset_runs", "source_rules", "expected_sessions", "data_quality_issues"}


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def prepare_bundle(primary: Path, external: Path, historical: list[Path], policy_path: Path) -> dict:
    primary_manifest = json.loads((primary / "manifest.json").read_text())
    external_manifest = json.loads((external / "manifest.json").read_text())
    policy = json.loads(policy_path.read_text())
    required_rules = {("yahoo_prices", symbol, "risk_prices") for symbol in CALENDARS}
    required_rules |= {("fred", "SP500", "context"), ("yahoo_index", "^GSPC", "quarantine")}
    actual_rules = {(r["source_id"], r["entity_id"], r["purpose"]) for r in policy["rules"]}
    if policy["policy_id"] != "DS-001" or actual_rules != required_rules or len(policy["rules"]) != 5:
        raise ValueError("Unsupported source policy; implement and test new semantics before changing DS-001")
    comparison = validate(external, primary, external_manifest)
    if not all(r["passed"] for r in comparison["website_checks"].values()):
        raise ValueError("Stock/ETF quote acceptance checks did not pass")
    benchmark_check = comparison["fred_benchmark_check"]
    if benchmark_check.get("error") or benchmark_check.get("missing_dates"):
        raise ValueError("Benchmark evidence has missing or unparseable required observations")

    captures = {path.name: path for path in [primary, *historical]}
    if len(captures) != len([primary, *historical]):
        raise ValueError("Supply each capture once; capture IDs must be unique")
    recipe = {"primary_manifest_sha256": sha256(primary / "manifest.json"),
              "external_manifest_sha256": sha256(external / "manifest.json"),
              "historical_manifests": sorted(sha256(p / "manifest.json") for p in historical),
              "policy": policy, "schema_sha256": sha256(SQL / "schema.sql"),
              "views_sha256": sha256(SQL / "views.sql"), "loader_sha256": sha256(Path(__file__)),
              "audit_sha256": sha256(ROOT / "scripts/audit_market_data.py"),
              "validator_sha256": sha256(ROOT / "scripts/cross_validate_sources.py"),
              "duckdb_version": duckdb.__version__}
    dataset_id = hashlib.sha256(canonical_json(recipe).encode()).hexdigest()
    frames = {table: [] for table in TABLES}
    stock_run = lambda path: "yahoo_prices:" + path.name
    primary_run = stock_run(primary)

    def add_run(run_id, source_id, path, manifest):
        frames["ingestion_runs"].append({"run_id": run_id, "source_id": source_id, "capture_id": path.name,
                                         "manifest_sha256": sha256(path / "manifest.json"),
                                         "manifest_json": canonical_json(manifest)})
        frames["dataset_runs"].append({"dataset_id": dataset_id, "run_id": run_id})

    for capture in [primary, *historical]:
        manifest = json.loads((capture / "manifest.json").read_text())
        result = inspect_snapshot(capture, manifest)
        if not result["structural_checks_pass"] or result["review_flags"]:
            raise ValueError(f"Capture {capture.name} requires data-quality review")
        run_id = stock_run(capture)
        add_run(run_id, "yahoo_prices", capture, manifest)
        for symbol in CALENDARS:
            frame = load_prices(capture / f"{symbol}.csv")
            for date, row in frame.iterrows():
                frames["prices_daily"].append({"run_id": run_id, "instrument_id": symbol,
                    "session_date": date.date(), "open": float(row["Open"]), "high": float(row["High"]),
                    "low": float(row["Low"]), "close": float(row["Close"]),
                    "adjusted_close": float(row["Adj Close"]), "volume": int(row["Volume"])})
                for field, kind in [("Dividends", "dividend"), ("Stock Splits", "split")]:
                    if row[field] > 0:
                        frames["corporate_actions"].append({"run_id": run_id, "instrument_id": symbol,
                            "session_date": date.date(), "action_type": kind, "value": float(row[field])})
    for symbol, calendar in CALENDARS.items():
        frames["instruments"].append({"instrument_id": symbol, "currency": "USD", "calendar_id": calendar})
        dates = expected_sessions(primary_manifest["start_inclusive"], primary_manifest["end_exclusive"], calendar)
        frames["expected_sessions"] += [{"dataset_id": dataset_id, "instrument_id": symbol,
                                        "session_date": d.date()} for d in dates]

    fred_run, yahoo_run = "fred:" + external.name, "yahoo_index:" + external.name
    for run_id, source in [(fred_run, "fred"), (yahoo_run, "yahoo_index")]:
        add_run(run_id, source, external, external_manifest)
    fred = pd.read_csv(external / "FRED_SP500.csv")
    date_col = next(c for c in fred if c.lower() in {"date", "observation_date"})
    fred.index = pd.to_datetime(fred[date_col])
    fred_values = pd.to_numeric(fred["SP500"], errors="coerce")
    yahoo_values = load_prices(external / "YAHOO_GSPC.csv")["Close"]
    if fred_values.index.has_duplicates:
        raise ValueError("FRED observations have duplicate dates")
    allowed = expected_sessions(primary_manifest["start_inclusive"], primary_manifest["end_exclusive"], "XNYS")
    if len(fred_values.dropna().index.difference(allowed)):
        raise ValueError("FRED contains unexpected non-null sessions")
    for run_id, series, values in [(fred_run, "SP500", fred_values), (yahoo_run, "^GSPC", yahoo_values)]:
        for date, value in values.items():
            frames["benchmark_observations"].append({"run_id": run_id, "series_id": series,
                "observation_date": date.date(), "index_level": float(value) if pd.notna(value) else None,
                "units": "price_index"})
    for date, difference in benchmark_check.get("mismatch_absolute_differences", {}).items():
        day = pd.Timestamp(date)
        frames["data_quality_issues"].append({"dataset_id": dataset_id, "issue_id": f"DQ-SP500-{date}",
            "entity_id": "SP500", "observation_date": day.date(), "rule_id": "same_index_close_v1",
            "observed_run_id": yahoo_run, "reference_run_id": fred_run,
            "observed_value": float(yahoo_values.loc[day]), "reference_value": float(fred_values.loc[day]),
            "absolute_difference": difference, "tolerance": benchmark_check["tolerance"],
            "status": "quarantined", "evidence_ref": f"data/validation/{external.name}/comparison.json",
            "resolution_note": "DS-001: comparator excluded; root cause remains unresolved"})
    frames["dataset_versions"] = [{"dataset_id": dataset_id, "primary_run_id": primary_run,
                                     "policy_id": policy["policy_id"], "recipe_json": canonical_json(recipe)}]
    frames["source_rules"] = [{"dataset_id": dataset_id, **rule} for rule in policy["rules"]]
    return {"dataset_id": dataset_id, "frames": frames, "recipe": recipe}


def load_bundle(connection, bundle: dict) -> None:
    """Apply all rows and switch the active dataset in one database transaction."""
    connection.execute("BEGIN TRANSACTION").fetchall()
    try:
        connection.execute((SQL / "schema.sql").read_text()).fetchall()
        for run in bundle["frames"]["ingestion_runs"]:
            previous = connection.execute("SELECT manifest_sha256 FROM ingestion_runs WHERE run_id = ?", [run["run_id"]]).fetchall()
            if previous and previous[0][0] != run["manifest_sha256"]:
                raise ValueError("An existing capture ID has a different manifest; retained inputs are immutable")
        order = ["ingestion_runs", "instruments", "prices_daily", "corporate_actions", "benchmark_observations",
                 "dataset_versions", "dataset_runs", "source_rules", "expected_sessions", "data_quality_issues"]
        for table in order:
            rows = bundle["frames"][table]
            if rows:
                connection.register("incoming_rows", pd.DataFrame(rows))
                connection.execute(f"INSERT OR IGNORE INTO {table} BY NAME SELECT * FROM incoming_rows").fetchall()
                connection.unregister("incoming_rows")
        connection.execute("INSERT INTO active_dataset VALUES (1, ?) ON CONFLICT (singleton) DO UPDATE SET dataset_id = excluded.dataset_id", [bundle["dataset_id"]]).fetchall()
        connection.execute((SQL / "views.sql").read_text()).fetchall()
        connection.execute("COMMIT").fetchall()
    except Exception:
        connection.execute("ROLLBACK").fetchall()
        raise


def export_dataset(connection, dataset_id: str, export_root: Path) -> dict:
    """Publish a complete Parquet cache after commit; verify existing cache on rerun."""
    queries = {
        "prices_daily": "SELECT p.* FROM prices_daily p JOIN dataset_runs d USING(run_id) WHERE d.dataset_id = ? ORDER BY run_id, instrument_id, session_date",
        "corporate_actions": "SELECT p.* FROM corporate_actions p JOIN dataset_runs d USING(run_id) WHERE d.dataset_id = ? ORDER BY run_id, instrument_id, session_date, action_type",
        "benchmark_observations": "SELECT p.* FROM benchmark_observations p JOIN dataset_runs d USING(run_id) WHERE d.dataset_id = ? ORDER BY run_id, series_id, observation_date",
        "data_quality_issues": "SELECT * FROM data_quality_issues WHERE dataset_id = ? ORDER BY issue_id",
        "source_rules": "SELECT * FROM source_rules WHERE dataset_id = ? ORDER BY source_id, entity_id",
    }
    destination = export_root / dataset_id
    if destination.exists():
        manifest = json.loads((destination / "manifest.json").read_text())
        if manifest["dataset_id"] != dataset_id:
            raise ValueError("Parquet manifest has a different dataset ID")
        for table, info in manifest["tables"].items():
            path = destination / f"{table}.parquet"
            if sha256(path) != info["sha256"]:
                raise ValueError("Parquet cache changed; preserve evidence and rebuild separately")
            query = queries[table]
            forward = connection.execute(f"SELECT count(*) FROM (({query}) EXCEPT ALL SELECT * FROM read_parquet(?))", [dataset_id, str(path)]).fetchall()[0][0]
            backward = connection.execute(f"SELECT count(*) FROM (SELECT * FROM read_parquet(?) EXCEPT ALL ({query}))", [str(path), dataset_id]).fetchall()[0][0]
            if forward or backward:
                raise ValueError("Existing Parquet cache disagrees with the database")
        return manifest
    export_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".pending-", dir=export_root))
    try:
        manifest = {"dataset_id": dataset_id, "duckdb": duckdb.__version__, "tables": {}}
        for table, query in queries.items():
            path = staging / f"{table}.parquet"
            connection.sql(query, params=[dataset_id]).write_parquet(str(path), compression="zstd")
            count = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchall()[0][0]
            manifest["tables"][table] = {"rows": count, "sha256": sha256(path)}
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        staging.rename(destination)
        return manifest
    except Exception:
        shutil.rmtree(staging)
        raise


def summary(connection, bundle, exports) -> dict:
    counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
              for table in ["ingestion_runs", "dataset_versions", "prices_daily", "corporate_actions"]}
    views = {view: connection.execute(f"SELECT count(*) FROM {view}").fetchall()[0][0]
             for view in ["accepted_prices_daily", "benchmark_context_daily", "quarantined_benchmark_daily", "active_quality_issues"]}
    diagnostics = connection.execute((SQL / "diagnostics.sql").read_text().split(";", 1)[0]).fetchall()
    return {"dataset_id": bundle["dataset_id"], "duckdb": duckdb.__version__, "table_counts": counts,
            "active_view_counts": views, "historical_inputs": [dict(zip(["instrument", "sessions", "daily_returns", "complete_20_return_windows"], row)) for row in diagnostics],
            "parquet_tables": exports["tables"]}


def write_report(result: dict) -> None:
    counts, views = result["table_counts"], result["active_view_counts"]
    rows = "\n".join(f"| {r['instrument']} | {r['sessions']:,} | {r['daily_returns']:,} | {r['complete_20_return_windows']:,} |" for r in result["historical_inputs"])
    text = f"""# SQL ingestion milestone

Updated November 4, 2026. Built from verified local snapshots without new market-data downloads.

## Observed result

- Dataset: `{result['dataset_id']}`; DuckDB {result['duckdb']}.
- Retained price observations across source captures: **{counts['prices_daily']:,}**.
- Accepted observations in the selected three-instrument dataset: **{views['accepted_prices_daily']:,}**.
- Accepted FRED index-context observations: **{views['benchmark_context_daily']:,}**.
- Yahoo index observations retained in quarantine: **{views['quarantined_benchmark_daily']:,}**.
- Active quality issues: **{views['active_quality_issues']}**, with original source values and evidence references retained.
- Parquet exports: **{len(result['parquet_tables'])}** versioned tables; detailed hashes and counts remain local.

| Instrument | Expected sessions | Valid daily returns | Complete 20-return windows |
| --- | ---: | ---: | ---: |
{rows}

The first session has no previous close and therefore no daily return. A trailing volatility estimate requires 20 valid one-session returns. The SQL uses `sqrt(252 * mean(return²))`, consistent with the project's squared-return convention; it is a historical input, not a trained forecast or portfolio risk report.

## Composition and data grain

| Table | Grain and purpose |
| --- | --- |
| ingestion_runs | One source capture, identified by source and capture ID, with manifest hash and settings |
| instruments | One instrument identity and calendar |
| prices_daily | One instrument/session/capture; earlier versions are retained |
| corporate_actions | One instrument/session/action type/capture |
| benchmark_observations | One series/date/capture, retaining FRED's null holiday rows |
| dataset_versions and dataset_runs | An explicit recipe and its source captures |
| source_rules | Versioned DS-001 rules for that dataset |
| expected_sessions | Instrument/session calendar alignment for a dataset |
| data_quality_issues | One discrepancy rule/date/dataset with source values, tolerance, and disposition |
| active_dataset | The explicitly selected dataset; no automatic latest-date selection |

```mermaid
flowchart LR
    A[Saved snapshots and manifests] --> B[Hash and audit validation]
    B --> C[Transactional DuckDB load]
    C --> D[Versioned source tables]
    D --> E[DS-001 accepted views]
    D --> F[Quarantined evidence and issue ledger]
    E --> G[Calendar-aligned SQL risk inputs]
    D --> H[Versioned Parquet cache]
```

## Guarantees and limits

- Inputs are hash-checked and re-audited before loading. A failed acceptance check prevents activation.
- Primary keys and conflict handling make identical loads idempotent. Different captures retain distinct records.
- Inserts and active-dataset selection use one database transaction. A database error rolls back that load.
- Parquet publication is a separate, recoverable cache step after database commit. Files are staged and published as a complete directory; existing files are hash-checked and compared with SQL rows on rerun. This is not a distributed transaction across the database and filesystem.
- Accepted risk prices, accepted FRED context, and quarantined Yahoo index observations have separate views. Context is not automatically approved as a predictive feature. The three discrepancies remain unresolved.
- The current scope is three instruments and explicit saved captures. General incremental provider ingestion, universe expansion, portfolio calculations, and model training remain subsequent work.

## Reproduction and inspection

```bash
.venv/bin/python -m scripts.build_warehouse --snapshot data/audit/20261104T170702705356Z --historical-snapshot data/audit/20261104T170309697872Z --external-snapshot data/validation/20261104T171500906975Z
# Run the same command again to verify duplicate-free loading and cached exports.
.venv/bin/python -m unittest discover -s tests -v
```

The database is local at `data/warehouse/portfolio-risk.duckdb`. Parquet tables and a manifest are under `data/normalized/<dataset-id>/`. Counts and provenance are saved in `data/warehouse/build-summary.json`. These artifacts are ignored by Git. Query examples are in [sql/diagnostics.sql](../sql/diagnostics.sql); the schema and view definitions are also plain SQL in that folder.

Read the [SQL walkthrough](03_SQL_WALKTHROUGH.md) and [source policy](DATA_SOURCE_POLICY.md) for interpretation. No source discrepancy has been silently corrected.
"""
    (ROOT / "docs/SQL_LAYER.md").write_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--external-snapshot", required=True, type=Path)
    parser.add_argument("--historical-snapshot", action="append", type=Path, default=[])
    parser.add_argument("--database", type=Path, default=ROOT / "data/warehouse/portfolio-risk.duckdb")
    parser.add_argument("--parquet-root", type=Path, default=ROOT / "data/normalized")
    args = parser.parse_args()
    bundle = prepare_bundle(args.snapshot.resolve(), args.external_snapshot.resolve(),
                            [p.resolve() for p in args.historical_snapshot], ROOT / "config/source_policy.json")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(args.database)) as connection:
        load_bundle(connection, bundle)
        exports = export_dataset(connection, bundle["dataset_id"], args.parquet_root)
        result = summary(connection, bundle, exports)
    write_report(result)
    (args.database.parent / "build-summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
