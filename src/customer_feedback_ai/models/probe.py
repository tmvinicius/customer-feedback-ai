"""Inference probe, run by `measure.profile_in_subprocess` in a fresh CPU-only process.

Usage: python -m customer_feedback_ai.models.probe <model> <artifact> <texts.json>

Prints one JSON line with the measurements and nothing from the texts.
"""

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from customer_feedback_ai.models.measure import InferenceProfile, peak_rss_bytes, run_per_item
from customer_feedback_ai.models.registry import load_model


def main(argv: list[str] | None = None) -> None:
    name, artifact, texts_path = argv if argv is not None else sys.argv[1:]
    texts = json.loads(Path(texts_path).read_text(encoding="utf-8"))
    before = peak_rss_bytes()
    start = time.perf_counter()
    model = load_model(name, Path(artifact))
    load_seconds = time.perf_counter() - start
    run = run_per_item(model.predict, texts)
    profile = InferenceProfile.from_run(run, load_seconds, before, peak_rss_bytes())
    print(json.dumps(asdict(profile)))


if __name__ == "__main__":
    main()
