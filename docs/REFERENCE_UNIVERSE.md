# Reference universe selection

Universe **RU-001**, selected November 4, 2026. [Configuration](../config/reference_universe.json), [structural audit](UNIVERSE_AUDIT.md).

## Purpose and selection rule

Expand the initial AAPL/SPY/BND sample to 16 USD-quoted instruments with varied exposures and histories preceding 2020. Selection is based on exposure coverage and usable history, not model performance in the reserved 2026 test. This is a purposeful research sample, not a recommended portfolio or a statistically representative market sample. The instruments are selected now; historical existence does not make the selection point-in-time.

| Group | Instruments | Research purpose |
| --- | --- | --- |
| Individual stocks | AAPL, MSFT, JPM, JNJ, XOM | Technology, banking, healthcare, and energy; single-company versus ETF risk |
| U.S. equity ETFs | SPY, QQQ, IWM | Broad large-cap, Nasdaq-100, and small-cap exposures |
| International equity ETFs | EFA, EEM | Developed ex-U.S./Canada and emerging-market equities, through USD-listed funds |
| Bond ETFs | BND, IEF, TLT, LQD, HYG | Broad bonds, Treasury duration, investment-grade credit, and high-yield credit |
| Gold trust | GLD | Gold exposure distinct from equities and bonds |

ETF/trust roles follow issuer descriptions: [iShares product directory](https://www.ishares.com/us/products/etf-investments), [Invesco QQQ](https://www.invesco.com/us/en/financial-products/etfs/invesco-qqq-trust-series-1.html), [Vanguard BND](https://investor.vanguard.com/investment-products/etfs/bond-etf), [SPDR Gold Shares](https://www.spdrgoldshares.com/usa/gld/). These sources describe exposures; they do not independently verify downloaded price histories. A U.S.-listed international ETF is USD-quoted but retains economic exposure to foreign assets and currencies.

## Observed acquisition and audit

The expanded capture contains **27,504 rows**, with **1,719 expected sessions per instrument** from January 2, 2020 through November 3, 2026. All 16 pass implemented structural checks, with no adjustment-threshold review flags. Returned actions comprise **645 dividend events and one split**. Counts describe provider data, not independent certification of every event.

The manifest preserves the complete universe configuration, its hash, per-instrument calendars, retrieval settings, metadata, versions, and source-file hashes. Offline replay verifies that the manifest includes exactly the declared instruments/calendars and that saved files remain intact. XNAS and XNYS are daily-session references; XNYS is used as a U.S. session proxy for NYSE Arca instruments.

The [date eligibility report](EVALUATION_SPLITS.md) records training, validation, and reserved-test membership without calculating model scores. A 252-return warmup and 20-session outcomes reduce the usable rows; raw observation counts must not be presented as independent labeled examples.

## Acceptance and limitations

The expanded capture is now **accepted for prototype SQL use under DS-002**. Eighty selected closes and four issuer references pass; the loader enforces exact universe/reference bindings and retains the three index discrepancies in quarantine. This is limited evidence, not certification of full histories or every ETF distribution. DS-001 and the original dataset remain retained. See [source validation](UNIVERSE_VALIDATION.md) and the [promotion walkthrough](05_EXPANDED_SQL_WALKTHROUGH.md).

Current-survivor selection omits delisted, merged, and failed instruments and closed funds. Broad ETFs, stocks, and bond funds have overlapping exposures; ticker count is not a count of independent observations. There is no claim to predict unseen securities or the entire investable market. USD quotation does not remove underlying currency risk. Current adjusted histories are revised proxies rather than point-in-time archives, and the first year supplies much of the feature warmup.

Freeze this selection before inspecting model scores. Record exclusions and source problems, including unsuccessful candidates, rather than removing instruments because forecasts are poor. Any later change to universe, dates, or acceptance semantics must create a distinct configuration and evidence version.

## Reproduce this stage

```bash
.venv/bin/python -m scripts.audit_market_data --universe config/reference_universe.json --start 2020-01-01 --end 2026-11-04
.venv/bin/python -m scripts.audit_market_data --snapshot data/audit/<expanded-run-id>
.venv/bin/python -m scripts.evaluation_splits --snapshot data/audit/<expanded-run-id>
```

New acquisitions receive distinct run identities. Offline replay uses the universe saved in that manifest and does not accept a replacement `--universe`. Expanded audit/validation reports are separate from the original audit. The portfolio baseline is refreshed with a distinct report identity; earlier local artifacts remain retained. Downloaded histories remain outside Git.
