"""Running a selection: months x deals, any of the three outputs.

    jobs = sources.plan(settings, months, deals)          one job per (month, deal)
    run(jobs, outputs, settings, log)                       read, write, report

Each deal is written as soon as it is done (a stopped or failed run keeps what was finished).
A deal that fails is reported and the run goes on.

Output (folders, file names and columns from config/settings.yaml `output`):
  <balance dir>/<file>, <performance dir>/<file>, <collateral dir>/<file>   per deal and month,
                                                                            only the outputs selected
  <run_reports>/run_report_<date>_<time>.xlsx                                every check of the run:
      summary            one line per deal and month (file found?, counts, statuses)
      balance_sources    where each balance value came from, and its status
      performance_flags  test rows with _status other than ok
      unmapped_tests     printed test names with no standard name yet (config performance.test_names)
      collateral_gaps    collateral columns that stayed empty
      collateral_sums    every printed subtotal/total vs the sum of the rows read
      xlarge_fallback    crops re-read by XLarge (only with --fallback)
"""
import datetime as dt
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pymupdf

from . import balance as B
from . import performance as P
from .collateral import collateral
from .config import load_trustees, pick_config
from .pages import select_pages

OUTPUTS = ("balance", "performance", "collateral")


@dataclass
class DealResult:
    job: dict
    report: dict                                        # one line of the summary sheet
    tables: dict = field(default_factory=dict)          # output name -> DataFrame (internal names)
    bal_sources: pd.DataFrame = None
    perf_flags: pd.DataFrame = None
    unmapped: pd.DataFrame = None
    coll_checks: pd.DataFrame = None
    empty_cols: list = field(default_factory=list)
    fallback: list = field(default_factory=list)


def month_label(job, settings):
    return dt.date(job["year"], job["month"], 1).strftime(settings["output"].get("month_format", "%Y-%m"))


# ---------------------------------------------------------------------------------------------
# reading one report
# ---------------------------------------------------------------------------------------------
def read_performance(doc, cfg):
    rows = [rec for i in select_pages(doc, cfg, "performance") for rec in P.performance(doc[i], cfg)]
    perf = pd.DataFrame(rows, columns=["test", "original tests", "current", "trigger", "result",
                                       "_status", "_mapped", "_page"])
    # the same test is often printed twice (summary page + detail page)
    return perf.drop_duplicates(subset=["original tests", "current", "trigger"], keep="first")


def read_balance(doc, cfg):
    """-> ({field: value}, {field: {value, status, how, label, page, n}})"""
    cands = [c for i in select_pages(doc, cfg, "balance") for c in B.candidates(doc[i], cfg)]
    res = B.resolve(cands, cfg)
    for f, spec in B.fields(cfg)[1].items():
        res[f] = B.table_total(doc, cfg, spec)
    return {f: r.get("value") for f, r in res.items()}, res


def process(job, outputs, defaults, trustees, settings, xl=None):
    """One deal and month -> DealResult (only the selected outputs are read)."""
    t0 = time.time()
    month = month_label(job, settings)
    report = dict(deal=job["deal"], month=f"{job['year']}-{job['month']:02d}", trustee=job["trustee"],
                  report_type=job["report_type"], file_status=job["file_status"], file_note=job["file_note"],
                  pdf=Path(job["pdf"]).name if job["pdf"] else "")
    res = DealResult(job, report)
    if not job["pdf"]:
        report["needs_attention"] = True
        return res
    doc = pymupdf.open(job["pdf"])
    layout, cfg = pick_config(doc, defaults, trustees, job["trustee"])
    report.update(layout=layout, pages=len(doc))
    common = {"deal name": job["deal"], "report_month": month, "asset class": cfg.get("asset_class", "CLO")}
    attention = layout == "unknown" or job["file_status"] != "ok"

    if "performance" in outputs:
        perf = read_performance(doc, cfg)
        res.tables["performance"] = perf.assign(**common)
        res.perf_flags = perf[perf["_status"] != "ok"]
        res.unmapped = perf[~perf["_mapped"].astype(bool)][["original tests", "_page"]]
        n_check = int((perf["_status"] != "ok").sum())
        report.update(tests=len(perf), tests_to_check=n_check, tests_unmapped=len(res.unmapped))
        attention |= not len(perf) or n_check > 0

    if "balance" in outputs:
        values, sources = read_balance(doc, cfg)
        res.tables["balance"] = pd.DataFrame([{**common, **values}])
        res.bal_sources = pd.DataFrame([{"field": f, **r} for f, r in sources.items()])
        report.update({f"bal:{f}": r.get("status", "missing") for f, r in sources.items()})
        attention |= any(r.get("status") != "ok" for r in sources.values())

    if "collateral" in outputs:
        rows, checks, fb = collateral(doc, select_pages(doc, cfg, "collateral"), cfg, xl)
        res.tables["collateral"] = rows.assign(**common)
        res.coll_checks, res.fallback = checks, fb
        wanted = [c for c in settings["output"]["columns"]["collateral"] if c not in common]
        res.empty_cols = [c for c in wanted if c not in rows or rows[c].isna().all()]
        report.update(collateral_rows=len(rows), collateral_empty_columns=len(res.empty_cols),
                      collateral_sums_ok=int(checks["check"].str.startswith("ok").sum()),
                      collateral_sums_to_check=int(checks["check"].str.startswith("check").sum()),
                      xlarge_crops=len(fb))
        attention |= not len(rows)

    report["needs_attention"] = bool(attention)
    report["seconds"] = round(time.time() - t0, 1)
    return res


# ---------------------------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------------------------
def output_path(job, name, settings):
    """<dir>/<file> of one output for one deal and month ({deal} {yyyy} {mm} filled in)."""
    o = settings["output"][name]
    safe = re.sub(r'[<>:"/\\|?*]+', "_", job["deal"]).strip()
    keys = dict(deal=safe, yyyy=job["year"], mm=f"{job['month']:02d}")
    return Path(o["dir"].format(**keys)) / o["file"].format(**keys)


def write_deal(res, settings):
    """The selected output files of one deal and month, schema columns only -> [paths]."""
    out = settings["output"]
    paths = []
    for name, df in res.tables.items():
        path = output_path(res.job, name, settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.reindex(columns=out["columns"][name]).rename(columns=out.get("rename") or {}).to_excel(path, index=False)
        paths.append(path)
    return paths


def write_run_report(results, settings, started):
    root = Path(settings["output"]["run_reports"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"run_report_{started:%Y-%m-%d_%H%M%S}.xlsx"

    def sheet(attr, cols=None):
        parts = []
        for r in results:
            df = getattr(r, attr)
            if df is not None and len(df):
                df = df.drop(columns=[c for c in ("_mapped",) if c in df])
                parts.append(df.assign(deal=r.report["deal"], month=r.report["month"]))
        if not parts:
            return pd.DataFrame(columns=cols or [])
        df = pd.concat(parts, ignore_index=True)
        return df[["deal", "month"] + [c for c in df.columns if c not in ("deal", "month")]]

    gaps = [{"deal": r.report["deal"], "month": r.report["month"], "empty collateral column": c}
            for r in results for c in r.empty_cols]
    xl = [{"deal": r.report["deal"], "month": r.report["month"], **e} for r in results for e in r.fallback]
    unmapped = sheet("unmapped")
    if len(unmapped):
        unmapped = unmapped.drop_duplicates(subset=["deal", "original tests"])
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame([r.report for r in results]).to_excel(xw, sheet_name="summary", index=False)
        sheet("bal_sources").to_excel(xw, sheet_name="balance_sources", index=False)
        sheet("perf_flags").to_excel(xw, sheet_name="performance_flags", index=False)
        unmapped.to_excel(xw, sheet_name="unmapped_tests", index=False)
        pd.DataFrame(gaps).to_excel(xw, sheet_name="collateral_gaps", index=False)
        sheet("coll_checks").to_excel(xw, sheet_name="collateral_sums", index=False)
        pd.DataFrame(xl).to_excel(xw, sheet_name="xlarge_fallback", index=False)
    return path


# ---------------------------------------------------------------------------------------------
# a whole run
# ---------------------------------------------------------------------------------------------
def run(jobs, outputs, settings, log=print, xl=None, stop=None, progress=None):
    """Process every job, write each deal right away, then the run report. -> run report path.
    stop: optional callable; returning True ends the run after the current deal.
    progress: optional callable(done, total), called after every deal."""
    started = dt.datetime.now()
    defaults, trustees = load_trustees()
    outputs = [o for o in OUTPUTS if o in outputs]
    results = []
    for n, job in enumerate(jobs, 1):
        if stop and stop():
            log("stopped")
            break
        tag = f"[{n}/{len(jobs)}] {job['year']}-{job['month']:02d}  {job['deal']}"
        if not job["pdf"]:
            log(f"{tag}: {job['file_status'].upper()}  {job['file_note']}")
            results.append(process(job, outputs, defaults, trustees, settings))
            if progress:
                progress(n, len(jobs))
            continue
        try:
            res = process(job, outputs, defaults, trustees, settings, xl)
            write_deal(res, settings)
            r = res.report
            bits = [f"{k}={r[k]}" for k in ("tests", "collateral_rows") if k in r]
            note = f"  ({job['file_note']})" if job["file_note"] else ""
            log(f"{tag}: {' '.join(bits) or 'done'}{'  CHECK' if r['needs_attention'] else ''}  "
                f"{r['seconds']}s{note}")
        except Exception as e:                       # noqa: BLE001  one bad deal must not stop the run
            res = DealResult(job, dict(deal=job["deal"], month=f"{job['year']}-{job['month']:02d}",
                                       trustee=job["trustee"], file_status=job["file_status"],
                                       pdf=Path(job["pdf"]).name, error=f"{type(e).__name__}: {e}",
                                       needs_attention=True))
            log(f"{tag}: ERROR {type(e).__name__}: {e}")
            traceback.print_exc()
        results.append(res)
        if progress:
            progress(n, len(jobs))
    path = write_run_report(results, settings, started)
    log(f"run report: {path}")
    return path
