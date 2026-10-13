"""XLarge (Docling egret-xlarge layout + TableFormer ACCURATE, OCR off, offline models).

Used in two places, both optional:
  - app.py run --fallback    re-read ONE crop whose IDs or sums failed (collateral.read_pages)
  - dev/crop_view.py         compare XLarge with PyMuPDF on full pages and crops

Docling is imported only when a table is actually needed, and the converter is loaded once.
A crop is the original page with its CropBox set (text layer kept), so no OCR is involved.
"""
import os
import tempfile
import time
from pathlib import Path

from .crops import write_crop_pdf


def default_artifacts():
    return os.environ.get("DOCLING_ARTIFACTS_PATH", str(Path.home() / ".cache" / "docling" / "models"))


class XLarge:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts or default_artifacts()
        self.conv = None
        self.calls = 0
        self.seconds = 0.0
        self.tmp = Path(tempfile.mkdtemp(prefix="wit_xl_"))

    def _converter(self):
        if self.conv is None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_EGRET_XLARGE
            from docling.datamodel.pipeline_options import (LayoutOptions, PdfPipelineOptions,
                                                            TableFormerMode, TableStructureOptions)
            from docling.document_converter import DocumentConverter, PdfFormatOption
            opts = PdfPipelineOptions(artifacts_path=self.artifacts, do_ocr=False, do_table_structure=True)
            opts.table_structure_options = TableStructureOptions(mode=TableFormerMode.ACCURATE,
                                                                 do_cell_matching=True)
            opts.layout_options = LayoutOptions(model_spec=DOCLING_LAYOUT_EGRET_XLARGE)
            self.conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
        return self.conv

    def pdf_tables(self, pdf, page_no=None):
        """Tables XLarge finds in a PDF (or in one 1-based page of it) -> [DataFrame of text]."""
        t0 = time.time()
        kw = {"page_range": (page_no, page_no)} if page_no else {}
        res = self._converter().convert(str(pdf), **kw)
        dfs = []
        for t in res.document.tables:
            try:
                df = t.export_to_dataframe(doc=res.document)
            except TypeError:                     # older docling
                df = t.export_to_dataframe()
            df.columns = [str(c) for c in df.columns]
            dfs.append(df.fillna("").astype(str))
        self.calls += 1
        self.seconds += time.time() - t0
        return dfs

    def tables(self, doc, pno, rect):
        """Tables XLarge finds in crop `rect` of page `pno` (0-based)."""
        pdf = write_crop_pdf(doc, pno, rect, self.tmp / f"p{pno + 1}_{self.calls}.pdf")
        return self.pdf_tables(pdf)
