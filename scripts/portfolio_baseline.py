"""Historical portfolio risk from accepted SQL inputs; no forecasts or trading.

Personal reports remain private. Publishing requires --publish-demo and an
explicitly labeled demonstration configuration. No market data is downloaded.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

import duckdb
import numpy as np
import pandas as pd

from scripts.audit_market_data import ROOT, sha256


def validate_configuration(config: dict) -> None:
    if config.get("schema_version") != 1 or type(config.get("is_demo")) is not bool:
        raise ValueError("Require schema_version 1 and an explicit boolean is_demo")
    date.fromisoformat(config["as_of_date"])
    if config.get("report_currency") != "USD":
        raise ValueError("Only USD portfolios are supported; no implicit FX conversion")
    if config.get("convention") != "fixed_weights_daily_rebalanced":
        raise ValueError("Only fixed-weight daily-rebalanced scenarios are implemented")
    window = config.get("risk_window_sessions")
    if type(window) is not int or window < 2:
        raise ValueError("risk_window_sessions must be an integer of at least two")
    portfolios = config.get("portfolios", [])
    if not portfolios:
        raise ValueError("Provide at least one portfolio")
    identifiers = set()
    for portfolio in portfolios:
        identifier = portfolio.get("id", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier) or identifier in identifiers:
            raise ValueError("Portfolio IDs must be unique simple identifiers")
        identifiers.add(identifier)
        if not isinstance(portfolio.get("name"), str) or not portfolio["name"].strip():
            raise ValueError("Each portfolio needs a name")
        kind = portfolio.get("input_type")
        if kind not in {"weights", "quantities"}:
            raise ValueError("input_type must be weights or quantities")
        field = "weight" if kind == "weights" else "quantity"
        symbols = set()
        positions = portfolio.get("positions", [])
        if not positions:
            raise ValueError("Empty portfolio")
        values = []
        for position in positions:
            symbol = position.get("instrument_id")
            if not isinstance(symbol, str) or symbol in symbols:
                raise ValueError("Instrument IDs must be present and unique within a portfolio")
            symbols.add(symbol)
            value = position.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Positions must be finite and strictly positive; omit zero positions")
            values.append(value)
        if kind == "weights" and not math.isclose(sum(values), 1.0, abs_tol=1e-10, rel_tol=0):
            raise ValueError("Weights must sum to one; they are not silently rescaled")


def prepare_panel(prices: pd.DataFrame, returns: pd.DataFrame, calendar: pd.DataFrame,
                  symbols: list[str], as_of: pd.Timestamp):
    available = set(prices.instrument_id)
    if set(symbols) - available:
        raise ValueError(f"Unsupported or unavailable instruments: {sorted(set(symbols) - available)}")
    selected = prices[prices.instrument_id.isin(symbols)].copy()
    selected["session_date"] = pd.to_datetime(selected.session_date)
    latest = selected.groupby("instrument_id").session_date.max().min()
    if as_of > latest:
        raise ValueError("Requested as-of date exceeds the common available price history")
    selected = selected[selected.session_date <= as_of]
    if selected.empty or selected.instrument_id.nunique() != len(symbols):
        raise ValueError("As-of date precedes available history")
    start = selected.groupby("instrument_id").session_date.min().max()
    end = selected.groupby("instrument_id").session_date.max().min()
    c = calendar[calendar.instrument_id.isin(symbols)].copy()
    c["session_date"] = pd.to_datetime(c.session_date)
    expected = pd.DatetimeIndex(c.loc[c.session_date.between(start, end), "session_date"].unique()).sort_values()
    if len(expected) < 3:
        raise ValueError("Insufficient common history")
    selected = selected[selected.session_date.between(start, end)]
    adjusted = selected.pivot(index="session_date", columns="instrument_id", values="adjusted_close").reindex(index=expected, columns=symbols)
    closes = selected.pivot(index="session_date", columns="instrument_id", values="close").reindex(index=expected, columns=symbols)
    if adjusted.isna().any().any() or closes.isna().any().any() or not np.isfinite(adjusted).all().all() or (adjusted <= 0).any().any():
        raise ValueError("Incomplete common price history; no filling or silent row dropping is allowed")
    r = returns[returns.instrument_id.isin(symbols)].copy()
    r["session_date"] = pd.to_datetime(r.session_date)
    panel = r.pivot(index="session_date", columns="instrument_id", values="simple_return").reindex(index=expected[1:], columns=symbols)
    if panel.isna().any().any() or not np.isfinite(panel).all().all() or (panel <= -1).any().any():
        raise ValueError("Invalid or missing one-session return")
    exclusions = {symbol: int(((prices.instrument_id == symbol) & (pd.to_datetime(prices.session_date) < start)).sum()) for symbol in symbols}
    return adjusted, closes, panel, latest, exclusions


def resolve_weights(portfolio: dict, symbols: list[str], close: pd.Series,
                    as_of: pd.Timestamp, latest: pd.Timestamp) -> np.ndarray:
    positions = {p["instrument_id"]: p for p in portfolio["positions"]}
    if portfolio["input_type"] == "weights":
        return np.array([positions.get(symbol, {}).get("weight", 0.0) for symbol in symbols], dtype=float)
    if as_of != latest or close.name != latest:
        raise ValueError("Quantity valuation is supported only at the latest available common close; historical share/split reconstruction is not implemented")
    values = np.array([positions.get(symbol, {}).get("quantity", 0.0) * close[symbol] for symbol in symbols], dtype=float)
    if not np.isfinite(values).all() or values.sum() <= 0:
        raise ValueError("Invalid quantity valuation")
    return values / values.sum()


def risk_decomposition(covariance: np.ndarray, weights: np.ndarray):
    variance = float(weights @ covariance @ weights)
    if variance < -1e-12:
        raise ValueError("Negative portfolio variance")
    volatility = math.sqrt(max(variance, 0.0))
    if volatility == 0:
        return volatility, np.zeros_like(weights), np.full_like(weights, np.nan)
    contributions = weights * (covariance @ weights) / volatility
    return volatility, contributions, contributions / volatility


def drawdown_summary(wealth: pd.Series) -> dict:
    drawdown = wealth / wealth.cummax() - 1
    minimum = float(drawdown.min())
    if minimum >= -1e-15:
        return {"maximum_drawdown": 0.0, "peak_date": None, "trough_date": None, "recovery_date": None}
    trough = drawdown.idxmin()
    before = wealth.loc[:trough]
    peak_value = before.max()
    peak = before[before == peak_value].index[-1]
    recovery = wealth.loc[wealth.index > trough]
    recovered = recovery[recovery >= peak_value * (1 - 1e-12)]
    return {"maximum_drawdown": minimum, "peak_date": str(peak.date()), "trough_date": str(trough.date()),
            "recovery_date": str(recovered.index[0].date()) if len(recovered) else None}


def publication_directory(config: dict, publish_demo: bool) -> Path | None:
    if publish_demo and not config["is_demo"]:
        raise ValueError("Personal reports cannot be published through --publish-demo")
    return ROOT / "docs" if publish_demo else None


def serializable(value):
    if isinstance(value, dict): return {k: serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)): return [serializable(v) for v in value]
    if isinstance(value, (float, np.floating)): return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer): return int(value)
    return value


def analyze(connection, config: dict):
    validate_configuration(config)
    symbols = sorted({p["instrument_id"] for portfolio in config["portfolios"] for p in portfolio["positions"]})
    as_of = pd.Timestamp(config["as_of_date"])
    dataset = connection.execute("SELECT dataset_id FROM active_dataset").fetchall()[0][0]
    prices = connection.execute("SELECT instrument_id,session_date,close,adjusted_close FROM accepted_prices_daily ORDER BY instrument_id,session_date").df()
    returns = connection.execute("SELECT instrument_id,session_date,simple_return FROM returns_daily").df()
    calendar = connection.execute("SELECT e.* FROM expected_sessions e JOIN active_dataset a USING(dataset_id)").df()
    adjusted, closes, panel, latest, exclusions = prepare_panel(prices, returns, calendar, symbols, as_of)
    window = config["risk_window_sessions"]
    if len(panel) < window:
        raise ValueError("Common history is shorter than the declared risk window")
    estimation = panel.iloc[-window:]
    covariance = np.atleast_2d(np.cov(estimation.to_numpy(), rowvar=False, ddof=1)) * 252
    standard_deviations = np.sqrt(np.diag(covariance))
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = covariance / np.outer(standard_deviations, standard_deviations)
    positions = pd.DataFrame({"instrument_id": symbols, "weight": np.zeros(len(symbols))})
    connection.register("input_positions", positions)
    # Different engine/algorithm: SQL sample covariance versus NumPy covariance.
    sql_covariance = connection.execute("""
        SELECT l.instrument_id AS left_id, r.instrument_id AS right_id,
               covar_samp(l.simple_return,r.simple_return)*252 AS covariance
        FROM returns_daily l JOIN returns_daily r
          ON l.dataset_id=r.dataset_id AND l.session_date=r.session_date
        JOIN input_positions lp ON lp.instrument_id=l.instrument_id
        JOIN input_positions rp ON rp.instrument_id=r.instrument_id
        WHERE l.session_date BETWEEN ? AND ?
        GROUP BY l.instrument_id,r.instrument_id ORDER BY l.instrument_id,r.instrument_id
    """, [estimation.index[0].date(), estimation.index[-1].date()]).df()
    sql_covariance = sql_covariance.pivot(index="left_id",columns="right_id",values="covariance").reindex(index=symbols,columns=symbols)
    np.testing.assert_allclose(covariance,sql_covariance.to_numpy(),rtol=0,atol=1e-10)
    connection.unregister("input_positions")
    scenarios, daily = [], pd.DataFrame(index=adjusted.index)
    for portfolio in config["portfolios"]:
        weights = resolve_weights(portfolio,symbols,closes.iloc[-1],as_of,latest)
        weighted = pd.Series(panel.to_numpy() @ weights,index=panel.index)
        position_frame = pd.DataFrame({"instrument_id":symbols,"weight":weights})
        connection.register("input_positions",position_frame)
        sql_daily = connection.execute((ROOT/"sql/portfolio_returns.sql").read_text(),[adjusted.index[0].date(),adjusted.index[-1].date()]).df()
        connection.unregister("input_positions")
        sql_daily.index = pd.to_datetime(sql_daily.session_date)
        if not sql_daily.index.equals(weighted.index) or not (sql_daily.available_holdings == len(symbols)).all():
            raise ValueError("Incomplete SQL portfolio aggregation")
        np.testing.assert_allclose(sql_daily.portfolio_return.to_numpy(),weighted.to_numpy(),rtol=0,atol=1e-12)
        volatility, contributions, shares = risk_decomposition(covariance,weights)
        np.testing.assert_allclose(volatility,np.std(weighted.loc[estimation.index],ddof=1)*math.sqrt(252),rtol=0,atol=1e-10)
        np.testing.assert_allclose(contributions.sum(),volatility,rtol=0,atol=1e-10)
        wealth = pd.Series(np.r_[1.0,np.cumprod(1+weighted.to_numpy())],index=adjusted.index)
        drawdown = drawdown_summary(wealth)
        # Independent scalar replay includes initial capital in the peak.
        scalar_wealth=scalar_peak=1.0; scalar_minimum=0.0
        for value in weighted:
            scalar_wealth*=1+float(value);scalar_peak=max(scalar_peak,scalar_wealth)
            scalar_minimum=min(scalar_minimum,scalar_wealth/scalar_peak-1)
        np.testing.assert_allclose(drawdown["maximum_drawdown"],scalar_minimum,rtol=0,atol=1e-12)
        scenarios.append({"id":portfolio["id"],"name":portfolio["name"],"input_type":portfolio["input_type"],
            "weights":weights,"annualized_sample_volatility":volatility,"volatility_contributions":contributions,
            "risk_shares":shares,**drawdown})
        daily[portfolio["id"]+"_wealth_index"]=wealth
        daily[portfolio["id"]+"_drawdown"]=wealth/wealth.cummax()-1
    input_hash = hashlib.sha256(adjusted.to_csv().encode()+closes.to_csv().encode()+panel.to_csv().encode()).hexdigest()
    recipe={"dataset_id":dataset,"configuration":config,"input_sha256":input_hash,
            "script_sha256":sha256(Path(__file__)),"aggregation_sql_sha256":sha256(ROOT/"sql/portfolio_returns.sql")}
    report_id=hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest()
    result={"report_id":report_id,"recipe":recipe,"symbols":symbols,"currency":"USD",
        "history_start":str(adjusted.index[0].date()),"history_end":str(adjusted.index[-1].date()),
        "historical_sessions":len(adjusted),"historical_returns":len(panel),"risk_window_sessions":window,
        "risk_window_start":str(estimation.index[0].date()),"risk_window_end":str(estimation.index[-1].date()),
        "history_excluded_before_common_start":exclusions,"annualized_covariance":covariance,"correlation":correlation,
        "scenarios":scenarios,"reconciliations_passed":True}
    return result,daily


def write_figures(result: dict, folder: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR",str(ROOT/"data/cache/matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams["svg.hashsalt"]="portfolio-risk-baseline"
    scenarios=result["scenarios"]
    fig,axes=plt.subplots(1,len(scenarios),figsize=(5*len(scenarios),4.8),squeeze=False,layout="constrained")
    x=np.arange(len(result["symbols"]))
    for ax,scenario in zip(axes[0],scenarios):
        ax.bar(x-.18,scenario["weights"],width=.36,label="Capital weight",color="#8eb1d4")
        ax.bar(x+.18,scenario["risk_shares"],width=.36,label="Share of volatility risk",color="#284f7d")
        ax.axhline(0,color="#52647a",linewidth=.8)
        ax.set_xticks(x,result["symbols"]);ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_title(scenario["name"],fontsize=11,weight="bold")
        ax.spines[["top","right"]].set_visible(False);ax.legend(fontsize=8,frameon=False)
    portfolio_label="Demonstration portfolios" if result['recipe']['configuration']['is_demo'] else "Private portfolios"
    fig.suptitle(f"{portfolio_label}: capital versus risk\nSample covariance over {result['risk_window_sessions']} sessions ending {result['risk_window_end']}\nDaily rebalanced · dataset {result['recipe']['dataset_id'][:12]}",fontsize=11)
    for figure,name in [(fig,"portfolio-risk-contributions")]:
        figure.savefig(folder/f"{name}.svg",metadata={"Date":None})
        figure.savefig(folder/f"{name}.png",dpi=160)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(5.3,4.5),layout="constrained")
    image=ax.imshow(result["correlation"],vmin=-1,vmax=1,cmap="RdBu")
    ax.set_xticks(x,result["symbols"]);ax.set_yticks(x,result["symbols"])
    for i in x:
        for j in x:
            value=result["correlation"][i,j]
            ax.text(j,i,f"{value:.2f}" if np.isfinite(value) else "undefined",ha="center",va="center",color="white" if abs(value)>.6 else "black")
    ax.set_title(f"Return correlations\n{result['risk_window_start']} to {result['risk_window_end']}\nDataset {result['recipe']['dataset_id'][:12]}",fontsize=10)
    fig.colorbar(image,ax=ax,label="Correlation")
    fig.savefig(folder/"portfolio-correlations.svg",metadata={"Date":None})
    fig.savefig(folder/"portfolio-correlations.png",dpi=160);plt.close(fig)
    for path in folder.glob('*.svg'):
        path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')


def write_report(result: dict, config: dict, folder: Path, publish: bool) -> Path:
    def percent(value): return f"{value:.2%}" if value is not None and np.isfinite(value) else "undefined"
    def escape(value):return str(value).replace('|','\\|').replace('\n',' ')
    summary=[];positions=[]
    for scenario in result["scenarios"]:
        name=escape(scenario["name"])
        summary.append(f"| {name} | {percent(scenario['annualized_sample_volatility'])} | {percent(scenario['maximum_drawdown'])} | {scenario['peak_date'] or '—'} | {scenario['trough_date'] or '—'} | {scenario['recovery_date'] or 'Not recovered / not applicable'} |")
        for symbol,weight,contribution,share in zip(result['symbols'],scenario['weights'],scenario['volatility_contributions'],scenario['risk_shares']):
            positions.append(f"| {name} | {symbol} | {percent(weight)} | {100*contribution:.2f} | {percent(share)} |")
    label="Demonstration portfolio baseline" if config['is_demo'] else "Private portfolio baseline"
    text=f"""# {label}

## Executive summary

This report compares declared portfolios using accepted historical market data. {'The allocations are illustrative inputs, not the author’s actual holdings or recommended allocations.' if config['is_demo'] else 'This report contains personal portfolio information and is saved privately.'} Risk estimates use a common {result['risk_window_sessions']}-session window; drawdowns use the common historical replay period. These are historical measurements, not trained forecasts.

## Results and periods

- Holdings snapshot: **{config['as_of_date']}**, currency **USD**.
- Covariance, volatility, correlation, and risk contributions: **{result['risk_window_start']} through {result['risk_window_end']}**, {result['risk_window_sessions']} daily returns; sample covariance with denominator N−1, annualized by 252.
- Drawdown replay: **{result['history_start']} through {result['history_end']}**, {result['historical_sessions']:,} closing sessions and {result['historical_returns']:,} one-session returns.
- Convention: **fixed weights, rebalanced daily**, using adjusted-price return proxies; no trading costs, slippage, or taxes. This is not the portfolios' actual investment performance.

| Portfolio | Annualized sample volatility | Maximum historical drawdown | Peak date | Trough date | Recovery date |
| --- | ---: | ---: | --- | --- | --- |
{chr(10).join(summary)}

## Capital and risk contributions

![Capital weights compared with covariance-based risk shares](assets/portfolio-risk-contributions.svg)

| Portfolio | Instrument | Capital weight | Contribution to annualized volatility, percentage points | Share of volatility risk |
| --- | --- | ---: | ---: | ---: |
{chr(10).join(positions)}

Contribution is `w_i × (Σw)_i / σ_portfolio`; contributions sum to portfolio volatility before display rounding. Risk share divides that contribution by portfolio volatility. A diversifying holding can have a negative contribution; values are not clipped. Risk shares are undefined when portfolio volatility is zero. These are instrument-level contributions; ETFs may hold overlapping underlying securities.

## Correlations

![Asset return correlations on the covariance-estimation window](assets/portfolio-correlations.svg)

## Composition, validation, and limitations

The calculation reads only accepted stock/ETF prices and calendar-aligned returns from DuckDB. A single common history is used across compared portfolios; missing internal sessions, unsupported instruments, and insufficient estimation history fail explicitly. Leading history excluded before the common start: `{result['history_excluded_before_common_start']}`.

SQL weighted-return aggregation is reconciled against NumPy. SQL sample covariance is reconciled against NumPy covariance. Portfolio volatility is reconciled against the weighted return series' sample standard deviation. Contributions are checked to sum to volatility, and maximum drawdown is checked with a separate scalar replay that includes the initial portfolio value.

This sample-covariance estimator is demeaned and uses N−1. It differs from the squared-return/RMS convention used for the existing 20-session realized-volatility input and planned forward target; the definitions must not be treated as interchangeable.

The three FRED/Yahoo index discrepancies remain quarantined and are not inputs here. Adjusted history is a revised return proxy rather than exact brokerage cash flows or point-in-time archival data. Results depend on the chosen window and scenario assumptions and do not establish future risk or performance.

Quantity inputs are valued using provider Close, not dividend-adjusted historical prices, and are supported only at the latest common close. Historical share/split reconstruction, cash positions, leverage, and currency conversion are not implemented. Weights must be positive and sum to one without automatic rescaling. Personal configurations default to ignored private report folders; public output requires an explicitly labeled demo and `--publish-demo`.

## Provenance and reproduction

- Dataset: `{result['recipe']['dataset_id']}`.
- Report: `{result['report_id']}`.
- Detailed metrics, recipe hashes, and replay series are saved locally; downloaded histories and personal inputs remain outside Git.

```bash
.venv/bin/python -m scripts.portfolio_baseline --input config/demo_portfolios.json --publish-demo
.venv/bin/python -m unittest discover -s tests -v
```

The portfolio input and the database must be available locally. Subsequent fresh database versions create distinct report identities. Source-policy and warehouse documentation explain upstream acceptance controls.
"""
    destination=folder/'BASELINE_PORTFOLIO_REPORT.md'
    destination.write_text(text)
    return destination


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=ROOT/'data/warehouse/portfolio-risk.duckdb')
    parser.add_argument('--publish-demo',action='store_true')
    args=parser.parse_args()
    config=json.loads(args.input.read_text());validate_configuration(config)
    public=publication_directory(config,args.publish_demo)
    with duckdb.connect(str(args.database),read_only=True) as connection:
        result,daily=analyze(connection,config)
    local=ROOT/('data/reports' if config['is_demo'] else 'private/portfolio_reports')/result['report_id']
    local.mkdir(parents=True,exist_ok=True)
    (local/'metrics.json').write_text(json.dumps(serializable(result),indent=2,allow_nan=False)+'\n')
    daily.to_csv(local/'daily_replay.csv',index_label='session_date')
    assets=local/'assets';assets.mkdir(exist_ok=True)
    write_figures(result,assets)
    report=write_report(result,config,local,public is not None)
    if public is not None:
        shutil.copy2(report,public/report.name)
        for path in assets.glob('*.svg'):shutil.copy2(path,public/'assets'/path.name)
    print(json.dumps(serializable({key:result[key] for key in ['report_id','history_start','history_end','risk_window_start','risk_window_end','scenarios','reconciliations_passed']}),indent=2,allow_nan=False))
    return 0


if __name__=='__main__':
    sys.exit(main())
