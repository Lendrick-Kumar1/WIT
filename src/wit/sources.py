"""Find the reports to process from the org's own metadata, not from the PDF text.

  deal list (Excel)  ->  active deals + trustee per deal
  reports root       ->  <root>/<deal folder>/<report type folder>/<file named by period>
  period 2026-08     ->  first report type (in priority order) that has a file for 2026_8

Deal name, trustee and report month therefore come from metadata, which is reliable.
All names and paths live in config/sources.yaml.
"""
import re
from pathlib import Path

import pandas as pd
import yaml

from .config import CONFIG_DIR


def load_sources(path=None):
    return yaml.safe_load(open(path or CONFIG_DIR / "sources.yaml", encoding="utf-8"))


def active_deals(src, trustee=None):
    dl = src["deal_list"]
    df = pd.read_excel(dl["path"], sheet_name=dl.get("sheet", 0))
    for col, val in (dl.get("filter") or {}).items():
        df = df[df[col].astype(str).str.strip().str.lower() == str(val).strip().lower()]
    c = dl["columns"]
    if trustee:
        df = df[df[c["trustee"]].astype(str).str.contains(trustee, case=False, regex=False)]
    return [dict(deal=str(r[c["deal"]]).strip(), trustee=str(r[c["trustee"]]).strip(),
                 folder=str(r[c.get("folder", c["deal"])]).strip()) for _, r in df.iterrows()]


def period_regex(src, period):
    y, m = [int(x) for x in period.split("-")]
    pat = src["file_period_regex"].replace("{yyyy}", str(y)).replace("{m}", str(m)).replace("{mm}", f"{m:02d}")
    return re.compile(pat, re.I)


def find_report(src, deal_folder, period):
    """First matching file in report-type priority order, or (None, None)."""
    root = Path(src["reports_root"]) / deal_folder
    rx = period_regex(src, period)
    for rtype in src["report_folders"]:
        d = root / rtype
        if not d.is_dir():
            continue
        hits = sorted(f for f in d.iterdir() if f.suffix.lower() == ".pdf" and rx.search(f.stem))
        if hits:
            return hits[0], rtype
    return None, None


def plan(period, trustee=None, src=None):
    """List of jobs: {deal, trustee, pdf, report_type, period} (pdf None = not found)."""
    src = src or load_sources()
    jobs = []
    for d in active_deals(src, trustee):
        pdf, rtype = find_report(src, d["folder"], period)
        jobs.append(dict(**d, pdf=str(pdf) if pdf else None, report_type=rtype, period=period))
    return jobs
