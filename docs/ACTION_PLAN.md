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

### 3. Build the Python ingestion and SQL foundation — three-instrument SQL milestone implemented

- [ ] Select 12–20 reference instruments and freeze initial history dates based on the audit. Record selection limits, including survivorship bias from today's instruments.
- [x] Implement explicit acquisition settings, visible errors, saved snapshots, and offline replay; general incremental provider updates remain future work.
- [x] Create versioned source/dataset tables, normalize to Parquet, and load DuckDB transactionally.
- [x] Write policy-controlled price/context views, a quality-issue ledger, calendar-aligned returns, and trailing-risk inputs.
- [x] Rerun the same load and verify unchanged counts, dataset ID, and five Parquet hashes; reconcile SQL calculations independently.

**Output:** one command produces an audited, versioned price dataset and quality report. **Done when:** failures are visible and reruns preserve reproducible results.

### 4. Produce a personally useful baseline report

- [ ] Support a dated portfolio entered as weights or quantities, with validation and a declared currency.
- [ ] Calculate adjusted returns, annualized volatility, drawdown, correlations, and covariance-based holding risk contributions.
- [ ] Reconcile selected results using a second calculation path. Show missing-history exclusions and common-history dates.
- [ ] Compare two user-defined portfolios under the same assumptions. If using demonstration holdings, label them explicitly and use real market history.

**Output:** a report that answers “where is my risk coming from?” **Done when:** the numbers reconcile and every chart identifies its period, portfolio convention, and data version.

## Checkpoint 2: trained model with evidence — weeks 3–4

### 5. Build features, future targets, and chronological splits

- [ ] Implement SQL features using only information available at the forecast origin: trailing variance, returns, downside variation, and drawdown.
- [ ] Calculate the next-20-session realized-variance target from the specification in the project plan. Preserve future targets separately from available-at-origin features.
- [ ] Freeze train, validation, and untouched test dates after the coverage audit. Remove training examples whose future target windows reach the next period.
- [ ] Check feature/target alignment manually for selected instrument-date rows, including a split boundary.

**Output:** a versioned modeling dataset, feature dictionary, and split manifest. **Done when:** each feature and target can be traced to its source sessions and no future values enter the inputs.

### 6. Train and compare against simple alternatives

- [ ] Implement trailing-20-day and exponentially weighted variance forecasts first.
- [ ] Train one pooled gradient-boosted model with a documented positive-variance output convention. Tune using development data only.
- [ ] Record dataset version, parameters, seed, metrics, and model artifacts in MLflow.
- [ ] Evaluate annualized-volatility MAE and variance QLIKE on identical forecast origins; inspect results by instrument and market period.
- [ ] Use non-overlapping 20-day origins for the primary comparison. Open the final test only after choosing the modeling procedure.

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

## Immediate work queue

1. Review the data-audit walkthrough and the three open benchmark source exceptions.
2. Read the SQL walkthrough and inspect accepted prices, context, and quarantined issues with the example queries.
3. Calculate a baseline portfolio report with declared holdings assumptions; expand the reference universe after that calculation is verified.

**Current state:** the source walkthrough, Python environment, real-data acquisition, structural audit, cross-source comparison, and 12 regression tests are implemented. The original three-instrument sample contains 5,157 rows. Three benchmark discrepancies remain open. SQL storage, explicit dataset selection, source-policy enforcement, and historical SQL inputs are implemented for three instruments. Twenty regression tests cover the current system. Qlib, portfolio risk calculations, and model training are not implemented.
