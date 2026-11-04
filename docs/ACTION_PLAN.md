# Action checklist

Updated November 3, 2026. This is the execution checklist; [PROJECT_PLAN.md](PROJECT_PLAN.md) holds the technical specifications. Work in order, with a demonstration every two weeks. Budget roughly 12–20 hours per week and five to six weeks for the first complete version, adjusting after the data audit.

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

### 2. Audit a small real-data sample — next implementation task

- [ ] Establish an isolated Python environment; check available compatible package versions before pinning dependencies.
- [ ] Probe AAPL, SPY, and BND as three data-test instruments, not investment recommendations. Request daily history for 2020-01-01 through 2026-11-02 inclusive, subject to provider coverage.
- [ ] Request original prices, adjusted close, dividends, and splits explicitly. Record the provider's actual response and adjustment settings; do not assume that every field exists.
- [ ] Retain the response or provider-library output, request settings, retrieval time, and content hash. Distinguish original provider payloads from library-transformed results.
- [ ] Inspect date coverage, missing fields/sessions, duplicate dates, nonpositive prices, and adjustments around actual corporate actions. Separate exchange closures from missing expected sessions.
- [ ] Record access conditions and whether the sample can support our intended returns calculation. On failure, save the failure and assess another source; do not substitute invented prices.

**Output:** a reproducible probe plus `docs/DATA_AUDIT.md` containing observed results. **Done when:** we can identify the source and price meaning of every sample, repeat the request, and explain any gaps. This step decides whether the provider is suitable before scaling up.

### 3. Build the Python ingestion and SQL foundation

- [ ] Select 12–20 reference instruments and freeze initial history dates based on the audit. Record selection limits, including survivorship bias from today's instruments.
- [ ] Implement one adapter with explicit date/settings inputs, visible errors, and cached snapshots.
- [ ] Create ingestion-run, instrument, price, and corporate-action tables; normalize to Parquet and load DuckDB.
- [ ] Write SQL coverage and quality queries and a canonical price view that selects a declared dataset version.
- [ ] Rerun the same ingestion and verify that canonical observations do not duplicate.

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

1. Read the first walkthrough: identify the model's inputs, its target, and the reason for a separate test period.
2. Run the three-instrument data audit in step 2 and inspect actual rows together.
3. Select the provider and initial universe from evidence, then implement the larger pipeline.

**Current state:** step 1's source review and adaptation notes are complete. Qlib has not been installed or executed. No market prices have been downloaded and no model has been trained. Step 2 has not started.
