# Audited replacement candidate screen

Implemented November 5, 2026. The screen evaluates a partial or full swap from one existing holding into an instrument from the audited research list. It preserves the [replacement guide's](PORTFOLIO_REPLACEMENT_CRITERIA.md) budget, minimum weights, locks, and historical target.

## Use the screen

Assess the portfolio and open **Explore lower-risk weights → What to look for in a replacement**. Choose a holding and how much of total portfolio value to replace. Select **Screen audited candidates**. The table shows each symbol, research exposure label, standalone volatility, correlation with the remaining holdings, resulting portfolio volatility, and target status. A qualifying row can be loaded into the optional alternative for drawdown, risk contributions, and stress replay.

## Eligibility and ranking

The screen checks the active warehouse's DS-002 policy and its hash-bound RU-001 registry. It uses accepted instruments from that 16-instrument list and excludes existing holdings. The broader directory supports discovery for manual analysis. The screen reads existing returns without downloading any data.

DuckDB selects returns over the current portfolio's exact risk window. The calculation uses the same exchange dates for every candidate and marks incomplete histories unavailable. It combines each candidate's weighted returns with the retained portfolio, then measures annualized sample volatility. A separate covariance identity reconciles the estimate. A candidate meets the historical target when the resulting estimate is at or below it. The table sorts by resulting volatility, with ties broken by ticker. The API returns the candidate universe, policy, dataset ID, and estimation dates for traceability.

Research exposure labels come from the dated RU-001 registry. Risk estimates reflect the saved price history. Liquidity, fees, tax consequences, and the effect on investment objectives require separate evidence. The list is small and contains current survivors.

## Verified example

In the equity-heavy demo, move 10% of portfolio value out of AAPL and set a 10% historical volatility target. On the 252-session window ending November 3, 2026, **six of thirteen** candidates meet the target. Loading IEF into the alternative produces **9.59%** historical volatility versus **11.29%** for the starting demo. The comparison uses fixed daily weights and excludes costs and taxes.

Candidate qualification changes with the estimation window. The same screen finds 13 qualifiers at 63 sessions, nine at 126, and six at 252. All **39 candidate and window calculations** reconcile with direct recalculation through the portfolio risk engine. A software fixture covers missing dates and existing-holding exclusion. [Demo](assets/dashboard-demo.gif)
