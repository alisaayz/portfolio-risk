# Price-based modeling dataset

Updated November 4, 2026. Features and development targets are implemented and independently reconciled. No model has been trained or scored. Final 2026 outcome values remain uncomputed.

## Observed result

- Market dataset: `80b5d80b266b0255f7c8de0310569de02f63a5ee0ff2a54e707ddfa2cd114166`.
- Modeling dataset: `ecc468b9aef284824e22c7c1cb47f0f89517ff583061cc72ef0eff4d37d23d83`.
- Predictor whitelist: **12** numeric features; future target/date/eligibility fields are excluded.
- Feature cells compared with NumPy, including matching null positions: **330,048**.
- Pre-2026 target rows independently compared, including incomplete tails: **24,128**.
- Reserved 2026 numeric targets: **0**. No model scores computed.
- Future-price perturbation at a fixed development cutoff leaves earlier features exactly unchanged.

| Instrument | Feature-ready rows | Computed development labels | Initial training | Main validation | Final refit eligible |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAPL | 1467 | 1488 | 986 | 230 | 1236 |
| BND | 1467 | 1488 | 986 | 230 | 1236 |
| EEM | 1467 | 1488 | 986 | 230 | 1236 |
| EFA | 1467 | 1488 | 986 | 230 | 1236 |
| GLD | 1467 | 1488 | 986 | 230 | 1236 |
| HYG | 1467 | 1488 | 986 | 230 | 1236 |
| IEF | 1467 | 1488 | 986 | 230 | 1236 |
| IWM | 1467 | 1488 | 986 | 230 | 1236 |
| JNJ | 1467 | 1488 | 986 | 230 | 1236 |
| JPM | 1467 | 1488 | 986 | 230 | 1236 |
| LQD | 1467 | 1488 | 986 | 230 | 1236 |
| MSFT | 1467 | 1488 | 986 | 230 | 1236 |
| QQQ | 1467 | 1488 | 986 | 230 | 1236 |
| SPY | 1467 | 1488 | 986 | 230 | 1236 |
| TLT | 1467 | 1488 | 986 | 230 | 1236 |
| XOM | 1467 | 1488 | 986 | 230 | 1236 |

Feature-ready rows include 2026 observations; development labels do not. Labels before full feature warmup are preserved for diagnostics but are not eligible training examples. Final refit includes pre-2026 rows excluded at the earlier training/validation boundary, after model selection only.

## Boundary and corporate-action examples

All rows below are AAPL; values are checked against independently sliced NumPy calculations. The split-date example tests the provider-adjusted return convention without applying the split a second time. It is not eligible training data because the 252-return warmup is incomplete.

| Origin | Target end | Features ready | Initial train eligible | Main validation eligible | Target value |
| --- | --- | --- | --- | --- | --- |
| 2020-08-31 | 2020-09-29 | False | False | False | Computed |
| 2024-12-02 | 2024-12-31 | True | True | False | Computed |
| 2024-12-03 | 2025-01-02 | True | False | False | Computed |
| 2025-12-02 | 2025-12-31 | True | False | True | Computed |
| 2025-12-03 | 2026-01-02 | True | False | False | Withheld |

Each target covers returns t+1 through t+20, excluding the origin return. Dates follow expected exchange sessions. Initial training labels reaching 2025 are excluded; validation/refit labels reaching 2026 are withheld. All 2026 origins retain features and membership only, with no numerical target. The last twenty observed origins also lack complete future horizons, as the separate date manifest records.

## Composition and reproducibility

The market database is read-only. Local modeling artifacts contain separate feature, development-target, split-membership, and joined development-example tables/Parquet files. Training, validation, and final-refit views select explicit membership flags. Model inputs must use the predictor whitelist; the joined diagnostic table contains metadata and future labels that must never be inferred as predictors.

Identity includes the accepted dataset/recipe, actual input hash, protocol, SQL definitions, builder/split code, and package versions. Existing exports are hash- and content-checked; different recipes produce distinct folders. Downloaded histories and derived modeling rows stay outside Git.

```bash
.venv/bin/python -m scripts.build_modeling_dataset
.venv/bin/python -m unittest discover -s tests -v
```

See the [feature dictionary and walkthrough](06_MODELING_DATASET_WALKTHROUGH.md) and [EV-001](EVALUATION_PROTOCOL.md). The features use revised adjusted histories, so transformation causality does not establish historical vendor availability. No preprocessing is fitted here; fit any future preprocessing on each training partition only. News, FRED/macro inputs, portfolio suggestions, and expected-return forecasts are absent from this feature version.
