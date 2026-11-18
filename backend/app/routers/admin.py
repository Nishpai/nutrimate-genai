from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ml.ingest import detect_format
from nutrimate_core.paths import MODELS, REPORTS, UPLOADS

from .. import db
from ..config import get_settings
from ..deps import admin_user
from ..rag.retriever import retriever
from ..services import jobs
from ..services.engine import engine

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _read_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


@router.get("/overview")
def overview(admin: dict = Depends(admin_user), t: db.Tx = Depends(db.get_tx)):
    counts = t.one("""SELECT (SELECT COUNT(*) FROM users) AS users, (SELECT COUNT(*) FROM recipes) AS recipes,
                             (SELECT COUNT(*) FROM foods) AS foods, (SELECT COUNT(*) FROM meal_logs) AS meal_logs,
                             (SELECT COUNT(*) FROM meal_plans) AS meal_plans,
                             (SELECT COUNT(*) FROM interactions) AS interactions,
                             (SELECT COUNT(*) FROM chat_messages) AS chat_messages,
                             (SELECT COUNT(*) FROM datasets) AS datasets,
                             (SELECT COUNT(*) FROM jobs WHERE status = 'running') AS running_jobs""")
    artifacts = []
    for f in sorted(MODELS.glob("*")):
        if f.is_file():
            artifacts.append({"name": f.name, "mb": round(f.stat().st_size / 1e6, 2)})
    return {"counts": counts, "engine": engine.info(), "retriever": {"ready": retriever.ready,
            "info": getattr(retriever, "info", None)}, "artifacts": artifacts,
            "processed_summary": _read_json(REPORTS.parent / "data" / "processed" / "summary.json")}


@router.get("/datasets")
def datasets(admin: dict = Depends(admin_user), t: db.Tx = Depends(db.get_tx)):
    rows = t.all("SELECT * FROM datasets ORDER BY id DESC")
    for r in rows:
        r["profile"] = db.loads(r["profile"])
    return rows


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)[:120] or "upload"


@router.post("/datasets/upload", status_code=201)
async def upload(file: UploadFile = File(...), name: str = Form(""), admin: dict = Depends(admin_user)):
    original = file.filename or "upload"
    try:
        fmt = detect_format(Path(original)) if not original.lower().endswith(".json") else "json"
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = UPLOADS / f"{uuid.uuid4().hex[:10]}_{_safe_name(original)}"
    limit = get_settings().max_upload_mb * 1024 * 1024
    size = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File is larger than {get_settings().max_upload_mb} MB")
            f.write(chunk)
    if fmt == "json":
        fmt = detect_format(dest)
    did = db.run("""INSERT INTO datasets (name, original_filename, stored_path, file_format, size_bytes, uploaded_by)
                    VALUES (%s,%s,%s,%s,%s,%s)""", ((name or original)[:120], original, str(dest), fmt, size, admin["id"]))
    return db.one("SELECT * FROM datasets WHERE id = %s", (did,))


class RegisterIn(BaseModel):
    path: str = Field(min_length=3, max_length=500)
    name: str = Field("", max_length=120)


@router.post("/datasets/register", status_code=201)
def register(body: RegisterIn, admin: dict = Depends(admin_user)):
    """Register a large file that is already on this computer, without copying it."""
    p = Path(body.path).expanduser()
    if not p.is_file():
        raise HTTPException(404, "File not found on the server")
    try:
        fmt = detect_format(p)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    did = db.run("""INSERT INTO datasets (name, original_filename, stored_path, file_format, size_bytes, uploaded_by)
                    VALUES (%s,%s,%s,%s,%s,%s)""", ((body.name or p.name)[:120], p.name, str(p), fmt,
                                                   p.stat().st_size, admin["id"]))
    return db.one("SELECT * FROM datasets WHERE id = %s", (did,))


@router.post("/datasets/{dataset_id}/process", status_code=202)
def process(dataset_id: int, admin: dict = Depends(admin_user)):
    if not db.one("SELECT id FROM datasets WHERE id = %s", (dataset_id,)):
        raise HTTPException(404, "Dataset not found")
    return {"job_id": jobs.submit("profile_clean", admin["id"], dataset_id)}


class ImportIn(BaseModel):
    mapping: dict[str, str] | None = None


@router.post("/datasets/{dataset_id}/import-foods", status_code=202)
def import_foods(dataset_id: int, body: ImportIn, admin: dict = Depends(admin_user)):
    ds = db.one("SELECT id, cleaned_path FROM datasets WHERE id = %s", (dataset_id,))
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if not ds["cleaned_path"]:
        raise HTTPException(409, "Run cleaning first")
    return {"job_id": jobs.submit("import_foods", admin["id"], dataset_id, mapping=body.mapping)}


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: int, admin: dict = Depends(admin_user), t: db.Tx = Depends(db.get_tx)):
    ds = t.one("SELECT * FROM datasets WHERE id = %s", (dataset_id,))
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if ds["stored_path"].startswith(str(UPLOADS)):
        Path(ds["stored_path"]).unlink(missing_ok=True)
    if ds["cleaned_path"]:
        Path(ds["cleaned_path"]).unlink(missing_ok=True)
    removed = t.run("DELETE FROM foods WHERE dataset_id = %s", (dataset_id,))
    t.run("DELETE FROM datasets WHERE id = %s", (dataset_id,))
    return {"ok": True, "foods_removed": removed}


@router.post("/index/rebuild", status_code=202)
def rebuild(admin: dict = Depends(admin_user)):
    return {"job_id": jobs.submit("rebuild_index", admin["id"])}


@router.get("/jobs")
def list_jobs(admin: dict = Depends(admin_user), t: db.Tx = Depends(db.get_tx)):
    rows = t.all("""SELECT j.*, d.name AS dataset_name FROM jobs j LEFT JOIN datasets d ON d.id = j.dataset_id
                    ORDER BY j.id DESC LIMIT 50""")
    for r in rows:
        r["result"] = db.loads(r["result"])
    return rows


@router.get("/jobs/{job_id}")
def get_job(job_id: int, admin: dict = Depends(admin_user), t: db.Tx = Depends(db.get_tx)):
    r = t.one("SELECT * FROM jobs WHERE id = %s", (job_id,))
    if not r:
        raise HTTPException(404, "Job not found")
    r["result"] = db.loads(r["result"])
    return r


@router.get("/models")
def models(admin: dict = Depends(admin_user)):
    runs = []
    try:
        import os
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        import mlflow

        from ml.tracking import EXPERIMENT, tracking_uri
        mlflow.set_tracking_uri(tracking_uri())
        df = mlflow.search_runs(experiment_names=[EXPERIMENT], max_results=40,
                                filter_string="attributes.run_name != ''", order_by=["start_time DESC"])
        df = df[~df["tags.mlflow.runName"].fillna("").str.startswith("lightfm-trial")]
        for _, r in df.head(15).iterrows():
            runs.append({"run_id": r["run_id"], "name": r.get("tags.mlflow.runName"), "status": r["status"],
                         "start_time": str(r["start_time"]),
                         "metrics": {k[8:]: v for k, v in r.items() if k.startswith("metrics.") and v == v}})
    except Exception as exc:  # MLflow store missing or unreadable
        runs = [{"error": f"MLflow runs unavailable: {type(exc).__name__}"}]
    return {"metrics": _read_json(REPORTS / "metrics.json"), "best_params": _read_json(REPORTS / "best_params.json"),
            "feature_importance": _read_json(REPORTS / "feature_importance.json"),
            "train_info": _read_json(REPORTS / "train_info.json"), "faiss": _read_json(MODELS / "faiss_info.json"),
            "ingest_benchmark": _read_json(REPORTS / "ingest_benchmark.json"), "mlflow_runs": runs}
