# Expanded source validation

Updated November 4, 2026. Quote/action acceptance checks: **Pass**. Benchmark comparison: **Not passed; original values retained**. No model forecasts or scores are evaluated.

## Scope and observed checks

- Price capture: `20261104T184106998030Z`.
- External capture: `20261104T190642106948Z`.
- Stock Analysis is a separate website; its upstream vendor independence is not established. Daily USD Close is compared on the last five completed sessions in the price capture, excluding intraday and later dates.
- Total quote pairs compared: **80** across **16 instruments**. Published cents and a $0.01 tolerance are used, with missing dates failing. Spot checks do not certify the full price histories.

| Instrument | Compared / required | Mismatches beyond tolerance | Result |
| --- | ---: | ---: | --- |
| AAPL | 5 / 5 | 0 | Pass |
| MSFT | 5 / 5 | 0 | Pass |
| JPM | 5 / 5 | 0 | Pass |
| JNJ | 5 / 5 | 0 | Pass |
| XOM | 5 / 5 | 0 | Pass |
| SPY | 5 / 5 | 0 | Pass |
| QQQ | 5 / 5 | 0 | Pass |
| IWM | 5 / 5 | 0 | Pass |
| EFA | 5 / 5 | 0 | Pass |
| EEM | 5 / 5 | 0 | Pass |
| BND | 5 / 5 | 0 | Pass |
| IEF | 5 / 5 | 0 | Pass |
| TLT | 5 / 5 | 0 | Pass |
| LQD | 5 / 5 | 0 | Pass |
| HYG | 5 / 5 | 0 | Pass |
| GLD | 5 / 5 | 0 | Pass |

## Selected corporate actions

The [CA-001 reference registry](../config/corporate_action_references.json) records manually reviewed issuer facts and the specific fields supported. Archived issuer text is checked for the reviewed evidence and compared with provider action values. This is a narrow replay check, not a general semantic extractor or verification of all 645 dividends. ETF distributions are not independently reconstructed.

| Reference | Result | Supported scope | Evidence |
| --- | --- | --- | --- |
| AAPL_SPLIT_2020 | Pass | Split ratio and first split-adjusted trading date | [Issuer source](https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/) |
| AAPL_DIVIDEND_BASIS_2020 | Pass | Amount basis only: issuer 0.82 divided by four; provider ex-date is not independently verified by this announcement | [Issuer source](https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/) |
| MSFT_DIVIDEND_2025 | Pass | Cash dividend amount and ex-dividend date | [Issuer source](https://news.microsoft.com/source/2025/09/15/microsoft-announces-quarterly-dividend-increase-6/) |
| JNJ_DIVIDEND_2025 | Pass | Cash dividend amount and ex-dividend date | [Issuer source](https://www.investor.jnj.com/investor-news/news-details/2025/Johnson--Johnson-Announces-63rd-Consecutive-Year-of-Dividend-Increase-Raises-Quarterly-Dividend-by-4-8/default.aspx) |

Apple's dividend check addresses the split-adjusted amount basis; its provider ex-date is a lookup key and is not verified by that announcement. The Microsoft and Johnson & Johnson references explicitly state their selected ex-dividend dates and amounts.

## Benchmark evidence remains separate

FRED SP500 is compared only with Yahoo ^GSPC, not ETF dollar prices. Compared sessions: **1719**. Tolerance: 0.02 index points at two-decimal precision. FRED is context; Yahoo's comparator remains quarantined. Agreement of individual-instrument quotes does not resolve these index differences.

| Date | Absolute difference, index points | Disposition |
| --- | ---: | --- |
| 2020-05-11 | 0.13 | Unresolved; comparator quarantined |
| 2020-10-05 | 0.03 | Unresolved; comparator quarantined |
| 2021-08-11 | 5.29 | Unresolved; comparator quarantined |



The validator returns exit status 2 while benchmark discrepancies remain. Prototype acceptance may proceed only through a documented policy that excludes the discrepant comparator and retains its original observations and issue records. It must not convert the full cross-source comparison into a pass.

## Provenance and reproduction

HTTP status, retrieval time, URLs, downloaded response hashes, package versions, reference-registry hash, and base-manifest binding are preserved in the local capture. All source files are hash-checked before replay. Local HTML/CSV files remain outside Git; public results are aggregate checks and source links.

```bash
.venv/bin/python -m scripts.cross_validate_sources --snapshot data/audit/20261104T184106998030Z --external-snapshot data/validation/20261104T190642106948Z
```

See the [source policy](DATA_SOURCE_POLICY.md), [reference universe](REFERENCE_UNIVERSE.md), and [SQL milestone](SQL_LAYER.md) for acceptance and loading status. Prices are revised histories, not point-in-time archives; quote checks do not establish redistribution rights, production availability, or future model accuracy.
