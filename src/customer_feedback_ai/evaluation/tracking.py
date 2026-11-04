"""Local MLflow tracking, without a server (AGENTS.md, sections 11 and 13).

Runs go to a SQLite file under the data directory (`<DATA_DIR>/mlflow/mlflow.db`),
because models trained on the corpus are derived data and stay out of Git. Each
run records commit, data hashes, configuration, metrics, size and latency.
Artifacts, if any, stay in `<DATA_DIR>/mlflow/artifacts/`. MLflow telemetry is off.

To browse the runs, use the full MLflow in a separate environment, for example:

    uvx mlflow ui --backend-store-uri sqlite:///data/mlflow/mlflow.db
"""

import os
import warnings
from pathlib import Path
from typing import Any

EXPERIMENT = "customer-feedback-ai"


def tracking_uri(directory: Path) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(directory / 'mlflow.db').resolve()}"


def _flatten(prefix: str, value: Any, out: dict[str, float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float):
        out[prefix] = float(value)
    elif isinstance(value, dict):
        for key, inner in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), inner, out)


def flatten_metrics(metrics: dict[str, Any]) -> dict[str, float]:
    """Nested numbers become dotted metric names; other values are left out."""
    out: dict[str, float] = {}
    _flatten("", metrics, out)
    return {key.replace("/", "_"): value for key, value in out.items()}


class Tracker:
    """Thin wrapper so the pipelines never depend on MLflow directly."""

    def __init__(self, directory: Path, enabled: bool = True):
        self.enabled = enabled
        self.uri = tracking_uri(directory) if enabled else None
        # Explicit, so MLflow never defaults to ./mlruns inside the repository.
        self.artifacts = (directory / "artifacts").resolve()

    def log_run(
        self, name: str, params: dict[str, Any], metrics: dict[str, Any], tags: dict[str, str]
    ) -> str | None:
        if not self.enabled or self.uri is None:
            return None
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        # The project contacts no external service it does not need (G1).
        os.environ["MLFLOW_DISABLE_TELEMETRY"] = "true"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import mlflow

            mlflow.set_tracking_uri(self.uri)
            if mlflow.get_experiment_by_name(EXPERIMENT) is None:
                mlflow.create_experiment(EXPERIMENT, artifact_location=self.artifacts.as_uri())
            mlflow.set_experiment(EXPERIMENT)
            with mlflow.start_run(run_name=name) as run:
                mlflow.log_params({k: str(v)[:500] for k, v in params.items()})
                mlflow.log_metrics(flatten_metrics(metrics))
                mlflow.set_tags(tags)
            run_id: str = run.info.run_id
            return run_id
