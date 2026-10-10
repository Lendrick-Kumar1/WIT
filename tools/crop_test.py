"""Look at how a PDF is cut into crops and read, page by page (diagnostic tool).

For every page:
  - the crops (crops.find_crops) as PNG + one-page PDF
  - each crop read by PyMuPDF (one table per crop, subtotals/totals checked)
  - optional: XLarge on the full page and on every crop, for comparison
And per PDF: tables that run over a page break, joined, with every subtotal/total checked.

  poetry run python tools/crop_test.py probs/*.pdf --no-docling      # PyMuPDF only (fast)
  poetry run python tools/crop_test.py some.pdf --pages 3,4          # + XLarge (slow, CPU)
  poetry run python tools/crop_test.py some.pdf --no-full            # XLarge on crops only

Output: out/crop_test/<pdf>/p<N>/  page.png, crop<k>.png, crop<k>.pdf, tables.xlsx
                                   (sheets full_t*, c<k>_docling_t*, c<k>_pymupdf_t*)
        out/crop_test/summary.xlsx sheet summary (one row per page/unit/engine),
                                   sheet stitched_checks (tables over page breaks)
"""
import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wit.crops import crop_table, find_crops, page_tables, preview_png, write_crop_pdf  # noqa: E402
from wit.pdfpage import page_model                                                      # noqa: E402
from wit.totals import mark_totals, stitch_pages                                        # noqa: E402


def check_flags(df):
    """'' if nothing to check, else e.g. '3 ok, 1 check'."""
    vals = [v for v in df["_check"] if v] if df is not None and "_check" in df else []
    if not vals:
        return ""
    ok = sum(v == "ok" for v in vals)
    return f"{ok} ok" + (f", {len(vals) - ok} check" if len(vals) > ok else "")


def shapes(dfs):
    return " ".join(f"{x.shape[0]}x{x.shape[1]}" for x in dfs)


def ram_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6)
    except Exception:
        return None


def stitched_checks(doc, pdf, pages):
    out = []
    parts = [(p - 1, raw.assign(_page=p)) for p in pages for _, raw in page_tables(doc[p - 1])]
    for pg, df in stitch_pages(parts):
        marked = mark_totals(df)
        if len(pg) < 2 or "_row" not in marked:
            continue
        for _, r in marked[marked["_row"] != "detail"].iterrows():
            out.append(dict(pdf=Path(pdf).name, pages=f"{pg[0] + 1}-{pg[-1] + 1}", row=r["_row"],
                            label=next((v for v in r if str(v).strip()), "")[:50],
                            check=r["_check"] or "not checked"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--pages", help="comma-separated page numbers (default: all)")
    ap.add_argument("--no-docling", action="store_true", help="PyMuPDF only (no XLarge)")
    ap.add_argument("--no-full", action="store_true", help="XLarge on crops only, not on full pages")
    ap.add_argument("--artifacts", help="Docling models folder (default ~/.cache/docling/models)")
    ap.add_argument("--out", default="out/crop_test")
    a = ap.parse_args()

    xl = None
    if not a.no_docling:
        from wit.fallback import XLarge
        print("XLarge (egret-xlarge + TableFormer ACCURATE, OCR off) is loaded on first use ...")
        xl = XLarge(a.artifacts)

    out_root = Path(a.out)
    rows, stitched = [], []
    for pdf in a.pdfs:
        doc = pymupdf.open(pdf)
        name = Path(pdf).name
        pages = [int(x) for x in a.pages.split(",")] if a.pages else range(1, len(doc) + 1)
        stitched += stitched_checks(doc, pdf, pages)
        for p in pages:
            d = out_root / Path(pdf).stem / f"p{p}"
            d.mkdir(parents=True, exist_ok=True)
            page = doc[p - 1]
            page.get_pixmap(dpi=90).save(d / "page.png")
            sheets = {}
            if xl and not a.no_full:
                t0 = time.time()
                dfs = xl.pdf_tables(pdf, p)
                sheets.update({f"full_t{i}": df for i, df in enumerate(dfs, 1)})
                rows.append(dict(pdf=name, page=p, unit="FULL PAGE", engine="docling", tables=len(dfs),
                                 shapes=shapes(dfs), seconds=round(time.time() - t0, 1), ram_mb=ram_mb()))
            model = page_model(page)
            for k, rect in enumerate(find_crops(page, model), 1):
                cpdf = d / f"crop{k}.pdf"
                write_crop_pdf(doc, p - 1, rect, cpdf)
                preview_png(cpdf, d / f"crop{k}.png")
                t0 = time.time()
                df = crop_table(model[0], rect)
                df = mark_totals(df) if df is not None else None
                dfs = [df] if df is not None else []
                if df is not None:
                    sheets[f"c{k}_pymupdf_t1"] = df
                rows.append(dict(pdf=name, page=p, unit=f"crop{k}", engine="pymupdf", tables=len(dfs),
                                 shapes=shapes(dfs), seconds=round(time.time() - t0, 2), ram_mb=None,
                                 checks=check_flags(df), crop_box=[round(v) for v in rect]))
                if xl:
                    t0 = time.time()
                    dfs = xl.pdf_tables(cpdf)
                    sheets.update({f"c{k}_docling_t{i}": x for i, x in enumerate(dfs, 1)})
                    rows.append(dict(pdf=name, page=p, unit=f"crop{k}", engine="docling", tables=len(dfs),
                                     shapes=shapes(dfs), seconds=round(time.time() - t0, 1), ram_mb=ram_mb(),
                                     crop_box=[round(v) for v in rect]))
            if sheets:
                with pd.ExcelWriter(d / "tables.xlsx") as xw:
                    for sheet, df in sheets.items():
                        df.to_excel(xw, sheet_name=sheet[:31], index=False)
            print(f"{name} p{p}: {sum(1 for r in rows if r['page'] == p and r['pdf'] == name)} results")
    out_root.mkdir(parents=True, exist_ok=True)
    summ = pd.DataFrame(rows)
    summ["correct? (fill in)"] = ""
    with pd.ExcelWriter(out_root / "summary.xlsx") as xw:
        summ.to_excel(xw, sheet_name="summary", index=False)
        pd.DataFrame(stitched).to_excel(xw, sheet_name="stitched_checks", index=False)
    if stitched:
        s = pd.DataFrame(stitched)
        print("\nacross pages:", (s["check"] == "ok").sum(), "ok,",
              s["check"].str.startswith("check").sum(), "to check  (sheet stitched_checks)")
    print(f"\nsummary: {(out_root / 'summary.xlsx').resolve()}")


if __name__ == "__main__":
    main()
