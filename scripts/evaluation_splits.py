"""Build date-only evaluation membership; never calculate test targets or scores.

Input snapshots are inspected for integrity, but no outcome values enter this
manifest. All intervals are start-inclusive and end-exclusive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from scripts.audit_market_data import ROOT, expected_sessions, inspect_snapshot, sha256


def validate_protocol(protocol: dict) -> None:
    if protocol.get("schema_version") != 1 or protocol.get("protocol_id") != "EV-001":
        raise ValueError("Unsupported evaluation protocol")
    dates = [pd.Timestamp(protocol[key]) for key in
             ["train_start", "validation_start", "test_start", "test_end_exclusive"]]
    if any(day.tz is not None or day != day.normalize() for day in dates) or not all(a < b for a, b in zip(dates, dates[1:])):
        raise ValueError("Require ordered date-only split boundaries")
    if [str(day.date()) for day in dates] != ["2020-01-01", "2025-01-01", "2026-01-01", "2027-01-01"]:
        raise ValueError("EV-001 reserves calendar 2026; version changes require explicit review")
    for key, expected in [("target_horizon_sessions", 20), ("feature_warmup_returns", 252), ("primary_origin_stride_sessions", 20)]:
        if type(protocol.get(key)) is not int or protocol[key] != expected:
            raise ValueError(f"EV-001 requires {key}={expected}")
    if protocol.get("development_validation_years") != [2023, 2024, 2025]:
        raise ValueError("Development folds must stay before 2026")
    if protocol.get("final_test_scores_opened") is not False:
        raise ValueError("Final test scores are reserved; opening them requires a reviewed protocol change")
    required = {
        "final_fit": "refit_selected_recipe_on_eligible_pre_2026_labels",
        "test_retraining": "none",
        "primary_metric": "equal_instrument_mean_annualized_volatility_mae",
        "secondary_metric": "equal_instrument_mean_variance_qlike",
    }
    if any(protocol.get(key) != value for key, value in required.items()):
        raise ValueError("Unsupported evaluation semantics")


def split_membership(calendar: pd.DatetimeIndex, observed: pd.DatetimeIndex, protocol: dict) -> pd.DataFrame:
    """Require exact observed sessions; retain unavailable horizon tails explicitly."""
    validate_protocol(protocol)
    for index in [calendar, observed]:
        if index.empty or index.has_duplicates or not index.is_monotonic_increasing or index.tz is not None:
            raise ValueError("Sessions must be nonempty, unique, sorted, timezone-free")
    if not observed.equals(calendar[(calendar >= observed[0]) & (calendar <= observed[-1])]):
        raise ValueError("Missing or unexpected observed sessions; no compressed horizons")
    offsets = calendar.get_indexer(observed)
    horizon = protocol["target_horizon_sessions"]
    if (offsets < 0).any() or offsets[-1] + horizon >= len(calendar):
        raise ValueError("Reference calendar must extend through every target horizon")
    ends = calendar.take(offsets + horizon)
    # Warmup counts prior one-session returns from the actual snapshot start.
    ready = pd.Series(range(len(observed))).ge(protocol["feature_warmup_returns"]).to_numpy()
    complete = ends <= observed[-1]
    origin = observed
    train_start, validation, test, test_end = [pd.Timestamp(protocol[k]) for k in
                                            ["train_start", "validation_start", "test_start", "test_end_exclusive"]]
    frame = pd.DataFrame({"origin_date": origin, "target_end_date": ends,
                          "feature_history_ready": ready, "target_complete": complete})
    in_train = (origin >= train_start) & (origin < validation)
    in_validation = (origin >= validation) & (origin < test)
    in_test = (origin >= test) & (origin < test_end)
    frame["partition"] = "outside"
    for mask, name in [(in_train, "train"), (in_validation, "validation"), (in_test, "test")]:
        frame.loc[mask, "partition"] = name
    frame["train_eligible"] = in_train & ready & complete & (ends < validation)
    frame["validation_eligible"] = in_validation & ready & complete & (ends < test)
    frame["final_refit_eligible"] = (origin >= train_start) & (origin < test) & ready & complete & (ends < test)
    frame["test_eligible_when_opened"] = in_test & ready & complete & (ends < test_end)
    # Anchor the grid before checking completeness: later data never shifts origins.
    frame["primary_test_origin"] = False
    test_rows = frame.index[in_test & ready]
    frame.loc[test_rows[::protocol["primary_origin_stride_sessions"]], "primary_test_origin"] = True
    frame["primary_test_scorable_when_opened"] = frame.primary_test_origin & frame.test_eligible_when_opened
    for year in protocol["development_validation_years"]:
        begin, end = pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year+1}-01-01")
        frame[f"fold_{year}_train"] = (origin >= train_start) & (origin < begin) & ready & complete & (ends < begin)
        frame[f"fold_{year}_validation"] = (origin >= begin) & (origin < end) & ready & complete & (ends < end)
    return frame


def build_manifest(snapshot: Path, protocol: dict) -> tuple[dict, pd.DataFrame]:
    manifest = json.loads((snapshot / "manifest.json").read_text())
    audit = inspect_snapshot(snapshot, manifest)
    if not audit["structural_checks_pass"]:
        raise ValueError("Snapshot fails structural checks; split construction stopped")
    frames, counts = [], []
    # Extend the session reference, not the price history, for pending horizons.
    calendar_end = (pd.Timestamp(protocol["test_end_exclusive"]) + pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    for symbol, record in manifest["instruments"].items():
        observed = expected_sessions(manifest["start_inclusive"], manifest["end_exclusive"], record["calendar"])
        calendar = expected_sessions(manifest["start_inclusive"], calendar_end, record["calendar"])
        frame = split_membership(calendar, observed, protocol)
        frame.insert(0, "instrument_id", symbol)
        frames.append(frame)
        boolean_fields = [name for name in frame if pd.api.types.is_bool_dtype(frame[name])]
        row = {"instrument": symbol, **{name: int(frame[name].sum()) for name in boolean_fields}}
        row["pending_test_targets"] = int(((frame.partition == "test") & ~frame.target_complete).sum())
        row["test_boundary_exclusions"] = int(((frame.partition == "test") & (frame.target_end_date >= pd.Timestamp(protocol["test_end_exclusive"]))).sum())
        counts.append(row)
    recipe = {"snapshot_manifest_sha256": sha256(snapshot / "manifest.json"), "protocol": protocol,
              "split_script_sha256": sha256(Path(__file__)), "audit_script_sha256": sha256(ROOT / "scripts/audit_market_data.py"),
              "snapshot_run": snapshot.name, "exchange_calendars_version": manifest["packages"]["exchange-calendars"]}
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    return {"manifest_id": identity, "recipe": recipe, "counts": counts,
            "model_scores_computed": False, "audit_review_flags": audit["review_flags"],
            "acceptance_note": "Date eligibility is not source-price acceptance or permission to train on flagged data."}, pd.concat(frames, ignore_index=True)


def write_report(result: dict, destination: Path) -> None:
    lines = []
    for row in result["counts"]:
        lines.append(f"| {row['instrument']} | {row['train_eligible']} | {row['validation_eligible']} | {row['final_refit_eligible']} | {row['test_eligible_when_opened']} | {row['primary_test_scorable_when_opened']} | {row['pending_test_targets']} |")
    destination.write_text(f"""# Evaluation date eligibility

Updated November 4, 2026. This date-only manifest reserves 2026 for final model evaluation. No test targets, forecasts, or model scores are calculated here. These are row-eligibility counts, not sample independence or model results.

- Snapshot: `{result['recipe']['snapshot_run']}`.
- Manifest: `{result['manifest_id']}`.
- Protocol: [EV-001](../config/evaluation_protocol.json).
- Source audit review flags: **{result['audit_review_flags']}**. Date eligibility does not approve flagged source data.

| Instrument | Train 2020–24 | Validate 2025 | Final refit pre-2026 | Eligible test dates | Completed primary test origins | Pending test outcomes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(lines)}

Training and validation counts exclude origins whose next-20-session label reaches the next partition. Final refitting may use eligible pre-2026 labels only after the recipe is selected. Features require 252 prior returns; outcomes require 20 future sessions. The primary test grid uses every twentieth origin, anchored before excluding incomplete targets; each included target window is non-overlapping within an instrument. Cross-instrument outcomes remain correlated.

Development folds validate on 2023, 2024, and 2025, each trained on eligible earlier labels. The selected model is frozen for the 2026 historical test: rolling inputs are permitted, model fitting or tuning on 2026 outcomes is not. Year-end-crossing targets are excluded even when later observations become available. The last 20 observed origins currently lack completed targets.

See the [evaluation protocol and testing plan](EVALUATION_PROTOCOL.md) for model comparisons, leakage checks, uncertainty limitations, and the conditions for opening final scores. Membership CSVs and full recipes stay local under `data/evaluation/<manifest-id>/`.
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=ROOT / "config/evaluation_protocol.json")
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text())
    validate_protocol(protocol)
    result, membership = build_manifest(args.snapshot, protocol)
    folder = ROOT / "data/evaluation" / result["manifest_id"]
    folder.mkdir(parents=True, exist_ok=True)
    membership.to_csv(folder / "membership.csv", index=False)
    (folder / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    write_report(result, ROOT / "docs/EVALUATION_SPLITS.md")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
