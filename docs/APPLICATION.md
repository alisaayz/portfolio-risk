# Local portfolio comparison application

Updated November 4, 2026. The local application connects the accepted SQL warehouse to the independently reconciled historical risk engine. It supports side-by-side portfolio analysis while keeping weights and portfolio amounts local. Requested new symbols are sent to the market-data provider for their history. It does not use machine-learning forecasts or recommend allocations.

![Local application showing demonstration portfolios, drawdown, risk shares, and historical stress windows](assets/application-preview.png)

## Run the application

Build the accepted market warehouse using the README instructions, then run from the repository root:

```bash
.venv/bin/python -m scripts.market_catalog
.venv/bin/python -m scripts.serve_portfolio_app
```

Open [the local application](http://127.0.0.1:8765). Stop the process with Ctrl+C. The application uses Python's local HTTP server and the existing pinned environment; no frontend package installation or external hosting is required. Bind address is restricted to `127.0.0.1`. This is a local research preview, not a publicly hosted production service.

## What is implemented

Enter two long-only USD portfolios as percentages, select an as-of date and a 63-, 126-, or 252-session estimation window, and run the comparison. The interface searches the versioned U.S. directory by ticker or company name. New histories are loaded and audited in a single-worker queue before use. Searchable listing candidates are broader than loaded/validated price histories; failures remain visible. See [the expansion report](US_MARKET_EXPANSION.md). The starting AAPL/SPY/BND holdings are demonstrations. “A weight (%)” and “B weight (%)” mean the percentage of each named portfolio allocated to a holding. Up to 100 positive positions per portfolio are supported. Zero positions are omitted; positive weights must sum to 100% without automatic rescaling. Invalid inputs produce a visible error. Editing inputs marks previous results stale and disables export until recalculation.

Results include annualized sample volatility, full-history maximum drawdown, wealth/drawdown charts, capital weights versus Euler volatility-risk shares, pairwise correlations, and three fixed historical windows. An optional annualized-volatility reference compares the historical estimate with a level entered by the user. It does not guarantee a future risk limit and does not generate suggestions.

The demonstration matches the existing portfolio baseline: 11.29% versus 7.24% annualized volatility over 252 returns ending November 3, 2026; full-history maximum drawdowns are −26.94% and −19.46%. AAPL's 30% capital allocation contributes 52.91% of the first demonstration's estimated volatility. These are labeled hypothetical allocations, not personal holdings or actual investment performance.

## Calculation and data flow

```mermaid
flowchart LR
    A[Local browser: portfolio weights and reference] --> B[Validated local JSON request]
    C[Accepted warehouse: read-only] --> D[Reconciled historical risk engine]
    A --> J[U.S. directory search]
    J --> K[Queued provider request and AP-001 audit]
    K --> L[Separate cached source evidence]
    C --> M[In-memory composition for additional symbols]
    L --> M
    M --> D
    B --> D
    D --> E[Sample covariance and risk contributions]
    D --> F[Daily-rebalanced historical wealth]
    F --> G[Fixed-window stress replay]
    E --> H[Browser charts and tables]
    F --> H
    G --> H
    H --> I[User-triggered local JSON export]
```

Both portfolios use the same complete common history. Sample covariance uses N−1, annualization by 252, and the selected estimation window. Portfolio variance is `wᵀΣw`; Euler contributions sum to volatility, and negative diversifying contributions are retained. Correlation and risk shares remain undefined when the required denominator is zero. The original SQL/NumPy reconciliations run for each analysis.

Full-history charts and maximum drawdown cover a different interval from the trailing covariance estimate; both windows are displayed. Replay assumes fixed weights rebalanced daily with no transaction costs or taxes. It describes how the entered exposures would have behaved, not how an actual investor traded.

## Historical scenario registry HS-001

| Window | Starting close | Ending close |
| --- | --- | --- |
| Early 2020 | 2020-02-19 | 2020-03-23 |
| 2022 calendar year | 2021-12-31 | 2022-12-30 |
| March 2023 | 2023-03-08 | 2023-03-24 |

The [registry](../config/stress_scenarios.json) fixes these dates for descriptive replay. Return is ending wealth divided by wealth at the starting close, minus one. Scenario drawdown uses a peak established within the window, including its initial capital. If either endpoint is outside the selected portfolio history, the complete scenario is unavailable; no partial or future period is substituted. These are historical examples, not probabilities, forecasts, or evidence of event causation.

## Privacy, verification, and limits

The service reads the warehouse without changing it and keeps submitted inputs in memory. It does not save portfolio weights/amounts, log request contents, or send analytics externally. An explicit Add request can download a new symbol’s history through the saved analysis cutoff; raw market evidence and source metadata are cached locally under AP-001. JSON export is user triggered and saved through the browser. The API serves a fixed asset list, checks local Host/Origin values, requires bounded JSON requests, and sends no cross-origin access permission. These controls support local use; public hosting would require a separate design and review.

The initial nine application tests cover equivalence with the verified engine, optional references, invalid inputs, scenario endpoints and within-window drawdown, unavailable periods, date formatting, JSON validation, local request boundaries, and unchanged warehouse hashes after actual HTTP analysis. Browser checks confirmed the demo metrics, reference comparisons, invalid totals, stale-result status, chart switching, JSON export, and desktop/mobile layout. The exported demonstration contains 1,719 chart dates and the expected unrounded risk values. A mobile overflow and date-only formatting inconsistency found during testing were corrected.

The saved market snapshot remains through November 3, 2026; this page makes no live-price claim. Three retained index-source exceptions remain excluded from portfolio calculations. Revised histories and the current-survivor universe remain limitations. ETF look-through, cash, leverage, FX conversion, trading costs, and taxes are not modeled. Weight entry is available in the browser; latest-close quantity input remains supported separately by the existing command-line engine. A hash-verified development scorecard now shows 2023–2025 instrument-level MAE and 2025 secondary QLIKE. Its values are separate from the entered portfolios and do not demonstrate statistical significance. The fixed model universe remains sixteen instruments, and final 2026 model outcomes/scores remain reserved. Portfolio forecasts, persistent private snapshots, news context, and adjustment suggestions are subsequent phases.

## Broader-search and measurement update

The full suite now contains 136 passing tests. Added checks cover directory classification/search, class-share mapping, immutable replay, cache tampering, metadata/type/currency/timezone mismatches, missing-session and adjustment barriers, failure retention, separate composition without warehouse writes, and verified metric-summary display. Actual local HTTP checks exercise queued loading and a mixed META/AAPL portfolio. Browser checks verify META addition, VOO keyboard addition, clear weight labels, unchanged demo metrics, a development scorecard, and mobile/desktop sizing. Existing user entries were preserved; public previews contain demonstration values only.

The proposed [user-measurement study](METRICS_AND_EXPERIMENTS.md) is documented but has not recruited participants, recorded task outcomes, collected telemetry, or produced a significance result. This distinction is explicit in the scorecard and README.
