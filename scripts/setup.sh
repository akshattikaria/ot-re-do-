#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r 'OT project/requirements.txt'
cd 'OT project/frontend'
npm ci --no-audit --no-fund
npm run build
