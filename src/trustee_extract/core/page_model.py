"""Per-page model from the PDF text layer (PyMuPDF). Never OCR.

S1 find_chrome + S2 load_page are ported from prototype/pipeline.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from collections import Counter

import pymupdf

from trustee_extract.core.geom import cy, group_rows
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


def word_key(x0, y0, t):
    return (t, round(x0 / 4), round(y0 / 4))   # 4pt buckets tolerate tiny jitter


def page_words(page, rotate=True):
    """Words as (x0, y0, x1, y1, text) in the *visual* page space.

    Fix (a): PyMuPDF returns words/drawings in unrotated space; `/Rotate 90` pages (us_1, us_2)
    must be mapped through `page.rotation_matrix`, or rows and columns swap.
    """
    m = page.rotation_matrix if rotate else pymupdf.Identity
    for x0, y0, x1, y1, t, *_ in page.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1) * m
        yield r.x0, r.y0, r.x1, r.y1, t


def find_chrome(doc, min_share=0.5, top=0.12, bottom=0.92, rotate=True):
    cnt = Counter()
    for p in doc:
        h = p.rect.height
        cnt.update({word_key(x0, y0, t)
                    for x0, y0, x1, y1, t in page_words(p, rotate)
                    if y1 < top * h or y0 > bottom * h})       # only page bands can be chrome
    return {k for k, c in cnt.items() if c >= min_share * len(doc)}


def is_title_bar(r, words):
    """Fix (b): a filled bar holding nothing or one short phrase on one line (a section title bar).
    Zebra stripes and shaded header rows hold several cells, so they are not bars."""
    if not (3 <= r.height <= 40 and r.width >= 40 and r.width >= 3 * r.height):
        return False
    inside = [w for w in words if r.contains(pymupdf.Point((w["x0"] + w["x1"]) / 2, (w["y0"] + w["y1"]) / 2))]
    if not inside:
        return True
    rows = group_rows(inside)
    if len(rows) > 1:
        return False
    ws = rows[0]["ws"]
    lh = max(w["y1"] - w["y0"] for w in ws)
    return all(b["x0"] - a["x1"] < 0.6 * lh for a, b in zip(ws, ws[1:]))


def load_page(page, chrome, top=0.12, rotate=True, hard_separators=True):
    m = page.rotation_matrix if rotate else pymupdf.Identity
    raw = list(page_words(page, rotate))
    h = page.rect.height
    # footer line = the line carrying the copyright mark (drop the whole line)
    foot = [(w[1] + w[3]) / 2 for w in raw if w[4].startswith("©")]
    words, removed, title_words = [], [], []
    for x0, y0, x1, y1, t in raw:
        w = dict(x0=x0, y0=y0, x1=x1, y1=y1, t=t)
        if word_key(x0, y0, t) in chrome or any(abs(cy(w) - f) < 4 for f in foot):
            removed.append(w)
        elif y1 < top * h:
            title_words.append(w)           # non-repeating text in the title bar = section title
        else:
            words.append(w)
    title = " ".join(w["t"] for r in group_rows(title_words) for w in r["ws"])

    H, V, fills, boxes = [], [], [], []
    HS, VS, bars = [], [], []               # fix (b): hard separators + title bars
    all_words = words + title_words
    for d in page.get_drawings():
        drect = d["rect"] * m
        if drect.width > 100 and drect.height > 100:
            boxes.append(drect)
        if d.get("fill") and drect.width > 4 and drect.height > 4:
            fills.append(drect)
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1] * m, it[2] * m
                r = pymupdf.Rect(min(a.x, b.x), min(a.y, b.y), max(a.x, b.x), max(a.y, b.y))
            elif it[0] == "re":
                r = it[1] * m
            elif it[0] == "qu" and hard_separators:
                r = it[1].rect * m
            else:
                continue
            if r.height < 3 and r.width > 30:
                H.append(r)                                   # horizontal rule
            elif r.width < 3 and r.height > 30:
                V.append(r)                                   # vertical rule
            elif it[0] == "re" and r.width > 30 and r.height > 30 and not d.get("fill"):
                # outlined box: its four sides are separators
                H += [pymupdf.Rect(r.x0, r.y0, r.x1, r.y0), pymupdf.Rect(r.x0, r.y1, r.x1, r.y1)]
                V += [pymupdf.Rect(r.x0, r.y0, r.x0, r.y1), pymupdf.Rect(r.x1, r.y0, r.x1, r.y1)]
            if not hard_separators:
                continue
            if "s" in (d.get("type") or "") and r.width > 30 and r.height > 30:
                # stroked box (outlined or filled + outlined): its sides are hard separators
                HS += [pymupdf.Rect(r.x0, r.y0, r.x1, r.y0), pymupdf.Rect(r.x0, r.y1, r.x1, r.y1)]
                VS += [pymupdf.Rect(r.x0, r.y0, r.x0, r.y1), pymupdf.Rect(r.x1, r.y0, r.x1, r.y1)]
            elif d.get("fill") and is_title_bar(r, all_words):
                bars.append(r)
                HS += [pymupdf.Rect(r.x0, r.y0, r.x1, r.y0), pymupdf.Rect(r.x0, r.y1, r.x1, r.y1)]
    return dict(words=words, removed=removed, title=title, H=H, V=V, fills=fills, boxes=boxes,
                HS=HS, VS=VS, bars=bars)
