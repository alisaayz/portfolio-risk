# Portfolio risk project plan

Working plan established November 3, 2026; implementation status updated November 5, 2026. Allocate approximately five to six weeks at 12–20 hours per week, using two-week demonstrations to adjust scope. Data access and the user's learning pace may change the schedule.

## Product and research scope

The user wants to understand investments they already own and optionally explore changes. The application defaults to one portfolio, with an opt-in alternative comparison. Begin with long-only, unleveraged, USD-denominated stocks and ETFs and daily data. A declared portfolio snapshot, holdings date, weight convention, and reporting currency accompany every report.

RU-001 selects 16 reference instruments with varied exposures and histories from January 2020 through November 2026. All pass structural checks; selected independent checks and DS-002 SQL promotion are implemented. See [REFERENCE_UNIVERSE.md](REFERENCE_UNIVERSE.md). This is a fixed research universe, not a recommended allocation. Application discovery now covers broader U.S. listing candidates with separately audited AP-001 histories; it does not expand model evaluation automatically.

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

- Follow [EV-001](EVALUATION_PROTOCOL.md): 2020–2024 initial training, 2025 main validation, and reserved 2026 historical model test. Earlier folds validate on 2023 and 2024; final refitting may use eligible pre-2026 labels after recipe selection. Development and final holdout scores are recorded in the later implementation checkpoints.
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

## Implemented modeling dataset — November 4, 2026

Twelve causal price-based SQL features, separate development targets, EV-001 membership, and explicit development views are implemented in a distinct versioned DuckDB/Parquet layer. The market warehouse is read-only. All 330,048 feature cells and 24,128 pre-2026 target rows reconcile with independent NumPy, including null positions and incomplete windows. The initial-training pool contains 15,776 examples; main validation contains 3,680; final refitting may later use 19,776 eligible pre-2026 examples after recipe selection.

Real-data boundary checks include the August 2020 Apple split and training/validation/test transitions. Future-value perturbation preserves earlier features; changing 2026 prices cannot alter development labels. Final-test numerical outcomes remain uncomputed. Eighty software tests pass locally. No preprocessing is fitted and no model is trained or scored. Read [MODELING_DATASET.md](MODELING_DATASET.md) and the [feature dictionary/walkthrough](06_MODELING_DATASET_WALKTHROUGH.md). Next: forecast baselines and chronological development evaluation before model training.

## Implemented historical forecast benchmarks — November 4, 2026

Trailing-20-session variance and three declared EWMA decays are evaluated on identical 2023–2025 development origins. Each method/year has 192 primary matched pairs across sixteen instruments, with non-overlapping targets within each instrument. Daily results and per-instrument/exposure-group metrics are preserved separately. EWMA recursion reconciles with pandas, known metric fixtures pass, and future-value perturbation preserves earlier forecasts.

EWMA 0.90 is selected by primary 2025 volatility MAE: 5.9087 percentage points versus 6.2989 for trailing variance. Trailing variance has lower 2025 QLIKE; earlier-year best EWMA decays differ. All candidates and tradeoffs are reported rather than treating development selection as final-test success. The experiment is versioned using local file-based records; MLflow and machine-learning training remain next. Ninety-two software tests pass locally. No 2026 forecast, outcome, or final score is computed. See [BASELINE_FORECAST_REPORT.md](BASELINE_FORECAST_REPORT.md) and [07_FORECAST_BASELINES_WALKTHROUGH.md](07_FORECAST_BASELINES_WALKTHROUGH.md).

## Implemented trained-model development experiment — November 4, 2026

ML-001 trains three fixed pooled histogram gradient-boosting candidates with positive variance output, explicit predictors, purged chronological folds, and disabled random internal early stopping. The selected seven-leaf model has 2025 primary volatility MAE 5.5566 percentage points versus 5.9087 for selected EWMA and 6.2989 for trailing variance. Its 2023 MAE is worse than both selected benchmarks; results are development evidence and remain mixed. All candidate scores, daily comparisons, per-instrument/group/regime errors, model files, failures, parameters, and hashes are retained locally.

Nine candidate/fold combinations reproduce predictions on repeat fitting and after persistence; an independent verifier checks all 81,536 per-origin errors and 42 aggregate comparisons. One hundred and six software tests pass locally. No final refit, 2026 prediction, numeric outcome, or final score is produced. Tracking is file based; MLflow remains optional and uninstalled. See [MODEL_DEVELOPMENT_REPORT.md](MODEL_DEVELOPMENT_REPORT.md) and [08_MODEL_TRAINING_WALKTHROUGH.md](08_MODEL_TRAINING_WALKTHROUGH.md). Next: robustness review and usable portfolio analysis, preserving the reserved final test.

## Implemented development robustness — November 4, 2026

RB-001 evaluates four non-overlapping-within-phase grid offsets and leave-one-instrument-out aggregation of saved development predictions, without refitting or reselection. The selected model beats EWMA in three of four 2025 phases and trailing variance in four; the five-session offset reverses the EWMA comparison. Phases are dependent, and omission ranges are descriptive rather than confidence intervals. The original primary and final-test grids remain unchanged. One hundred and twelve tests pass locally. See [DEVELOPMENT_ROBUSTNESS.md](DEVELOPMENT_ROBUSTNESS.md).

## Implemented local historical application — November 4, 2026

The localhost-only browser application connects validated portfolio weights to the reconciled historical engine through a read-only warehouse connection. It adds optional user-entered volatility-reference comparisons, wealth/drawdown views, risk shares, correlations, fixed HS-001 stress windows, and JSON export. Missing complete scenario windows remain unavailable. Entries are kept in memory; no private snapshot persistence or external transmission is implemented. Nine application tests cover numerical equivalence, boundary/error behavior, actual local HTTP analysis, and unchanged warehouse hashes; browser testing confirms real demo metrics, invalid totals, stale-result handling, chart switching, export, and responsive layout. The full suite has 121 tests. See [APPLICATION.md](APPLICATION.md). Portfolio forecasts, final testing, news, suggestions, persistent snapshots, and operational refresh remain later work.

## Broader application scope and measurement design — November 4, 2026

The user selected U.S.-listed stocks and ETFs for broader search and asked for user metrics and hypothesis-testing skills relevant to data-science work. A versioned Nasdaq directory supplies 13,237 active non-test records and 11,806 eligible search candidates under explicit classification rules. Requested histories pass separate AP-001 provider/structural checks and are cached; additional assets compose only in an in-memory application dataset. META, VOO, and BRK.B each have 1,719 verified sessions, with retained META extreme-move warnings and no independent price cross-check. The research warehouse/hash and sixteen-instrument model scope remain unchanged.

The dashboard clarifies allocation percentages and displays hash-verified development MAE/QLIKE. The measurement plan defines proposed user-task success, guardrails, participant-level randomized report comparison, power planning, effect sizes/intervals, and dependence-aware forecast inference. No user outcome collection or statistical-significance result is implemented. The full software suite has 136 passing tests; source, model, user and operational evidence remain distinct. See [the expansion report](US_MARKET_EXPANSION.md) and [measurement design](METRICS_AND_EXPERIMENTS.md).

## Implemented personal workflow and preference reflection — November 4, 2026

The user requested a single-portfolio default and a short questionnaire for people who cannot choose a volatility percentage. The interface now starts with one portfolio and an optional alternative copied from current weights. RQ-001 asks five original questions about horizon, cash-access flexibility, stability/growth preference, reaction to a 20% decline, and explicitly stated loss comfort. Deterministic summaries keep willingness and capacity-related notes separate, preserve uncertainty, and compare selected loss comfort with observed drawdown. No validated score, inferred volatility target, suitability judgment, or allocation recommendation is generated. Manual volatility input remains Advanced; model scope/source rules and final 2026 testing are unchanged. The complete software suite has 146 passing tests, with actual browser and real-data API checks. Read [RISK_PREFERENCES.md](RISK_PREFERENCES.md).

## Implemented comprehension pilot workflow — November 4, 2026

UX-P01 compares a fixed numerical report with the same report plus a chart. Three questions assess interpretation with the report available. The default practice mode scores responses in memory. Explicit recording mode obtains consent, assigns a format at random, and stores anonymous responses and timing locally. A read-only SQL summary reports success among all assigned sessions, completion, early exit, critical misunderstandings, and completion time. The complete suite has 149 passing tests. Browser and software verification precede real participant evaluation. See [COMPREHENSION_PILOT.md](COMPREHENSION_PILOT.md).

## Implemented report experiment analysis — November 4, 2026

The product brief connects portfolio risk comprehension to the decision about the default chart. The analysis plans sample size, checks cohort identity and allocation, and compares comprehension rates with a one-sided Fisher exact test and a score-based interval. The decision rule considers effect size, noncompletion, and observed critical misunderstandings. Temporary fixtures verify the checks. Real participant evaluation remains pending. See the [report experiment brief](REPORT_EXPERIMENT.md).

## Implemented portfolio forecast development evaluation

PF-001 combines fixed holding forecasts with a 60-session co-movement estimate and compares them with the trailing portfolio benchmark on the two preexisting demo portfolios. It reports matched annualized volatility error, QLIKE, and exploratory paired date-block intervals across 36 pre-2026 dates. The trained model's average MAE advantage over EWMA is 0.045 percentage points. The interval spans zero. The next model milestone is the final procedure freeze. [Portfolio forecast evaluation](PORTFOLIO_FORECAST_DEVELOPMENT.md)

## Completed 2026 model holdout — November 5, 2026

EV-002 freezes the model, forecasts, metrics, and decision rule before scoring the ten complete primary windows. The model improves demo portfolio MAE by 0.60 percentage points versus EWMA and 0.57 versus trailing 20. Both nominal two-date intervals include zero. The dashboard continues to present historical risk, with the forecast results available in the research report. [Holdout report](FINAL_EVALUATION_REPORT.md)
