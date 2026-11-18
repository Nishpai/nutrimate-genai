"""Download the raw source files into data/raw/. All three are public and need no account.

  1. Food.com Recipes and Reviews (CC0). The untouched recipes and reviews tables, as a
     DuckDB file (about 750 MB) from the jiava/foodrs-data dataset on Hugging Face.
  2. Indian Nutrient Databank (INDB), Anuvaad, release 2024.11 (xlsx).
  3. USDA FoodData Central, SR Legacy (April 2018), CSV zip. Public domain.

    python scripts/download_data.py
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
FILES = {
    "foodrs.duckdb": "https://huggingface.co/datasets/jiava/foodrs-data/resolve/main/data/foodrs.duckdb",
    "Anuvaad_INDB_2024.11.xlsx": "https://www.anuvaad.org.in/wp-content/uploads/2020/07/Anuvaad_INDB_2024.11.xlsx",
    "FoodData_Central_sr_legacy_food_csv_2018-04.zip":
        "https://fdc.nal.usda.gov/fdc-datasets/FoodData_Central_sr_legacy_food_csv_2018-04.zip",
}


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"already have {dest.name}, skipping")
        return
    print(f"downloading {dest.name} ...", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    print(f"  saved {dest.stat().st_size / 1e6:.1f} MB")


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        download(url, RAW / name)
    z = RAW / "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
    target = RAW / "usda_sr_legacy"
    if not any(target.glob("**/food.csv")):
        with zipfile.ZipFile(z) as zf:
            zf.extractall(target)
    print("done. Next: dvc repro (or scripts/rebuild.ps1 / scripts/rebuild.sh)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
