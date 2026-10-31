"""Expected pipeline failures end with a message and exit code 1, not a traceback."""

import logging

import pytest

from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.pipelines._common import run_cli


def test_expected_errors_exit_with_code_one(caplog: pytest.LogCaptureFixture) -> None:
    def step() -> None:
        raise DataPipelineError("CSV is missing expected columns: ['data_abertura']")

    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit) as exit_info:
        run_cli(step)

    assert exit_info.value.code == 1
    assert "DataPipelineError" in caplog.text
    assert "data_abertura" in caplog.text


def test_unexpected_errors_keep_their_traceback() -> None:
    def step() -> None:
        raise RuntimeError("bug")

    with pytest.raises(RuntimeError, match="bug"):
        run_cli(step)
