#!/usr/bin/env bash
# Rebuild data and models from the public sources, then load MySQL.
# Run from the project root with the virtual environment active:
#   bash scripts/rebuild.sh            full rebuild (download, process, tune, train, index)
#   bash scripts/rebuild.sh --no-tune  reuse reports/best_params.json instead of running Optuna
set -euo pipefail
cd "$(dirname "$0")/.."

python scripts/download_data.py
python -m ml.ingest
python -m ml.preprocess
python -m ml.split
if [[ "${1:-}" != "--no-tune" ]]; then
  python -m ml.tune
fi
python -m ml.evaluate
python -m ml.train
python -m ml.build_index
python -m backend.scripts.load_catalogue
python -m backend.scripts.seed_demo
echo "Rebuild finished. Start the API with: uvicorn backend.app.main:app --port 8000"
