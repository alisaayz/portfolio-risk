"""Evaluate fixed-form variance forecasts on development years only.

All candidates, matching origins, scores, and selection rules are recorded.
Final 2026 outcomes/predictions/scores are not computed by this module.
"""
from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
import math
import os
import platform
from pathlib import Path
import shutil
import tempfile

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256
from scripts.evaluation_splits import validate_protocol

KEYS = ["instrument_id", "origin_date"]


def validate_configuration(config):
    expected = {
        "baseline_protocol_id":"BL-001", "schema_version":1,
        "development_years":[2023,2024,2025], "ewma_decays":[.90,.94,.97],
        "ewma_initialization":"first_valid_annualized_squared_return", "ewma_adjust":False,
        "missing_return_rule":"reset_state_and_consecutive_history",
        "target_assumption":"current_variance_persists_over_next_20_sessions",
        "primary_stride_sessions":20,
        "primary_grid_anchor":"first_feature_ready_origin_in_each_calendar_year_before_label_filtering",
        "ewma_selection_year":2025,
        "ewma_selection_metric":"equal_instrument_mean_annualized_volatility_mae",
        "selection_tiebreak":"ascending_method_id", "qlike_prediction_floor":1e-12,
    }
    if config != expected:
        raise ValueError("Unsupported BL-001 semantics; record a reviewed protocol version before changing the experiment")


def ewma_variance(annual_squared_returns, decay):
    if not math.isfinite(decay) or not 0 < decay < 1:
        raise ValueError("EWMA decay must be strictly between zero and one")
    values = np.asarray(annual_squared_returns,dtype=float)
    if np.isinf(values).any() or (values[np.isfinite(values)]<0).any():
        raise ValueError("Variance observations must be nonnegative and finite or explicitly missing")
    output = np.full(len(values),np.nan)
    consecutive = np.zeros(len(values),dtype=int)
    state, count = np.nan, 0
    for index,value in enumerate(values):
        if np.isnan(value):
            state,count = np.nan,0
            continue
        state = value if np.isnan(state) else decay*state+(1-decay)*value
        count += 1
        output[index],consecutive[index] = state,count
    return output,consecutive


def generate_forecasts(features, config, protocol):
    validate_configuration(config);validate_protocol(protocol)
    if features.duplicated(KEYS).any():
        raise ValueError("Duplicate forecast-source keys")
    # Clip before any forecast calculation or output.
    development = features[features.origin_date < pd.Timestamp(protocol["test_start"])].copy()
    frames=[]
    for symbol,group in development.groupby("instrument_id",sort=True):
        group=group.sort_values("origin_date")
        ready=group.feature_ready.to_numpy(dtype=bool)
        trailing=group.variance_20.to_numpy(dtype=float)
        if not np.isfinite(trailing[ready]).all() or (trailing[ready]<0).any():
            raise ValueError("Invalid trailing-variance forecasts")
        forecasts={"trailing_20":trailing}
        squared=252*group.return_1.to_numpy(dtype=float)**2
        for decay in config["ewma_decays"]:
            values,counts=ewma_variance(squared,decay)
            if (counts[ready]<protocol["feature_warmup_returns"]).any():
                raise ValueError("Declared ready rows have an interrupted EWMA history")
            # Independent library implementation on each contiguous valid run.
            reference=np.full(len(squared),np.nan)
            start=0
            while start<len(squared):
                if not np.isfinite(squared[start]):start+=1;continue
                end=start+1
                while end<len(squared) and np.isfinite(squared[end]):end+=1
                reference[start:end]=pd.Series(squared[start:end]).ewm(alpha=1-decay,adjust=False).mean().to_numpy()
                start=end
            np.testing.assert_allclose(values,reference,rtol=0,atol=1e-12,equal_nan=True)
            forecasts[f"ewma_{decay:.2f}"]=values
        for method,values in forecasts.items():
            frame=group.loc[ready,KEYS].copy()
            frame["method"]=method
            frame["predicted_variance"]=values[ready]
            frames.append(frame)
    return pd.concat(frames,ignore_index=True).sort_values(["method",*KEYS]).reset_index(drop=True)


def evaluation_origins(membership, year, mode, config):
    validate_configuration(config)
    if year not in config["development_years"] or year>=2026 or mode not in {"primary","daily"}:
        raise ValueError("Only declared pre-2026 development comparisons are permitted")
    if membership.duplicated(KEYS).any():raise ValueError("Duplicate membership keys")
    start,end=pd.Timestamp(f"{year}-01-01"),pd.Timestamp(f"{year+1}-01-01")
    frame=membership[membership.origin_date.between(start,end,inclusive="left") & membership.feature_history_ready].copy()
    frame=frame.sort_values(KEYS)
    frame["primary_grid"] = frame.groupby("instrument_id").cumcount()%config["primary_stride_sessions"]==0
    # Anchor first, then apply label availability/year-boundary exclusions.
    selected=frame[f"fold_{year}_validation"] & (frame.primary_grid if mode=="primary" else True)
    frame=frame.loc[selected,KEYS+["target_end_date"]].copy()
    if frame.empty or (frame.target_end_date>=end).any():raise ValueError("Invalid development target endpoints")
    if mode=="primary":
        for _,group in frame.groupby("instrument_id"):
            if not (group.target_end_date.iloc[:-1].to_numpy()<=group.origin_date.iloc[1:].to_numpy()).all():
                raise ValueError("Primary target windows overlap")
    frame["year"],frame["evaluation_mode"]=year,mode
    return frame.reset_index(drop=True)


def score_common_origins(predictions, origins, targets, methods, floor):
    if predictions.duplicated(["method",*KEYS]).any() or targets.duplicated(KEYS).any() or origins.duplicated(KEYS).any():
        raise ValueError("Duplicate evaluation keys")
    if set(predictions.method)!=set(methods):raise ValueError("Forecast method inventory differs")
    if (origins.origin_date>=pd.Timestamp("2026-01-01")).any() or (origins.target_end_date>=pd.Timestamp("2026-01-01")).any():
        raise ValueError("Final-test scores are reserved")
    truth=origins.merge(targets[KEYS+["target_variance"]],on=KEYS,how="left",validate="one_to_one")
    if not np.isfinite(truth.target_variance).all() or (truth.target_variance<0).any():
        raise ValueError("Every evaluation origin needs a valid realized target")
    frames=[]
    for method in methods:
        forecasts=predictions[predictions.method==method]
        frame=truth.merge(forecasts,on=KEYS,how="left",validate="one_to_one")
        predicted=frame.predicted_variance.to_numpy(dtype=float)
        actual=frame.target_variance.to_numpy(dtype=float)
        if not np.isfinite(predicted).all() or (predicted<0).any():
            raise ValueError("Missing, nonfinite, or negative forecast; common sample cannot be reduced")
        safe=np.maximum(predicted,floor)
        frame["volatility_absolute_error_pp"]=100*np.abs(np.sqrt(predicted)-np.sqrt(actual))
        frame["variance_qlike"]=np.log(safe)+actual/safe
        frame["prediction_floored"]=predicted<floor
        frame["method"]=method
        frames.append(frame)
    return pd.concat(frames,ignore_index=True)


def metric_tables(errors, kinds):
    per_instrument=errors.groupby(["year","evaluation_mode","method","instrument_id"],sort=True).agg(
        observations=("target_variance","size"),volatility_mae_pp=("volatility_absolute_error_pp","mean"),
        variance_qlike=("variance_qlike","mean"),prediction_floors=("prediction_floored","sum")).reset_index()
    overall=per_instrument.groupby(["year","evaluation_mode","method"],sort=True).agg(
        instruments=("instrument_id","size"),observations=("observations","sum"),
        volatility_mae_pp=("volatility_mae_pp","mean"),variance_qlike=("variance_qlike","mean"),
        prediction_floors=("prediction_floors","sum")).reset_index()
    per_instrument["exposure_group"]=per_instrument.instrument_id.map(kinds)
    if per_instrument.exposure_group.isna().any():raise ValueError("Missing predeclared instrument grouping")
    groups=per_instrument.groupby(["year","evaluation_mode","method","exposure_group"],sort=True).agg(
        instruments=("instrument_id","size"),observations=("observations","sum"),
        volatility_mae_pp=("volatility_mae_pp","mean"),variance_qlike=("variance_qlike","mean")).reset_index()
    return overall,per_instrument,groups


def select_ewma(overall,config):
    choices=overall[(overall.year==config["ewma_selection_year"]) & (overall.evaluation_mode=="primary") & overall.method.str.startswith("ewma_")]
    expected={f"ewma_{value:.2f}" for value in config["ewma_decays"]}
    if set(choices.method)!=expected or choices.method.duplicated().any():raise ValueError("Incomplete EWMA selection candidates")
    return choices.sort_values(["volatility_mae_pp","method"],kind="stable").iloc[0].method


def load_modeling_artifacts(folder):
    manifest=json.loads((folder/"manifest.json").read_text())
    identity=hashlib.sha256(json.dumps(manifest["recipe"],sort_keys=True).encode()).hexdigest()
    if manifest["modeling_dataset_id"]!=identity or folder.name!=identity:
        raise ValueError("Modeling artifact identity/recipe differs")
    if sha256(folder/"modeling.duckdb")!=manifest["database_sha256"]:
        raise ValueError("Modeling database hash differs")
    required={"features_daily","targets_development","split_membership","development_examples"}
    if set(manifest["exports"])!=required:raise ValueError("Incomplete modeling artifact inventory")
    frames={}
    with duckdb.connect() as connection:
        for name in sorted(required):
            path=folder/(name+".parquet")
            if sha256(path)!=manifest["exports"][name]["sha256"]:raise ValueError("Modeling export hash differs")
            frame=connection.execute("SELECT * FROM read_parquet(?)",[str(path)]).df()
            if len(frame)!=manifest["exports"][name]["rows"]:raise ValueError("Modeling row count differs")
            frames[name]=frame
    protocol=manifest["recipe"]["protocol"];validate_protocol(protocol)
    if frames["targets_development"].loc[frames["targets_development"].origin_date>=pd.Timestamp(protocol["test_start"]),"target_variance"].notna().any():
        raise ValueError("Reserved target values must remain uncomputed")
    return manifest,frames


def evaluate(folder,config):
    validate_configuration(config)
    manifest,frames=load_modeling_artifacts(folder)
    protocol=manifest["recipe"]["protocol"]
    forecasts=generate_forecasts(frames["features_daily"],config,protocol)
    methods=["trailing_20",*[f"ewma_{d:.2f}" for d in config["ewma_decays"]]]
    origins=pd.concat([evaluation_origins(frames["split_membership"],year,mode,config)
                       for year in config["development_years"] for mode in ["primary","daily"]],ignore_index=True)
    errors=[]
    for (_,mode),group in origins.groupby(["year","evaluation_mode"],sort=True):
        errors.append(score_common_origins(forecasts,group,frames["targets_development"],methods,config["qlike_prediction_floor"]))
    errors=pd.concat(errors,ignore_index=True)
    universe=json.loads((ROOT/"config/reference_universe.json").read_text())
    overall,per_instrument,groups=metric_tables(errors,{r["symbol"]:r["kind"] for r in universe["instruments"]})
    selected=select_ewma(overall,config)
    # A fixed development cutoff establishes forecast causality without accessing any test outcome.
    cutoff=pd.Timestamp("2024-06-28");changed=frames["features_daily"].copy()
    mask=changed.origin_date>cutoff
    changed.loc[mask,"return_1"]*=3;changed.loc[mask,"variance_20"]*=5
    after=generate_forecasts(changed,config,protocol)
    pd.testing.assert_frame_equal(forecasts[forecasts.origin_date<=cutoff].reset_index(drop=True),after[after.origin_date<=cutoff].reset_index(drop=True),check_exact=True)
    recipe={"modeling_dataset_id":manifest["modeling_dataset_id"],"modeling_manifest_sha256":sha256(folder/"manifest.json"),
            "baseline_configuration":config,"protocol":protocol,"evaluator_sha256":sha256(Path(__file__)),
            "reference_universe_sha256":sha256(ROOT/"config/reference_universe.json"),
            "python":platform.python_version(),"platform":platform.system(),
            "packages":{name:version(name) for name in ["numpy","pandas","duckdb","matplotlib"]}}
    identity=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
    result={"experiment_id":identity,"recipe":recipe,"selected_ewma":selected,
            "selection_scope":"2025 primary development MAE; selection-data performance, not final test",
            "overall_metrics":overall.to_dict("records"),"future_perturbation_pass":True,
            "final_test_scores_computed":False,"machine_learning_model_trained":False}
    return result,{"forecasts":forecasts,"evaluation_origins":origins,"per_origin_errors":errors,
                   "per_instrument_metrics":per_instrument,"exposure_group_metrics":groups}


def write_figures(result,frames,folder):
    os.environ.setdefault("MPLCONFIGDIR",str(ROOT/"data/cache/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["svg.hashsalt"]="portfolio-risk-baseline-forecasts"
    overall=pd.DataFrame(result["overall_metrics"])
    primary=overall[overall.evaluation_mode=="primary"]
    methods=["trailing_20","ewma_0.90","ewma_0.94","ewma_0.97"]
    labels=["Trailing 20","EWMA 0.90","EWMA 0.94","EWMA 0.97"]
    colors=["#284f7d","#8eb1d4","#448e7b","#c38d47"]
    years=sorted(primary.year.unique());x=np.arange(len(years))
    fig,ax=plt.subplots(figsize=(9.5,4.8),layout="constrained")
    for i,(method,label,color) in enumerate(zip(methods,labels,colors)):
        values=primary[primary.method==method].set_index("year").loc[years,"volatility_mae_pp"]
        ax.bar(x+(i-1.5)*.19,values,width=.18,label=label,color=color)
    ax.set_xticks(x,[str(y) for y in years]);ax.set_ylabel("Volatility MAE (percentage points)")
    ax.spines[["top","right"]].set_visible(False);ax.legend(ncols=2,frameon=False,fontsize=9)
    ax.set_title("Development forecasts: equal-instrument average error\nNon-overlapping 20-session outcomes; lower is better\nModeling dataset "+result['recipe']['modeling_dataset_id'][:12],fontsize=11)
    fig.savefig(folder/"baseline-development-mae.svg",metadata={"Date":None});fig.savefig(folder/"baseline-development-mae.png",dpi=160);plt.close(fig)
    detail=frames["per_instrument_metrics"]
    detail=detail[(detail.year==2025)&(detail.evaluation_mode=="primary")]
    symbols=sorted(detail.instrument_id.unique());y=np.arange(len(symbols))
    fig,ax=plt.subplots(figsize=(8.5,6.8),layout="constrained")
    for method,label,offset,color in [("trailing_20","Trailing 20",-.12,colors[0]),(result['selected_ewma'],result['selected_ewma'].replace('_',' ').upper(),.12,colors[methods.index(result['selected_ewma'])])]:
        values=detail[detail.method==method].set_index("instrument_id").loc[symbols,"volatility_mae_pp"]
        ax.scatter(values,y+offset,label=label,color=color,s=32)
    ax.set_yticks(y,symbols);ax.set_xlabel("Volatility MAE (percentage points)");ax.invert_yaxis()
    ax.spines[["top","right"]].set_visible(False);ax.legend(frameon=False,fontsize=9)
    ax.set_title("2025 development errors by instrument\nEWMA selected using these development scores; not final-test evidence\nModeling dataset "+result['recipe']['modeling_dataset_id'][:12],fontsize=10)
    fig.savefig(folder/"baseline-instrument-errors.svg",metadata={"Date":None});fig.savefig(folder/"baseline-instrument-errors.png",dpi=160);plt.close(fig)
    for path in folder.glob('*.svg'):path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')


def write_report(result,folder,frames):
    overall=pd.DataFrame(result["overall_metrics"])
    rows=[]
    for r in overall.itertuples():
        rows.append(f"| {r.year} | {r.evaluation_mode} | {r.method} | {r.observations} | {r.volatility_mae_pp:.4f} | {r.variance_qlike:.4f} | {r.prediction_floors} |")
    selected=overall[(overall.year==2025)&(overall.evaluation_mode=="primary")&(overall.method==result['selected_ewma'])].iloc[0]
    trailing=overall[(overall.year==2025)&(overall.evaluation_mode=="primary")&(overall.method=='trailing_20')].iloc[0]
    grouped=frames['exposure_group_metrics']
    grouped=grouped[(grouped.year==2025)&(grouped.evaluation_mode=='primary')&grouped.method.isin(['trailing_20',result['selected_ewma']])]
    group_rows="\n".join(f"| {r.exposure_group} | {r.method} | {r.instruments} | {r.volatility_mae_pp:.4f} | {r.variance_qlike:.4f} |" for r in grouped.itertuples())
    text=f"""# Historical forecast baseline comparison

Updated November 4, 2026. Four fixed-form forecast candidates are evaluated on development years only. No machine-learning model or final-test scores are produced.

## Executive result

The EWMA candidate selected by the declared 2025 primary MAE rule is **{result['selected_ewma']}**. All three decays and the fixed trailing-20 benchmark are reported below. In 2025, selected EWMA has volatility MAE **{selected.volatility_mae_pp:.4f} percentage points**, compared with **{trailing.volatility_mae_pp:.4f}** for trailing variance. However, trailing variance has lower QLIKE in 2025. The best EWMA decay by MAE differs in the earlier development years. This is development selection evidence, not an unbiased final-test comparison or proof of future superiority.

| Development year | Evaluation grid | Method | Matched forecast/target pairs | Volatility MAE, percentage points | Variance QLIKE | Prediction floors |
| --- | --- | --- | ---: | ---: | ---: | ---: |
{chr(10).join(rows)}

Scores first average errors within each instrument and then weight instruments equally. The primary grid is anchored to each year's first feature-ready origin before availability/boundary filtering and advances every twenty sessions. Target windows do not overlap within an instrument; instruments still share market events. Daily overlapping results are secondary and dependent. QLIKE may be negative under `log(predicted_variance) + realized_variance/predicted_variance`; lower remains better on the same outcomes.

![Primary development volatility errors for all forecast candidates](assets/baseline-development-mae.svg)

![2025 instrument-level errors for trailing variance and selected EWMA](assets/baseline-instrument-errors.svg)

## 2025 primary errors by exposure group

| Exposure group | Method | Instruments | Volatility MAE, percentage points | Variance QLIKE |
| --- | --- | ---: | ---: | ---: |
{group_rows}

These categories follow the predeclared research-universe classification. This is instrument-level analysis, not ETF holdings look-through or evidence of a model for portfolio-level risk. The selected EWMA does not improve every group or metric.

## Forecast definitions and validation

- Trailing 20: forecast next-20-session average annualized variance using `252 × mean(r²)` over the latest twenty returns, including the origin return.
- EWMA candidates: `v[t] = lambda × v[t-1] + (1-lambda) × 252 × r[t]²`, with lambda 0.90, 0.94, or 0.97. Initialize at the first valid annualized squared return and reset after missing data. Forecast the twenty-session average by assuming the current variance level persists; this is not a future-volatility guarantee.
- All forecasts require the modeling layer's 252-return readiness. EWMA recursion is reconciled with pandas `ewm(adjust=False)`; a fixed-cutoff future perturbation leaves earlier forecasts exactly unchanged.
- Predicted variance must be finite/nonnegative, and outcomes finite/nonnegative. A missing forecast blocks scoring rather than shrinking the comparison sample. QLIKE uses a 1e-12 prediction floor with counts reported; volatility MAE uses the raw nonnegative prediction.
- Selection uses equal-instrument primary volatility MAE in 2025, with ascending method ID as a deterministic tie-break. Earlier years provide development context. No 2026 forecast, target, or score is computed.

## Reproducible experiment record

- Experiment: `{result['experiment_id']}`.
- Modeling dataset: `{result['recipe']['modeling_dataset_id']}`.
- Baseline specification: [BL-001](../config/forecast_baselines.json).
- Existing modeling manifest, database, and export hashes are verified before use. All candidates, forecasts, matched origins, per-origin errors, per-instrument/group metrics, code/configuration hashes, and package versions remain in local versioned experiment artifacts. This is file-based tracking; MLflow is not installed or claimed here.

```bash
.venv/bin/python -m scripts.evaluate_baselines --modeling-dataset data/modeling/{result['recipe']['modeling_dataset_id']}
.venv/bin/python -m unittest discover -s tests -v
```

The [method walkthrough](07_FORECAST_BASELINES_WALKTHROUGH.md) explains interpretation and checks. The original market histories and modeling rows remain outside Git; public outputs contain aggregate metrics and figures. Revised histories, current-survivor selection, limited non-overlapping origins, and correlated instruments limit conclusions. Next: train and evaluate one documented model using the same development samples and benchmark definitions, then freeze the full recipe before any final 2026 evaluation.
"""
    (folder/'BASELINE_FORECAST_REPORT.md').write_text(text)


def publish(result,frames,root):
    root.mkdir(parents=True,exist_ok=True)
    destination=root/result['experiment_id']
    staging=Path(tempfile.mkdtemp(prefix='.pending-',dir=root))
    try:
        for name,frame in frames.items():
            with duckdb.connect() as connection:
                connection.register('records',frame)
                connection.sql('SELECT * FROM records').write_parquet(str(staging/(name+'.parquet')),compression='zstd')
        (staging/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        assets=staging/'assets';assets.mkdir()
        write_figures(result,frames,assets);write_report(result,staging,frames)
        outputs={str(path.relative_to(staging)):sha256(path) for path in sorted(staging.rglob('*')) if path.is_file()}
        manifest={'experiment_id':result['experiment_id'],'outputs':outputs}
        (staging/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        if destination.exists():
            existing=json.loads((destination/'manifest.json').read_text())
            if existing!=manifest:raise ValueError('Repeated experiment differs from saved artifact hashes')
            for name,digest in existing['outputs'].items():
                if sha256(destination/name)!=digest:raise ValueError('Saved experiment artifact hash differs')
            shutil.rmtree(staging)
        else:staging.rename(destination)
        shutil.copy2(destination/'BASELINE_FORECAST_REPORT.md',ROOT/'docs/BASELINE_FORECAST_REPORT.md')
        for path in (destination/'assets').glob('*.svg'):shutil.copy2(path,ROOT/'docs/assets'/path.name)
    except Exception:
        if staging.exists():shutil.rmtree(staging)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modeling-dataset',type=Path,required=True)
    args=parser.parse_args()
    config=json.loads((ROOT/'config/forecast_baselines.json').read_text())
    result,frames=evaluate(args.modeling_dataset,config)
    publish(result,frames,ROOT/'data/experiments/baselines')
    print(json.dumps({'experiment_id':result['experiment_id'],'selected_ewma':result['selected_ewma'],
                     'primary_metrics':[r for r in result['overall_metrics'] if r['evaluation_mode']=='primary'],
                     'final_test_scores_computed':False},indent=2))


if __name__=='__main__':main()
