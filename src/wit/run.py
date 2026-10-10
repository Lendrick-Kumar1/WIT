"""Command line and orchestration.

  python run.py --period 2026-08                    all active deals (deal list + folder tree)
  python run.py --period 2026-08 --trustee "US Bank"
  python run.py some.pdf other.pdf                  ad-hoc files (trustee detected from the text)
  python run.py ... --fallback                      XLarge for crops whose checks fail (slow, optional)
  python run.py some.pdf --debug 3,5                per page: tests + balance candidates
  python run.py some.pdf --dump 3                   per page: every crop table + label/value pairs

Outputs:
  out/<period>/<deal>/Balance.xlsx, Performance.xlsx, Collateral.xlsx     schema columns only
  out/<period>/_run_report.xlsx    every check in one file:
      summary            one line per deal (counts, statuses, needs_attention)
      balance_sources    where each balance value came from, and its status
      performance_flags  test rows with _status other than ok
      collateral_gaps    collateral columns that stayed empty
      collateral_sums    every printed subtotal/total vs the sum of the rows read
      xlarge_fallback    crops re-read by XLarge (only with --fallback)
"""
import argparse
import re
import statistics as st
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pymupdf

from . import balance as B
from . import performance as P
from .collateral import collateral
from .config import load_trustees, pick_config
from .pages import select_pages
from .pdfpage import page_model, phrases, rows_of, to_num

PERF_COLS = ["deal name", "test", "report_month", "current", "trigger", "result", "original tests", "asset class"]
BAL_FIELDS = ["principal balance", "default balance", "proceeds balance", "ccc balance"]
BAL_COLS = ["deal name", "report_month", *BAL_FIELDS, "asset class"]


@dataclass
class DealResult:
    report: dict                                  # one line of the summary sheet
    perf: pd.DataFrame                            # Performance rows (+ _status, _page)
    bal: pd.DataFrame                             # Balance row
    bal_sources: pd.DataFrame                     # where each balance value came from
    coll: pd.DataFrame                            # Collateral rows (+ _pages)
    coll_checks: pd.DataFrame                     # subtotal / total checks
    empty_cols: list = field(default_factory=list)
    fallback: list = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# one deal
# ---------------------------------------------------------------------------------------------
def deal_info_from_text(doc, cfg):
    """Ad-hoc runs only: deal name + month read from the first pages (config `deal:` regexes)."""
    name = month = ""
    d = cfg.get("deal", {})
    for p in list(doc)[:5]:
        for r in rows_of(page_model(p)[0]):
            txt = r["text"]
            if not name and min(w["y0"] for w in r["ws"]) < p.rect.height * 0.25 \
                    and re.search(d["deal_name"], txt) and len(txt) < 70:
                name = re.split(d.get("deal_name_stop", r"$^"), txt)[0].strip()
            if not month:
                m = re.search(d["report_month"], txt, re.I)
                if m:
                    month = next(g for g in m.groups() if g)
    return name, month


def read_performance(doc, cfg, deal, month):
    rows = []
    for i in select_pages(doc, cfg, "performance"):
        for rec in P.performance(doc[i], cfg):
            rec.update({"deal name": deal, "report_month": month, "asset class": cfg.get("asset_class", "CLO")})
            rows.append(rec)
    perf = pd.DataFrame(rows)
    if len(perf):
        perf = perf.drop_duplicates(subset=["test", "current", "trigger"], keep="first")
    return perf.reindex(columns=PERF_COLS + ["_status", "_page"])


def read_balance(doc, cfg, deal, month):
    """-> (Balance row, {field: {value, status, how, label, page, n}})"""
    cands = []
    for i in select_pages(doc, cfg, "balance"):
        cands += B.candidates(doc[i], cfg)
    res = B.resolve(cands, cfg)
    for f, spec in B.fields(cfg)[1].items():
        res[f] = B.table_total(doc, cfg, spec)
    bal = pd.DataFrame([{"deal name": deal, "report_month": month, "asset class": cfg.get("asset_class", "CLO"),
                         **{f: res.get(f, {}).get("value") for f in BAL_FIELDS}}])[BAL_COLS]
    return bal, res


def process(pdf, defaults, trustees, meta=None, xl=None):
    """One report -> DealResult. meta (from the deal list): deal, trustee, period, report_type."""
    meta = meta or {}
    t0 = time.time()
    doc = pymupdf.open(pdf)
    layout, cfg = pick_config(doc, defaults, trustees, meta.get("trustee"))
    deal, month = (meta["deal"], meta["period"]) if meta.get("deal") else deal_info_from_text(doc, cfg)

    perf = read_performance(doc, cfg, deal, month)
    bal, res = read_balance(doc, cfg, deal, month)
    coll, coll_checks, fallback = collateral(doc, select_pages(doc, cfg, "collateral"), cfg, deal, month, xl)
    data_cols = [c for c in cfg["collateral"]["output_columns"] if c not in ("deal name", "report_month")]
    empty_cols = [c for c in data_cols if c not in coll or coll[c].isna().all()]

    n_check = int((perf["_status"] != "ok").sum()) if len(perf) else 0
    report = dict(
        deal=deal, period=month, trustee=meta.get("trustee", ""), layout=layout, pdf=Path(pdf).name,
        report_type=meta.get("report_type", ""), pages=len(doc),
        tests=len(perf), tests_to_check=n_check,
        **{f"bal:{f}": res.get(f, {}).get("status", "missing") for f in BAL_FIELDS},
        collateral_rows=len(coll), collateral_empty_columns=len(empty_cols),
        collateral_sums_ok=int((coll_checks["check"] == "ok").sum()),
        collateral_sums_to_check=int(coll_checks["check"].str.startswith("check").sum()),
        xlarge_crops=len(fallback),
        seconds=round(time.time() - t0, 1))
    report["needs_attention"] = bool(
        layout == "unknown" or not len(perf) or n_check
        or any(report[f"bal:{f}"] != "ok" for f in BAL_FIELDS) or not len(coll))
    bal_sources = pd.DataFrame([{"field": f, **r} for f, r in res.items()])
    return DealResult(report, perf, bal, bal_sources, coll, coll_checks, empty_cols, fallback)


# ---------------------------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------------------------
def write_outputs(results, out, period=""):
    """3 clean files per deal + one _run_report.xlsx with every check."""
    root = out / (period or "adhoc")
    root.mkdir(parents=True, exist_ok=True)
    summary, bal_checks, perf_flags, gaps, sums, xl_events = [], [], [], [], [], []
    for r in results:
        deal = r.report["deal"] or Path(r.report["pdf"]).stem
        d = root / re.sub(r'[<>:"/\\|?*]+', "_", deal).strip()
        d.mkdir(parents=True, exist_ok=True)
        r.bal.to_excel(d / "Balance.xlsx", index=False)
        r.perf.drop(columns=["_status", "_page"], errors="ignore").to_excel(d / "Performance.xlsx", index=False)
        r.coll.drop(columns=["_pages"], errors="ignore").to_excel(d / "Collateral.xlsx", index=False)
        summary.append(r.report)
        if len(r.bal_sources):
            bal_checks.append(r.bal_sources.assign(deal=deal))
        if len(r.perf):
            f = r.perf[r.perf["_status"] != "ok"]
            if len(f):
                perf_flags.append(f.assign(deal=deal)[["deal", "test", "current", "trigger", "result",
                                                       "_status", "_page"]])
        gaps += [{"deal": deal, "empty collateral column": c} for c in r.empty_cols]
        if len(r.coll_checks):
            sums.append(r.coll_checks.assign(deal=deal)[["deal", *r.coll_checks.columns]])
        xl_events += [{"deal": deal, **e} for e in r.fallback]
    with pd.ExcelWriter(root / "_run_report.xlsx") as xw:
        pd.DataFrame(summary).to_excel(xw, sheet_name="summary", index=False)
        (pd.concat(bal_checks) if bal_checks else pd.DataFrame()).to_excel(xw, sheet_name="balance_sources", index=False)
        (pd.concat(perf_flags) if perf_flags else pd.DataFrame()).to_excel(xw, sheet_name="performance_flags", index=False)
        pd.DataFrame(gaps).to_excel(xw, sheet_name="collateral_gaps", index=False)
        (pd.concat(sums) if sums else pd.DataFrame()).to_excel(xw, sheet_name="collateral_sums", index=False)
        pd.DataFrame(xl_events).to_excel(xw, sheet_name="xlarge_fallback", index=False)
    return root


# ---------------------------------------------------------------------------------------------
# looking at single pages
# ---------------------------------------------------------------------------------------------
def dump_pages(doc, cfg, layout, page_numbers):
    """Print every crop table (with _row/_check) and every 'label  value' pair on each page."""
    from .crops import page_tables
    from .totals import mark_totals
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    for n in page_numbers:
        page = doc[n - 1]
        print(f"\n================ page {n}  (layout {layout})")
        for k, (rect, raw) in enumerate(page_tables(page)):
            df = mark_totals(raw)
            print(f"--- crop {k + 1} {[round(v) for v in rect]}: {df.shape[0]} rows x {df.shape[1]} cols")
            print(df.head(8).to_string(max_colwidth=28))
        words = page_model(page)[0]
        lh = st.median(w["y1"] - w["y0"] for w in words) if words else 8
        kv = []
        for r in rows_of(words):
            ps = phrases(r["ws"], lh * 0.9)
            if len(ps) == 2 and to_num(ps[0]["t"]) is None and not any(c.isdigit() for c in ps[0]["t"][:1]):
                kv.append((ps[0]["t"], ps[1]["t"]))
        if kv:
            print("--- label : value pairs")
            for k, v in kv:
                print(f"   {k[:55]:55s} : {v}")


def debug_pages(doc, cfg, layout, page_numbers):
    """Print the test rows and balance candidates found on each page."""
    print("layout config:", layout)
    for n in page_numbers:
        print(f"--- page {n}")
        for r in P.performance(doc[n - 1], cfg):
            print(f"  {r['original tests'][:22]:22s} | {r['test'][:45]:45s} | {r['current']} | "
                  f"{r['trigger']} | {r['result']} | {r.get('_status')}")
        for c in B.candidates(doc[n - 1], cfg):
            print(f"  balance candidate: {c}")


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="*")
    ap.add_argument("--period", help="YYYY-MM: use deal list + folder tree (config/sources.yaml)")
    ap.add_argument("--trustee", help="only deals whose trustee contains this text")
    ap.add_argument("--out", default="out")
    ap.add_argument("--debug", help="comma-separated page numbers: print per-page results")
    ap.add_argument("--dump", help="comma-separated page numbers: print every table + label/value pair read")
    ap.add_argument("--fallback", action="store_true",
                    help="XLarge on crops whose checks fail (needs docling + cached models)")
    ap.add_argument("--artifacts", help="Docling models folder (default ~/.cache/docling/models)")
    a = ap.parse_args(argv)
    defaults, trustees = load_trustees()

    if a.dump or a.debug:
        doc = pymupdf.open(a.pdfs[0])
        layout, cfg = pick_config(doc, defaults, trustees, a.trustee)
        pages = [int(x) for x in (a.dump or a.debug).split(",")]
        (dump_pages if a.dump else debug_pages)(doc, cfg, layout, pages)
        return

    xl = None
    if a.fallback:
        from .fallback import XLarge
        xl = XLarge(a.artifacts)
    results = []
    if a.period:
        from .sources import plan
        for job in plan(a.period, a.trustee):
            if not job["pdf"]:
                print(f"MISSING  {job['deal']}  ({job['trustee']}): no report for {a.period}")
                continue
            r = process(job["pdf"], defaults, trustees, job, xl)
            print({k: r.report[k] for k in ("deal", "layout", "report_type", "tests", "collateral_rows",
                                            "needs_attention", "seconds")})
            results.append(r)
    else:
        for pdf in a.pdfs:
            r = process(pdf, defaults, trustees, None, xl)
            print({k: r.report[k] for k in ("pdf", "deal", "layout", "tests", "collateral_rows",
                                            "needs_attention", "seconds")})
            results.append(r)
    if results:
        root = write_outputs(results, Path(a.out), a.period or "")
        if xl is not None:
            print(f"XLarge fallback: {xl.calls} crops, {xl.seconds:.0f} s")
        print(f"\noutput: {root.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
