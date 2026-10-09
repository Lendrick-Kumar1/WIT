"""`cli doctor`: check this machine and recommend the Docling worker count.

Checks Python, installed deps vs poetry.lock, model files, offline mode, reports folder,
free RAM and CPU cores. With --measure, converts one real page to measure peak RAM per worker.
"""

from __future__ import annotations

import os
import sys
import time
import tomllib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import psutil

from trustee_extract.core.config import (
    LOCAL,
    REPO_ROOT,
    docling_artifacts_path,
    load_config,
    physical_cores,
    reports_dir,
    resolve_path,
)

KEY_PACKAGES = ["docling", "docling-core", "docling-ibm-models", "torch", "pymupdf", "pandas", "pyyaml", "psutil"]
GB = 2**30


@dataclass
class Check:
    status: str  # OK | WARN | FAIL
    name: str
    detail: str


def check_python() -> Check:
    from packaging.specifiers import SpecifierSet

    spec = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
    v = ".".join(map(str, sys.version_info[:3]))
    ok = v in SpecifierSet(spec)
    return Check("OK" if ok else "FAIL", "python", f"{v} (requires {spec}) at {sys.executable}")


def check_deps() -> list[Check]:
    lock = tomllib.loads((REPO_ROOT / "poetry.lock").read_text(encoding="utf-8"))
    locked = {p["name"].lower(): p["version"] for p in lock["package"]}
    out = []
    for name in KEY_PACKAGES:
        try:
            have = version(name)
        except PackageNotFoundError:
            out.append(Check("FAIL", f"dep {name}", "not installed: run `poetry install`"))
            continue
        want = locked.get(name)
        status = "OK" if have == want else "WARN"
        out.append(Check(status, f"dep {name}", have if status == "OK" else f"{have}, lock has {want}: run `poetry install`"))
    return out


def check_models(cfg: dict) -> list[Check]:
    root = docling_artifacts_path(cfg)
    if not root.is_dir():
        return [Check("FAIL", "models", f"{root} missing: see docs/SETUP.md")]
    from trustee_extract.detect.docling_layout import set_offline_env

    set_offline_env()
    from docling.datamodel.pipeline_options import LayoutObjectDetectionOptions

    d = cfg["docling"]
    repo = LayoutObjectDetectionOptions.from_preset(d["layout_preset"]).model_spec.repo_id.replace("/", "--")
    tf = root / "docling-project--docling-models" / "model_artifacts" / "tableformer" / d["table_mode"]
    wanted = {
        f"layout {d['layout_preset']}": [root / repo / "config.json", root / repo / "model.safetensors"],
        f"tableformer {d['table_mode']}": [tf / "tm_config.json", tf / f"tableformer_{d['table_mode']}.safetensors"],
    }
    out = []
    for name, files in wanted.items():
        missing = [str(f.relative_to(root)) for f in files if not f.exists()]
        out.append(Check("FAIL" if missing else "OK", name, f"missing {missing}" if missing else str(files[0].parent)))
    yolo = resolve_path(cfg["yolo"]["weights"])
    out.append(Check("OK" if yolo.exists() else "WARN", "yolo weights",
                     str(yolo) if yolo.exists() else f"{yolo} not found (optional; docs/SETUP.md)"))
    return out


def check_offline() -> Check:
    from trustee_extract.detect.docling_layout import set_offline_env

    shell = os.environ.get("HF_HUB_OFFLINE")
    set_offline_env()
    return Check("OK", "offline", f"HF_HUB_OFFLINE=1 enforced in code (shell value: {shell or 'unset'}); remote services off")


def check_reports(cfg: dict) -> Check:
    d = reports_dir(cfg)
    n = len(list(d.glob("*.pdf"))) if d.is_dir() else 0
    return Check("OK" if n else "WARN", "reports", f"{d}: {n} PDFs")


def measure_peak_gb(cfg: dict, pdf: Path | None, page: int | None) -> tuple[float, str]:
    """Convert one real page with the configured pipeline; return peak RSS of this process."""
    import pymupdf

    from trustee_extract.detect.docling_layout import build_converter

    if pdf is None:
        pdfs = sorted(reports_dir(cfg).glob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError("no PDFs to measure with; pass --pdf")
        pdf = pdfs[0]
    if page is None:  # densest of the first 10 pages, so TableFormer actually runs
        with pymupdf.open(pdf) as doc:
            page = 1 + max(range(min(10, doc.page_count)), key=lambda i: len(doc[i].get_text("words")))
    t = time.perf_counter()
    build_converter(cfg).convert(pdf, page_range=(page, page))
    mi = psutil.Process().memory_info()
    peak = getattr(mi, "peak_wset", None)
    if peak is None:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    return peak / GB, f"{pdf.name} p{page}, {time.perf_counter() - t:.1f}s"


def recommend_workers(free_gb: float, peak_gb: float, cores: int, min_free_for_2: float) -> int:
    """1 by default; 2 only with >= min_free_for_2 GB free, room for 2 workers + 4 GB headroom, and 4+ cores."""
    if cores >= 4 and free_gb >= max(min_free_for_2, 2 * peak_gb + 4):
        return 2
    return 1


def run(measure: bool = False, pdf: Path | None = None, page: int | None = None) -> int:
    cfg = load_config()
    checks = [check_python(), *check_deps(), check_offline(), *check_models(cfg), check_reports(cfg)]
    checks.append(Check("OK", "config", f"defaults.yaml + {'local.yaml' if LOCAL.exists() else 'no local.yaml'}"))

    vm = psutil.virtual_memory()
    free_gb, total_gb = vm.available / GB, vm.total / GB
    cores, logical = physical_cores(), os.cpu_count()
    checks.append(Check("OK", "cpu", f"{cores} physical / {logical} logical cores"))
    checks.append(Check("OK" if free_gb >= 4 else "WARN", "ram", f"{free_gb:.1f} GB free of {total_gb:.1f} GB"))

    rt = cfg["runtime"]
    peak, how = rt["worker_peak_ram_gb"], "config runtime.worker_peak_ram_gb"
    if measure and not any(c.status == "FAIL" and c.name.startswith(("layout", "tableformer", "models")) for c in checks):
        peak, sample = measure_peak_gb(cfg, pdf, page)
        how = f"measured on {sample}"
    checks.append(Check("OK", "worker peak RAM", f"{peak:.2f} GB ({how})"))

    for c in checks:
        print(f"[{c.status:4}] {c.name:24} {c.detail}")

    rec = recommend_workers(free_gb, peak, cores, rt["min_free_ram_gb_for_2_workers"])
    threads = max(1, cores // rec)
    print(f"\nRecommended: workers={rec}, threads_per_worker={threads}  (configured: workers={rt['workers']}, "
          f"threads_per_worker={rt['threads_per_worker'] or 'auto'})")
    if rec != rt["workers"]:
        print(f"  To apply on this machine: set runtime.workers: {rec} in config/local.yaml (or env TE_WORKERS={rec}).")
    return 1 if any(c.status == "FAIL" for c in checks) else 0
