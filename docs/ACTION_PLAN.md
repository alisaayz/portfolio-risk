# Action checklist

Updated November 4, 2026. This is the execution checklist; [PROJECT_PLAN.md](PROJECT_PLAN.md) holds the technical specifications. Work in order, with a demonstration every two weeks. Budget roughly 12–20 hours per week and five to six weeks for the first complete version, adjusting after the data audit.

## The problem we are solving

For a portfolio I own or am considering, how much risk am I taking, which holdings contribute to it, and can a trained model improve my estimate of volatility over the next 20 trading days?

The system must connect real market data to an explainable risk report. A forecast is an estimate, and historical scenarios are hypothetical exposures under stated assumptions. We will report unsuccessful modeling experiments as well as successful ones.

## Checkpoint 1: real data to a baseline report — weeks 1–2

### 1. Understand and adapt a working reference — source review complete

- [x] Trace Microsoft's Qlib LightGBM example through configuration, data handler, model, and result records.
- [x] Identify what must change for a risk application.
- [x] Write the project question, forecast target, and first scope.
- [ ] Review the walkthrough together and resolve questions about inputs, targets, and evaluation.

**Output:** [01_QLIB_WALKTHROUGH.md](01_QLIB_WALKTHROUGH.md). This is a source-code review, not an executed training run.

### 2. Audit a small real-data sample — implemented; benchmark exceptions remain open

- [x] Establish an isolated Python 3.13.7 environment and record exact dependencies.
- [x] Download daily AAPL, SPY, and BND history from 2020-01-01 through 2026-11-03, with explicit adjustment, missing-row, and corporate-action settings.
- [x] Preserve provider-library output, structured metadata, retrieval times, request settings, code hashes, and file hashes in versioned local snapshots.
- [x] Check expected exchange sessions, duplicate dates, invalid prices, volume, OHLC consistency, and action adjustments.
- [x] Cross-check a selected Apple split and dividend amount against an issuer announcement.
- [x] Compare five completed-session closes per instrument with Stock Analysis and reconcile the S&P 500 benchmark against FRED.
- [x] Run 12 regression tests and reproduce findings from saved evidence without new downloads.
- [x] Formally disposition the three benchmark discrepancies under [DS-001](DATA_SOURCE_POLICY.md): retain original values, prefer FRED for index context, and quarantine Yahoo ^GSPC. The underlying causes remain unresolved.

**Outputs:** [data audit](DATA_AUDIT.md), [cross-source validation](CROSS_SOURCE_VALIDATION.md), [implementation walkthrough](02_DATA_AUDIT_WALKTHROUGH.md), scripts, and ignored local snapshots. The stock/ETF sample passes structural checks and limited quote spot checks. Benchmark source agreement is not complete; see the exception report.

### 3. Build the Python ingestion and SQL foundation — 16-instrument SQL milestone implemented

- [x] Select and structurally audit 16 reference instruments, preserving January 2020–November 2026 capture dates and current-survivor selection limits in [RU-001](REFERENCE_UNIVERSE.md).
- [x] Check 80 selected closes and four issuer references; implement/test DS-002; promote 27,504 observations across sixteen instruments while retaining earlier versions. All 27,488 SQL returns and 27,184 complete volatility windows reconcile independently.
- [x] Implement explicit acquisition settings, visible errors, saved snapshots, and offline replay; general incremental provider updates remain future work.
- [x] Create versioned source/dataset tables, normalize to Parquet, and load DuckDB transactionally.
- [x] Write policy-controlled price/context views, a quality-issue ledger, calendar-aligned returns, and trailing-risk inputs.
- [x] Rerun the same load and verify unchanged counts, dataset ID, and five Parquet hashes; reconcile SQL calculations independently.

**Output:** one command produces an audited, versioned price dataset and quality report. **Done when:** failures are visible and reruns preserve reproducible results.

### 4. Produce a personally useful baseline report — implemented for the initial sample

- [x] Support a dated portfolio entered as weights or quantities, with validation and a declared currency.
- [x] Calculate adjusted returns, annualized volatility, drawdown, correlations, and covariance-based holding risk contributions.
- [x] Reconcile selected results using a second calculation path. Show missing-history exclusions and common-history dates.
- [x] Compare two user-defined portfolios under the same assumptions. If using demonstration holdings, label them explicitly and use real market history.

**Output:** [baseline report](BASELINE_PORTFOLIO_REPORT.md) and [walkthrough](04_PORTFOLIO_BASELINE_WALKTHROUGH.md). SQL returns and sample covariance reconcile with NumPy; volatility and drawdown also have separate calculation checks. Charts identify their windows and dataset, with portfolio conventions in the report. Quantity valuation is limited to the latest common close; historical share/split reconstruction remains outside this implementation.

## Checkpoint 2: trained model with evidence — weeks 3–4

### 5. Build features, future targets, and chronological splits

- [x] Implement twelve SQL features using prices through the forecast origin: returns, trailing variance, downside variation, drawdown, negative frequency, and extreme moves.
- [x] Calculate next-20-session realized-variance targets for development origins, storing them separately from features. Clip source observations before 2026 and withhold boundary-crossing/final-test target values.
- [x] Record EV-001: 2020–2024 initial training, 2025 main validation, reserved 2026 historical model test, and earlier development folds. Implement and test date-only membership, warmup, and label-boundary exclusions.
- [x] Apply EV-001 to actual features/development targets and preserve a versioned feature/target recipe. Reconcile values and endpoints; future-price perturbation cannot alter earlier inputs.
- [ ] Freeze preprocessing, baseline parameters, model settings, and the complete procedure before opening final scores.
- [x] Record independently reconciled AAPL examples at the 2020 split and 2024/2025 year boundaries; test shifted endpoints, missing sessions, and zero-return paths.

**Output:** a versioned modeling dataset, feature dictionary, and split manifest. **Done when:** each feature and target can be traced to its source sessions and no future values enter the inputs.

### 6. Train and compare against simple alternatives

- [x] Implement trailing-20-session variance and EWMA candidates 0.90/0.94/0.97; verify recurrence, causality, matched origins, and metrics.
- [x] Train three declared pooled gradient-boosting candidates with a Poisson log-link positive-variance convention; select using 2025 primary development MAE.
- [x] Preserve all benchmark candidates, data/code versions, configurations, forecasts, origins, per-origin errors, and metrics in content-addressed local experiment records.
- [x] Preserve trained-model recipes, fold dates, parameters, model files, predictions, failures, and hashes in reproducible local file-based records.
- [ ] Optionally integrate MLflow for experiment browsing; it is not installed and is not a prerequisite for the current verified file-based records.
- [x] Evaluate benchmark volatility MAE and variance QLIKE on identical 2023–2025 development origins; report all candidates and per-instrument/exposure-group results.
- [x] Evaluate all trained candidates against identical benchmark samples; report worse 2023 errors, all candidates, daily sensitivity, and instrument/regime breakdowns.
- [x] Use a fixed twenty-session primary grid for development comparisons, with daily overlapping results identified separately.
- [ ] Freeze the complete modeling procedure before deriving final 2026 outcomes or opening final-test scores.

**Output:** a comparison report showing when the model helps and when it fails. **Done when:** the experiment is reproducible and conclusions match the evidence, even if a baseline wins.

## Checkpoint 3: usable application — weeks 5–6

### 7. Connect instrument forecasts to portfolio scenarios

- [ ] Combine predicted instrument volatilities with a documented trailing, regularized correlation estimate.
- [ ] Evaluate portfolio forecasts against portfolio baselines; do not infer portfolio accuracy solely from instrument accuracy.
- [ ] Replay selected historical stress periods using fixed weights and explicit daily-rebalancing assumptions; keep buy-and-hold results separate.
- [ ] Explain holdings that lack the required history rather than silently filling it.

**Output:** existing-versus-alternative portfolio reports with forecast and historical risk views.

### 8. Package the system and make it repeatable

- [ ] Add a local interface for portfolio entry, comparison, and inspecting results.
- [ ] Add a repeatable batch workflow with caching, job status, and stale-data warnings based on observed failures.
- [ ] Document environment setup, commands, sources, assumptions, limitations, and reproduction steps.
- [ ] Prepare a short demonstration and an interview explanation covering one data problem, one modeling decision, and one unsuccessful experiment.

**Output:** a usable application, reproducible repository, evaluation report, and demonstration. Deployment, streaming, deep learning, and automated trading are later choices, outside this first-version checklist.

## News extension — feasibility audit completed; implementation remains proposed

- [x] Inspect bounded historical archive samples and document schema, title, timestamp, duplicate, and candidate-company coverage.
- [x] Preserve unavailable API responses and distinguish those from successful bulk-metadata access.
- [ ] Implement a forward-recorded after-close collector with relevance and coverage controls; evaluate text classification separately.
- [ ] Establish compatible historical news coverage before any prices-plus-news forecasting comparison. Do not open 2026 scores or alter EV-001 during source exploration.

## Later phase: portfolio adjustment suggestions — requested, not implemented

- [ ] Add dated user risk preferences, protected holdings, position bounds, and limits on allocation changes.
- [ ] Suggest feasible reweightings of current holdings and show before/after risk, concentration, and allocation turnover. Report infeasible targets.
- [ ] Describe useful replacement criteria, then optionally screen an approved candidate universe with supporting evidence.
- [ ] Independently verify constraints, chronological policy evaluation, sensitivity, and explanation accuracy before release.

See [the adjustment roadmap](PORTFOLIO_ADJUSTMENT_ROADMAP.md). Schedule after validation of the core risk system; this does not replace the immediate work below.

## Immediate work queue

1. Review the data-audit walkthrough and the three open benchmark source exceptions.
2. Read the SQL walkthrough and inspect accepted prices, context, and quarantined issues with the example queries.
3. Review the baseline report, especially capital weights versus risk contributions and the different estimation/replay windows.
4. Review DS-002 acceptance evidence, the maintenance-page failure, adjusted-price differences, and full SQL reconciliation in the expanded walkthrough.
5. Review the modeling feature dictionary, split/corporate-action examples, and distinction between predictor columns and outcomes.
6. Review the benchmark report, particularly primary-versus-secondary metric tradeoffs and the limits of selecting EWMA using 2025 scores.
7. Review trained-model evidence and the completed fixed-model grid/aggregation sensitivity; implement usable portfolio analysis before final procedure freeze. Keep 2026 outcomes/scores reserved.
8. Develop the proposed news-context layer separately, preserving coverage/availability records and verifying historical compatibility before predictive use.

**Current state:** data acquisition, audit, cross-source comparison, versioned SQL/Parquet storage, historical inputs, and the baseline portfolio report are implemented. The original three-instrument dataset remains retained with 5,157 selected rows; the active dataset now uses the expanded capture. Three benchmark discrepancies remain quarantined. One hundred and twelve regression tests cover the current system. A bounded news metadata audit is implemented; news collection, sentiment inference, and event-return analysis remain proposed. DS-002 selects 27,504 accepted rows across sixteen instruments; 37,818 retained price rows preserve earlier captures. All returns and complete historical volatility windows reconcile with NumPy. The modeling layer implements twelve features, development-only targets, and chronological membership with independent numerical/leakage checks. The dataset has 15,776 initial-training and 3,680 validation examples. Fixed-form benchmarks and three trained candidates have measured development scores. Repeat fitting, model restoration, and independent saved-score reconciliation pass. Final refitting, 2026 forecasts/numerical targets, and final-test scores remain uncomputed. Two labeled demonstration portfolios use real data; no personal holdings have been supplied. Qlib execution, final model testing, dedicated stress scenarios, and the application remain outstanding.

## Development sensitivity checkpoint

RB-001 evaluates four grid phases and leave-one-instrument-out score aggregation without refitting or reselection. Offset zero exactly matches the original primary comparison. The model/EWMA 2025 MAE ranking changes at the five-session offset; the selected model wins three of four phases versus EWMA and four versus trailing variance. These are dependent development diagnostics. Read [DEVELOPMENT_ROBUSTNESS.md](DEVELOPMENT_ROBUSTNESS.md). Final-test outcomes remain reserved.
