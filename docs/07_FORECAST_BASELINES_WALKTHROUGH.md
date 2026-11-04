# Forecast baseline walkthrough

Updated November 4, 2026. The first forecasting experiment compares fixed-form historical risk estimates on development data. It does not train a machine-learning model or open the reserved 2026 test. [Observed results](BASELINE_FORECAST_REPORT.md).

## 1. Why benchmarks come before machine learning

A trained model needs to outperform useful, reproducible alternatives rather than merely produce forecasts. Both baselines estimate the same next-twenty-session squared-return variance target defined in EV-001. They use only returns observed through the forecast origin. Their displayed volatility is the square root of their annualized variance forecast.

## 2. Two forecast families

**Trailing twenty sessions:** use `252 × mean(r²)` across the latest twenty valid returns. This forecast is already represented by the modeling feature `variance_20`; treating it as a prediction means assuming the recent risk level will persist over the next twenty sessions.

**Exponentially weighted variance:** update the estimate after each newly observed return:

```text
v[t] = lambda × v[t-1] + (1-lambda) × 252 × r[t]²
forecast_target_variance[t] = v[t]
```

Three declared candidates use lambda 0.90, 0.94, and 0.97. A lower decay responds more quickly to recent changes; a higher decay retains older observations for longer. Approximate weight half-lives are 6.6, 11.2, and 22.8 sessions, respectively. These are specified candidates, not parameters selected from 2026 outcomes.

Initialize each instrument's recursion with its first valid annualized squared return. Reset state and consecutive-history counts after missing data. Require the same 252-return readiness as the modeling dataset before publishing any forecast. The independent pandas comparison uses `ewm(alpha=1-lambda, adjust=False)` on each uninterrupted run. Both forecasts use the squared-return convention, without subtracting a sample mean.

Using the current EWMA level for the twenty-session average assumes that level persists. No future correlation estimate, portfolio forecast, price prediction, or expected-return forecast is implied by this instrument-level experiment.

## 3. Match outcomes and dates before comparing scores

The evaluator reads a verified modeling-artifact identity and hashes; it does not download new observations. It generates pre-2026 forecasts and selects the existing 2023, 2024, and 2025 validation-fold origins.

The primary grid is anchored at each calendar year's first feature-ready origin, then advances every twenty sessions. Only afterward are incomplete or year-boundary-crossing outcomes excluded. Every method must provide a valid forecast for every selected origin; missing predictions cause an error rather than silently reducing its sample.

The current primary sample has **12 origins per instrument per year**, or **192 matched pairs per method per year**. Daily overlapping samples are secondary: 3,680 pairs per method in 2023, 3,712 in 2024, and 3,680 in 2025. Instruments share dates and exposures; these pair counts are not independent market-event counts. No confidence or significance claim is inferred from the number of ticker rows.

The state updates using actual returns as they become available during a validation year. This is a legitimate rolling input update, not fitting on that origin's future outcome. The decay is fixed within each candidate run. The final 2026 year is excluded before forecast generation and prohibited by the scoring function.

## 4. Metrics and selection

Primary error is absolute annualized-volatility error, in percentage points:

```text
error_pp = 100 × abs(sqrt(predicted_variance) - sqrt(realized_variance))
```

For example, a forecast of 14% annualized volatility against 20% realized annualized volatility has a six-percentage-point error. This is an error in a risk estimate, not an investment return or portfolio loss.

Secondary QLIKE uses `log(predicted_variance) + realized_variance/predicted_variance`. It can be negative; lower is better when comparing the same outcomes. QLIKE applies an explicit prediction floor of 1e-12, with floor counts recorded. MAE uses the raw nonnegative variance prediction. Negative or nonfinite forecasts and negative or unavailable outcomes are rejected. A zero realized variance is valid.

For each method, average errors within each instrument, then average instruments equally. This differs from pooling rows when histories have different sizes. Report individual instruments and predeclared exposure groups as well as the aggregate.

[BL-001](../config/forecast_baselines.json) chooses the EWMA decay with the lowest primary 2025 equal-instrument MAE; ties use ascending method ID. Main validation data therefore influences the choice. All candidates remain in the experiment record, including their earlier-year and secondary-metric results. The selected candidate's 2025 performance is selection-data evidence, not an unbiased final-test result.

## 5. What the first result actually says

EWMA 0.90 is selected by the declared 2025 primary rule: its annualized-volatility MAE is approximately **5.91 percentage points**, compared with **6.30** for trailing twenty sessions. However, trailing variance has lower QLIKE in 2025. The best EWMA decay by MAE also varies across development years: 0.94 in 2023 and 0.97 in 2024. The evidence supports retaining strong benchmarks and reporting metric tradeoffs, not declaring one method universally best.

These are instrument-level errors on a small, current-survivor research universe. A model's portfolio-level forecasting accuracy must be evaluated separately after correlation estimation is implemented. Revised source histories and the finite sample remain limitations.

## 6. Verification and experiment artifacts

Checks cover hand-calculated recurrence and metrics, explicit zero handling, gap resets, equal-instrument averaging, unchanged earlier forecasts after future-input changes, instrument isolation, common-sample requirements, primary-grid endpoints, selection/tie rules, and refusal to score final-test dates. Real-data EWMA values match pandas, and a fixed development-cutoff perturbation leaves earlier forecasts exactly unchanged.

Local content-addressed artifacts contain all candidate forecasts, evaluation origins, per-origin errors, per-instrument/group metrics, recipe, summary, figures, and output hashes. A repeated run must preserve all recorded output hashes. Source modeling files are verified before use. This implements file-based experiment tracking; MLflow integration remains planned for trained-model experiments and is not claimed here.

```bash
.venv/bin/python -m scripts.evaluate_baselines --modeling-dataset data/modeling/<modeling-dataset-id>
.venv/bin/python -m unittest discover -s tests -v
```

## 7. Next experiment

Train one pooled positive-variance model using the explicit feature whitelist and chronological development folds. Fit any preprocessing on the corresponding training partition, compare predictions on these same primary and secondary origin grids, and record every attempted recipe. Evaluate the trained model against both trailing variance and the development-selected EWMA. Freeze the full procedure before deriving final 2026 outcomes or opening final-test scores.

References: [pandas exponentially weighted calculations](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.ewm.html), [Forecasting: Principles and Practice on chronological forecast evaluation](https://otexts.com/fpp3/tscv.html), and the project's [EV-001 protocol](EVALUATION_PROTOCOL.md). The reported numerical results come from the saved project experiment, not those reference pages.
