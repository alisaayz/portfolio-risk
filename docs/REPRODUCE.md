# Reproduce riskitnot locally

Verified November 5, 2026, on macOS with Python 3.13.7. A fresh checkout and fresh virtual environment passed 159 tests. Using the saved source evidence, the checkout rebuilt the accepted DS-002 dataset, verified the SQL outputs, rebuilt the symbol directory, and served the assessment, reweighting, candidate screen, and practice study locally.

## Install and test

From a checkout of the repository, run:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
```

The tests use local fixtures. The exact dashboard demo and research results depend on archived source inputs. The public repository includes code, figures, and aggregate reports. Provider captures and private artifacts are kept separately.

## Rebuild from saved evidence

In the original project folder, the accepted warehouse and symbol directory are already available. For an isolated rebuild, copy the saved input folders named below from the original project into the same relative locations in a separate checkout. Rebuild the warehouse and verify the resulting SQL data.

```bash
.venv/bin/python -m scripts.build_warehouse \
  --snapshot data/audit/20261104T184106998030Z \
  --external-snapshot data/validation/20261104T190642106948Z \
  --historical-snapshot data/audit/20261104T170702705356Z \
  --historical-snapshot data/audit/20261104T170309697872Z \
  --policy config/expanded_source_policy.json
.venv/bin/python -m scripts.verify_warehouse
```

The saved build selects dataset `80b5d80b266b0255f7c8de0310569de02f63a5ee0ff2a54e707ddfa2cd114166`. A new acquisition produces a separate capture and may differ when vendors revise their histories. To build new evidence, use the explicit RU-001 registry and exclusive end date with the audit command, then apply the cross-source checks and acceptance policy. [Acquisition and source verification](UNIVERSE_VALIDATION.md) · [Warehouse build](SQL_LAYER.md)

The symbol directory is optional for the 16-instrument demo. For offline directory replay, pass an existing Nasdaq Trader text snapshot to the catalog command.

```bash
.venv/bin/python -m scripts.market_catalog \
  --source data/symbol_directory/20261105T030920170383Z/nasdaqtraded.txt
```

## Launch and check the demo

```bash
.venv/bin/python -m scripts.serve_portfolio_app
```

Open [the local dashboard](http://127.0.0.1:8765/). The demo shows 11.29% historical volatility at the 252-session setting. For reweighting, the default 10% move limit gives 9.58% on the same dates. With a 10% manual target and a 10% replacement out of AAPL, the screen shows six qualifying scenarios. The practice study opens at [the local study page](http://127.0.0.1:8765/study).

The 2026 model scores were computed from the published freeze commit, the pinned environment, and the preserved warehouse and development artifacts. See the holdout report for the exact replay command and inputs. [2026 holdout reproduction](FINAL_EVALUATION_REPORT.md)
