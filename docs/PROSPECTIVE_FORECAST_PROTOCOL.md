# PF-002 prospective portfolio forecast protocol

Frozen for the Version 2 technical preview on November 5, 2026. The earlier EV-002 results remain retrospective evidence. The dashboard uses historical estimates while forward evidence is pending. [Retrospective report](FINAL_EVALUATION_REPORT.md)

## Predictions and enrollment

Use the four demonstration portfolios in the PF-002 configuration. Fit the previously selected gradient boosting recipe on the same 19,776 examples with target dates before 2026. Keep the sample, feature SQL, model settings, 60-session co-movement estimate, and portfolio weights fixed. The comparators are the direct trailing 20-session portfolio variance and the frozen 0.90 EWMA holding variance combined using the same co-movement estimate as the model. All methods predict next-20-session annualized variance for the same date and portfolio. [Machine-readable configuration](../config/prospective_forecast.json) · [Model recipe](../config/final_evaluation.json)

Anchor the schedule on the November 6, 2026 NYSE session and step forward 20 exchange sessions for 72 scheduled origins. Enroll only after the designated close and before the next exchange open. Require an audited snapshot ending exactly at the designated close for all reference instruments. Preserve the captured vintage and check all exchange dates. The recorder requires the capture to start after the designated close and to finish before the forecast is written. Skip and report any origin with missing data, failed checks, or a late recording. Each record includes the data, code and configuration hashes, forecast and target dates, software versions, and a UTC clock reading. The recorder refuses to replace an existing origin.

For confirmatory evidence, independently timestamp each record digest before the next open and preserve the receipt with the local record. The recorder prints the digest for this purpose. A local clock is sufficient for a rehearsal. The study requires the separate timestamp evidence to admit an origin. Retain a fixed approved capture of each complete outcome window and report revisions separately. The receipt workflow below has been rehearsed. Live enrollment requires a current capture with documented provider access.

## Evaluation and decision

Evaluate once after all 72 scheduled opportunities and their outcome windows have closed. Require at least 60 independently timestamped, matched and scored market origins. Record the count and reason at every skipped slot. This schedule represents several years of new market dates. Forecast performance remains pending at the technical preview.

The primary outcome is annualized RMS volatility over the next 20 sessions using the same fixed weights and matched dates. Compute absolute volatility error in percentage points. Average equally over the four portfolios at each origin before comparing methods. Report mean error by portfolio and the pooled estimate. Secondary measures are variance QLIKE using the existing prediction floor, signed forecast error, and understatement of realized volatility by at least five percentage points. Also report error on the highest quintile of realized downside deviation for each portfolio, with the sample counts.

Pair all methods on the same dates. Use 20,000 circular block resamples of three adjacent scheduled origins, with two- and six-origin sensitivity checks, preserving the four portfolios and missing slots together. Use one-sided 97.5% upper bounds on the two model-minus-baseline MAE differences to control the two planned comparisons. Require a point improvement of at least 0.50 percentage points and a bound below zero against both baselines, with no worse mean MAE on any of the four portfolios. The confidence bounds depend on the block dependence assumption. Report missing-origin patterns and sensitivity before considering a separate dashboard experiment.

## Check readiness and record

Run the preflight with the intended warehouse and frozen training input. It reports the next recording window, whether the training digest matches, and whether the snapshot and capture times meet that window. The check reads local inputs.

```bash
.venv/bin/python -m scripts.record_prospective_forecast --preflight \
  --database /path/to/accepted/warehouse.duckdb \
  --training /path/to/frozen/development_examples.parquet
```

During an open window, run the same command without `--preflight`. Use an authorized, audited snapshot through that origin. Keep the forecast file created under `private/prospective/` and preserve the warehouse vintage it references.

## Verify the timestamp receipt

FreeTSA issues an RFC 3161 response to a request containing the SHA-256 digest and a random nonce. The workflow sends the request file. The forecast JSON and data archive stay local. The verifier checks the authority certificate fingerprints, signature, exact forecast bytes, and original query before checking whether the signed time falls in the scheduled window. A response issued at or after the next open fails that check. [FreeTSA instructions](https://www.freetsa.org/index_en.php) · [FreeTSA usage policy](https://www.freetsa.org/freetsa.html) · [RFC 3161](https://datatracker.ietf.org/doc/html/rfc3161)

Obtain `cacert.pem` and `tsa.crt` from the authority's instructions and keep both with the private evidence. The verifier pins the November 2026 files. Verify any certificate rotation from the authority before updating those pins. Use a fresh receipt directory for each attempt and retain the original request with the response.

```bash
openssl ts -query -sha256 -cert -data "$forecast_file" -out "$receipt_dir/request.tsq"
curl --fail --silent --show-error --max-time 15 \
  -H 'Content-Type: application/timestamp-query' \
  --data-binary "@$receipt_dir/request.tsq" \
  https://freetsa.org/tsr -o "$receipt_dir/response.tsr"
.venv/bin/python -m scripts.verify_forecast_receipt \
  --record "$forecast_file" --query "$receipt_dir/request.tsq" \
  --receipt "$receipt_dir/response.tsr" --trust-dir "$trust_dir"
```

Here, `forecast_file` is the path printed by the recorder, `receipt_dir` is the new local directory for this attempt, and `trust_dir` contains the two downloaded certificate files. Preserve the verifier output with the forecast, request, receipt, and certificates. The signed time verifies that these forecast bytes existed by that time. The warehouse audit and capture records provide separate evidence about the source vintage.

On November 5, 2026, preflight verified the locked training digest and all 16 instrument histories. The available data ended November 3. The first scheduled forecast requires data through November 6, with a recording window from **Friday at 1:00 p.m. Pacific to Monday at 6:30 a.m. Pacific**. The independent service signed a generated test digest, and verification rejected a changed file. The forecast ledger awaits an eligible vintage. Outcome scoring remains a separate step after the evidence window closes.
