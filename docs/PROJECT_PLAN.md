# Portfolio risk project plan

Working plan established November 3, 2026; implementation status updated November 4, 2026. Allocate approximately five to six weeks at 12–20 hours per week, using two-week demonstrations to adjust scope. Data access and the user's learning pace may change the schedule.

## Product and research scope

The user wants to understand investments they already own and explore potential portfolios. Begin with long-only, unleveraged, USD-denominated stocks and ETFs and daily data. A declared portfolio snapshot, holdings date, weight convention, and reporting currency accompany every report.

RU-001 selects 16 reference instruments with varied exposures and histories from January 2020 through November 2026. All pass structural checks; selected independent checks and DS-002 SQL promotion are implemented. See [REFERENCE_UNIVERSE.md](REFERENCE_UNIVERSE.md). This is a research universe, not a recommended investment allocation. Later expansion to additional instruments should preserve the same data contracts.

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

- Follow [EV-001](EVALUATION_PROTOCOL.md): 2020–2024 initial training, 2025 main validation, and reserved 2026 historical model test. Earlier folds validate on 2023 and 2024; final refitting may use eligible pre-2026 labels after recipe selection. No model scores have been computed.
- Remove training examples whose forward target windows cross into validation or test periods. Apply the same rule within rolling evaluation folds.
- Begin with non-overlapping 20-day forecast origins for the main comparison to reduce dependence between targets. Any daily overlapping evaluation must be identified as dependent and not treated as independent samples.
- Primary metric: equal-instrument mean of annualized-volatility MAE. Secondary: equal-instrument mean of variance QLIKE. Positive-forecast evaluation conventions and floor reporting are fixed in EV-001.
- Break down results by instrument, market period, and volatility level. Show where the model is worse than the baselines.
- Fix primary metrics, baselines, and test periods before tuning; log model and dataset versions.
- Evaluate fixed-weight scenario portfolios using daily simple portfolio returns computed from the declared weights. Describe daily rebalancing explicitly. A buy-and-hold simulation instead requires evolving weights and must be labeled separately.

The success criterion is a reproducible, honest comparison and a useful risk application. Better ML performance is a research outcome, not a prerequisite for reporting the work.

## Data acquisition decisions

### Market prices and corporate actions

First candidate: yfinance for personal research, with explicit settings, saved provider-library output, corporate-action checks, and provider-use constraints recorded. It is an unofficial interface; availability and completeness need testing. Public sharing of code does not establish rights to redistribute downloaded prices.

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

Explainable portfolio adjustment suggestions are a requested later phase: reweight current holdings first, then provide replacement criteria and optional candidates from an approved universe. See [PORTFOLIO_ADJUSTMENT_ROADMAP.md](PORTFOLIO_ADJUSTMENT_ROADMAP.md). Implementation follows validation of the core risk platform. Neural networks, real-time streaming, and language-model commentary remain possible extensions. Add them only when they answer an observed limitation of the core system. If an LLM is added later, supply its numerical statements from validated calculation outputs and evaluate faithfulness.

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

## Implemented SQL milestone — November 4, 2026

The warehouse retains two price captures (10,314 rows) and selects 5,157 canonical observations through an explicit dataset pointer. SQL enforces DS-001, retains three active discrepancy records, and calculates calendar-aligned returns and complete historical volatility windows. Five normalized Parquet tables are versioned and hash-checked. Repeated real-data loading preserves counts, dataset identity, and exports; all SQL returns and complete volatility windows reconcile with NumPy. Portfolio baseline calculations are implemented as described below. The larger universe is now accepted under DS-002 as described below; forecasting remains subsequent work. See [SQL_LAYER.md](SQL_LAYER.md).

## Implemented portfolio baseline — November 4, 2026

Dated JSON inputs accept validated positive weights summing to one or quantities valued at the latest common provider Close. Personal inputs and reports remain private. The public demonstration compares AAPL/SPY/BND allocations of 30%/50%/20% and 10%/40%/50% using real market data.

Sample covariance uses the last 252 common returns, N−1, and a 252-session annualization convention. Portfolio volatility, correlations, and Euler holding contributions use that window; maximum drawdown uses the full common 2020–2026 replay. Both scenarios assume fixed weights rebalanced daily without costs or taxes. Sample covariance differs from the squared-return forward target defined above.

SQL and NumPy returns and covariance reconcile; weighted-series volatility, Euler sums, and a separate scalar drawdown replay also reconcile. Thirty regression tests cover the complete implementation. See the [measured report](BASELINE_PORTFOLIO_REPORT.md) and [walkthrough](04_PORTFOLIO_BASELINE_WALKTHROUGH.md). Portfolio snapshot persistence in SQL, dedicated stress analysis, forecasting, and the interface remain planned; this milestone uses validated JSON inputs.

## Implemented universe audit and date contract — November 4, 2026

RU-001 preserves 27,504 rows across 16 instruments, with complete expected coverage and no structural failures or adjustment-threshold review flags. This capture has since been promoted under DS-002 following additional evidence and tested source-policy/loader changes, as described below.

EV-001 reserves 2026 model scores, adds earlier development years, and implements date-only membership with a 252-return warmup and exact 20-session target boundaries. Each instrument currently has 986 initial-training, 230 main-validation, and 191 completed daily test origins; ten completed primary test windows are non-overlapping within that instrument. Twenty recent origins lack complete outcomes. These are eligibility counts, not forecast results or independent sample counts. Forty-six regression tests pass. Features, actual target values, and all model scores remain unimplemented. See [EVALUATION_SPLITS.md](EVALUATION_SPLITS.md).

## Implemented expanded acceptance and SQL promotion — November 4, 2026

DS-002 accepts all sixteen RU-001 instruments after 80 matching quote pairs and four selected issuer checks. The failed maintenance-page response remains archived; a public investor-relations announcement supplied the missing J&J evidence in a new capture. The three index discrepancies remain unresolved and quarantined.

The warehouse selects 27,504 rows, retaining 37,818 across three price captures, seven source runs, and two dataset versions. Repeated builds preserve counts, identity, and all five export hashes. Every one of 27,488 returns and 27,184 complete historical volatility windows reconciles with NumPy. Sixty-two software tests pass locally.

Small adjusted-close differences between captures are preserved rather than patched. The descriptive baseline was refreshed under the expanded dataset; displayed volatility/drawdown results remain unchanged, while unrounded values and report identity differ. Next: separate modeling features/targets, future-value perturbation, and independent target/date reconciliation under EV-001. No model forecasts or final-test scores have been calculated. See [05_EXPANDED_SQL_WALKTHROUGH.md](05_EXPANDED_SQL_WALKTHROUGH.md).

## News feasibility checkpoint — November 4, 2026

The user requested consideration of breaking news and measurable market reactions, with feasibility reviewed first. Three bounded GDELT archive probes contain 5,944 records and 5,942 titles. Precise publication fields are present in 2,778 records, with 90 later-than-batch values requiring review. The DOC API probe returned 429; the SEC probe returned 403. No restriction was bypassed and no API access or complete historical coverage is claimed.

A reproducible offline auditor and six regression checks cover metadata shape, timestamp handling, duplicates, hashes, and candidate aliases. The complete suite has 68 passing tests. Source/model candidates and their limits are documented in [NEWS_FEASIBILITY.md](NEWS_FEASIBILITY.md). News collection, NLP inference, event reactions, and any predictive benefit remain proposed; no dependency, SQL policy, or EV-001 change was made. Next: complete price-only modeling features/targets, then develop a separately evaluated news-context prototype before admitting news to a forecast.

## Requested later phase: portfolio adjustment suggestions — November 4, 2026

The user wants the platform to propose weight changes when existing holdings exceed personal risk tolerance, and later suggest replacement characteristics or specific screened candidates. Record personal constraints, evaluate alternatives using consistent risk estimates, explain tradeoffs, and report infeasible targets. Implement reweighting before expanding the candidate universe. This is a future roadmap item; no optimizer, recommendation engine, preference profile, or trading capability is implemented. The next core task remains the price-only feature/target pipeline.
