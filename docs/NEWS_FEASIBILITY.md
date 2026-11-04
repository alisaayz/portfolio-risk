# News-source feasibility audit

Updated November 4, 2026. **Finding: historical metadata access is demonstrated; a complete news forecasting dataset is not established.** No news model, sentiment inference, price reaction, forecast input, or model score is implemented by this audit.

## Executive summary

Three deliberately selected GDELT 15-minute archive files contain **5,944 records**, with **5,942 titles** and **2,778 valid precise-publication fields**. **90** publication timestamps are later than their record batch and require review. The sample supports further work on an after-close news-context layer, subject to company relevance, availability, missing-coverage, and deduplication checks. It does not establish continuous 2020–2026 coverage or predictive improvement.

## Observed evidence

| GDELT batch, UTC | Records | Titles present | Valid precise publication | Publication later than batch |
| --- | ---: | ---: | ---: | ---: |
| 20200316150000 | 2,527 | 2,525 | 977 | 40 |
| 20230313150000 | 1,725 | 1,725 | 826 | 22 |
| 20250127150000 | 1,692 | 1,692 | 975 | 28 |

All sampled records have 27 fields. Within-batch duplicate record IDs: **0**; duplicate document URLs: **0**. This does not establish uniqueness across batches, publishers, syndicated copies, or rewritten stories. These are selected stress-era dates, not random samples, complete days, or estimates of typical coverage. Archive endpoints: [gdelt_gkg_2020](https://data.gdeltproject.org/gdeltv2/20200316150000.gkg.csv.zip), [gdelt_gkg_2023](https://data.gdeltproject.org/gdeltv2/20230313150000.gkg.csv.zip), [gdelt_gkg_2025](https://data.gdeltproject.org/gdeltv2/20250127150000.gkg.csv.zip).

| Other probe | HTTP result | Disposition |
| --- | ---: | --- |
| gdelt_doc_historical | 429 | Not accepted as usable API evidence |
| sec_msft | 403 | Not accepted as usable API evidence |

The DOC API returned HTTP 429 and the SEC submissions request returned HTTP 403. Responses are retained; no access restriction or rate limit was bypassed. The bulk archives are separate public metadata resources, not successful DOC API full-text queries. SEC API access is unverified from this environment, although its [official documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) describes public filing metadata.

## Timestamp interpretation

The [GKG codebook](https://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf) defines record IDs using their update batch; its date field is redundant within a file. The separate [precise-publication field](https://blog.gdeltproject.org/new-gkg-2-0-article-metadata-fields/) is extracted from publishers and may be missing. In these samples, the ordinary metadata date equals the record batch. It must not be presented as an independently verified, exact article-publication time.

Preserve separately: archive batch time, extracted publisher time, local retrieval time, and any future collector's first-observed time. Late, missing, invalid, and midnight publication values need explicit rules; do not silently replace them with a convenient timestamp. An archive label is not proof that a future user could have obtained that record at that instant. Conservative lags and a forward-recorded collection can test availability assumptions; current retrieval times must not be backdated.

The 90 later-than-batch values are review flags, not proof of a particular extraction or clock error. This audit neither repairs them nor treats them as eligible historical features.

## Company matching is candidate generation

Exact, case-insensitive organization aliases produce the following candidate mention counts. One record can mention multiple companies, and an incidental mention need not be relevant financial news. No precision/recall claim is made.

| Stock | Candidate organization matches |
| --- | ---: |
| AAPL | 6 |
| MSFT | 49 |
| JPM | 11 |
| JNJ | 4 |
| XOM | 2 |

Entity relevance requires a manually labeled sample and handling of ambiguous names. ETF ticker exposure cannot be inferred directly from company mentions; underlying holdings need separately dated data, and broad macro news needs a separate relevance rule. No underlying-ETF exposure model is implemented.

## Source and model comparison

| Candidate | Evidence and practical fit | Outstanding limitation |
| --- | --- | --- |
| GDELT bulk GKG | Three archive samples downloaded and replayed; titles, organization tags, and existing tone fields are available | Continuous coverage, relevance, historical availability, deduplication, and processing scale unverified; tone is not FinBERT output |
| GDELT DOC API | Official documentation describes a recent search window | Probe rate-limited; not a demonstrated full-history solution |
| SEC submissions/filings | Official API documentation supplies company identifiers and filing metadata | Probe forbidden; filings are a narrower source than all breaking news, and acceptance time is not guaranteed first public availability |
| FNSPID | [Authors' dataset paper](https://arxiv.org/abs/2402.06698) describes coverage through 2023 | Potential development resource; that published version does not supply our reserved 2026 test |
| FinMultiTime | [Authors' paper](https://arxiv.org/abs/2506.05019) describes coverage through 2025 | Potential development resource; no demonstrated 2026 coverage, and large downloads were not performed |
| FinBERT | [Model card](https://huggingface.co/ProsusAI/finbert) describes financial sentiment classification | No weights installed or inference run; current weights have CC BY-NC-SA 4.0 terms, distinct from training-code terms |

Public metadata access does not itself transfer publisher article-body rights. This audit does not retrieve article bodies or redistribute titles; public outputs contain aggregate counts and source links only. Candidate model versions, training-data cutoffs, and suitability for a later public/commercial deployment require review before selection.

## Recommended project sequence

1. Complete the price-only feature/target pipeline under EV-001, creating a verifiable comparison baseline.
2. Build a small, forward-recorded after-close news-context prototype for direct company matches. Record availability, source, duplicates, and coverage explicitly; zero stories and an unobserved feed are different states.
3. Label company relevance and event categories on a development sample, then evaluate a selected sentiment/event classifier. Keep text quality and risk-forecast quality as separate tests.
4. Audit continuous, compatible historical coverage before comparing prices-only and prices-plus-news forecasts. Use identical origins and targets, and freeze choices before opening 2026 model scores. Do not substitute an older news dataset for missing 2026 observations or fill missing feeds with zero sentiment.
5. Treat market reactions as outcomes when evaluating an event. Later returns, volume, or volatility cannot enter an earlier prediction. Association around an event does not establish causation.

This sequence retains news as a meaningful planned extension without claiming live response, comprehensive coverage, or predictive performance. The current SQL dataset, source policy, and EV-001 dates remain unchanged.

## Reproduction and provenance

- Probe snapshot: `20261104T192619021235Z`.
- Audit identity: `e3c51cf3699bf5aec737a3318a90e4407b0676dbdaeae3c022efc8f9708628cd`.
- Response bytes, HTTP status, request parameters, retrieval times, and SHA-256 hashes remain local under `data/news_audit/`.
- The offline auditor verifies every saved response hash, parses archives without extracting files, rejects unexpected schemas/oversized samples, and records timestamp/relevance diagnostics. It makes no requests or model calls.

```bash
.venv/bin/python -m scripts.audit_news_metadata --snapshot data/news_audit/20261104T192619021235Z
.venv/bin/python -m unittest discover -s tests -v
```

General source references: [GDELT data](https://gdeltproject.org/data.html), [DOC API documentation](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/), [SEC timestamp/access guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions). The SEC guidance distinguishes acceptance from public availability; no exact public-availability timestamp is guaranteed by that field.
