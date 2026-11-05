#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    python3.13 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
exec .venv/bin/python -m scripts.serve_portfolio_app --synthetic-demo --port "${PORT:-8766}"
