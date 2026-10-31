"""Loading of the versioned YAML files in `configs/`."""

from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIGS_DIR = Path("configs")


def load_yaml_model[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    """Parse a YAML file and validate it against a Pydantic model."""
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return model.model_validate(raw if raw is not None else {})
