"""Experiment: does egret-XLarge + TableFormer get it right when it only sees ONE table?

For every page of the given PDFs:
  1. full page  -> Docling (egret-xlarge layout, TableFormer ACCURATE, OCR off)
  2. PyMuPDF cuts the page into crops (section bars + full-height vertical rules), deterministic
  3. each crop  -> Docling (same settings)          and  -> our PyMuPDF table engine
Everything is written next to each other so you can compare by eye.

  poetry run python tools/crop_test.py probs/*.pdf
  poetry run python tools/crop_test.py probs/dashboard_bands.pdf --pages 1,2
  poetry run python tools/crop_test.py probs/*.pdf --no-docling        # only crops + PyMuPDF

Output: out/crop_test/<pdf>/p<N>/
          page.png                   the full page
          crop<k>.png / crop<k>.pdf  each crop (the PDF is what Docling receives)
          tables.xlsx                one sheet per table: full_t1.., c1_docling_t1.., c1_pymupdf_t1..
        out/crop_test/summary.xlsx   one row per (page, unit, engine): tables found, shapes, seconds
"""
import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wit import geometry as G                          # noqa: E402
from wit.crops import find_crops, preview_png, write_crop_pdf  # noqa: E402
from wit.croptable import read_crop                    # noqa: E402
from wit.pdfpage import page_model                     # noqa: E402


# ----------------------------------------------------------------------------- Docling (XLarge)
def make_converter(artifacts):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_EGRET_XLARGE
    from docling.datamodel.pipeline_options import (LayoutOptions, PdfPipelineOptions,
                                                    TableFormerMode, TableStructureOptions)
    from docling.document_converter import DocumentConverter, PdfFormatOption

    opts = PdfPipelineOptions(artifacts_path=artifacts, do_ocr=False, do_table_structure=True)
    opts.table_structure_options = TableStructureOptions(mode=TableFormerMode.ACCURATE,
                                                         do_cell_matching=True)
    opts.layout_options = LayoutOptions(model_spec=DOCLING_LAYOUT_EGRET_XLARGE)
    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def docling_tables(conv, pdf, page_no=None):
    t0 = time.time()
    kw = {"page_range": (page_no, page_no)} if page_no else {}
    res = conv.convert(str(pdf), **kw)
    dfs = []
    for t in res.document.tables:
        try:
            dfs.append(t.export_to_dataframe(doc=res.document))
        except TypeError:
            dfs.append(t.export_to_dataframe())
    return dfs, time.time() - t0


# ----------------------------------------------------------------------------- PyMuPDF engine
def pymupdf_tables(page, engine="crop"):
    """engine='crop' (default): the whole crop is ONE table (croptable.read_crop: grouped rows,
    subtotals, checks). engine='old': the previous behaviour (re-segment the crop with xy_cut)."""
    t0 = time.time()
    if engine == "crop":
        df = read_crop(page)
        return ([df] if df is not None else []), time.time() - t0
    words, H, V = page_model(page)
    dfs = []
    if len(words) >= 3:
        for blk in G.attach_headers(G.xy_cut(words, H, V)):
            r = G.Region(page=page.number + 1, words=blk, bbox=G.bbox(blk))
            G.build_table(r)
            if r.df is not None and len(r.df) and r.df.shape[1] >= 2:
                dfs.append(r.df)
    return dfs, time.time() - t0


def check_flags(dfs):
    """'' if nothing to check, else e.g. '3 ok, 1 check' (from croptable's _check column)."""
    vals = [v for df in dfs if "_check" in df for v in df["_check"] if v]
    if not vals:
        return ""
    ok = sum(v == "ok" for v in vals)
    return f"{ok} ok" + (f", {len(vals) - ok} check" if len(vals) > ok else "")


def peak_ram_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdfs", nargs="+")
    ap.add_argument("--pages", help="comma-separated page numbers (default: all)")
    ap.add_argument("--no-docling", action="store_true", help="skip Docling (crops + PyMuPDF only)")
    ap.add_argument("--artifacts", default=os.environ.get(
        "DOCLING_ARTIFACTS_PATH", str(Path.home() / ".cache" / "docling" / "models")))
    ap.add_argument("--no-full", action="store_true", help="skip Docling on FULL pages (crops only)")
    ap.add_argument("--engine", choices=["crop", "old"], default="crop",
                    help="PyMuPDF: crop = whole crop is one table (default); old = re-segment it")
    ap.add_argument("--out", default="out/crop_test")
    a = ap.parse_args()

    conv = None
    if not a.no_docling:
        print("loading Docling (egret-xlarge + TableFormer ACCURATE, OCR off) ...")
        conv = make_converter(a.artifacts)

    out_root = Path(a.out)
    rows = []
    for pdf in a.pdfs:
        doc = pymupdf.open(pdf)
        pages = [int(x) for x in a.pages.split(",")] if a.pages else range(1, len(doc) + 1)
        for p in pages:
            d = out_root / Path(pdf).stem / f"p{p}"
            d.mkdir(parents=True, exist_ok=True)
            doc[p - 1].get_pixmap(dpi=90).save(d / "page.png")
            sheets = {}

            if conv and not a.no_full:
                dfs, sec = docling_tables(conv, pdf, p)
                for i, df in enumerate(dfs, 1):
                    sheets[f"full_t{i}"] = df
                rows.append(dict(pdf=Path(pdf).name, page=p, unit="FULL PAGE", engine="docling",
                                 tables=len(dfs), shapes=" ".join(f"{x.shape[0]}x{x.shape[1]}" for x in dfs),
                                 seconds=round(sec, 1), ram_mb=peak_ram_mb()))

            for k, rect in enumerate(find_crops(doc[p - 1]), 1):
                cpdf = d / f"crop{k}.pdf"
                write_crop_pdf(doc, p - 1, rect, cpdf)
                preview_png(cpdf, d / f"crop{k}.png", dpi=110)
                crop_page = pymupdf.open(cpdf)[0]
                dfs, sec = pymupdf_tables(crop_page, a.engine)
                for i, df in enumerate(dfs, 1):
                    sheets[f"c{k}_pymupdf_t{i}"] = df
                rows.append(dict(pdf=Path(pdf).name, page=p, unit=f"crop{k}", engine="pymupdf",
                                 tables=len(dfs), shapes=" ".join(f"{x.shape[0]}x{x.shape[1]}" for x in dfs),
                                 seconds=round(sec, 2), ram_mb=None, checks=check_flags(dfs),
                                 crop_box=[round(v) for v in rect]))
                if conv:
                    dfs, sec = docling_tables(conv, cpdf)
                    for i, df in enumerate(dfs, 1):
                        sheets[f"c{k}_docling_t{i}"] = df
                    rows.append(dict(pdf=Path(pdf).name, page=p, unit=f"crop{k}", engine="docling",
                                     tables=len(dfs), shapes=" ".join(f"{x.shape[0]}x{x.shape[1]}" for x in dfs),
                                     seconds=round(sec, 1), ram_mb=peak_ram_mb(),
                                     crop_box=[round(v) for v in rect]))
            if sheets:
                with pd.ExcelWriter(d / "tables.xlsx") as xw:
                    for name, df in sheets.items():
                        df.to_excel(xw, sheet_name=name[:31], index=False)
            print(f"{Path(pdf).name} p{p}: {sum(1 for r in rows if r['page'] == p and r['pdf'] == Path(pdf).name)} results")
    out_root.mkdir(parents=True, exist_ok=True)
    summ = pd.DataFrame(rows)
    summ["correct? (fill in)"] = ""
    summ.to_excel(out_root / "summary.xlsx", index=False)
    print(f"\nsummary: {(out_root / 'summary.xlsx').resolve()}")


if __name__ == "__main__":
    main()
