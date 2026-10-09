"""Command line: extract | docling | explain | bench | eval | doctor | review-export.

    poetry run python -m trustee_extract.cli extract reports/bny_3.pdf --out out/
    poetry run python -m trustee_extract.cli docling reports/citi_1.pdf:3-5 reports/bny_1.pdf:2-3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def parse_pages(spec: str) -> list[int]:
    """'1,4,7-9' -> [1, 4, 7, 8, 9] (1-based)."""
    pages: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return sorted(pages)


def cmd_docling(args) -> int:
    """Docling (egret + TableFormer ACCURATE, OCR off) on selected pages; models load once.

    Writes out/<stem>/docling/: p<NNN>_t<K>.csv, docling.xlsx (one sheet per table), docling.json.
    """
    import pandas as pd

    from trustee_extract.core.config import sha256_file
    from trustee_extract.detect.docling_layout import build_converter, layout_boxes

    t0 = time.perf_counter()
    converter = build_converter()
    load_s = round(time.perf_counter() - t0, 2)

    for target in args.targets:
        pdf_s, _, spec = target.rpartition(":")
        pdf = Path(pdf_s)
        out = Path(args.out) / pdf.stem / "docling"
        out.mkdir(parents=True, exist_ok=True)
        report = {"pdf": str(pdf), "sha256": sha256_file(pdf), "model_load_s": load_s, "pages": []}
        sheets = {}
        for page in parse_pages(spec):
            t = time.perf_counter()
            res = converter.convert(pdf, page_range=(page, page))
            elapsed = time.perf_counter() - t
            doc = res.document
            tables = []
            for i, table in enumerate(doc.tables, 1):
                df = table.export_to_dataframe(doc=doc)
                name = f"p{page:03d}_t{i}"
                df.to_csv(out / f"{name}.csv", index=False)
                sheets[name] = df
                prov = table.prov[0] if table.prov else None
                tables.append({
                    "name": name,
                    "shape": list(df.shape),
                    "bbox": prov.bbox.to_top_left_origin(doc.pages[prov.page_no].size.height).as_tuple() if prov else None,
                })
            report["pages"].append({
                "page": page,
                "status": res.status.value,
                "seconds": round(elapsed, 2),
                "layout_boxes": len(layout_boxes(res)),
                "tables": tables,
            })
            print(f"{pdf.name} p{page}: {res.status.value}, {len(tables)} tables, {elapsed:.1f}s", flush=True)
        if sheets:
            with pd.ExcelWriter(out / "docling.xlsx") as xw:
                for name, df in sheets.items():
                    df.to_excel(xw, sheet_name=name, index=False)
        (out / "docling.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"model load {load_s}s")
    return 0


def cmd_review_export(args) -> int:
    from trustee_extract.review.labelstudio_export import export

    n = export([Path(p) for p in args.pdfs], Path(args.out), pages=args.pages,
               golden_manifest=Path(args.golden) if args.golden else None, url_prefix=args.url_prefix)
    print(f"exported {n} page tasks to {args.out}")
    return 0


def cmd_doctor(args) -> int:
    from trustee_extract.doctor import run

    return run(args.measure, args.pdf, args.page)


def not_yet(task: str):
    def run(args) -> int:
        print(f"'{args.cmd}' is not implemented yet ({task}).", file=sys.stderr)
        return 2
    return run


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="trustee_extract")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("docling", help="Docling on selected pages, e.g. reports/citi_1.pdf:3-5")
    p.add_argument("targets", nargs="+", help="<pdf>:<pages>, pages 1-based like 1,4,7-9")
    p.add_argument("--out", default="out")
    p.set_defaults(func=cmd_docling)

    p = sub.add_parser("explain", help="stage-by-stage PNG for one page")
    p.add_argument("pdf"); p.add_argument("page", type=int)
    p.set_defaults(func=not_yet("Task 2"))

    p = sub.add_parser("bench", help="time pipelines over a folder")
    p.add_argument("folder"); p.add_argument("--pages-from", default="capture")
    p.set_defaults(func=not_yet("Task 0"))

    p = sub.add_parser("eval", help="score against the golden set")
    p.add_argument("golden", nargs="?", default="data/golden")
    p.set_defaults(func=not_yet("Task 1"))

    p = sub.add_parser("doctor", help="check this machine; recommend worker count")
    p.add_argument("--measure", action="store_true", help="convert one real page to measure peak RAM per worker")
    p.add_argument("--pdf", type=Path, default=None, help="PDF for --measure (default: first in reports dir)")
    p.add_argument("--page", type=int, default=None, help="page for --measure (default: densest of first 10)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("review-export", help="Label Studio tasks with egret pre-annotations")
    p.add_argument("pdfs", nargs="+")
    p.add_argument("--out", default="out/labelstudio")
    p.add_argument("--pages", default=None, help="1-based page spec applied to every PDF (default: all)")
    p.add_argument("--golden", default=None, help="manifest of golden docs to exclude (default: config paths.golden_manifest)")
    p.add_argument("--url-prefix", default="/data/local-files/?d=labelstudio/images")
    p.set_defaults(func=cmd_review_export)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
