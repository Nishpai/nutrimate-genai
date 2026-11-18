"""Prometheus metrics, exposed at /metrics."""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter("nutrimate_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("nutrimate_http_request_seconds", "HTTP request latency", ["method", "route"],
                    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))
RECOMMEND_SECONDS = Histogram("nutrimate_recommend_seconds", "Time to build one recommendation list",
                              buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5))
ASSISTANT_REPLIES = Counter("nutrimate_assistant_replies_total", "Assistant replies by mode", ["mode"])
LLM_SECONDS = Histogram("nutrimate_llm_seconds", "Gemini call latency", buckets=(0.5, 1, 2, 4, 8, 16, 32))
RETRIEVAL_SECONDS = Histogram("nutrimate_retrieval_seconds", "FAISS retrieval latency",
                              buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5))
JOBS = Counter("nutrimate_jobs_total", "Background jobs finished", ["job_type", "status"])
JOBS_RUNNING = Gauge("nutrimate_jobs_running", "Background jobs running now")
MODEL_LOADED = Gauge("nutrimate_model_loaded", "1 when a model artifact is loaded", ["model"])


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        if path != "/metrics":
            LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
            REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
