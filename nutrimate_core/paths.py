"""Project paths and pipeline parameters, shared by the ML pipeline and the API."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
UPLOADS = DATA / "uploads"
MODELS = ROOT / "models"
REPORTS = ROOT / "reports"


@lru_cache(maxsize=1)
def params() -> dict:
    with open(ROOT / "params.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
