"""Load `config/defaults.yaml` and resolve repo-relative paths."""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = REPO_ROOT / "config" / "defaults.yaml"


@lru_cache(maxsize=None)
def load_config(path: Path = DEFAULTS) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


def docling_artifacts_path(cfg: dict | None = None) -> Path:
    """Model folder: env DOCLING_ARTIFACTS_PATH wins, else config, `~` expanded."""
    cfg = cfg or load_config()
    raw = os.environ.get("DOCLING_ARTIFACTS_PATH") or cfg["docling"]["artifacts_path"]
    return Path(raw).expanduser()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
