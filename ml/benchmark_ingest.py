"""Benchmark the streaming ingester on a CSV larger than 1 GB built from real data.

The file is every Food.com review (about 1.4 million rows) joined to its recipe's name,
category, keywords, ingredients, description, instructions and nutrition
columns, exported to CSV with DuckDB. That
gives a real, denormalised file well over 1 GB. It is written once to
data/bench/ and reused. The ingest runs in a child process so its peak memory can be
measured on its own. Results go to reports/ingest_benchmark.json.

    python -m ml.benchmark_ingest
"""

from __future__ import annotations

import json
import multiprocessing as mp
import platform
import sys
import time
from pathlib import Path

import duckdb

from nutrimate_core.paths import DATA, INTERIM, REPORTS

BENCH = DATA / "bench"
CSV = BENCH / "foodcom_reviews_joined.csv"
OUT = BENCH / "foodcom_reviews_joined.parquet"


def build_csv() -> Path:
    if CSV.exists() and CSV.stat().st_size > 1e9:
        return CSV
    BENCH.mkdir(parents=True, exist_ok=True)
    rec = (INTERIM / "recipes_raw.parquet").as_posix()
    rev = (INTERIM / "reviews_raw.parquet").as_posix()
    tmp = BENCH / (CSV.name + ".part")
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    con.execute("COPY (SELECT v.ReviewId, v.RecipeId, v.AuthorId, v.Rating, v.Review, v.DateSubmitted, "
        "r.Name, r.RecipeCategory, array_to_string(r.Keywords, '|') AS Keywords, "
        "array_to_string(r.RecipeIngredientParts, '|') AS Ingredients, "
        "array_to_string(r.RecipeIngredientQuantities, '|') AS Quantities, "
        "r.Description, array_to_string(r.RecipeInstructions, ' ') AS Instructions, "
        "r.Calories, r.FatContent, r.SaturatedFatContent, r.CholesterolContent, r.SodiumContent, "
        "r.CarbohydrateContent, r.FiberContent, r.SugarContent, r.ProteinContent, r.RecipeServings "
        f"FROM read_parquet('{rev}') v LEFT JOIN read_parquet('{rec}') r ON v.RecipeId = CAST(r.RecipeId AS INTEGER)) "
        f"TO '{tmp.as_posix()}' (HEADER, DELIMITER ',')")
    con.close()
    tmp.replace(CSV)
    if CSV.stat().st_size < 1e9:
        raise SystemExit(f"benchmark CSV is only {CSV.stat().st_size / 1e6:.0f} MB, expected over 1 GB")
    return CSV


def _child(path: str, out: str, q):
    from ml.ingest import ingest_file

    t0 = time.time()
    prof = ingest_file(Path(path), Path(out))
    peak = None
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak = r / 1024 if sys.platform != "darwin" else r / 1024 / 1024  # KB on Linux, bytes on macOS
    except ImportError:  # Windows
        pass
    q.put({"seconds": round(time.time() - t0, 1), "rows": prof["rows"], "columns": len(prof["columns"]),
           "skipped_rows": prof["skipped_rows"], "output_bytes": prof["output_bytes"],
           "null_cells": sum(c["nulls"] for c in prof["columns"]), "peak_rss_mb": None if peak is None else round(peak)})


def main():
    t0 = time.time()
    path = build_csv()
    build_seconds = round(time.time() - t0, 1)
    q = mp.get_context("spawn").Queue()
    p = mp.get_context("spawn").Process(target=_child, args=(str(path), str(OUT), q))
    p.start()
    res = q.get()
    p.join()
    size = path.stat().st_size
    out = {
        "file": path.name,
        "source": "Food.com reviews joined to recipe name, ingredients, instructions and nutrition, exported to CSV",
        "source_mb": round(size / 1e6, 1), "rows": res["rows"], "columns": res["columns"],
        "skipped_rows": res["skipped_rows"], "null_cells": res["null_cells"],
        "seconds": res["seconds"], "rows_per_second": round(res["rows"] / max(res["seconds"], 1e-9)),
        "mb_per_second": round(size / 1e6 / max(res["seconds"], 1e-9), 1),
        "peak_rss_mb": res["peak_rss_mb"], "output_mb": round(res["output_bytes"] / 1e6, 1),
        "csv_build_seconds": build_seconds,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "ingest_benchmark.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
