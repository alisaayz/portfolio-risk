# Portfolio risk project plan

Working plan dated November 3, 2026. Allocate approximately five to six weeks at 12–20 hours per week, using two-week demonstrations to adjust scope. Data access and the user's learning pace may change the schedule.

## Product and research scope

The user wants to understand investments they already own and explore potential portfolios. Begin with long-only, unleveraged, USD-denominated stocks and ETFs and daily data. A declared portfolio snapshot, holdings date, weight convention, and reporting currency accompany every report.

The initial reference universe should contain approximately 12–20 instruments with sufficient histories and varied exposures. Final symbols and history dates depend on the data audit. This is a research universe, not a recommended investment allocation. Later expansion to additional instruments should preserve the same data contracts.

Use Qlib to learn the structure of a reproducible quantitative workflow. Study its LightGBM example and its separation of datasets, models, and records. Implement our risk-specific SQL layer and objectives explicitly; decide whether to integrate Qlib itself after testing compatibility and data access.

## Core capabilities

1. **Data foundation:** validated market history, corporate-action handling, provenance, and repeatable incremental ingestion.
2. **Risk engine:** returns, annualized volatility, drawdown, correlation, and instrument-level covariance risk contributions.
3. **Machine learning:** next-20-trading-day volatility forecasts compared with historical baselines.
4. **Scenario analysis:** historical stress replay and user-defined what-if portfolios with explicit exposure assumptions.
5. **Application:** a usable local interface, reproducible reports, scheduled updates, and visible data/job status.

Do not infer underlying sector diversification solely from ETF ticker weights. Instrument-level risk contributions and ETF holdings overlap are different questions. Look-through analysis requires separately sourced holdings and dates.

## Learning and modeling contract

The first learning task uses instrument-level daily simple total-return proxies derived from verified dividend/split-adjusted prices:

```text
r[t] = adjusted_close[t] / adjusted_close[t-1] - 1

target_variance[t] = (252 / 20) * sum(r[t+i]^2 for i = 1..20)
target_volatility[t] = sqrt(target_variance[t])
```

This is annualized forward realized variance based on squared daily returns. Document the estimator and the 252-day convention. Predictions are made after the close at t using only available information; the target is observed later. Dropping missing trading days must not silently change the target horizon.

Candidate features include lagged returns, trailing realized variance over several windows, downside variation, drawdown, and past correlations. Fit preprocessing only on training data. Any economic features enter only after their historical availability is verified.

### Baselines and models

- Trailing 20-trading-day realized variance.
- An exponentially weighted variance estimate with its decay parameter documented.
- A pooled gradient-boosted tree model, with a positive variance output convention defined before training.
- A GARCH baseline or a second model family only if time and evaluation results justify the extension.

A first portfolio forecast can combine predicted instrument volatilities with a trailing, regularized correlation estimate. This assumes correlations follow the declared estimator; it is not a model of future correlations. Evaluate this approximation separately against portfolio baselines.

### Evaluation

- Use chronological development and untouched final test periods; freeze their dates after auditing coverage.
- Remove training examples whose forward target windows cross into validation or test periods. Apply the same rule within rolling evaluation folds.
- Begin with non-overlapping 20-day forecast origins for the main comparison to reduce dependence between targets. Any daily overlapping evaluation must be identified as dependent and not treated as independent samples.
- Primary metric: mean absolute error of annualized volatility. Secondary metric: QLIKE on strictly positive variance forecasts and realized variance.
- Break down results by instrument, market period, and volatility level. Show where the model is worse than the baselines.
- Fix primary metrics, baselines, and test periods before tuning; log model and dataset versions.
- Evaluate fixed-weight scenario portfolios using daily simple portfolio returns computed from the declared weights. Describe daily rebalancing explicitly. A buy-and-hold simulation instead requires evolving weights and must be labeled separately.

The success criterion is a reproducible, honest comparison and a useful risk application. Better ML performance is a research outcome, not a prerequisite for reporting the work.

## Data acquisition decisions

### Market prices and corporate actions

First candidate: yfinance for personal research, with explicit settings, saved raw responses, corporate-action checks, and provider-use constraints recorded. It is an unofficial interface; availability and completeness need testing. Public sharing of code does not establish rights to redistribute downloaded prices.

Alternative candidates can include a documented public historical snapshot or an API provider. Audit adjustments, history coverage, access restrictions, update options, and usage terms before selecting. Alpha Vantage documents adjusted time-series endpoints, but suitable endpoint access and any paid requirement must be checked; do not assume the needed data is free or purchase access.

Qlib currently notes that its official prepackaged dataset is temporarily unavailable. Do not make downloading that bundle a prerequisite for our project.

### Economic context

Use FRED/ALFRED for a small, documented set of economic series. Start with context charts if release timing is not yet implemented. For model features, distinguish observation dates from availability dates and retrieve historical vintages as appropriate. A revised value known today must not be inserted into a historical prediction as though it was known then.

Do not place API keys in the repository or request that the user paste them into chat. Public CSV downloads can be evaluated before an API-key setup is necessary.

## Database design to implement first

| Table | Purpose | Proposed record key |
| --- | --- | --- |
| instruments | Symbol identity, currency, classification, provenance | instrument_id |
| ingestion_runs | Source, request parameters, timestamps, content hashes, outcome | ingestion_run_id |
| prices_daily | Original OHLCV, adjusted close, currency, source run | instrument_id, session_date, ingestion_run_id |
| corporate_actions | Dividends and splits for price/return audits | instrument_id, event_date, action_type, ingestion_run_id |
| macro_observations | Economic values, observation dates, vintage/availability metadata | series_id, observation_date, vintage_date |
| portfolio_snapshots | User-defined portfolio name, date, currency, weight convention | portfolio_id, as_of_date |
| positions | Instrument weights or quantities for a portfolio snapshot | portfolio_id, as_of_date, instrument_id |
| features_daily | Versioned, as-of model features | instrument_id, session_date, feature_version, dataset_version |
| forecasts | Origin, horizon, prediction, model run | instrument_id, origin_date, horizon, model_run_id |
| evaluation_results | Metrics, periods, slices, and evaluation run | evaluation_run_id, slice_id, metric |
| data_quality_issues | Source/date/field discrepancies, rules, tolerances, evidence, and resolution status | issue_id |

Historical ingestion snapshots are retained; canonical price views select an explicit dataset version. Rerunning the same input should not create duplicate canonical observations.

## Delivery outline

| Phase | Approximate time | Reviewable output |
| --- | --- | --- |
| Data and baseline foundation | Weeks 1–2 | Provenance report, SQL database, reproducible baseline portfolio report |
| Modeling and evaluation | Weeks 3–4 | Feature pipeline, tracked model runs, chronological comparison with baselines |
| Application and operation | Weeks 5–6 | Holdings/scenario interface, stress reports, scheduled updates, documentation and demo |

Forecast-driven portfolio optimization, neural networks, real-time streaming, and language-model commentary are possible extensions. Add them only when they answer an observed limitation of the core system. If an LLM is added later, supply its numerical statements from validated calculation outputs and evaluate faithfulness.

## First two-week sprint

### Session 1 — Define and inspect, approximately 2–3 hours

- Explain Qlib's dataset, model, evaluation, and experiment-record components in our own words.
- Confirm the forecast target, USD/daily starting scope, and portfolio input conventions.
- Inspect a small market-data response before installing a large framework or downloading a large universe.
- Record available history, corporate-action fields, missing observations, and access/usage conditions.

### Sessions 2–3 — Build the data foundation

- Create a reproducible Python environment with pinned dependencies.
- Implement one market-data adapter with explicit request settings and provenance.
- Preserve raw snapshots, normalize data, and load canonical DuckDB views.
- Add checks for duplicate keys, nonpositive prices, unexplained gaps, and extreme movements requiring corporate-action review.
- Write SQL for returns, coverage summaries, rolling features, and baseline risk inputs.

### Sessions 4–5 — Baseline and audit

- Calculate portfolio risk from an explicitly labeled user-input or demonstration portfolio.
- Reconcile selected results against independent hand calculations or a second calculation path.
- Write the fixed-weight scenario assumptions, data dictionary, and modeling split specification.
- Record remaining problems and freeze the first dataset version.

### Sprint completion criteria

- A fresh run ingests, validates, and queries the initial universe reproducibly.
- A rerun has no duplicate canonical price rows.
- A coverage report identifies missing or unsupported history; failures are visible rather than silently skipped.
- Adjusted-price behavior is documented and checked around selected dividends/splits.
- A baseline report shows portfolio volatility, drawdown, correlations, and instrument risk contributions with assumptions and timestamps.
- The modeling target and leakage-safe evaluation design are written before training.

## Project working agreement

Use reviewable checkpoints and explain the reasoning behind code and modeling choices so the user can discuss and defend the work in interviews. Keep a decision log as implementation starts. Preserve the financial research engine as the saved next-project candidate in the parent AGENTS.md.

## Implemented data audit — November 4, 2026

The three-instrument sample contains 5,157 daily observations with no missing expected sessions, duplicate dates, or nonpositive prices detected. Acquisition settings and local snapshot hashes are recorded. Twelve regression tests cover audit failures and cross-source alignment.

Five selected completed-session closes for each instrument match a separate website at published price precision. FRED SP500 versus Yahoo ^GSPC retains three unresolved historical discrepancies after precision normalization. FRED is a same-index benchmark check, not validation of individual stock or ETF quotes. See [the external validation report](CROSS_SOURCE_VALIDATION.md).

The planned SQL layer must retain source values and quality issues separately. Record source identity, observation date, field, tolerance, evidence references, and resolution status; do not silently overwrite discrepant data. A later source-selection decision can select a canonical benchmark without deleting contrary evidence. Source policy [DS-001](DATA_SOURCE_POLICY.md) selects FRED for index context and quarantines Yahoo ^GSPC. Future model features and benchmark calculations must exclude that comparator until its underlying issues are reconciled or an independently justified acceptance rule is documented.
