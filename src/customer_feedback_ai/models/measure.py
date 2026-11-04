"""Operational measurements of a local model (AGENTS.md, section 8).

- Training time: wall clock of `fit`.
- Latency: individual `predict` calls, one complaint each, reported as p50/p95.
- Memory: peak Python heap during `fit` and during inference, from `tracemalloc`
  (NumPy and SciPy report their buffers to it). It is not the process RSS.
- Artifact size: bytes of the saved model.
"""

import time
import tracemalloc
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from customer_feedback_ai.evaluation.bootstrap import quantile
from customer_feedback_ai.models.base import TopicUrgencyModel


@dataclass(frozen=True)
class Timed[T]:
    value: T
    seconds: float
    peak_bytes: int


def timed[T](step: Callable[[], T], clock: Callable[[], float] = time.perf_counter) -> Timed[T]:
    """Run a step, measuring wall time and the peak traced memory."""
    tracemalloc.start()
    start = clock()
    try:
        value = step()
        seconds = clock() - start
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return Timed(value, seconds, peak)


@dataclass(frozen=True)
class Latency:
    p50_s: float | None
    p95_s: float | None
    calls: int
    peak_bytes: int


def per_item_latency(
    model: TopicUrgencyModel,
    texts: Sequence[str],
    clock: Callable[[], float] = time.perf_counter,
) -> Latency:
    """One `predict` call per complaint, after one warm-up call left out of the numbers."""
    if not texts:
        return Latency(None, None, 0, 0)
    model.predict([texts[0]])
    durations: list[float] = []

    def run() -> None:
        for text in texts:
            start = clock()
            model.predict([text])
            durations.append(clock() - start)

    measured = timed(run, clock)
    ordered = sorted(durations)
    return Latency(
        quantile(ordered, 0.5), quantile(ordered, 0.95), len(ordered), measured.peak_bytes
    )


def artifact_bytes(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0
