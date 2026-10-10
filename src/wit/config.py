"""Config = config/defaults.yaml deep-merged with config/trustees/<trustee>.yaml.

Adding a trustee = adding one YAML file. No code changes.
Which trustee file applies is decided by `detect:` patterns matched against the first pages' text.
"""
import copy
import re
from pathlib import Path

import yaml

from .pdfpage import page_model, rows_of

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _merge(base, over):
    """Dicts merge recursively; lists and scalars in the trustee file replace the default."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_trustees(config_dir=CONFIG_DIR):
    defaults = yaml.safe_load(open(config_dir / "defaults.yaml", encoding="utf-8"))
    trustees = {}
    for f in sorted((config_dir / "trustees").glob("*.yaml")):
        if f.name.startswith("_"):
            continue                                   # _template.yaml is documentation only
        t = yaml.safe_load(open(f, encoding="utf-8")) or {}
        if not t.get("enabled", True):
            continue
        trustees[f.stem] = _merge(defaults, t)
    return defaults, trustees


def doc_text(doc, n_pages=3):
    txt = []
    for p in list(doc)[:n_pages]:
        words = page_model(p)[0]
        txt += [r["text"] for r in rows_of(words)]
    meta = " ".join(str(v) for v in (doc.metadata or {}).values() if v)
    return "\n".join(txt) + "\n" + meta


def layouts_for(trustee_name, trustees):
    """Trustee configs whose `names` regex matches the deal list's trustee value."""
    return {k: v for k, v in trustees.items()
            if v.get("names") and re.search(v["names"], trustee_name or "", re.I)}


def pick_config(doc, defaults, trustees, trustee_name=None):
    """Known trustee (from the deal list) -> its layout(s); several layouts -> `detect` picks one.
    Unknown trustee -> detect across all configs."""
    if trustee_name:
        cands = layouts_for(trustee_name, trustees)
        if len(cands) == 1:
            return next(iter(cands.items()))
        if len(cands) > 1:
            name, cfg = detect_trustee(doc, defaults, cands)
            return (name, cfg) if name != "unknown" else next(iter(cands.items()))
    return detect_trustee(doc, defaults, trustees)


def detect_trustee(doc, defaults, trustees):
    """Pick the trustee config whose `detect.all` patterns all match and whose `detect.any`
    patterns match most. Falls back to defaults (trustee 'unknown')."""
    text = doc_text(doc)
    best, best_score = None, 0
    for name, cfg in trustees.items():
        d = cfg.get("detect", {})
        if not all(re.search(p, text, re.I | re.M) for p in d.get("all", [])):
            continue
        score = sum(bool(re.search(p, text, re.I | re.M)) for p in d.get("any", []))
        score += len(d.get("all", []))
        if score > best_score:
            best, best_score = name, score
    if best is None:
        return "unknown", defaults
    return best, trustees[best]
