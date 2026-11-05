# PF-002 prospective portfolio forecast protocol

Frozen for the Version 2 technical preview on November 5, 2026. The earlier EV-002 results remain retrospective evidence. The dashboard uses historical estimates while forward evidence is pending. [Retrospective report](FINAL_EVALUATION_REPORT.md)

## Predictions and enrollment

Use the four demonstration portfolios in the PF-002 configuration. Fit the previously selected gradient boosting recipe on the same 19,776 examples with target dates before 2026. Keep the sample, feature SQL, model settings, 60-session co-movement estimate, and portfolio weights fixed. The comparators are the direct trailing 20-session portfolio variance and the frozen 0.90 EWMA holding variance combined using the same co-movement estimate as the model. All methods predict next-20-session annualized variance for the same date and portfolio. [Machine-readable configuration](../config/prospective_forecast.json) · [Model recipe](../config/final_evaluation.json)

Anchor the schedule on the November 6, 2026 NYSE session and step forward 20 exchange sessions for 72 scheduled origins. Enroll only after the designated close and before the next exchange open. Require an audited snapshot ending exactly at the designated close for all reference instruments. Preserve the captured vintage and check all exchange dates. Skip and report any origin with missing data, failed checks, or a late recording. Each record includes the data, code and configuration hashes, forecast and target dates, software versions, and a UTC clock reading. The recorder refuses to replace an existing origin.

For confirmatory evidence, independently timestamp each record digest before the next open and preserve the receipt with the local record. The recorder prints the digest for this purpose. A local clock is sufficient for a rehearsal. The study requires the separate timestamp evidence to admit an origin. Retain a fixed approved capture of each complete outcome window and report revisions separately. Provider permission and the timestamping arrangement remain open.

## Evaluation and decision

Evaluate once after all 72 scheduled opportunities and their outcome windows have closed. Require at least 60 independently timestamped, matched and scored market origins. Record the count and reason at every skipped slot. This schedule represents several years of new market dates. Forecast performance remains pending at the technical preview.

The primary outcome is annualized RMS volatility over the next 20 sessions using the same fixed weights and matched dates. Compute absolute volatility error in percentage points. Average equally over the four portfolios at each origin before comparing methods. Report mean error by portfolio and the pooled estimate. Secondary measures are variance QLIKE using the existing prediction floor, signed forecast error, and understatement of realized volatility by at least five percentage points. Also report error on the highest quintile of realized downside deviation for each portfolio, with the sample counts.

Pair all methods on the same dates. Use 20,000 circular block resamples of three adjacent scheduled origins, with two- and six-origin sensitivity checks, preserving the four portfolios and missing slots together. Use one-sided 97.5% upper bounds on the two model-minus-baseline MAE differences to control the two planned comparisons. Require a point improvement of at least 0.50 percentage points and a bound below zero against both baselines, with no worse mean MAE on any of the four portfolios. The confidence bounds depend on the block dependence assumption. Report missing-origin patterns and sensitivity before considering a separate dashboard experiment.

## Record a forecast

Run on a scheduled date with an authorized, audited warehouse and the frozen local training input.

```bash
.venv/bin/python -m scripts.record_prospective_forecast \
  --database /path/to/accepted/warehouse.duckdb \
  --training /path/to/frozen/development_examples.parquet
```

The private ledger starts when an eligible input arrives. The implementation was rehearsed on the saved November 3 snapshot for four demo portfolios and three methods. That check had no outcome input and created no live record. Scoring and independent receipt verification are reserved for the forward study.
