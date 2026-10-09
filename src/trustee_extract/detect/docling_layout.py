"""Docling, configured offline: egret layout, OCR off, TableFormer ACCURATE.

Built once per worker process (model load is the expensive part); reuse the converter.
Option names are for docling 2.135; they have changed across releases.
"""

from __future__ import annotations

import os
from pathlib import Path

from trustee_extract.core.config import docling_artifacts_path, load_config
from trustee_extract.core.types import Box

# Docling layout label -> our annotation class. Anything else is ignored.
LABEL_MAP = {
    "table": "table",
    "caption": "table_title",
    "section_header": "section_header",
    "title": "section_header",
    "key_value_region": "key_value_block",
    "form": "key_value_block",
}


def set_offline_env() -> None:
    """Must run before huggingface_hub / docling are imported."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"


def build_pipeline_options(cfg: dict | None = None, table_structure: bool = True):
    set_offline_env()
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.pipeline_options import (
        LayoutObjectDetectionOptions,
        PdfPipelineOptions,
        TableFormerMode,
        TableStructureOptions,
    )

    cfg = cfg or load_config()
    d = cfg["docling"]
    artifacts = docling_artifacts_path(cfg)
    if not artifacts.is_dir():
        raise FileNotFoundError(f"Docling models not found at {artifacts}")

    return PdfPipelineOptions(
        artifacts_path=artifacts,
        enable_remote_services=False,
        do_ocr=d["do_ocr"],
        do_table_structure=table_structure,
        table_structure_options=TableStructureOptions(
            mode=TableFormerMode(d["table_mode"]),
            do_cell_matching=d["do_cell_matching"],
        ),
        layout_options=LayoutObjectDetectionOptions.from_preset(d["layout_preset"]),
        accelerator_options=AcceleratorOptions(
            num_threads=d["num_threads"], device=AcceleratorDevice.CPU
        ),
    )


def build_converter(cfg: dict | None = None, table_structure: bool = True, keep_images: bool = False):
    opts = build_pipeline_options(cfg, table_structure)
    opts.generate_page_images = keep_images
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter, PdfFormatOption

    return DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})


def layout_boxes(conv_res, source: str = "egret") -> list[Box]:
    """Raw layout clusters from a conversion, mapped to our classes. Top-left origin, points."""
    boxes: list[Box] = []
    for p in conv_res.pages:
        if p.predictions.layout is None:
            continue
        for c in p.predictions.layout.clusters:
            label = LABEL_MAP.get(c.label.value)
            if label:
                b = c.bbox.to_top_left_origin(p.size.height)
                boxes.append(Box(p.page_no + 1, (b.l, b.t, b.r, b.b), label, float(c.confidence), source))
    return boxes


class EgretDetector:
    """`Detector` backed by Docling layout only (no TableFormer). Baseline detector."""

    def __init__(self, cfg: dict | None = None):
        self.converter = build_converter(cfg, table_structure=False)

    def detect_pages(self, pdf_path: Path, first: int, last: int) -> list[Box]:
        return layout_boxes(self.converter.convert(pdf_path, page_range=(first, last)))

    def detect(self, page) -> list[Box]:
        return self.detect_pages(page.pdf_path, page.page, page.page)
