"""Guards against committing corpus data, model weights or secrets (AGENTS.md, rule 6)."""

import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_SUFFIXES = frozenset(
    {
        # corpus data and derived tables or arrays
        ".csv",
        ".parquet",
        ".npy",
        ".npz",
        ".duckdb",
        # model weights and serialized estimators
        ".safetensors",
        ".pt",
        ".pth",
        ".bin",
        ".onnx",
        ".joblib",
        ".pkl",
    }
)
SYNTHETIC_FIXTURES_DIR = PurePosixPath("tests/fixtures")

MUST_BE_IGNORED = [
    ".env",
    ".env.local",
    "data/raw/consumerbr.csv",
    "data/bronze/complaints.parquet",
    "data/gold/index/embeddings.npy",
    "data/logs/llm_calls.jsonl",
    "models/c3/model.safetensors",
    "mlruns/0/meta.yaml",
    "exports/complaints.csv",
    "artifacts/c1.joblib",
]

MUST_BE_VERSIONED = [
    ".env.example",
    "reports/metrics.json",
    "evals/cassettes/classify/example.json",
    "tests/fixtures/synthetic_complaints.csv",
    "src/customer_feedback_ai/settings.py",
]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module", autouse=True)
def _require_git_checkout() -> None:
    if shutil.which("git") is None or _git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("requires a git checkout")


def _is_ignored(path: str) -> bool:
    result = _git("check-ignore", "--quiet", "--no-index", path)
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_sensitive_paths_are_ignored(path: str) -> None:
    assert _is_ignored(path), f"{path} must be listed in .gitignore"


@pytest.mark.parametrize("path", MUST_BE_VERSIONED)
def test_project_paths_are_not_ignored(path: str) -> None:
    assert not _is_ignored(path), f"{path} must not be ignored"


def test_no_forbidden_files_are_tracked() -> None:
    result = _git("ls-files", "-z")
    assert result.returncode == 0, result.stderr

    offenders = []
    for name in filter(None, result.stdout.split("\0")):
        path = PurePosixPath(name)
        if SYNTHETIC_FIXTURES_DIR in path.parents:
            continue
        if path.name == ".env" or path.parts[0] == "data" or path.suffix in FORBIDDEN_SUFFIXES:
            offenders.append(name)

    assert offenders == [], f"files that must not be in Git: {offenders}"
