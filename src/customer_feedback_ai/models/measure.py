"""Operational measurements of a local model (AGENTS.md, section 8).

- Training time: wall clock of `fit`, with no profiler running alongside.
- Inference: measured in a fresh process that loads the saved model on CPU and
  classifies complaints one call at a time (`models/probe.py`). It reports load
  time, latency p50/p95, CPU seconds per 1,000 complaints and peak resident
  memory (RSS). A fresh process gives every model the same starting point, and
  the RSS covers memory allocated by native libraries (NumPy, SciPy, PyTorch),
  which a Python heap profiler does not see.
- Artifact size: bytes of the saved model, file or folder.
"""

import json
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from customer_feedback_ai.errors import DataPipelineError
from customer_feedback_ai.evaluation.bootstrap import quantile


@dataclass(frozen=True)
class Timed[T]:
    value: T
    seconds: float


def timed[T](step: Callable[[], T], clock: Callable[[], float] = time.perf_counter) -> Timed[T]:
    start = clock()
    value = step()
    return Timed(value, clock() - start)


@dataclass(frozen=True)
class PerItemRun:
    durations: tuple[float, ...]
    cpu_seconds: float


def run_per_item(
    predict: Callable[[Sequence[str]], object],
    texts: Sequence[str],
    clock: Callable[[], float] = time.perf_counter,
    cpu_clock: Callable[[], float] = time.process_time,
) -> PerItemRun:
    """One call per complaint, after one warm-up call left out of the numbers."""
    if not texts:
        return PerItemRun((), 0.0)
    predict([texts[0]])
    durations = []
    cpu_start = cpu_clock()
    for text in texts:
        start = clock()
        predict([text])
        durations.append(clock() - start)
    return PerItemRun(tuple(durations), cpu_clock() - cpu_start)


PROC_STATUS = Path("/proc/self/status")


def rss_method() -> str | None:
    if PROC_STATUS.exists():
        return "VmHWM"
    if sys.platform == "darwin":
        return "ru_maxrss"
    return None


def peak_rss_bytes() -> int | None:
    """Peak resident memory of this process so far; None where it is not available.

    On Linux it reads VmHWM, the high-water mark of the current process image.
    `ru_maxrss` is not used there: a child started with fork or vfork inherits
    the parent's peak at that moment, which would hide the model's own memory.
    """
    method = rss_method()
    if method == "VmHWM":
        for line in PROC_STATUS.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
        return None
    if method == "ru_maxrss":
        import resource

        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)  # bytes on macOS
    return None  # Windows and others


@dataclass(frozen=True)
class InferenceProfile:
    calls: int
    latency_p50_s: float | None
    latency_p95_s: float | None
    cpu_seconds_per_1000: float | None
    load_seconds: float
    rss_before_load_bytes: int | None
    peak_rss_bytes: int | None

    @property
    def model_rss_bytes(self) -> int | None:
        """Peak RSS added by loading and running the model, libraries included."""
        if self.peak_rss_bytes is None or self.rss_before_load_bytes is None:
            return None
        return self.peak_rss_bytes - self.rss_before_load_bytes

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "model_rss_bytes": self.model_rss_bytes}

    @classmethod
    def from_run(
        cls, run: PerItemRun, load_seconds: float, before: int | None, peak: int | None
    ) -> "InferenceProfile":
        ordered = sorted(run.durations)
        n = len(ordered)
        return cls(
            calls=n,
            latency_p50_s=quantile(ordered, 0.5) if n else None,
            latency_p95_s=quantile(ordered, 0.95) if n else None,
            cpu_seconds_per_1000=run.cpu_seconds / n * 1000 if n else None,
            load_seconds=load_seconds,
            rss_before_load_bytes=before,
            peak_rss_bytes=peak,
        )


PROBE_MODULE = "customer_feedback_ai.models.probe"
CPU_ONLY_ENV = {"CUDA_VISIBLE_DEVICES": "", "TOKENIZERS_PARALLELISM": "false"}


def profile_in_subprocess(
    name: str, artifact: Path, texts: Sequence[str], work_dir: Path, timeout_s: float = 3600
) -> InferenceProfile:
    """Load the saved model in a fresh CPU-only process and profile its inference.

    The texts go through a temporary file in the local data directory, removed
    at the end; they never appear in the command line or in the output.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    texts_path = work_dir / f"probe-{name}-{os.getpid()}.json"
    texts_path.write_text(json.dumps(list(texts), ensure_ascii=False), encoding="utf-8")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", PROBE_MODULE, name, str(artifact), str(texts_path)],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, **CPU_ONLY_ENV},
            check=False,
        )
    finally:
        texts_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        tail = "\n".join(completed.stderr.strip().splitlines()[-5:])
        msg = f"inference probe for {name} failed (exit {completed.returncode}): {tail}"
        raise DataPipelineError(msg)
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    return InferenceProfile(**payload)


def artifact_bytes(path: Path) -> int:
    if path.is_dir():
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return path.stat().st_size if path.exists() else 0


def machine() -> dict[str, Any]:
    """Where the measurements ran, to declare in the report (same machine for all)."""
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "rss_method": rss_method(),
    }
