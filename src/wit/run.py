"""CLI.

  python run.py --period 2026-08                    # all active deals (deal list + folder tree)
  python run.py --period 2026-08 --trustee "US Bank"
  python run.py some.pdf other.pdf                  # ad-hoc files (trustee detected from text)
  python run.py reports/us_1.pdf --debug 3,5        # per-page debug

Outputs:  out/<period>/<Deal>/Balance.xlsx, Performance.xlsx, Collateral.xlsx   (clean, schema only)
          out/<period>/_run_report.xlsx   (all checks in one file: summary, balance_sources,
                                           performance_flags, collateral_gaps)
"""
import argparse
import re
import sys
import time
from pathlib import Path

import pandas as pd
import pymupdf

from . import balance as B
from . import performance as P
from .collateral import collateral
from .config import load_trustees, pick_config
from .pages import select_pages
from .pdfpage import page_model, rows_of

PERF_COLS = ["deal name", "test", "report_month", "current", "trigger", "result", "original tests", "asset class"]
BAL_FIELDS = ["principal balance", "default balance", "proceeds balance", "ccc balance"]
BAL_COLS = ["deal name", "report_month", *BAL_FIELDS, "asset class"]


def text_deal_info(doc, cfg):
    """Fallback only (ad-hoc PDFs): deal name + month from the PDF text."""
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


def process(pdf, defaults, trustees, meta=None):
    meta = meta or {}
    t0 = time.time()
    doc = pymupdf.open(pdf)
    layout, cfg = pick_config(doc, defaults, trustees, meta.get("trustee"))
    P.configure(cfg)
    B.configure(cfg)
    if meta.get("deal"):
        deal, month = meta["deal"], meta["period"]
    else:
        deal, month = text_deal_info(doc, cfg)
    ac = cfg.get("asset_class", "CLO")

    # Performance
    perf = []
    for i in select_pages(doc, cfg, "performance"):
        for rec in P.performance(doc[i]):
            rec.update({"deal name": deal, "report_month": month, "asset class": ac})
            perf.append(rec)
    perf = pd.DataFrame(perf)
    if len(perf):
        perf = perf.drop_duplicates(subset=["test", "current", "trigger"], keep="first")
    perf = perf.reindex(columns=PERF_COLS + ["_status", "_page"])

    # Balance
    cands = []
    for i in select_pages(doc, cfg, "balance"):
        cands += B.candidates(doc[i])
    res = B.resolve(cands)
    bal = pd.DataFrame([{"deal name": deal, "report_month": month, "asset class": ac,
                         **{f: res.get(f, {}).get("value") for f in BAL_FIELDS}}])[BAL_COLS]
    bal_src = pd.DataFrame([{"field": f, **r} for f, r in res.items()])

    # Collateral
    coll = collateral(doc, select_pages(doc, cfg, "collateral"), cfg, deal, month)
    data_cols = [c for c in cfg["collateral"]["output_columns"] if c not in ("deal name", "report_month")]
    empty_cols = [c for c in data_cols if c not in coll or coll[c].isna().all()]

    n_check = int((perf["_status"] != "ok").sum()) if len(perf) else 0
    report = dict(
        deal=deal, period=month, trustee=meta.get("trustee", ""), layout=layout, pdf=Path(pdf).name,
        report_type=meta.get("report_type", ""), pages=len(doc),
        tests=len(perf), tests_to_check=n_check,
        **{f"bal:{f}": res.get(f, {}).get("status", "missing") for f in BAL_FIELDS},
        collateral_rows=len(coll), collateral_empty_columns=len(empty_cols),
        seconds=round(time.time() - t0, 1))
    report["needs_attention"] = bool(
        layout == "unknown" or not len(perf) or n_check
        or any(report[f"bal:{f}"] != "ok" for f in BAL_FIELDS) or not len(coll))
    return report, perf, bal, bal_src, coll, empty_cols


def write_outputs(results, out, period=""):
    """out/<period>/<Deal>/Balance.xlsx, Performance.xlsx, Collateral.xlsx  (clean schema only)
       out/<period>/_run_report.xlsx  (ONE file with all checks: summary + details per deal)"""
    root = out / (period or "adhoc")
    root.mkdir(parents=True, exist_ok=True)
    summary, bal_checks, perf_flags, gaps = [], [], [], []
    for report, perf, bal, bal_src, coll, empty_cols in results:
        deal = report["deal"] or Path(report["pdf"]).stem
        d = root / re.sub(r'[<>:"/\\|?*]+', "_", deal).strip()
        d.mkdir(parents=True, exist_ok=True)
        bal.to_excel(d / "Balance.xlsx", index=False)
        perf.drop(columns=["_status", "_page"], errors="ignore").to_excel(d / "Performance.xlsx", index=False)
        coll.drop(columns=["_pages"], errors="ignore").to_excel(d / "Collateral.xlsx", index=False)
        summary.append(report)
        if len(bal_src):
            bal_checks.append(bal_src.assign(deal=deal))
        if len(perf):
            f = perf[perf["_status"] != "ok"]
            if len(f):
                perf_flags.append(f.assign(deal=deal)[["deal", "test", "current", "trigger", "result",
                                                       "_status", "_page"]])
        gaps += [{"deal": deal, "empty collateral column": c} for c in empty_cols]
    with pd.ExcelWriter(root / "_run_report.xlsx") as xw:
        pd.DataFrame(summary).to_excel(xw, sheet_name="summary", index=False)
        (pd.concat(bal_checks) if bal_checks else pd.DataFrame()).to_excel(xw, sheet_name="balance_sources", index=False)
        (pd.concat(perf_flags) if perf_flags else pd.DataFrame()).to_excel(xw, sheet_name="performance_flags", index=False)
        pd.DataFrame(gaps).to_excel(xw, sheet_name="collateral_gaps", index=False)
    return root


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="*")
    ap.add_argument("--period", help="YYYY-MM: use deal list + folder tree (config/sources.yaml)")
    ap.add_argument("--trustee", help="only deals whose trustee contains this text")
    ap.add_argument("--out", default="out")
    ap.add_argument("--debug", help="comma-separated page numbers: print per-page results")
    a = ap.parse_args(argv)
    defaults, trustees = load_trustees()

    if a.debug:
        doc = pymupdf.open(a.pdfs[0])
        layout, cfg = pick_config(doc, defaults, trustees, a.trustee)
        P.configure(cfg)
        B.configure(cfg)
        print("layout config:", layout)
        for n in [int(x) for x in a.debug.split(",")]:
            print(f"--- page {n}")
            for r in P.performance(doc[n - 1]):
                print(f"  {r['original tests'][:22]:22s} | {r['test'][:45]:45s} | {r['current']} | "
                      f"{r['trigger']} | {r['result']} | {r.get('_status')}")
            for c in B.candidates(doc[n - 1]):
                print(f"  balance candidate: {c}")
        return

    results = []
    if a.period:
        from .sources import plan
        for job in plan(a.period, a.trustee):
            if not job["pdf"]:
                print(f"MISSING  {job['deal']}  ({job['trustee']}): no report for {a.period}")
                continue
            r = process(job["pdf"], defaults, trustees, job)
            print({k: r[0][k] for k in ("deal", "layout", "report_type", "tests", "collateral_rows",
                                         "needs_attention", "seconds")})
            results.append(r)
    else:
        for pdf in a.pdfs:
            r = process(pdf, defaults, trustees)
            print({k: r[0][k] for k in ("pdf", "deal", "layout", "tests", "collateral_rows",
                                         "needs_attention", "seconds")})
            results.append(r)
    if results:
        root = write_outputs(results, Path(a.out), a.period or "")
        print(f"\noutput: {root.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
