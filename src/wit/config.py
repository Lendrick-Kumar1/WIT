"""Configuration files (all in the `config/` folder, next to WIT.exe or at the repo root):

  settings.yaml           where things are: reports folder, deal list, report types, outputs
  defaults.yaml           extraction vocabulary shared by every trustee
  trustees/<name>.yaml    what differs per trustee layout (merged on top of defaults.yaml)

Adding a trustee = adding one YAML file. No code changes.
"""
import copy
import re
import sys
from pathlib import Path

import yaml

from .pdfpage import page_model, rows_of


def app_dir():
    """Folder of WIT.exe when frozen, else the repo root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


CONFIG_DIR = app_dir() / "config"


def _read(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


OUTPUT_NAMES = {"balance": "Balance", "performance": "Performance", "collateral": "Collateral"}


def load_settings(path=None):
    """settings.yaml. Relative paths in it are relative to the app folder."""
    s = _read(path or CONFIG_DIR / "settings.yaml")

    def absolute(p):
        return str(p) if Path(p).is_absolute() else str(app_dir() / p)
    s["reports_root"] = absolute(s["reports_root"])
    s["deal_list"]["path"] = absolute(s["deal_list"]["path"])
    out = s["output"]
    for name in OUTPUT_NAMES:
        out[name]["dir"] = absolute(out[name]["dir"])
    out["run_reports"] = absolute(out["run_reports"])
    return s


def redirect_outputs(settings, folder):
    """All outputs under one folder (<folder>/Balance, /Performance, /Collateral, /Run reports),
    e.g. for comparing two versions of the code. File names stay as configured."""
    out = settings["output"]
    for name, sub in OUTPUT_NAMES.items():
        out[name]["dir"] = str(Path(folder) / sub)
    out["run_reports"] = str(Path(folder) / "Run reports")
    return settings


def _merge(base, over):
    """Dicts merge recursively; lists and scalars in the trustee file replace the default."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_trustees(config_dir=None):
    """-> (defaults, {layout name: defaults merged with that trustee file})"""
    config_dir = Path(config_dir or CONFIG_DIR)
    defaults = _read(config_dir / "defaults.yaml")
    trustees = {}
    for f in sorted((config_dir / "trustees").glob("*.yaml")):
        if f.name.startswith("_"):
            continue                                   # _template.yaml is documentation only
        t = _read(f)
        if t.get("enabled", True):
            trustees[f.stem] = _merge(defaults, t)
    return defaults, trustees


def doc_text(doc, n_pages=3):
    txt = []
    for p in list(doc)[:n_pages]:
        txt += [r["text"] for r in rows_of(page_model(p)[0])]
    meta = " ".join(str(v) for v in (doc.metadata or {}).values() if v)
    return "\n".join(txt) + "\n" + meta


def layouts_for(trustee_name, trustees):
    """Trustee configs whose `names` regex matches the trustee value from the deal list."""
    return {k: v for k, v in trustees.items()
            if v.get("names") and re.search(v["names"], trustee_name or "", re.I)}


def pick_config(doc, defaults, trustees, trustee_name=None):
    """The deal list's trustee -> its layout(s); several layouts -> `detect` patterns pick one.
    No trustee given (inspecting a single PDF) -> detect across all configs."""
    if trustee_name:
        cands = layouts_for(trustee_name, trustees)
        if len(cands) == 1:
            return next(iter(cands.items()))
        if len(cands) > 1:
            name, cfg = detect_trustee(doc, defaults, cands)
            return (name, cfg) if name != "unknown" else next(iter(cands.items()))
    return detect_trustee(doc, defaults, trustees)


def detect_trustee(doc, defaults, trustees):
    """Configs whose `detect.all` patterns all match; the one matching most `detect.any` wins.
    None -> 'unknown' (defaults only; the run report flags it)."""
    text = doc_text(doc)
    best, best_score = None, 0
    for name, cfg in trustees.items():
        d = cfg.get("detect", {})
        if not all(re.search(p, text, re.I | re.M) for p in d.get("all", [])):
            continue
        score = len(d.get("all", [])) + sum(bool(re.search(p, text, re.I | re.M)) for p in d.get("any", []))
        if score > best_score:
            best, best_score = name, score
    if best is None:
        return "unknown", defaults
    return best, trustees[best]
