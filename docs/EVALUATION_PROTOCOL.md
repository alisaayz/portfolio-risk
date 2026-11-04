# Evaluation protocol and testing plan

Protocol **EV-001**, established November 4, 2026, before any model has been trained or scored. The user requested extensive testing and a reserved 2026 historical test. [Machine-readable contract](../config/evaluation_protocol.json).

## Research question

Can a pooled model improve next-20-session realized-volatility estimates relative to trailing-20-session and exponentially weighted variance forecasts? A reproducible comparison is the success criterion; superior machine learning performance is not assumed.

## Dates and model selection

![Chronological development and reserved 2026 test, with target-boundary exclusions](assets/evaluation-timeline.svg)

| Stage | Forecast-origin dates | Rule |
| --- | --- | --- |
| Initial training | 2020–2024 | Require complete feature history and a target ending before 2025 |
| Main validation | 2025 | Choose features, settings, and methods; targets must end before 2026 |
| Earlier development folds | Validate on 2023 and 2024 | Train on eligible earlier origins; remove labels reaching the validation year |
| Final refit | Eligible pre-2026 origins | Refit the selected recipe using only labels ending before 2026 |
| Reserved historical test | 2026 | Frozen model; rolling historical inputs allowed; no fitting or tuning on 2026 outcomes |

The 2025 fold is the main validation year, not an additional independent holdout after selection. Development years may inform model choices; their scores will be reported as development evidence. Preprocessing is fitted within each training partition. All instruments use the same date boundaries; random row splitting is prohibited.

The reference dataset starts in 2020. A maximum 252-return feature window consumes its first 252 origins as warmup. Thus the nominal 2020–2024 training period does not provide eligible forecasts throughout the 2020 market shock. Extending pre-2020 context would require a versioned data/protocol review before model selection, rather than a performance-driven change after testing.

We have already inspected 2026 for data quality and descriptive portfolio risk. This is a **retrospective model holdout**, not a blinded or prospective experiment. Its model scores remain unopened. A later forward-recorded experiment will preserve forecasts before their outcomes occur.

## Targets and leakage controls

For a prediction made after the close at origin t:

```text
return[t] = adjusted_close[t] / adjusted_close[t-1] - 1
target_variance[t] = (252/20) × sum(return[t+i]^2, i=1..20)
target_volatility[t] = sqrt(target_variance[t])
```

Twenty means exchange sessions, not calendar days or twenty nonmissing rows. Targets whose end date reaches the next partition are excluded from the earlier partition. Targets not yet fully observed remain explicitly incomplete. 2026 origins whose outcomes extend into 2027 are excluded from this calendar-year test even once those outcomes become available.

The implemented [date-membership builder](../scripts/evaluation_splits.py) enforces warmup, session integrity, fold boundaries, future-label availability, and a stable non-overlapping primary test grid. It calculates dates and counts only. It does not compute test outcome values or model scores, or confer source acceptance on additional instruments. [Observed membership counts](EVALUATION_SPLITS.md).

The [modeling layer](MODELING_DATASET.md) now passes future-value perturbation tests: altering observations after t leaves earlier features unchanged. It stores features, development labels, and membership separately and computes no numerical final-test outcomes. New feature versions must pass the same controls. Revised adjusted histories remain a limitation: those tests establish transformation causality, not historical vendor availability or point-in-time archival accuracy.

## Comparisons fixed before opening the final test

- Primary: mean absolute error of annualized volatility, reported in percentage points. Calculate per-instrument MAE on identical eligible origins, then average instruments equally. Also show each instrument and exposure group.
- Secondary: variance QLIKE, `log(predicted_variance) + realized_variance / predicted_variance`. Use a declared lower bound of `1e-12` on predicted annual variance for numerical evaluation, report floor counts, and separately reject nonfinite or negative forecasts. Zero realized variance is permitted by this score.
- Compare the trained model, trailing-20-session variance, and exponentially weighted variance on the same observations. Decay parameters and all model choices are selected using development data only.
- Primary test origins are every twentieth session, anchored to the first eligible 2026 origin. Retain that grid as data is appended; do not move it to improve results. Daily overlapping results are secondary and identified as dependent.
- Keep every attempted development recipe and its scores, seeds, parameters, dataset identity, and failures in experiment records. Do not repeatedly inspect final-test scores while modifying the model.

At the November 3 snapshot cutoff, each instrument has ten completed primary test windows. Sixteen instruments do not create 160 independent market episodes; they share dates and exposures. Report paired errors by origin and instrument, avoid precise significance claims from this small sample, and extend evidence through earlier validation years and later forward observations. Any resampling must preserve dependence across instruments and sessions rather than treating rows as independent.

## Testing layers and implementation status

| Layer | Checks and purpose | State |
| --- | --- | --- |
| Source integrity | Hashes, exchange sessions, duplicates, currencies, OHLC, actions, and missing values | Implemented; expanded sample passes structural checks |
| Source acceptance | Selected independent quote/action checks, source policy, and discrepancy quarantine | Implemented for sixteen instruments with limited quote/action evidence; comparator quarantined |
| Storage and recovery | Repeated loads, transaction rollback, explicit versions, export corruption | Implemented for expanded warehouse; every SQL return and complete risk window reconciled |
| Date membership | Warmup, fold purging, horizon completeness, year-end exclusions, stable primary grid | Implemented and regression-tested |
| Feature/target correctness | SQL versus NumPy, complete session endpoints, future-price perturbation, and split/year-boundary examples | Implemented for twelve price features and pre-2026 targets; final-test values withheld |
| Forecast baselines | Known constant/variable-return fixtures, positive outputs, common evaluation origins | Planned with forecasting implementation |
| Model evaluation | Rolling development years, pooled/per-instrument errors, fixed final test, reproducible seeds | Protocol fixed; execution planned |
| Robustness | Predeclared development slices for high/low volatility, equity/bond/gold groups, and sensitivity to feature windows | Planned; choices fixed before final scoring |
| Portfolio forecasts | Evaluate portfolio predictions separately, including correlation estimation | Planned; descriptive portfolio baseline already reconciled |
| Operation | Failed requests, stale data, interrupted jobs, and forward-recorded predictions | Partially implemented for acquisition; operational application planned |

Stress slices and sensitivity experiments use development data to guide decisions. Test-period breakdowns are descriptive reporting after the recipe is frozen. No test-year slice may be used to choose a replacement model without retiring the holdout and labeling subsequent results exploratory.

## Conditions for final scoring

Before opening 2026 model scores, freeze source acceptance, dataset, features, splits, baseline definitions, preprocessing, model settings, seeds, metrics, and primary origins. Complete feature/target reconciliation and leakage tests. Record the final procedure and code commit, then explicitly version the protocol to allow final scoring. The current configuration rejects an opened-test flag; it is a workflow guard, not a security barrier around historical data.

## Reproduction and references

```bash
.venv/bin/python -m scripts.evaluation_splits --snapshot data/audit/<expanded-run-id>
.venv/bin/python -m unittest discover -s tests -v
```

Generated membership CSVs and full manifests remain local. Identical evidence, code, calendar version, and protocol reproduce the same manifest identity. The public report contains eligibility counts rather than prices or forecast scores.

Chronological evaluation follows [scikit-learn's time-series split guidance](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) and [Forecasting: Principles and Practice on time-series cross-validation](https://otexts.com/fpp3/tscv.html). The custom session/end-date rules address this project's overlapping 20-session labels; a generic chronological split alone does not establish those rules.
