"""Per-page model from the PDF text layer (PyMuPDF). Never OCR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from trustee_extract.core.types import Word


@dataclass
class PageModel:
    pdf_path: Path
    page: int  # 1-based
    width: float
    height: float
    words: list[Word]

    @classmethod
    def load(cls, pdf_path: Path, page: int) -> "PageModel":
        with pymupdf.open(pdf_path) as doc:
            p = doc[page - 1]
            words = [Word(w[0], w[1], w[2], w[3], w[4]) for w in p.get_text("words")]
            return cls(Path(pdf_path), page, p.rect.width, p.rect.height, words)

    def render_png(self, out: Path, dpi: int = 144) -> Path:
        with pymupdf.open(self.pdf_path) as doc:
            doc[self.page - 1].get_pixmap(dpi=dpi).save(out)
        return out
