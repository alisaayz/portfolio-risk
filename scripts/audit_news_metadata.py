"""Offline feasibility audit of bounded GDELT archive samples; no forecast inputs.

This module makes no network requests, retrieves no article bodies, and computes
no sentiment, market reactions, training targets, forecasts, or model scores.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

from scripts.audit_market_data import ROOT, sha256

ALIASES = {
    "AAPL": {"apple", "apple inc", "apple inc."},
    "MSFT": {"microsoft", "microsoft corp", "microsoft corporation"},
    "JPM": {"jpmorgan", "jpmorgan chase", "jp morgan", "jpmorgan chase co"},
    "JNJ": {"johnson johnson", "johnson & johnson"},
    "XOM": {"exxon", "exxonmobil", "exxon mobil"},
}


def timestamp(value: str) -> datetime:
    if not re.fullmatch(r"\d{14}", value):
        raise ValueError("Require a complete 14-digit GDELT timestamp")
    return datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def tag_value(extras: str, tag: str) -> str | None:
    match = re.search(r"<" + tag + r">(.*?)</" + tag + r">", extras, flags=re.DOTALL)
    return match.group(1).strip() if match and match.group(1).strip() else None


def inspect_archive(path: Path) -> dict:
    counts, widths, candidates = Counter(), Counter(), Counter()
    identifiers, urls, batch_dates = set(), set(), set()
    with zipfile.ZipFile(path) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if not members or sum(info.file_size for info in members) > 512 * 1024**2:
            raise ValueError("Missing archive members or sample exceeds bounded inspection size")
        for member in members:
            with archive.open(member) as raw:
                reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
                for row in reader:
                    counts["rows"] += 1
                    widths[len(row)] += 1
                    if len(row) != 27:
                        raise ValueError("Unexpected GKG schema: require exactly 27 fields")
                    record_batch = row[0].split("-", 1)[0]
                    batch = timestamp(record_batch)
                    timestamp(row[1])
                    identifiers.add(row[0]); urls.add(row[4]); batch_dates.add(record_batch)
                    counts["metadata_date_matches_record_batch"] += row[1] == record_batch
                    counts["web_collection_records"] += row[2] == "1"
                    counts["translated_record_ids"] += "-T" in row[0]
                    counts["has_title"] += tag_value(row[26], "PAGE_TITLE") is not None
                    counts["has_organization_field"] += bool(row[13])
                    counts["seven_tone_fields"] += len(row[15].split(",")) == 7
                    publication = tag_value(row[26], "PAGE_PRECISEPUBTIMESTAMP")
                    counts["has_precise_publication_field"] += publication is not None
                    if publication is not None:
                        try:
                            published = timestamp(publication)
                        except ValueError:
                            counts["invalid_precise_publication"] += 1
                        else:
                            counts["valid_precise_publication"] += 1
                            counts["precise_after_batch"] += published > batch
                            counts["precise_midnight"] += publication.endswith("000000")
                    organizations = {name.strip().casefold() for name in row[13].split(";") if name.strip()}
                    matched = [symbol for symbol, aliases in ALIASES.items() if organizations & aliases]
                    candidates.update(matched)
                    counts["candidate_company_rows"] += bool(matched)
    if not counts["rows"]:
        raise ValueError("Empty archive is not evidence of coverage")
    return {"counts": dict(counts), "column_widths": {str(k): v for k, v in widths.items()},
            "unique_record_ids": len(identifiers), "duplicate_record_ids": counts["rows"]-len(identifiers),
            "unique_document_urls": len(urls), "duplicate_document_urls": counts["rows"]-len(urls),
            "batch_timestamps": sorted(batch_dates), "alias_candidate_counts": dict(candidates)}


def inspect_snapshot(folder: Path) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text())
    archives, endpoints = [], []
    for name, record in manifest["sources"].items():
        if "file" not in record:
            endpoints.append({"source": name, "http_status": record.get("http_status"), "error": record.get("error")})
            continue
        filename = record["file"]
        if Path(filename).name != filename:
            raise ValueError("Evidence files must be immediate snapshot members")
        path = folder / filename
        if sha256(path) != record["sha256"]:
            raise ValueError("Saved news-probe response hash mismatch")
        if name.startswith("gdelt_gkg_") and record["http_status"] == 200:
            archives.append({"source": name, "source_url": record["url"], **inspect_archive(path)})
        else:
            endpoints.append({"source": name, "http_status": record["http_status"],
                              "bytes": record["bytes"], "content_type": record.get("content_type")})
    if not archives:
        raise ValueError("No successful bulk-archive samples; no coverage conclusion")
    recipe = {"snapshot_manifest_sha256": sha256(folder / "manifest.json"),
              "audit_script_sha256": sha256(Path(__file__))}
    identity = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
    return {"audit_id": identity, "snapshot_run": manifest["run_id"], "recipe": recipe,
            "archive_samples": archives, "other_endpoint_results": endpoints,
            "scope": "Purposeful 15-minute metadata samples; not complete historical coverage or verified entity labels",
            "news_pipeline_implemented": False, "market_effects_or_model_scores_computed": False}


def write_report(result: dict, destination: Path) -> None:
    samples = result["archive_samples"]
    total = sum(s["counts"]["rows"] for s in samples)
    titles = sum(s["counts"].get("has_title", 0) for s in samples)
    precise = sum(s["counts"].get("valid_precise_publication", 0) for s in samples)
    future = sum(s["counts"].get("precise_after_batch", 0) for s in samples)
    duplicate_ids = sum(s["duplicate_record_ids"] for s in samples)
    duplicate_urls = sum(s["duplicate_document_urls"] for s in samples)
    rows = "\n".join(f"| {', '.join(s['batch_timestamps'])} | {s['counts']['rows']:,} | {s['counts'].get('has_title',0):,} | {s['counts'].get('valid_precise_publication',0):,} | {s['counts'].get('precise_after_batch',0)} |" for s in samples)
    aliases = "\n".join(f"| {symbol} | {sum(s['alias_candidate_counts'].get(symbol,0) for s in samples)} |" for symbol in ALIASES)
    endpoints = "\n".join(f"| {s['source']} | {s.get('http_status','unavailable')} | Not accepted as usable API evidence |" for s in result["other_endpoint_results"])
    links = ", ".join(f"[{s['source']}]({s['source_url']})" for s in samples)
    destination.write_text(f"""# News-source feasibility audit

Updated November 4, 2026. **Finding: historical metadata access is demonstrated; a complete news forecasting dataset is not established.** No news model, sentiment inference, price reaction, forecast input, or model score is implemented by this audit.

## Executive summary

Three deliberately selected GDELT 15-minute archive files contain **{total:,} records**, with **{titles:,} titles** and **{precise:,} valid precise-publication fields**. **{future}** publication timestamps are later than their record batch and require review. The sample supports further work on an after-close news-context layer, subject to company relevance, availability, missing-coverage, and deduplication checks. It does not establish continuous 2020–2026 coverage or predictive improvement.

## Observed evidence

| GDELT batch, UTC | Records | Titles present | Valid precise publication | Publication later than batch |
| --- | ---: | ---: | ---: | ---: |
{rows}

All sampled records have 27 fields. Within-batch duplicate record IDs: **{duplicate_ids}**; duplicate document URLs: **{duplicate_urls}**. This does not establish uniqueness across batches, publishers, syndicated copies, or rewritten stories. These are selected stress-era dates, not random samples, complete days, or estimates of typical coverage. Archive endpoints: {links}.

| Other probe | HTTP result | Disposition |
| --- | ---: | --- |
{endpoints}

The DOC API returned HTTP 429 and the SEC submissions request returned HTTP 403. Responses are retained; no access restriction or rate limit was bypassed. The bulk archives are separate public metadata resources, not successful DOC API full-text queries. SEC API access is unverified from this environment, although its [official documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) describes public filing metadata.

## Timestamp interpretation

The [GKG codebook](https://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf) defines record IDs using their update batch; its date field is redundant within a file. The separate [precise-publication field](https://blog.gdeltproject.org/new-gkg-2-0-article-metadata-fields/) is extracted from publishers and may be missing. In these samples, the ordinary metadata date equals the record batch. It must not be presented as an independently verified, exact article-publication time.

Preserve separately: archive batch time, extracted publisher time, local retrieval time, and any future collector's first-observed time. Late, missing, invalid, and midnight publication values need explicit rules; do not silently replace them with a convenient timestamp. An archive label is not proof that a future user could have obtained that record at that instant. Conservative lags and a forward-recorded collection can test availability assumptions; current retrieval times must not be backdated.

The {future} later-than-batch values are review flags, not proof of a particular extraction or clock error. This audit neither repairs them nor treats them as eligible historical features.

## Company matching is candidate generation

Exact, case-insensitive organization aliases produce the following candidate mention counts. One record can mention multiple companies, and an incidental mention need not be relevant financial news. No precision/recall claim is made.

| Stock | Candidate organization matches |
| --- | ---: |
{aliases}

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

- Probe snapshot: `{result['snapshot_run']}`.
- Audit identity: `{result['audit_id']}`.
- Response bytes, HTTP status, request parameters, retrieval times, and SHA-256 hashes remain local under `data/news_audit/`.
- The offline auditor verifies every saved response hash, parses archives without extracting files, rejects unexpected schemas/oversized samples, and records timestamp/relevance diagnostics. It makes no requests or model calls.

```bash
.venv/bin/python -m scripts.audit_news_metadata --snapshot data/news_audit/{result['snapshot_run']}
.venv/bin/python -m unittest discover -s tests -v
```

General source references: [GDELT data](https://gdeltproject.org/data.html), [DOC API documentation](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/), [SEC timestamp/access guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions). The SEC guidance distinguishes acceptance from public availability; no exact public-availability timestamp is guaranteed by that field.
""")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    result = inspect_snapshot(args.snapshot)
    (args.snapshot / "metadata-audit.json").write_text(json.dumps(result, indent=2)+"\n")
    write_report(result, ROOT / "docs/NEWS_FEASIBILITY.md")
    print(json.dumps({"audit_id": result["audit_id"], "samples": len(result["archive_samples"]),
                      "records": sum(s["counts"]["rows"] for s in result["archive_samples"]),
                      "market_effects_or_model_scores_computed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
