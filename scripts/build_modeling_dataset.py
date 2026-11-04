"""Build separate causal features, development-only targets, and split membership.

The market warehouse is read-only. Final 2026 outcomes and model scores remain
uncomputed; outputs are versioned local research artifacts, not a trained model.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import tempfile

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, expected_sessions, sha256
from scripts.evaluation_splits import split_membership, validate_protocol

FEATURE_COLUMNS = ["return_1", "return_5", "return_20", "return_60",
                   "variance_5", "variance_20", "variance_60", "variance_252",
                   "downside_variance_20", "negative_fraction_20", "drawdown_60", "max_abs_return_20"]
KEYS = ["dataset_id", "instrument_id", "origin_date"]
SQL = ROOT / "sql"


def sql_tables(prices: pd.DataFrame, protocol: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    validate_protocol(protocol)
    if prices.duplicated(["dataset_id", "instrument_id", "session_date"]).any():
        raise ValueError("Duplicate instrument/session inputs")
    with duckdb.connect() as connection:
        connection.register("modeling_prices", prices)
        features = connection.execute((SQL / "modeling_features.sql").read_text()).df()
        targets = connection.execute((SQL / "modeling_targets.sql").read_text(), [protocol["test_start"]]).df()
    return features, targets


def reference_tables(prices: pd.DataFrame, protocol: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Independent scalar slices/NumPy, including explicit gap barriers."""
    feature_rows, target_rows = [], []
    for (dataset, symbol), group in prices.groupby(["dataset_id", "instrument_id"], sort=True):
        group = group.sort_values("session_date")
        dates = pd.DatetimeIndex(group.session_date)
        values = group.adjusted_close.to_numpy(dtype=float)
        returns = np.r_[np.nan, values[1:]/values[:-1]-1]
        for index, day in enumerate(dates):
            row = {"dataset_id": dataset, "instrument_id": symbol, "origin_date": day,
                   **dict.fromkeys(FEATURE_COLUMNS, np.nan), "feature_ready": False}
            row["return_1"] = returns[index]
            for window in [5, 20, 60, 252]:
                sample = returns[max(0,index-window+1):index+1]
                if len(sample) == window and np.isfinite(sample).all():
                    row[f"variance_{window}"] = 252 * float(np.dot(sample, sample)) / window
                    if window in [5,20,60]:
                        # Product of consecutive returns is independent of SQL's lagged-price ratio.
                        row[f"return_{window}"] = float(np.prod(1+sample))-1
                    if window == 20:
                        row["downside_variance_20"] = 252 * float(np.sum(np.minimum(sample,0)**2)) / 20
                        row["negative_fraction_20"] = float(np.sum(sample < 0)) / 20
                        row["max_abs_return_20"] = float(np.max(np.abs(sample)))
                    if window == 252:
                        row["feature_ready"] = True
            peak_prices = values[max(0,index-60):index+1]
            if len(peak_prices) == 61 and np.isfinite(peak_prices).all():
                row["drawdown_60"] = values[index]/max(peak_prices)-1
            feature_rows.append(row)
        # Clip first, so even this reference implementation never derives 2026 outcomes.
        mask = dates < pd.Timestamp(protocol["test_start"])
        development_dates, development_values = dates[mask], values[mask]
        development_returns = np.r_[np.nan, development_values[1:]/development_values[:-1]-1]
        for index, day in enumerate(development_dates):
            sample = development_returns[index+1:index+21]
            complete = len(sample) == 20 and np.isfinite(sample).all()
            variance = 252 * float(np.dot(sample,sample)) / 20 if complete else np.nan
            target_rows.append({"dataset_id":dataset, "instrument_id":symbol, "origin_date":day,
                                "target_variance":variance, "target_volatility":np.sqrt(variance)})
    return pd.DataFrame(feature_rows), pd.DataFrame(target_rows)


def reconcile(prices, features, targets, protocol) -> dict:
    reference_features, reference_targets = reference_tables(prices, protocol)
    for actual, reference, columns in [(features,reference_features,FEATURE_COLUMNS),
                                       (targets,reference_targets,["target_variance","target_volatility"])]:
        left = actual.set_index(KEYS).sort_index()
        right = reference.set_index(KEYS).sort_index()
        if not left.index.equals(right.index):
            raise ValueError("Independent calculation keys differ")
        np.testing.assert_allclose(left[columns].to_numpy(),right[columns].to_numpy(),rtol=0,atol=1e-12,equal_nan=True)
    np.testing.assert_array_equal(features.feature_ready.to_numpy(),reference_features.feature_ready.to_numpy())
    return {"all_checks_pass":True, "feature_cells_compared":int(len(features)*len(FEATURE_COLUMNS)),
            "development_target_rows_compared":len(targets), "absolute_tolerance":1e-12}


def make_membership(prices, instruments, manifest, protocol) -> pd.DataFrame:
    frames = []
    calendar_end = (pd.Timestamp(protocol["test_end_exclusive"])+pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    for symbol, group in prices.groupby("instrument_id", sort=True):
        calendar = instruments[symbol]["calendar"]
        observed = pd.DatetimeIndex(group.sort_values("session_date").session_date)
        expected = expected_sessions(manifest["start_inclusive"],manifest["end_exclusive"],calendar)
        if not observed.equals(expected):
            raise ValueError("Market input dates differ from the full expected session index")
        future_calendar = expected_sessions(manifest["start_inclusive"],calendar_end,calendar)
        frame = split_membership(future_calendar,observed,protocol)
        frame.insert(0,"instrument_id",symbol)
        frame.insert(0,"dataset_id",group.dataset_id.iloc[0])
        frames.append(frame)
    return pd.concat(frames,ignore_index=True)


def assemble(features, raw_targets, membership, protocol):
    dates = membership[KEYS+["target_end_date"]]
    targets = dates.merge(raw_targets,on=KEYS,how="left",validate="one_to_one")
    reserved = targets.origin_date >= pd.Timestamp(protocol["test_start"])
    crosses = ~reserved & (targets.target_end_date >= pd.Timestamp(protocol["test_start"]))
    complete = targets.target_variance.notna()
    targets["target_status"] = np.select([reserved,crosses,complete],
                                         ["reserved_test","crosses_test_boundary","development_complete"],
                                         default="incomplete_development")
    if targets.loc[reserved | crosses,"target_variance"].notna().any():
        raise ValueError("Reserved outcome values must remain uncomputed")
    labeled = targets.target_variance.notna()
    np.testing.assert_array_equal(targets.loc[labeled,"target_end_date"].to_numpy(),
                                  targets.loc[labeled,"observed_target_end"].to_numpy(),
                                  err_msg="Forward-window endpoint differs from session membership")
    joined = features.merge(membership,on=KEYS,how="inner",validate="one_to_one")
    if len(joined)!=len(features) or len(joined)!=len(membership):
        raise ValueError("Incomplete feature/membership keys")
    if not np.array_equal(joined.feature_ready,joined.feature_history_ready):
        raise ValueError("Calculated feature readiness differs from date-only warmup")
    if not np.isfinite(joined.loc[joined.feature_ready,FEATURE_COLUMNS].to_numpy()).all():
        raise ValueError("Ready features contain missing/nonfinite values")
    development = joined.merge(targets[KEYS+["target_variance","target_volatility"]],on=KEYS,validate="one_to_one")
    for flag in ["train_eligible","validation_eligible","final_refit_eligible"]:
        rows = development[development[flag]]
        if not rows.feature_ready.all() or rows.target_variance.isna().any():
            raise ValueError("Date-eligible development rows lack complete inputs or labels")
    # Test targets are not included in any development/training view.
    development = development[development.origin_date < pd.Timestamp(protocol["test_start"])].reset_index(drop=True)
    return targets, development


def read_market_inputs(connection, protocol):
    records = connection.execute("""SELECT d.dataset_id,d.recipe_json,r.manifest_json
        FROM active_dataset a JOIN dataset_versions d USING(dataset_id)
        JOIN ingestion_runs r ON r.run_id=d.primary_run_id""").fetchall()
    if len(records)!=1:
        raise ValueError("Require one explicitly selected market dataset")
    dataset, recipe, raw_manifest = records[0]
    manifest = json.loads(raw_manifest)
    if manifest["start_inclusive"] != protocol["train_start"]:
        raise ValueError("History start differs from the frozen evaluation context")
    prices = connection.execute("""SELECT e.dataset_id,e.instrument_id,e.session_date,p.adjusted_close
        FROM expected_sessions e JOIN active_dataset a USING(dataset_id)
        LEFT JOIN accepted_prices_daily p USING(dataset_id,instrument_id,session_date)
        ORDER BY e.instrument_id,e.session_date""").df()
    if prices.empty or prices.adjusted_close.isna().any() or not np.isfinite(prices.adjusted_close).all() or (prices.adjusted_close<=0).any():
        raise ValueError("Accepted market history is incomplete or invalid; do not fill gaps")
    if set(prices.instrument_id)!=set(manifest["instruments"]):
        raise ValueError("Accepted scope differs from the selected manifest")
    return dataset, manifest, prices, json.loads(recipe)


def build(connection, protocol):
    validate_protocol(protocol)
    dataset,manifest,prices,market_recipe = read_market_inputs(connection,protocol)
    features, raw_targets = sql_tables(prices,protocol)
    reconciliation = reconcile(prices,features,raw_targets,protocol)
    membership = make_membership(prices,manifest["instruments"],manifest,protocol)
    targets, development = assemble(features,raw_targets,membership,protocol)
    # Real-data perturbation at a predetermined development cutoff, not selected by scores.
    cutoff = pd.Timestamp("2024-06-28")
    perturbed = prices.copy()
    later = perturbed.session_date > cutoff
    perturbed.loc[later,"adjusted_close"] *= 1.5 + np.arange(int(later.sum()))*.0001
    mutated_features,_ = sql_tables(perturbed,protocol)
    before = features[features.origin_date<=cutoff].set_index(KEYS)[FEATURE_COLUMNS]
    after = mutated_features[mutated_features.origin_date<=cutoff].set_index(KEYS)[FEATURE_COLUMNS]
    pd.testing.assert_frame_equal(before,after,check_exact=True)
    counts = []
    for symbol, group in membership.groupby("instrument_id",sort=True):
        f = features[features.instrument_id==symbol]
        t = targets[targets.instrument_id==symbol]
        counts.append({"instrument":symbol,"sessions":len(f),"ready_features":int(f.feature_ready.sum()),
                       "development_labels":int(t.target_variance.notna().sum()),
                       **{key:int(group[key].sum()) for key in ["train_eligible","validation_eligible","final_refit_eligible","test_eligible_when_opened","primary_test_scorable_when_opened"]}})
    recipe = {"schema_version":1,"market_dataset_id":dataset,"market_recipe":market_recipe,"protocol":protocol,
              "feature_columns":FEATURE_COLUMNS,"inputs_sha256":hashlib.sha256(prices.to_csv(index=False).encode()).hexdigest(),
              "feature_sql_sha256":sha256(SQL/"modeling_features.sql"),"target_sql_sha256":sha256(SQL/"modeling_targets.sql"),
              "builder_sha256":sha256(Path(__file__)),"split_code_sha256":sha256(ROOT/"scripts/evaluation_splits.py"),
              "packages":{name:version(name) for name in ["duckdb","numpy","pandas","exchange-calendars"]}}
    identity = hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
    manual = development[(development.instrument_id=="AAPL") & development.origin_date.isin(pd.to_datetime([
        "2020-08-31","2024-12-02","2024-12-03","2025-12-02","2025-12-03"]))]
    evidence = [{key:(str(value.date()) if isinstance(value,pd.Timestamp) else bool(value) if isinstance(value,(bool,np.bool_)) else None if pd.isna(value) else float(value))
                 for key,value in row.items()}
                for row in manual[["origin_date","target_end_date","feature_ready","train_eligible","validation_eligible","return_1","variance_20","target_variance"]].to_dict("records")]
    result={"modeling_dataset_id":identity,"recipe":recipe,"counts":counts,"reconciliation":reconciliation,
            "future_perturbation_pass":True,"manual_boundary_checks":evidence,
            "reserved_numeric_targets":int(targets.loc[targets.origin_date>=pd.Timestamp(protocol['test_start']),"target_variance"].notna().sum()),
            "model_trained":False,"model_scores_computed":False}
    return result,{"features_daily":features,"targets_development":targets,"split_membership":membership,"development_examples":development}


def export(result,frames,root):
    destination = root/result["modeling_dataset_id"]
    if destination.exists():
        manifest=json.loads((destination/"manifest.json").read_text())
        if manifest["modeling_dataset_id"]!=result["modeling_dataset_id"] or manifest["recipe"]!=result["recipe"]:
            raise ValueError("Existing modeling artifact identity or recipe differs")
        if sha256(destination/"modeling.duckdb")!=manifest["database_sha256"]:
            raise ValueError("Saved modeling database hash differs")
        if set(manifest["exports"])!=set(frames):
            raise ValueError("Modeling export inventory differs")
        with duckdb.connect() as connection:
            for name,frame in frames.items():
                path=destination/(name+".parquet")
                if sha256(path)!=manifest["exports"][name]["sha256"]:
                    raise ValueError("Saved modeling export hash differs")
                restored=connection.execute("SELECT * FROM read_parquet(?)",[str(path)]).df()
                pd.testing.assert_frame_equal(restored,frame,check_dtype=False,check_exact=True)
        return manifest
    root.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix=".pending-",dir=root))
    try:
        exports={}
        with duckdb.connect(str(staging/"modeling.duckdb")) as connection:
            for name,frame in frames.items():
                connection.register("incoming",frame)
                connection.execute(f"CREATE TABLE {name} AS SELECT * FROM incoming").fetchall()
                connection.unregister("incoming")
                connection.sql(f"SELECT * FROM {name}").write_parquet(str(staging/(name+".parquet")),compression="zstd")
                exports[name]={"rows":len(frame),"sha256":sha256(staging/(name+".parquet"))}
            connection.execute("CREATE VIEW training_examples AS SELECT * FROM development_examples WHERE train_eligible").fetchall()
            connection.execute("CREATE VIEW validation_examples AS SELECT * FROM development_examples WHERE validation_eligible").fetchall()
            connection.execute("CREATE VIEW final_refit_examples AS SELECT * FROM development_examples WHERE final_refit_eligible").fetchall()
        manifest={**result,"exports":exports,"database_sha256":sha256(staging/"modeling.duckdb")}
        (staging/"manifest.json").write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n")
        staging.rename(destination)
        return manifest
    except Exception:
        shutil.rmtree(staging)
        raise


def write_report(result):
    rows="\n".join(f"| {r['instrument']} | {r['ready_features']} | {r['development_labels']} | {r['train_eligible']} | {r['validation_eligible']} | {r['final_refit_eligible']} |" for r in result['counts'])
    checks="\n".join(f"| {r['origin_date']} | {r['target_end_date']} | {r['feature_ready']} | {r['train_eligible']} | {r['validation_eligible']} | {'Computed' if r['target_variance'] is not None else 'Withheld'} |" for r in result['manual_boundary_checks'])
    (ROOT/'docs/MODELING_DATASET.md').write_text(f"""# Price-based modeling dataset

Updated November 4, 2026. Features and development targets are implemented and independently reconciled. No model has been trained or scored. Final 2026 outcome values remain uncomputed.

## Observed result

- Market dataset: `{result['recipe']['market_dataset_id']}`.
- Modeling dataset: `{result['modeling_dataset_id']}`.
- Predictor whitelist: **{len(FEATURE_COLUMNS)}** numeric features; future target/date/eligibility fields are excluded.
- Feature cells compared with NumPy, including matching null positions: **{result['reconciliation']['feature_cells_compared']:,}**.
- Pre-2026 target rows independently compared, including incomplete tails: **{result['reconciliation']['development_target_rows_compared']:,}**.
- Reserved 2026 numeric targets: **{result['reserved_numeric_targets']}**. No model scores computed.
- Future-price perturbation at a fixed development cutoff leaves earlier features exactly unchanged.

| Instrument | Feature-ready rows | Computed development labels | Initial training | Main validation | Final refit eligible |
| --- | ---: | ---: | ---: | ---: | ---: |
{rows}

Feature-ready rows include 2026 observations; development labels do not. Labels before full feature warmup are preserved for diagnostics but are not eligible training examples. Final refit includes pre-2026 rows excluded at the earlier training/validation boundary, after model selection only.

## Boundary and corporate-action examples

All rows below are AAPL; values are checked against independently sliced NumPy calculations. The split-date example tests the provider-adjusted return convention without applying the split a second time. It is not eligible training data because the 252-return warmup is incomplete.

| Origin | Target end | Features ready | Initial train eligible | Main validation eligible | Target value |
| --- | --- | --- | --- | --- | --- |
{checks}

Each target covers returns t+1 through t+20, excluding the origin return. Dates follow expected exchange sessions. Initial training labels reaching 2025 are excluded; validation/refit labels reaching 2026 are withheld. All 2026 origins retain features and membership only, with no numerical target. The last twenty observed origins also lack complete future horizons, as the separate date manifest records.

## Composition and reproducibility

The market database is read-only. Local modeling artifacts contain separate feature, development-target, split-membership, and joined development-example tables/Parquet files. Training, validation, and final-refit views select explicit membership flags. Model inputs must use the predictor whitelist; the joined diagnostic table contains metadata and future labels that must never be inferred as predictors.

Identity includes the accepted dataset/recipe, actual input hash, protocol, SQL definitions, builder/split code, and package versions. Existing exports are hash- and content-checked; different recipes produce distinct folders. Downloaded histories and derived modeling rows stay outside Git.

```bash
.venv/bin/python -m scripts.build_modeling_dataset
.venv/bin/python -m unittest discover -s tests -v
```

See the [feature dictionary and walkthrough](06_MODELING_DATASET_WALKTHROUGH.md) and [EV-001](EVALUATION_PROTOCOL.md). The features use revised adjusted histories, so transformation causality does not establish historical vendor availability. No preprocessing is fitted here; fit any future preprocessing on each training partition only. News, FRED/macro inputs, portfolio suggestions, and expected-return forecasts are absent from this feature version.
""")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'data/warehouse/portfolio-risk.duckdb')
    parser.add_argument('--output',type=Path,default=ROOT/'data/modeling')
    args=parser.parse_args()
    protocol=json.loads((ROOT/'config/evaluation_protocol.json').read_text())
    with duckdb.connect(str(args.database),read_only=True) as connection:result,frames=build(connection,protocol)
    export(result,frames,args.output)
    write_report(result)
    print(json.dumps({key:result[key] for key in ['modeling_dataset_id','counts','reconciliation','future_perturbation_pass','reserved_numeric_targets','model_trained','model_scores_computed']},indent=2))


if __name__=='__main__':main()
