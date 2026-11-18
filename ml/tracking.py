"""MLflow setup: a local SQLite tracking store in the project folder (no server needed).

Open the UI with:  mlflow ui --backend-store-uri sqlite:///mlflow.db
"""

from __future__ import annotations

import os

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow  # noqa: E402

from nutrimate_core.paths import ROOT  # noqa: E402

EXPERIMENT = "nutrimate-recommender"


def tracking_uri() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI") or f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}"


def setup() -> None:
    mlflow.set_tracking_uri(tracking_uri())
    if mlflow.get_experiment_by_name(EXPERIMENT) is None:
        mlflow.create_experiment(EXPERIMENT, artifact_location=(ROOT / "mlartifacts").as_uri())
    mlflow.set_experiment(EXPERIMENT)
