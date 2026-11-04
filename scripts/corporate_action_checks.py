"""Replay manually reviewed issuer-event references against a saved price capture.

Literal checks locate reviewed evidence; they are not a general language-based
extractor or an independent reconstruction of every distribution.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import math
from pathlib import Path

import pandas as pd

from scripts.audit_market_data import ROOT, sha256

REFERENCE_PATH = ROOT / "config/corporate_action_references.json"


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def visible_text(html: str) -> str:
    parser = VisibleText()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split()).casefold()


def reference_configuration() -> dict:
    return json.loads(REFERENCE_PATH.read_text())


def check_action(frame: pd.DataFrame, html: str, reference: dict) -> dict:
    text = visible_text(html)
    missing_text = [phrase for phrase in reference["required_text"] if phrase.casefold() not in text]
    day = pd.Timestamp(reference["provider_date"])
    if frame.index.has_duplicates:
        raise ValueError("Duplicate provider dates in corporate-action check")
    observed = float(frame.loc[day, reference["field"]]) if day in frame.index else None
    matched = observed is not None and math.isfinite(observed) and abs(observed-reference["expected_provider_value"]) <= reference["tolerance"]
    return {"reference_id": reference["id"], "symbol": reference["symbol"], "provider_date": reference["provider_date"],
            "field": reference["field"], "expected_provider_value": reference["expected_provider_value"],
            "observed_provider_value": observed, "missing_evidence_text": missing_text,
            "source_url": reference["source_url"], "scope": reference["scope"],
            "passed": bool(matched and not missing_text)}


def validate_actions(run: Path, base: Path, manifest: dict, load_prices) -> list[dict]:
    if manifest.get("issuer_reference_sha256") != sha256(REFERENCE_PATH):
        raise ValueError("Issuer reference configuration differs from captured acceptance contract")
    results = []
    for reference in reference_configuration()["references"]:
        record = manifest["sources"].get(reference["id"], {})
        if record.get("status") != "downloaded":
            results.append({"reference_id": reference["id"], "symbol": reference["symbol"],
                            "source_url": reference["source_url"], "scope": reference["scope"],
                            "passed": False, "error": "Issuer source unavailable"})
            continue
        path = run / record["file"]
        if sha256(path) != record["sha256"]:
            raise ValueError("Issuer reference file hash mismatch")
        results.append(check_action(load_prices(base / f"{reference['symbol']}.csv"), path.read_text(), reference))
    return results
