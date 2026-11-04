# Personal Portfolio Risk Platform

**Status:** Research and design. **Last updated:** November 3, 2026.

## 1. Executive summary

The Personal Portfolio Risk Platform is a planned financial analytics application for evaluating existing investments and comparing hypothetical portfolios. It will combine historical market data, SQL analysis, and machine learning to explain volatility, identify major sources of portfolio risk, and examine exposure to historical market stress.

The central research question is whether a trained model can forecast volatility over the next 20 trading days more accurately than historical estimates. The intended outcome is a reproducible application supported by transparent assumptions and measurable evidence. No forecasting results are available at the current stage.

## 2. Work completed

Work to date comprises the project scope, data requirements, proposed database structure, forecasting target, evaluation approach, and delivery checklist. A source review of Microsoft's Qlib LightGBM workflow identified changes required to adapt a return-prediction example to volatility forecasting. These decisions are documented in the [technical walkthrough](docs/01_QLIB_WALKTHROUGH.md).

Implementation has not begun. Market data has not been downloaded, the proposed software dependencies have not been installed, and no models have been trained or evaluated. This summary will be updated as verified deliverables and results become available.

## 3. Project composition and methodology

### Research question

Can a trained model forecast the next 20 trading days of volatility more accurately than standard historical estimates, and does it improve the information available for portfolio review?

### Intended experience

1. Enter a dated portfolio of stocks and ETFs, using weights or quantities and a portfolio value.
2. Inspect historical volatility, drawdown, correlations, and instrument-level risk contributions.
3. Compare historical risk estimates with an evaluated machine-learning forecast.
4. Examine selected historical stress periods and alternative portfolio scenarios.
5. See the data timestamp, assumptions, model version, and evaluation evidence behind the results.

Historical scenario results for today's weights describe a hypothetical exposure, not the user's actual past investment performance. ETF look-through holdings, taxes, leverage, and derivatives require additional data and are later extensions.

### Proposed architecture

![Proposed workflow: real market data flows through Python ingestion, quality checks, and DuckDB SQL storage. Historical risk analysis and model evaluation feed portfolio scenarios and a local application. All components are planned.](docs/assets/project-workflow.svg)

*Figure 1. Proposed architecture. The diagram describes intended components, not implemented capabilities or measured results.*

| Component | Method | Intended output |
| --- | --- | --- |
| Data acquisition | Retrieve daily prices and corporate actions; record request settings and retrieval times | Traceable, versioned source data |
| Quality control | Inspect coverage, duplicate records, missing sessions, and price adjustments | Data audit and documented exclusions |
| SQL analysis | Store normalized observations and calculate returns and historical features in DuckDB | Reproducible analytical dataset |
| Historical risk | Calculate volatility, drawdown, correlations, and holding risk contributions | Baseline portfolio report |
| Model development | Predict subsequent 20-session realized variance from information available at each forecast date | Instrument-level risk forecasts |
| Evaluation | Compare a trained model with trailing and exponentially weighted estimates on later periods | Forecast errors and documented limitations |
| Portfolio scenarios | Combine instrument forecasts with an explicit correlation estimate; replay historical stress periods | Existing-versus-alternative portfolio comparisons |
| Application | Display portfolio inputs, results, assumptions, data timestamps, and job status | Usable analytical workflow |

### Forecasting and evaluation

Each learning example will represent one instrument on one forecast date. Inputs will include past returns, trailing variance, downside variation, and drawdown. The target will be realized variance over the following 20 trading sessions, using verified adjusted prices and a 252-session annualization convention. Forecasts will be displayed as volatility after taking the square root of variance.

Training, validation, and final testing will use successive time periods. Training observations whose future target windows reach the next evaluation period will be excluded. Model selection will use development data; final testing will follow after the procedure is fixed. Primary comparisons will use non-overlapping 20-session forecast origins.

The primary metric will be mean absolute error in annualized volatility. A secondary measure, QLIKE, will assess positive variance forecasts. Results will include periods and instruments where a simple baseline performs better than the trained model. Portfolio forecast quality will be evaluated separately because a correlation estimate is also required.

### First milestone

A reproducible, audited market-data pipeline, a SQL database, a baseline risk report, and a documented evaluation design. Start with the [action checklist](docs/ACTION_PLAN.md); use the [project plan](docs/PROJECT_PLAN.md) for technical specifications.

The first source review is complete: [Qlib walkthrough and adaptation decisions](docs/01_QLIB_WALKTHROUGH.md). Next is a small real-data audit before scaling the pipeline.

### Planned technology

- Python for ingestion, financial calculations, modeling, and orchestration.
- DuckDB for a local analytical database and explicit SQL transformations.
- Parquet for normalized snapshots and intermediate datasets, with original provider responses retained separately.
- scikit-learn and a gradient-boosted tree implementation for modeling, selected after the baseline.
- MLflow for recording model parameters, datasets, metrics, and artifacts.
- A local Python application for the first usable interface; choose the UI framework after the risk engine works.
- Microsoft Qlib as a reference for reproducible data, training, inference, and evaluation workflows.

These are planning choices, not installed dependencies or completed capabilities.

### Implementation status on November 3, 2026

- Project scope, research target, source shortlist, and first milestone documented.
- Actionable delivery checklist and Qlib source walkthrough completed; Qlib itself has not been installed or executed.
- Local Python 3.13 and Git are available; a compatible, pinned ML environment and price-data feasibility still need to be established.
- No market data downloaded, models trained, or pipeline code implemented yet.

### References

- [Qlib workflow](https://qlib.readthedocs.io/en/latest/component/workflow.html)
- [Qlib repository and data availability notice](https://github.com/microsoft/qlib)
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/)
- [FRED real-time periods and ALFRED](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)
- [yfinance data access and usage notes](https://github.com/ranaroussi/yfinance)
- [MLflow experiment tracking](https://mlflow.org/docs/latest/ml/tracking/)
