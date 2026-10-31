"""Helpers shared by the command-line pipelines."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from customer_feedback_ai.data.paths import DataPaths
from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.settings import get_settings

LOGGER = logging.getLogger("customer_feedback_ai")


EXPECTED_ERRORS = (DataPipelineError, FileNotFoundError, FileExistsError, ValidationError)


def run_cli(step: Callable[[], object]) -> None:
    """Run a pipeline step; expected failures end with a message and exit code 1."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        step()
    except EXPECTED_ERRORS as error:
        LOGGER.error("%s: %s", type(error).__name__, error)
        raise SystemExit(1) from None


def default_paths() -> DataPaths:
    return DataPaths(get_settings().data_dir)


def write_json(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require(path: Path, hint: str) -> Path:
    if not path.exists():
        msg = f"{path} not found. {hint}"
        raise FileNotFoundError(msg)
    return path
