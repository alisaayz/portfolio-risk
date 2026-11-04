# Data-source decision: initial prototype

**Decision:** DS-001 · **Date:** November 4, 2026
**Status:** Accepted for prototype planning; enforcement in SQL is a subsequent task.

## Decision and scope

Use the audited Yahoo Finance/yfinance snapshots for initial AAPL, SPY, and BND prototype work. Structural checks passed and 15 selected closes matched a separate website. This is a bounded acceptance of the observed sample, not certification of the full history or future downloads. New acquisitions must run the same quality checks.

Select **FRED SP500** as the preferred historical S&P 500 price-index source for local research context. Its series notes identify the index publisher and define its units. This decision selects a consistent source; it does not prove FRED is correct on every disputed date. The series excludes dividends and must not substitute for an ETF's adjusted prices. [FRED definition and source notes](https://fred.stlouisfed.org/series/SP500).

Keep **Yahoo ^GSPC comparison-only**. It is not accepted for benchmark calculations or model features while the three observed discrepancies remain unexplained. Do not patch its rows with FRED values or blend sources into an undocumented series.

| Data | Permitted initial use | Conditions |
| --- | --- | --- |
| Audited AAPL, SPY, BND history | Prototype ingestion and historical risk development | Retain snapshot versions; expose quality flags and the limits of spot checks |
| FRED SP500 | Preferred price-index context source | Preserve source/units and release metadata; keep downloaded observations local |
| Yahoo ^GSPC | Source comparison and investigation | Quarantine from benchmark calculations and model features |
| Any benchmark or economic series | Future predictive features | Require a separate historical-availability assessment before inclusion |

## Discrepancy disposition

| Issue | Observation date | Absolute difference, index points | Status |
| --- | --- | ---: | --- |
| DQ-SP500-001 | 2020-05-11 | 0.13 | Quarantined comparator; cause unresolved |
| DQ-SP500-002 | 2020-10-05 | 0.03 | Quarantined comparator; cause unresolved |
| DQ-SP500-003 | 2021-08-11 | 5.29 | Quarantined comparator; cause unresolved |

The separate Yahoo request around August 11 reproduced its original values. This rules out a one-off difference between the two captured request windows, but does not identify the underlying cause. The source observations, hashes, comparison results, and recheck remain preserved locally. [Comparison evidence and method](CROSS_SOURCE_VALIDATION.md).

The cross-source validator continues to return exit status 2 for these mismatches. This decision does not convert a failed comparison into a pass. Reopen a quarantined source only after documenting a supported explanation, a provider correction, or a revised acceptance rule justified independently of the desired result.

## Implementation requirements for the next milestone

The SQL layer must retain observations by source and ingestion run, select canonical data through an explicit versioned policy, and store quality issues separately from prices. Its issue ledger must include observation date, instrument/series, compared fields, tolerance, evidence references, status, and resolution notes. Quarantined observations must remain queryable for review while being excluded from accepted analytical inputs.

No canonical SQL views, benchmark calculations, or model features are implemented yet. The current enforcement is the validator's nonzero status and the explicit prohibition on using Yahoo ^GSPC for those future inputs.
