# Personal Portfolio Risk Platform

**Status:** Data audit implemented; three benchmark source discrepancies remain open.
**Last updated:** November 4, 2026.

## 1. Executive summary

The Personal Portfolio Risk Platform is a financial analytics project for evaluating existing investments and comparing hypothetical portfolios. Its intended application will explain portfolio volatility, identify major sources of risk, and examine exposure to historical market stress.

The central research question is whether a trained model can forecast volatility over the next 20 trading days more accurately than historical estimates. The first implementation establishes the data foundation: a reproducible Python workflow that downloads real market history, checks its quality, and preserves evidence. Portfolio calculations, SQL storage, model training, and the application are subsequent milestones.

## 2. Work completed

The current implementation includes an isolated Python environment, pinned dependencies, a market-data acquisition and audit script, versioned local snapshots, and a generated quality report. The audit retrieved **5,157 daily observations** across AAPL, SPY, and BND, covering January 2, 2020 through November 3, 2026. Each instrument contained all **1,719 expected trading sessions**, with no duplicate dates, nonpositive prices, or inconsistent OHLC rows detected.

Corporate-action diagnostics cover **134 dividend events and one split**. A selected Apple split and dividend amount were checked against an issuer announcement. Fifteen selected closes match a separate finance website. A full-window comparison of FRED SP500 with Yahoo ^GSPC identified **three unresolved benchmark discrepancies** after accounting for published precision. Original source values are retained; benchmark acceptance is on hold.

Twelve regression tests validate audit failures and source alignment. Both audits can be replayed from saved evidence without new downloads. The stock/ETF sample supports further prototype work, while the benchmark requires a documented source decision. No claim of complete independent price certification or model performance is made.

The research scope, SQL schema, forecast target, evaluation design, and delivery checklist are also documented. A [Qlib source walkthrough](docs/01_QLIB_WALKTHROUGH.md) explains the adaptations required for volatility forecasting. No risk model has been trained.

## 3. Project composition and methodology

### Architecture and implementation status

![Architecture showing the implemented market-data sample and Python audit, with SQL storage, risk calculations, modeling, scenarios, and application still planned](docs/assets/project-workflow.svg)

*Green components are implemented for the initial sample. Remaining components describe the planned platform.*

| Component | Method | Current state |
| --- | --- | --- |
| Acquisition | Yahoo Finance history through yfinance, with explicit adjustment settings and corporate actions | Implemented for three instruments |
| Evidence | Timestamped CSV snapshots, structured metadata, request settings, package versions, and SHA-256 hashes | Implemented; downloaded prices remain local |
| Quality control | Exchange-session coverage, duplicates, missing/invalid values, OHLC consistency, volume, and adjustment diagnostics | Implemented; see the [audit report](docs/DATA_AUDIT.md) |
| Verification | Regression tests, issuer cross-check, separate website spot checks, FRED benchmark reconciliation, and offline replay | Implemented; three benchmark exceptions remain open |
| SQL foundation | Versioned DuckDB tables and Parquet normalization | Planned |
| Historical risk | Returns, volatility, drawdown, correlations, and holding risk contributions | Planned |
| Modeling | Next-20-session variance forecasts compared with historical baselines | Planned |
| Application | Dated holdings, portfolio comparisons, historical scenarios, and visible assumptions | Planned |

### Data quality findings

![Observed and missing expected trading sessions by instrument](docs/assets/data-audit-summary.svg)

The audit compares observed dates with configured exchange-session calendars, retains missing observations, and does not repair prices or fill gaps. It records dividend and split events and checks changes in the adjusted-close/close ratio. Threshold breaches produce review flags rather than automatic corrections.

A material finding is that the provider's Close field must not be assumed to be split-unadjusted. Around Apple's August 2020 split, applying the split ratio again would introduce an artificial return exceeding 300%. The [audit report](docs/DATA_AUDIT.md) documents this diagnostic, its issuer reference, and the limits of the verification.

The [cross-source report](docs/CROSS_SOURCE_VALIDATION.md) separates individual-instrument spot checks from same-index benchmark reconciliation. Yahoo ^GSPC remains excluded from model features and benchmark calculations until its source exceptions are resolved or formally dispositioned. No observed value is silently replaced.

yfinance is an unofficial interface to Yahoo Finance. The downloaded snapshots preserve library output rather than original HTTP payloads. Current adjusted histories can be revised and do not establish what was known at each historical forecast date. Downloaded prices, credentials, personal holdings, caches, and model artifacts remain outside version control.

### Run the implemented milestone

Tested with **Python 3.13.7**. Direct dependencies are listed in [requirements.in](requirements.in); exact installed versions are recorded in [requirements.txt](requirements.txt).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/audit_market_data.py --start 2020-01-01 --end 2026-11-04
.venv/bin/python -m unittest discover -s tests -v
```

The end date is exclusive. Each download creates a new local snapshot. To reproduce the audit from existing evidence without a new request:

```bash
.venv/bin/python scripts/audit_market_data.py --snapshot data/audit/<run-id>
```

The script generates `docs/DATA_AUDIT.md`, a coverage figure, and detailed local audit JSON. A structural failure produces a nonzero exit status. Unit tests use small synthetic fixtures to test failures; reported project findings come from downloaded market data.

To acquire external references and check a saved baseline:

```bash
.venv/bin/python -m scripts.cross_validate_sources --snapshot data/audit/<run-id>
```

This comparison generates `docs/CROSS_SOURCE_VALIDATION.md` and returns exit status 2 while unresolved comparisons remain. That is a data-quality finding, not a failed regression test. Offline replay instructions are in the report.

### Planned forecasting and portfolio methodology

Each modeling row will represent an instrument at a forecast date, with inputs available by that day's close. The target will be realized variance over the following 20 trading sessions, annualized using a 252-session convention. Displayed volatility will be the square root of variance.

Training, validation, and final testing will use successive periods. Training labels whose future windows reach the next evaluation period will be excluded. A trained model will be compared with trailing and exponentially weighted variance forecasts using annualized-volatility mean absolute error and variance QLIKE. The final test will remain untouched until model selection is complete.

The initial application will support daily, USD-denominated stocks and ETFs in long-only, unleveraged portfolios. Fixed-weight historical scenarios will explicitly assume daily rebalancing; they will represent hypothetical exposures rather than actual past investment performance. Portfolio forecasting will require a separate correlation estimate and separate evaluation. ETF look-through holdings, taxes, derivatives, and automated trading are outside the initial scope.

### Documentation and next milestone

- [Data audit](docs/DATA_AUDIT.md): observed findings, provenance, methods, and limitations.
- [Cross-source validation](docs/CROSS_SOURCE_VALIDATION.md): website quote checks and unresolved FRED/Yahoo benchmark differences.
- [Data-audit walkthrough](docs/02_DATA_AUDIT_WALKTHROUGH.md): how to read and explain the implementation.
- [Action checklist](docs/ACTION_PLAN.md): tasks and completion criteria.
- [Project plan](docs/PROJECT_PLAN.md): the broader technical specifications.

The [source policy](docs/DATA_SOURCE_POLICY.md) accepts the audited stock/ETF sample for prototype work, selects FRED as the preferred price-index context source, and quarantines Yahoo ^GSPC. The underlying three discrepancies remain unresolved.

Next: implement the versioned SQL ingestion layer and issue ledger, including enforcement of this source policy. Portfolio risk calculations follow those data controls.

### References

- [yfinance source and usage notes](https://github.com/ranaroussi/yfinance)
- [Exchange calendars](https://github.com/gerrymanoim/exchange_calendars)
- [Apple issuer announcement](https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/)
- [Microsoft Qlib workflow](https://qlib.readthedocs.io/en/latest/component/workflow.html)
- [FRED API and historical vintages](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)
- [MLflow experiment tracking](https://mlflow.org/docs/latest/ml/tracking/)
