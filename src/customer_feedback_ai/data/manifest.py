"""Pipeline manifests: input and output hashes, counts, seed, config and commit.

Every stage writes one manifest to `data/manifests/`. Two runs with the same
input, config and code must produce manifests that differ only in `created_at`.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel, ConfigDict

from customer_feedback_ai import __version__

_CHUNK = 1 << 20


class FileRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    path: str
    sha256: str
    bytes: int
    rows: int | None = None


class GitState(BaseModel):
    model_config = ConfigDict(frozen=True)

    commit: str | None
    dirty: bool | None


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    created_at: datetime
    git: GitState
    package_version: str
    duckdb_version: str
    seed: int | None
    config: dict[str, Any]
    config_sha256: str
    inputs: list[FileRecord]
    outputs: list[FileRecord]
    counts: dict[str, int]
    details: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, relative_path: str, rows: int | None = None) -> FileRecord:
    return FileRecord(
        path=relative_path,
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
        rows=rows,
    )


def git_state(cwd: Path | None = None) -> GitState:
    """Current commit and whether the working tree has uncommitted changes."""

    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
            )
        except OSError:
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    if commit is None:
        return GitState(commit=None, dirty=None)
    status = run("status", "--porcelain", "--untracked-files=no")
    return GitState(commit=commit, dirty=None if status is None else bool(status))


def config_sha256(config: dict[str, Any]) -> str:
    canonical = json.dumps(config, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    stage: str,
    config: dict[str, Any],
    inputs: list[FileRecord],
    outputs: list[FileRecord],
    counts: dict[str, int],
    seed: int | None = None,
    details: dict[str, Any] | None = None,
) -> Manifest:
    return Manifest(
        stage=stage,
        created_at=datetime.now(UTC),
        git=git_state(),
        package_version=__version__,
        duckdb_version=duckdb.__version__,
        seed=seed,
        config=config,
        config_sha256=config_sha256(config),
        inputs=inputs,
        outputs=outputs,
        counts=counts,
        details=details or {},
    )


def write_manifest(manifest: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump(mode="json")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> Manifest:
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))
