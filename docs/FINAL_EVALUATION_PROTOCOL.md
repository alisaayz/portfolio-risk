# Frozen 2026 evaluation protocol

Frozen November 5, 2026, before computing the 2026 model outcomes or scores. EV-002 opens a separate evaluation path for the saved DS-002 snapshot through November 3. The original EV-001 development code retains its 2026 boundary. The model holdout is retrospective. The 2026 price data were previously inspected for source quality and historical risk.

## Frozen inputs and sample

The [run specification](../config/final_evaluation.json) pins the warehouse hash, modeling dataset, development experiment, selected methods, and primary origin/end pairs. The repository commit pins feature, model, source policy, portfolio, and evaluation code and configurations. The evaluator checks the stored manifests and pins the runtime package versions to the development experiment.

Refit the seven-leaf gradient boosting model on all 19,776 eligible pre-2026 labels. The latest label end is December 31, 2025. Use the original twelve features, Poisson loss, equal-instrument training weights, fixed seed, and disabled early stopping. Freeze the fitted estimator throughout 2026. Trailing-20 and EWMA 0.90 are the comparators. Both use returns through each forecast date and the EWMA state carries forward from the available history.

Use the ten complete primary windows for every instrument and both fixed demo portfolios. Report overlapping daily results as a secondary diagnostic using all 191 common origins. Retain incomplete horizons outside the score sample. The two portfolios use the PF-001 60-session normalized return matrix to combine trained and EWMA holding forecasts. The direct portfolio benchmark uses trailing-20 weighted daily returns. Compute realized variance as 252 times the mean squared daily return over sessions t+1 through t+20, with fixed weights and daily rebalancing for portfolios.

## Metrics, uncertainty, and decision

Use annualized volatility MAE in percentage points as the primary metric and variance QLIKE as a secondary metric. Compute the score for each entity and take equal-weight averages. The primary research comparison is trained minus EWMA MAE across instruments. A negative difference favors the trained model. For uncertainty, average paired loss differences within each market date first. Estimate a nominal 95% percentile interval by circular resampling of adjacent two-date blocks across the ten ordered dates. Use 20,000 replicates and seed 42. One- and five-date blocks are sensitivity diagnostics. Apply the same procedure to the two demo portfolios and include the trailing comparison. Ten dates provide limited information about dependence and regime changes, so the intervals are descriptive and the report omits formal significance claims. [Paired forecast loss](https://www.nber.org/papers/t0169) · [Circular block resampling](https://statistics.stanford.edu/technical-reports/circular-block-resampling-procedure-stationary-data)

Consider the trained forecast for a forward dashboard trial only if the primary demo average improves by at least 0.50 percentage points versus **each** baseline, the upper end of both two-date intervals is below zero, and neither demo has worse MAE than either baseline. The 0.50-point threshold is a project decision criterion for the added model complexity. Otherwise keep the historical dashboard and retain the trained forecast for research. Review QLIKE and per-entity errors to explain tradeoffs. The result applies to these instruments, two allocations, and the saved observation period.

## Execution and audit

The evaluator first verifies the freeze commit, data identity, training boundary and exact date grid. It saves frozen forecast variances before computing outcome values. It then reads the required return windows, checks the exact number of sessions and dates, and reconciles realized values with SQL. It writes local predictions, matched scores, aggregate results and content hashes. Identical reruns verify the saved evidence.
