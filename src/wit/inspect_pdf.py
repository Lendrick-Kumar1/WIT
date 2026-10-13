"""Look at what the reader sees on single pages of one PDF (for diagnosing a problem).

  python app.py inspect <pdf> --pages 12,13 [--trustee "BNY"]

Per page: the test rows performance finds, the balance candidates, every crop read as a table
(with its subtotal/total checks), and every 'label  value' pair on the page.
"""
import statistics as st

import pandas as pd
import pymupdf

from . import balance as B
from . import performance as P
from .config import load_trustees, pick_config
from .crops import page_tables
from .pdfpage import page_model, phrases, rows_of, to_num
from .totals import mark_totals


def inspect(pdf, pages, trustee=None):
    doc = pymupdf.open(pdf)
    defaults, trustees = load_trustees()
    layout, cfg = pick_config(doc, defaults, trustees, trustee)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"layout config: {layout}")
    for n in pages:
        page = doc[n - 1]
        print(f"\n================ page {n}")
        tests = P.performance(page, cfg)
        if tests:
            print("--- test rows (standard name | printed name | current | trigger | result | status)")
            for r in tests:
                print(f"   {r['test'][:30]:30s} | {r['original tests'][:40]:40s} | {r['current']} | "
                      f"{r['trigger']} | {r['result']} | {r['_status']}")
        for c in B.candidates(page, cfg):
            print(f"--- balance candidate: {c}")
        for k, (rect, raw) in enumerate(page_tables(page)):
            df = mark_totals(raw)
            print(f"--- table {k + 1} {[round(v) for v in rect]}: {df.shape[0]} rows x {df.shape[1]} cols")
            print(df.head(8).to_string(max_colwidth=28))
        words = page_model(page)[0]
        lh = st.median(w["y1"] - w["y0"] for w in words) if words else 8
        kv = [(ps[0]["t"], ps[1]["t"]) for r in rows_of(words)
              for ps in [phrases(r["ws"], lh * 0.9)]
              if len(ps) == 2 and to_num(ps[0]["t"]) is None and not ps[0]["t"][:1].isdigit()]
        if kv:
            print("--- label : value pairs")
            for k, v in kv:
                print(f"   {k[:55]:55s} : {v}")
