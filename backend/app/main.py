"""NutriMate API.

    uvicorn backend.app.main:app --port 8000
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from nutrimate_core.paths import ROOT

from . import db
from .config import get_settings
from .metrics import MetricsMiddleware, metrics_response
from .rag import llm
from .rag.retriever import retriever
from .routers import admin, assistant, auth, dashboard, explorer, history, planner, profile, recommend, tracker
from .services import jobs
from .services.engine import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
for noisy in ("faiss.loader", "httpx", "httpx2", "huggingface_hub", "sentence_transformers"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("nutrimate")


def _load_retriever():
    try:
        retriever.load()
    except Exception as exc:
        retriever.error = f"{type(exc).__name__}: {exc}"
        log.error("FAISS index not loaded: %s", retriever.error)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    db.init_schema()
    jobs.mark_interrupted()
    if settings.load_models:
        try:
            engine.load()
        except Exception as exc:
            engine.error = f"{type(exc).__name__}: {exc}"
            log.error("recommendation engine not loaded: %s", engine.error)
        threading.Thread(target=_load_retriever, daemon=True).start()
    log.info("Gemini %s", "enabled" if settings.gemini_enabled else "not configured (template answers)")
    yield


app = FastAPI(title="NutriMate API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(MetricsMiddleware)
for r in (auth, profile, recommend, explorer, tracker, dashboard, planner, history, assistant, admin):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    try:
        db.one("SELECT 1 AS ok")
        database = "ok"
    except Exception as exc:
        database = f"error: {type(exc).__name__}"
    return {"status": "ok" if database == "ok" else "degraded", "database": database, "engine": engine.info(),
            "retriever": {"ready": retriever.ready, "error": retriever.error}, "gemini": llm.gemini_available()}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return metrics_response()


# Serve the built frontend (frontend/dist) when it exists, so one process can run everything.
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
