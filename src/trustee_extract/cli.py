"""Command line: extract | explain | bench | eval | doctor | review-export.

    poetry run python -m trustee_extract.cli extract reports/bny_1.pdf --pages 1,4 --out out/
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


def cmd_extract(args) -> int:
    # Current state: Docling primary path (egret + TableFormer ACCURATE, OCR off) per page.
    # Splitter, mapping and validation arrive in later tasks.
    from trustee_extract.core.config import sha256_file
    from trustee_extract.detect.docling_layout import build_converter, layout_boxes

    pdf = Path(args.pdf)
    out = Path(args.out) / pdf.stem
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    converter = build_converter()
    report = {"pdf": str(pdf), "sha256": sha256_file(pdf), "model_load_s": None, "pages": []}
    report["model_load_s"] = round(time.perf_counter() - t0, 2)

    for page in parse_pages(args.pages):
        t = time.perf_counter()
        res = converter.convert(pdf, page_range=(page, page))
        elapsed = time.perf_counter() - t
        doc = res.document
        tables = []
        for i, table in enumerate(doc.tables, 1):
            df = table.export_to_dataframe(doc=doc)
            csv = out / f"p{page:03d}_t{i}.csv"
            df.to_csv(csv, index=False)
            prov = table.prov[0] if table.prov else None
            tables.append({
                "csv": csv.name,
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
        print(f"page {page}: {res.status.value}, {len(tables)} tables, {elapsed:.1f}s")

    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"model load {report['model_load_s']}s; wrote {out / 'report.json'}")
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

    p = sub.add_parser("extract", help="extract tables from one PDF")
    p.add_argument("pdf")
    p.add_argument("--pages", required=True, help="1-based, e.g. 1,4,7-9")
    p.add_argument("--out", default="out")
    p.set_defaults(func=cmd_extract)

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
