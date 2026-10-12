"""Cut a page into CROPS, one table per crop, from the PDF itself (no model involved).

  1. the title block at the top and the footer at the bottom are MEASURED and left out
  2. the page is cut into BANDS at full-width section separators (drawn lines, and the thin
     coloured image bars some trustees use); dotted rules between groups are not cuts
  3. a band holding only a header (no amounts) is glued to the band below it, so every crop
     carries its own header; a header followed by RULED RECORDS (one security per band) takes
     all of them
  4. inside a band, a vertical rule running down most of the band splits side-by-side tables

page_tables(page) then reads every crop as ONE table (table.build_table).
write_crop_pdf() saves one crop as a PDF (the original page with its CropBox set, text layer
kept) for the XLarge fallback and for looking at it.
"""
import re
import statistics as st

import pymupdf

from .pdfpage import page_model, rows_of
from .table import build_table, first_full_line

AMOUNT = re.compile(r"^\(?-?\d[\d,]*\.\d+%?\)?$|^\(?-?\d{1,3}(,\d{3})+\)?$|^-?\d+(\.\d+)?%$")


def has_amount(ws):
    """Amounts, decimals or percents (dates like 5/2/2024 in a header do not count)."""
    return any(AMOUNT.match(w["t"]) for w in ws)


def section_separators(page, min_width, min_image_height=3.0):
    """y of full-width SECTION separators: drawn lines / hairline boxes, and images at least
    `min_image_height` tall. Filled row shading (~12pt) and thin dotted images (~2pt, between
    groups or above totals) are not section boundaries."""
    m = page.rotation_matrix
    ys = []
    for d in page.get_drawings():
        r = d["rect"] * m
        if r.width >= min_width and r.height <= 2.5:
            ys.append((r.y0 + r.y1) / 2)
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) * m
        if r.width >= min_width and min_image_height <= r.height <= 12:
            ys.append((r.y0 + r.y1) / 2)
    return sorted(ys)


def title_bottom(words, page_height, max_band=0.2):
    """Bottom of the TITLE BLOCK: the leading lines that are a single phrase (no column gaps)
    printed larger than the body text (deal name, section title, 'As of' lines). Stops at the
    first line that looks like table text, or at vertical (rotated) column headers. Only lines in
    the top `max_band` of the page can be title lines."""
    if not words:
        return 0.0
    body = st.median(w["y1"] - w["y0"] for w in words)
    bottom, prev_h = 0.0, None
    for r in rows_of(words):
        ws = r["ws"]
        if ws[0]["y1"] > page_height * max_band:
            break
        if any(len(w["t"]) >= 4 and w["y1"] - w["y0"] > 2 * (w["x1"] - w["x0"]) for w in ws):
            break
        height = max(w["y1"] - w["y0"] for w in ws)
        single = all(b["x0"] - a["x1"] < 1.5 * body for a, b in zip(ws, ws[1:]))
        # larger than body text, or the same size as the title line just above it
        big = height >= 1.1 * body or (prev_h is not None and height >= prev_h - 0.5)
        if not (single and big):
            break
        bottom, prev_h = max(w["y1"] for w in ws), height
    return bottom


PAGE_NUMBER = re.compile(r"\bpage\s*\d|\b\d+\s+(of\s+)+\d+\b", re.I)    # "Page 9", "4 of 9"


def footer_top(words, page_height, max_band=0.15):
    """Top of the FOOTER, from two signals (the higher one wins), both only for lines in the
    bottom `max_band` of the page that hold no money amounts (a subtotal does):
      - a gap clearly larger than the normal line step above the bottom lines
      - page numbering ('Page 9 of 48', 'Collateral Detail 4 of 9'): that line and everything
        below it
    Neither -> no footer."""
    rows = rows_of(words)
    if len(rows) < 3:
        return page_height
    step = st.median(b["c"] - a["c"] for a, b in zip(rows, rows[1:]))
    top = page_height
    for k in range(len(rows) - 1, 0, -1):
        if rows[k]["c"] < page_height * (1 - max_band) or has_amount(rows[k]["ws"]):
            break
        if PAGE_NUMBER.search(rows[k]["text"]):
            top = min(top, min(w["y0"] for w in rows[k]["ws"]) - 0.5)
        if rows[k]["c"] - rows[k - 1]["c"] > 1.25 * step:
            top = min(top, min(w["y0"] for w in rows[k]["ws"]) - 0.5)
            break
    return top


def find_crops(page, model=None, min_sep_width=0.6, pad=4.0):
    """Crop rectangles (rotation-corrected page coordinates), one per table, in reading order."""
    words, H, V = model or page_model(page)
    W, Ht = page.rect.width, page.rect.height
    top = title_bottom(words, Ht) + 0.5
    bottom = footer_top(words, Ht)
    words = [w for w in words if w["y0"] >= top and w["y1"] <= bottom]
    if not words:
        return []
    # 1) bands between section separators
    seps = sorted({round(y, 1) for y in section_separators(page, min_sep_width * W) if top <= y <= bottom})
    edges = [top] + seps + [bottom]
    bands = []
    for a, b in zip(edges, edges[1:]):
        ws = [w for w in words if a <= (w["y0"] + w["y1"]) / 2 < b]
        if ws:
            bands.append(ws)
    # 2) a header-only band (no amounts, <= 4 lines) is glued to the band below; a header
    #    followed by ruled records (every band: text lines first, then amounts) takes them all
    merged, i = [], 0
    while i < len(bands):
        n = _records_after(bands, i)
        if n:
            merged.append([w for b in bands[i:i + 1 + n] for w in b])
            i += 1 + n
            continue
        if i + 1 < len(bands) and not has_amount(bands[i]) and len(rows_of(bands[i])) <= 4:
            merged.append(bands[i] + bands[i + 1])
            i += 2
            continue
        merged.append(bands[i])
        i += 1
    # 3) split a band at vertical rules covering >= 80% of the height of its amount lines
    crops = []
    for ws in merged:
        body = [w for r in rows_of(ws) if has_amount(r["ws"]) for w in r["ws"]] or ws
        by0, by1 = min(w["y0"] for w in body), max(w["y1"] for w in body)
        cuts = sorted({round((v.x0 + v.x1) / 2, 1) for v in V
                       if min(v.y1, by1) - max(v.y0, by0) >= 0.8 * (by1 - by0)})
        xs = [min(w["x0"] for w in ws) - 1] + cuts + [max(w["x1"] for w in ws) + 1]
        for xa, xb in zip(xs, xs[1:]):
            cw = [w for w in ws if xa <= (w["x0"] + w["x1"]) / 2 < xb]
            if len(cw) < 3:
                continue
            r = pymupdf.Rect(min(w["x0"] for w in cw) - pad, min(w["y0"] for w in cw) - pad,
                             max(w["x1"] for w in cw) + pad, max(w["y1"] for w in cw) + pad)
            crops.append(r & page.rect)
    return crops


def _records_after(bands, i, max_header_lines=10):
    """Number of ruled-record bands right after a header-only band i (0 if fewer than 2)."""
    if has_amount(bands[i]) or len(rows_of(bands[i])) > max_header_lines:
        return 0
    n = 0
    for b in bands[i + 1:]:
        if not first_full_line(rows_of(b)):          # None (no amounts) or 0 (no text first)
            break
        n += 1
    if n >= 2 and i + 1 + n < len(bands) and _amounts_only(bands[i + 1 + n]):
        n += 1                                       # the total printed after the last record
    return n if n >= 2 else 0


def _amounts_only(band):
    """A band of 1-2 lines holding nothing but amounts (a total printed under ruled records)."""
    rows = rows_of(band)
    return len(rows) <= 2 and all(AMOUNT.match(w["t"]) for w in band)


def crop_table(words, rect, vocab=(), min_words=3, rules=()):
    """The words whose centre lies inside `rect`, read as ONE table -> DataFrame, or None."""
    ws = [w for w in words if rect.x0 <= (w["x0"] + w["x1"]) / 2 <= rect.x1
          and rect.y0 <= (w["y0"] + w["y1"]) / 2 <= rect.y1]
    if len(ws) < min_words:
        return None
    df = build_table(ws, vocab, [y for y in rules if rect.y0 < y < rect.y1])
    return df if len(df) and df.shape[1] >= 2 else None


def page_tables(page, vocab=(), min_words=3):
    """Every crop of the page read as ONE table -> [(crop_rect, DataFrame)].
    vocab = header regexes from config (only used to split two header names that touch)."""
    model = page_model(page)
    out = []
    rules = section_separators(page, 0.6 * page.rect.width)
    for rect in find_crops(page, model):
        df = crop_table(model[0], rect, vocab, min_words, rules)
        if df is not None:
            out.append((rect, df))
    return out


def write_crop_pdf(src_doc, pno, rect, out_pdf):
    """One-page PDF = page `pno` with its CropBox set to `rect` (rotation-corrected coordinates).
    Nothing is re-drawn: the text layer stays, so a model can match cells to the real text."""
    page = src_doc[pno]
    out = pymupdf.open()
    out.insert_pdf(src_doc, from_page=pno, to_page=pno)
    clip = rect * page.derotation_matrix
    clip.normalize()
    out[0].set_cropbox(clip & out[0].mediabox)
    out.save(str(out_pdf))
    out.close()
    return out_pdf


def preview_png(pdf_path, png_path, dpi=110):
    d = pymupdf.open(str(pdf_path))
    d[0].get_pixmap(dpi=dpi).save(str(png_path))
    d.close()
