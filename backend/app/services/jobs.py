"""Background jobs for the admin page: clean and profile a dataset, import foods from a
cleaned dataset into MySQL, and rebuild the FAISS index. Jobs run in a small thread pool
inside the API process; their status and progress live in the jobs table."""

from __future__ import annotations

import logging
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from nutrimate_core.paths import PROCESSED

from .. import db
from ..metrics import JOBS, JOBS_RUNNING

log = logging.getLogger("nutrimate.jobs")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job")

FOOD_FIELDS = {  # target column -> patterns tried in order against cleaned column names
    "name": [r"^(food_)?name$", r"^description$", r"^food$", r"^item(_name)?$", r"^product(_name)?$", r"name"],
    "kcal_100g": [r"^(energy_)?kcal", r"kcal", r"^calories", r"calor", r"^energy$"],
    "protein_100g": [r"^protein", r"protein"],
    "carbs_100g": [r"^carb", r"carbohydrate", r"carb"],
    "fat_100g": [r"^(total_)?fat(_g|_100g)?$", r"^fat", r"(?<!sat)(?<!trans)fat"],
    "fiber_100g": [r"^fib(er|re)", r"fib(er|re)"],
    "sugar_100g": [r"^(total_|free)?sugars?", r"sugar"],
    "sodium_100g": [r"^sodium", r"sodium"],
    "food_group": [r"^(food_)?(group|category)$", r"category", r"group"],
}
LIMITS = {"kcal_100g": 902, "protein_100g": 100, "carbs_100g": 100, "fat_100g": 100, "fiber_100g": 100,
          "sugar_100g": 100}
MAX_IMPORT_ROWS = 500_000


def detect_mapping(columns: list[str]) -> dict:
    mapping, used = {}, set()
    for target, patterns in FOOD_FIELDS.items():
        for pat in patterns:
            hit = next((c for c in columns if c not in used and re.search(pat, c)), None)
            if hit:
                mapping[target] = hit
                used.add(hit)
                break
    return mapping


class Progress:
    def __init__(self, job_id: int):
        self.job_id, self.last = job_id, 0.0

    def __call__(self, frac: float, msg: str, force: bool = False):
        now = time.time()
        if force or now - self.last > 0.5:
            db.run("UPDATE jobs SET progress = %s, message = %s WHERE id = %s",
                   (round(min(max(frac, 0), 1), 3), msg[:250], self.job_id))
            self.last = now


def submit(job_type: str, user_id: int, dataset_id: int | None = None, **kwargs) -> int:
    job_id = db.run("INSERT INTO jobs (job_type, dataset_id, created_by, message) VALUES (%s, %s, %s, 'queued')",
                    (job_type, dataset_id, user_id))
    _pool.submit(_run, job_id, job_type, dataset_id, kwargs)
    return job_id


def _run(job_id: int, job_type: str, dataset_id: int | None, kwargs: dict):
    JOBS_RUNNING.inc()
    db.run("UPDATE jobs SET status = 'running', started_at = NOW() WHERE id = %s", (job_id,))
    progress = Progress(job_id)
    try:
        fn = {"profile_clean": profile_clean, "import_foods": import_foods, "rebuild_index": rebuild_index}[job_type]
        result = fn(dataset_id, progress, **kwargs)
        db.run("UPDATE jobs SET status = 'succeeded', progress = 1, message = 'done', result = %s, "
               "finished_at = NOW() WHERE id = %s", (db.dumps(result), job_id))
        JOBS.labels(job_type, "succeeded").inc()
    except Exception as exc:
        log.exception("job %s failed", job_id)
        db.run("UPDATE jobs SET status = 'failed', message = %s, error = %s, finished_at = NOW() WHERE id = %s",
               (f"{type(exc).__name__}: {exc}"[:250], traceback.format_exc()[-4000:], job_id))
        if dataset_id and job_type == "profile_clean":
            db.run("UPDATE datasets SET status = 'failed' WHERE id = %s", (dataset_id,))
        JOBS.labels(job_type, "failed").inc()
    finally:
        JOBS_RUNNING.dec()


def profile_clean(dataset_id: int, progress: Progress) -> dict:
    from ml.ingest import ingest_file

    ds = db.one("SELECT * FROM datasets WHERE id = %s", (dataset_id,))
    if ds is None:
        raise ValueError("dataset not found")
    db.run("UPDATE datasets SET status = 'processing' WHERE id = %s", (dataset_id,))
    out = PROCESSED.parent / "cleaned" / f"dataset_{dataset_id}.parquet"
    prof = ingest_file(Path(ds["stored_path"]), out, progress=progress)
    prof["suggested_food_mapping"] = detect_mapping([c["name"] for c in prof["columns"]])
    db.run("UPDATE datasets SET status = 'cleaned', row_count = %s, profile = %s, cleaned_path = %s WHERE id = %s",
           (prof["rows"], db.dumps(prof), str(out), dataset_id))
    return {"rows": prof["rows"], "columns": len(prof["columns"]), "seconds": prof["seconds"],
            "output_mb": round(prof["output_bytes"] / 1e6, 2)}


def import_foods(dataset_id: int, progress: Progress, mapping: dict | None = None) -> dict:
    ds = db.one("SELECT * FROM datasets WHERE id = %s", (dataset_id,))
    if ds is None or not ds["cleaned_path"]:
        raise ValueError("clean the dataset first")
    pf = pq.ParquetFile(ds["cleaned_path"])
    cols = pf.schema_arrow.names
    mapping = mapping or detect_mapping(cols)
    if "name" not in mapping or "kcal_100g" not in mapping:
        raise ValueError(f"need at least a name and a calorie column; found mapping {mapping}")
    missing = [c for c in mapping.values() if c not in cols]
    if missing:
        raise ValueError(f"columns not in dataset: {missing}")
    targets = ["name", "food_group", *[k for k in FOOD_FIELDS if k.endswith("_100g")]]
    total_rows = min(pf.metadata.num_rows, MAX_IMPORT_ROWS)
    sql = ("INSERT INTO foods (food_id, name, source, food_group, kcal_100g, protein_100g, carbs_100g, fat_100g, "
           "fiber_100g, sugar_100g, sodium_100g, dataset_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
           "ON DUPLICATE KEY UPDATE name = VALUES(name), kcal_100g = VALUES(kcal_100g), "
           "protein_100g = VALUES(protein_100g), carbs_100g = VALUES(carbs_100g), fat_100g = VALUES(fat_100g), "
           "fiber_100g = VALUES(fiber_100g), sugar_100g = VALUES(sugar_100g), sodium_100g = VALUES(sodium_100g)")
    done = skipped = 0
    source = f"Imported: {ds['name']}"[:120]
    for batch in pf.iter_batches(batch_size=5000, columns=list(dict.fromkeys(mapping.values()))):
        df = batch.to_pandas()
        out = pd.DataFrame({t: (df[mapping[t]] if t in mapping else None) for t in targets})
        for c in targets[2:]:
            out[c] = pd.to_numeric(out[c], errors="coerce")
            if c in LIMITS:
                out.loc[(out[c] < 0) | (out[c] > LIMITS[c]), c] = None
        out["name"] = out["name"].astype("string").str.strip().str.slice(0, 255)
        keep = out["name"].notna() & (out["name"] != "")
        skipped += int((~keep).sum())
        out = out[keep]
        rows = []
        for n, r in enumerate(out.itertuples(index=False), start=done):
            vals = [None if pd.isna(v) else (float(v) if isinstance(v, (int, float)) else str(v)) for v in r]
            rows.append((f"DS{dataset_id}:{n}", vals[0], source, vals[1], *vals[2:], dataset_id))
        rows = rows[: max(0, total_rows - done)]
        with db.tx() as t:
            t.many(sql, rows)
        done += len(rows)
        progress(done / max(total_rows, 1), f"imported {done:,} foods")
        if done >= total_rows:
            break
    return {"imported": done, "skipped_without_name": skipped, "mapping": mapping,
            "note": "values are read as per 100 g; run 'Rebuild search index' to make them searchable in chat"}


def rebuild_index(_dataset_id, progress: Progress) -> dict:
    from ml.build_index import build, food_docs, recipe_docs

    from ..rag.retriever import retriever

    progress(0.02, "reading recipes and foods from MySQL", force=True)
    recipes = pd.DataFrame(db.all_rows("SELECT recipe_id, name, ingredients, cuisine, meal_type, category FROM recipes"))
    foods = pd.DataFrame(db.all_rows("SELECT food_id, name, source, food_group FROM foods"))
    docs = pd.concat([recipe_docs(recipes), food_docs(foods)], ignore_index=True)
    info = build(docs, progress=lambda f, m: progress(0.05 + 0.9 * f, m))
    progress(0.97, "reloading index", force=True)
    retriever.load()
    return info


def mark_interrupted() -> None:
    """Jobs left running by a previous server process can not finish any more."""
    db.run("UPDATE jobs SET status = 'failed', message = 'interrupted by a server restart', finished_at = NOW() "
           "WHERE status IN ('queued', 'running')")
