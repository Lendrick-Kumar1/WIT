"""Layered config: `config/defaults.yaml` < `config/local.yaml` (git-ignored) < env vars.

No machine-specific values live in code. Per-machine settings (models path, reports path,
workers, threads) go in `config/local.yaml` or env vars (see ENV_OVERRIDES).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = REPO_ROOT / "config" / "defaults.yaml"
LOCAL = REPO_ROOT / "config" / "local.yaml"

# env var -> (config path, type)
ENV_OVERRIDES: dict[str, tuple[tuple[str, ...], type]] = {
    "DOCLING_ARTIFACTS_PATH": (("docling", "artifacts_path"), str),
    "TE_REPORTS_DIR": (("paths", "reports"), str),
    "TE_WORKERS": (("runtime", "workers"), int),
    "TE_THREADS": (("runtime", "threads_per_worker"), int),
    "TE_YOLO_WEIGHTS": (("yolo", "weights"), str),
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def build_config(defaults: Path = DEFAULTS, local: Path = LOCAL, env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    with open(defaults, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if local.exists():
        with open(local, encoding="utf-8") as f:
            cfg = deep_merge(cfg, yaml.safe_load(f) or {})
    for var, (keys, typ) in ENV_OVERRIDES.items():
        if env.get(var):
            node = cfg
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = typ(env[var])
    return cfg


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Process-wide config (cached; workers load it once)."""
    return build_config()


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


def resolve_path(raw: str) -> Path:
    """Expand `~` and env vars; relative paths are relative to the repo root."""
    p = Path(os.path.expandvars(raw)).expanduser()
    return p if p.is_absolute() else REPO_ROOT / p


def docling_artifacts_path(cfg: dict | None = None) -> Path:
    return resolve_path((cfg or load_config())["docling"]["artifacts_path"])


def reports_dir(cfg: dict | None = None) -> Path:
    return resolve_path((cfg or load_config())["paths"]["reports"])


def physical_cores() -> int:
    import psutil

    return psutil.cpu_count(logical=False) or max(1, (os.cpu_count() or 2) // 2)


def threads_per_worker(cfg: dict | None = None) -> int:
    """Configured value, else physical cores split across workers (workers x threads <= cores)."""
    rt = (cfg or load_config())["runtime"]
    return rt.get("threads_per_worker") or max(1, physical_cores() // max(1, rt["workers"]))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
