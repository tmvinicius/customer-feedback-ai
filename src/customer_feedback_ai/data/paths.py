"""File layout of the local data directory (AGENTS.md, section 6)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SplitSource = Literal["silver", "dev_sample"]


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @property
    def raw_dir(self) -> Path:
        return self.root / "raw"

    @property
    def bronze(self) -> Path:
        return self.root / "bronze" / "complaints.parquet"

    @property
    def silver(self) -> Path:
        return self.root / "silver" / "complaints.parquet"

    @property
    def dev_sample(self) -> Path:
        return self.root / "silver" / "dev_sample.parquet"

    @property
    def gold_dir(self) -> Path:
        return self.root / "gold"

    @property
    def manifests_dir(self) -> Path:
        return self.root / "manifests"

    @property
    def eda_dir(self) -> Path:
        return self.root / "eda"

    @property
    def tmp_dir(self) -> Path:
        return self.root / "tmp"

    @property
    def taxonomy_review_sample(self) -> Path:
        return self.gold_dir / "taxonomy_review_sample.csv"

    def split_input(self, source: SplitSource) -> Path:
        return self.silver if source == "silver" else self.dev_sample

    def splits_dir(self, source: SplitSource) -> Path:
        if source == "silver":
            return self.gold_dir / "splits"
        return self.gold_dir / "dev_sample" / "splits"

    def manifest(self, stage: str) -> Path:
        return self.manifests_dir / f"{stage}.json"

    def relative(self, path: Path) -> str:
        """Path relative to the data root, so manifests do not depend on where data lives."""
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def find_raw_csv(self) -> Path:
        """Return the only CSV in `raw/`, or fail if there are none or several."""
        candidates = sorted(self.raw_dir.glob("*.csv"))
        if len(candidates) != 1:
            found = [path.name for path in candidates]
            msg = (
                f"expected exactly one CSV in {self.raw_dir}, found {len(candidates)}: {found}. "
                "Pass the file explicitly with --raw."
            )
            raise FileNotFoundError(msg)
        return candidates[0]
