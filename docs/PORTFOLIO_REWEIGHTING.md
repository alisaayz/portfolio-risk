# Reweight existing holdings

Implemented November 5, 2026. RW-001 helps a user explore how changing weights could affect measured historical risk. It starts with positive-weight holdings from the current portfolio and uses the same date and estimation window as the dashboard.

## Use the dashboard

1. Assess a portfolio with at least two holdings and open **Explore lower-risk weights**.
2. Set how much of the portfolio can move. The default is 10% of portfolio value, so selling 10% in one holding and buying 10% in another uses the full budget. Set optional minimum and maximum weights, or lock a holding at its current weight. The bounds must include the current weights.
3. Preview the allocation. The manual volatility reference, if supplied, becomes the optional target. Compare historical volatility, full replay drawdown, largest weight, value moved, and holding risk shares. Choose **Use as alternative** to load the scenario into the dashboard for charts and historical stress comparisons.

The preview returns the current weights when the target is already met or feasible changes cannot materially reduce estimated volatility. If the target is unreachable and a lower-risk scenario exists, the preview shows that scenario and labels the shortfall. The user can keep the current allocation or explore the alternative. Calculations use historical data, and scenario replays exclude trading costs and taxes.

## Method

The solver minimizes portfolio variance under a long-only weight budget, holding limits, locks, and a move limit. A move is half the sum of absolute changes in allocation. The solver uses nonnegative purchase and sale variables, with total purchases equal to total sales. It minimizes the quadratic form in the weights using the dashboard's reconciled annualized sample covariance. If a target is reachable, the solver stops at the first target crossing along the straight path from the current weights to its lowest-risk solution.

The application checks weight sums, holding bounds, locks, and the move budget. It replays the resulting weights through the existing risk engine and reconciles estimated volatility against the optimization calculation. [SciPy solver documentation](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html) · [Portfolio optimization reference](https://stanford.edu/~boyd/papers/portfolio.html)

## Demonstration

With a 10% move limit and no target, the November 3, 2026 snapshot shifts ten percentage points from AAPL to BND in the equity-heavy demonstration. SPY stays at 50%. This historical scenario lowers annualized volatility from **11.29% to 9.58%** and maximum drawdown magnitude from **26.94% to 24.14%**. Its largest weight stays at 50%. The application also verifies an AAPL lock and reports that a 5% volatility target is unreachable under these limits.

## Development replay

The rule uses only returns available through each of 36 shared forecast dates from 2023 through 2025. Both existing demo allocations start at their original weights on each date. Each scenario uses a 10% move limit and measures annualized sample volatility over the next 20 sessions. The alternatives use unchanged weights, a move toward equal weights, and a direct shift from the highest to the lowest standalone historical volatility. These are separate hypothetical decisions with daily rebalancing, without accumulated positions, transaction costs, or taxes.

| Estimation window | Demo | Unchanged | Toward equal | Direct shift | Optimizer |
| --- | --- | ---: | ---: | ---: | ---: |
| 63 sessions | Equity-heavy | 12.82% | 12.16% | 10.88% | 10.88% |
| 63 sessions | Higher-bond | 8.12% | 9.54% | 6.82% | 6.84% |
| 126 sessions | Equity-heavy | 12.82% | 12.16% | 10.88% | 10.88% |
| 126 sessions | Higher-bond | 8.12% | 9.54% | 6.82% | 6.83% |
| 252 sessions | Equity-heavy | 12.82% | 12.16% | 10.88% | 10.88% |
| 252 sessions | Higher-bond | 8.12% | 9.54% | 6.82% | 6.82% |

Values are means across the 36 realized windows per portfolio and setting. The optimizer lowers realized volatility versus unchanged weights in all 36 windows for both demos. The simple risk shift matches or beats its mean in these examples. Both demos hold the same three instruments, so results are descriptive and apply to this historical development sample. The replay evaluates a volatility objective. Expected returns and investment suitability require separate evidence.

```bash
.venv/bin/python -m scripts.evaluate_reweight
```

The command verifies the saved warehouse hash and development calendar, then emits matched observations and aggregate metrics. Repeated runs produced identical output. Replacement criteria and candidate screening are later stages. [Adjustment roadmap](PORTFOLIO_ADJUSTMENT_ROADMAP.md)
