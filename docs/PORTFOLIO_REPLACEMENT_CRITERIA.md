# Replacement criteria for one holding

Implemented November 5, 2026. RP-001 shows how volatile a substitute could be at different levels of correlation with the remaining portfolio. It uses the same historical risk window and constraints as the reweighting preview.

## Use the guide

After assessing a portfolio, open **Explore lower-risk weights**, then **What to look for in a replacement**. Choose an existing holding and enter the percentage of total portfolio value to move into one new holding. Other allocations stay fixed. The move must respect the budget, minimum weight, and lock. The existing maximum weights remain satisfied because every retained holding stays at or below its original weight. The replacement receives exactly the weight removed.

The manual volatility reference becomes the target. With a blank reference, the guide uses the current portfolio's estimated volatility as the ceiling. The table gives a feasible range at five assumed correlations. Correlation is measured against the combined remaining holdings, including any weight retained in the reduced position. A row can have no feasible range. In some negative-correlation cases, a minimum candidate volatility is required because the substitute needs enough offsetting movement to lower total variance.

## Calculation

Let \(x\) be the replacement weight, \(s\) the annualized volatility of the remaining weighted return contribution, \(v\) the substitute's standalone annualized volatility, and \(\rho\) its correlation with the remainder. The new portfolio variance is

```text
s² + (x × v)² + 2 × s × x × v × ρ
```

The solver finds the nonnegative values of \(v\) for which this expression is at most the squared target. If the remainder has zero measured volatility, the formula reduces to \(xv\) in volatility units and correlation is undefined. All estimates use the dashboard's annualized sample covariance. The assumed correlation values illustrate the tradeoff. In a candidate check, compute the exact correlation and volatility over the same exchange sessions. [SEC guidance on diversification and asset allocation](https://www.investor.gov/introduction-investing/getting-started/asset-allocation)

## Demonstration and verification

The 252-session demo ending November 3, 2026 reduces AAPL from 30% to 20%, leaving SPY and BND at 50% and 20%. A hypothetical replacement receives 10% of portfolio value. With a 10% annualized portfolio volatility target, the maximum standalone volatility is **34.05% at zero correlation** and **11.03% at +0.50 correlation**. The target and correlations in this example are scenario inputs.

The bounds were checked against 39 direct recalculations using 13 other DS-002 instruments and the 63-, 126-, and 252-session windows. The variance identity reconciled to within 1e-12 in volatility units, and all 39 target classifications agreed. Fixtures cover a negative-correlation band, an infeasible band, a zero-risk remainder, and a locked holding. Browser verification exercised the live demo and lock enforcement.

The guide addresses historical volatility. A candidate assessment also needs complete matched history, documented asset exposure, liquidity evidence, and costs. The audited candidate screen uses this guide’s target and swap constraints on matched histories. [Candidate screen](PORTFOLIO_CANDIDATE_SCREEN.md)
