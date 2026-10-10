"""XLarge fallback for ONE crop (off by default; `python run.py ... --fallback`).

Same settings as tools/crop_test.py (egret-xlarge layout + TableFormer ACCURATE, OCR off, offline
models). Docling is imported only when a crop actually needs it, and the converter is loaded once.
The crop is the original page with its CropBox set (text layer kept), so no OCR is involved.
"""
import os
import tempfile
import time
from pathlib import Path

import pandas as pd

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

    def tables(self, doc, pno, rect):
        """Tables XLarge finds in crop `rect` (display coordinates) of page `pno` (0-based)."""
        t0 = time.time()
        pdf = write_crop_pdf(doc, pno, rect, str(self.tmp / f"p{pno + 1}_{self.calls}.pdf"))
        res = self._converter().convert(str(pdf))
        dfs = []
        for t in res.document.tables:
            try:
                df = t.export_to_dataframe(doc=res.document)
            except TypeError:
                df = t.export_to_dataframe()
            df.columns = [str(c) for c in df.columns]
            dfs.append(df.fillna("").astype(str))
        self.calls += 1
        self.seconds += time.time() - t0
        return dfs
