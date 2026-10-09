"""Export page images + egret boxes as Label Studio tasks with pre-annotations.

Annotators correct boxes instead of drawing them. Classes: table, table_title,
section_header, key_value_block. Rule: every adjacent table gets its own `table` box.

Documents listed in the golden manifest are skipped (matched by sha256), so the golden set
never ends up in training data.

Output:
    <out>/images/<stem>_p<NNN>.png
    <out>/tasks.json          import into Label Studio
    <out>/label_config.xml    paste into the project's Labeling Interface
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import yaml

from trustee_extract.core.config import load_config, sha256_file

LABEL_CONFIG = """<View>
  <Header value="One box per table. Adjacent tables (side by side or stacked without a gap) get separate boxes. table_title = the title line directly above a table."/>
  <Image name="image" value="$image" zoom="true" zoomControl="true"/>
  <RectangleLabels name="label" toName="image">
{labels}
  </RectangleLabels>
</View>
"""
COLORS = {"table": "#1f77b4", "table_title": "#ff7f0e", "section_header": "#2ca02c", "key_value_block": "#d62728"}


def golden_hashes(manifest: Path) -> set[str]:
    if not manifest.exists():
        return set()
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    return {d["sha256"] for d in data.get("documents", []) if d.get("sha256")}


def to_result(box, page_w: float, page_h: float, img_w: int, img_h: int, idx: int) -> dict:
    x0, y0, x1, y1 = box.bbox
    return {
        "id": f"r{idx}",
        "from_name": "label",
        "to_name": "image",
        "type": "rectanglelabels",
        "original_width": img_w,
        "original_height": img_h,
        "image_rotation": 0,
        "score": box.score,
        "value": {
            "x": 100 * x0 / page_w,
            "y": 100 * y0 / page_h,
            "width": 100 * (x1 - x0) / page_w,
            "height": 100 * (y1 - y0) / page_h,
            "rotation": 0,
            "rectanglelabels": [box.label],
        },
    }


def export(pdfs: list[Path], out: Path, pages: str | None = None,
           golden_manifest: Path = Path("data/golden/manifest.yaml"),
           url_prefix: str = "/data/local-files/?d=labelstudio/images", detector=None) -> int:
    from trustee_extract.cli import parse_pages
    from trustee_extract.detect.docling_layout import EgretDetector

    cfg = load_config()
    dpi = cfg["labelstudio"]["render_dpi"]
    classes = cfg["labelstudio"]["classes"]
    excluded = golden_hashes(golden_manifest)
    detector = detector or EgretDetector(cfg)

    (out / "images").mkdir(parents=True, exist_ok=True)
    tasks = []
    for pdf in pdfs:
        sha = sha256_file(pdf)
        if sha in excluded:
            print(f"skip {pdf.name}: in golden set")
            continue
        with pymupdf.open(pdf) as doc:
            page_list = parse_pages(pages) if pages else range(1, doc.page_count + 1)
            for pno in page_list:
                page = doc[pno - 1]
                img = out / "images" / f"{pdf.stem}_p{pno:03d}.png"
                pix = page.get_pixmap(dpi=dpi)
                pix.save(img)
                boxes = [b for b in detector.detect_pages(pdf, pno, pno) if b.label in classes]
                results = [to_result(b, page.rect.width, page.rect.height, pix.width, pix.height, i)
                           for i, b in enumerate(boxes)]
                tasks.append({
                    "data": {"image": f"{url_prefix}/{img.name}", "pdf": pdf.name, "sha256": sha, "page": pno},
                    "predictions": [{
                        "model_version": cfg["docling"]["layout_preset"],
                        "score": min((b.score for b in boxes), default=0.0),
                        "result": results,
                    }],
                })

    (out / "tasks.json").write_text(json.dumps(tasks, indent=1), encoding="utf-8")
    labels = "\n".join(f'    <Label value="{c}" background="{COLORS.get(c, "#888888")}"/>' for c in classes)
    (out / "label_config.xml").write_text(LABEL_CONFIG.format(labels=labels), encoding="utf-8")
    return len(tasks)
