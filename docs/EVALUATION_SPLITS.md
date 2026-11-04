# Evaluation date eligibility

Updated November 4, 2026. This date-only manifest reserves 2026 for final model evaluation. No test targets, forecasts, or model scores are calculated here. These are row-eligibility counts, not sample independence or model results.

- Snapshot: `20261104T184106998030Z`.
- Manifest: `b9edd8cf1ad18c49b27a08d3977f3bba196a1748de033794767a180acf1c1381`.
- Protocol: [EV-001](../config/evaluation_protocol.json).
- Source audit review flags: **0**. Date eligibility does not approve flagged source data.

| Instrument | Train 2020–24 | Validate 2025 | Final refit pre-2026 | Eligible test dates | Completed primary test origins | Pending test outcomes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AAPL | 986 | 230 | 1236 | 191 | 10 | 20 |
| MSFT | 986 | 230 | 1236 | 191 | 10 | 20 |
| JPM | 986 | 230 | 1236 | 191 | 10 | 20 |
| JNJ | 986 | 230 | 1236 | 191 | 10 | 20 |
| XOM | 986 | 230 | 1236 | 191 | 10 | 20 |
| SPY | 986 | 230 | 1236 | 191 | 10 | 20 |
| QQQ | 986 | 230 | 1236 | 191 | 10 | 20 |
| IWM | 986 | 230 | 1236 | 191 | 10 | 20 |
| EFA | 986 | 230 | 1236 | 191 | 10 | 20 |
| EEM | 986 | 230 | 1236 | 191 | 10 | 20 |
| BND | 986 | 230 | 1236 | 191 | 10 | 20 |
| IEF | 986 | 230 | 1236 | 191 | 10 | 20 |
| TLT | 986 | 230 | 1236 | 191 | 10 | 20 |
| LQD | 986 | 230 | 1236 | 191 | 10 | 20 |
| HYG | 986 | 230 | 1236 | 191 | 10 | 20 |
| GLD | 986 | 230 | 1236 | 191 | 10 | 20 |

Training and validation counts exclude origins whose next-20-session label reaches the next partition. Final refitting may use eligible pre-2026 labels only after the recipe is selected. Features require 252 prior returns; outcomes require 20 future sessions. The primary test grid uses every twentieth origin, anchored before excluding incomplete targets; each included target window is non-overlapping within an instrument. Cross-instrument outcomes remain correlated.

Development folds validate on 2023, 2024, and 2025, each trained on eligible earlier labels. The selected model is frozen for the 2026 historical test: rolling inputs are permitted, model fitting or tuning on 2026 outcomes is not. Year-end-crossing targets are excluded even when later observations become available. The last 20 observed origins currently lack completed targets.

See the [evaluation protocol and testing plan](EVALUATION_PROTOCOL.md) for model comparisons, leakage checks, uncertainty limitations, and the conditions for opening final scores. Membership CSVs and full recipes stay local under `data/evaluation/<manifest-id>/`.
