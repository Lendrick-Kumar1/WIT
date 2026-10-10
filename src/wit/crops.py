"""Deterministic table crops from the PDF itself (no model involved).

A page is cut into BANDS at its full-width separators (drawn lines / filled bars / the thin
gradient IMAGES US Bank uses). Inside a band, a vertical rule that runs (almost) the full band
height splits it into side-by-side CELLS. A band that only holds a header (no digits) is glued to
the band below it, so every crop carries its own header.

Each crop is written as a one-page mini-PDF (vector + text layer kept, so Docling can still match
cells to the real PDF text; no OCR) and as a PNG preview.
"""
import re

import pymupdf

from .pdfpage import page_model, rows_of

AMOUNT = re.compile(r"^\(?-?\d[\d,]*\.\d+%?\)?$|^\(?-?\d{1,3}(,\d{3})+\)?$|^-?\d+(\.\d+)?%$")


def _has_amount(ws):
    """Real data (amounts, decimals, percents). Dates like 5/2/2024 in headers don't count."""
    return any(AMOUNT.match(w["t"]) for w in ws)


def major_separators(page, min_width, min_image_height=3.0):
    """Full-width SECTION separators: drawn lines / filled bars of any thickness, and images
    at least `min_image_height` tall (US Bank's coloured bars). Thin images (~2pt dotted rules
    between groups or above totals) are NOT section boundaries."""
    m = page.rotation_matrix
    ys = []
    for d in page.get_drawings():
        r = d["rect"] * m
        # lines / hairline rects only; filled zebra-row rectangles (~12pt tall) are not separators
        if r.width >= min_width and r.height <= 2.5:
            ys.append((r.y0 + r.y1) / 2)
    for info in page.get_image_info():
        r = pymupdf.Rect(info["bbox"]) * m
        if r.width >= min_width and min_image_height <= r.height <= 12:
            ys.append((r.y0 + r.y1) / 2)
    return sorted(ys)


def find_crops(page, title_band=0.12, footer_band=0.93, min_sep_width=0.6, pad=4.0):
    """Return a list of crop rects in DISPLAY (rotation-corrected) coordinates."""
    words, H, V = page_model(page)
    W, Ht = page.rect.width, page.rect.height
    top, bottom = Ht * title_band, Ht * footer_band
    words = [w for w in words if w["y0"] >= top and w["y1"] <= bottom]
    if not words:
        return []
    # 1) full-width SECTION separators -> band edges (dotted group rules are ignored)
    seps = sorted({round(y, 1) for y in major_separators(page, min_sep_width * W) if top <= y <= bottom})
    edges = [top] + seps + [bottom]
    bands = []
    for a, b in zip(edges, edges[1:]):
        ws = [w for w in words if a <= (w["y0"] + w["y1"]) / 2 < b]
        if ws:
            bands.append((a, b, ws))
    # 2) header-only band (no digits, <= 4 text rows) glues onto the band below
    merged = []
    i = 0
    while i < len(bands):
        a, b, ws = bands[i]
        if (i + 1 < len(bands) and not _has_amount(ws) and len(rows_of(ws)) <= 4):
            a2, b2, ws2 = bands[i + 1]
            merged.append((a, b2, ws + ws2))
            i += 2
            continue
        merged.append((a, b, ws))
        i += 1
    # 3) inside each band: split at vertical rules covering >= 80% of the band's text height
    crops = []
    for a, b, ws in merged:
        y0 = min(w["y0"] for w in ws)
        y1 = max(w["y1"] for w in ws)
        # body = rows with amounts; a vertical rule must cover most of the BODY height
        body = [w for r in rows_of(ws) if _has_amount(r["ws"]) for w in r["ws"]] or ws
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


def write_crop_pdf(src_doc, pno, rect_display, out_pdf):
    """One-page PDF = a copy of page `pno` whose CropBox is `rect_display`.
    Nothing is re-drawn: rotation, vector graphics and the text layer stay exactly as in the
    source, so Docling still matches table cells to the real PDF text (no OCR)."""
    page = src_doc[pno]
    out = pymupdf.open()
    out.insert_pdf(src_doc, from_page=pno, to_page=pno)
    clip = rect_display * page.derotation_matrix        # display -> unrotated page coordinates
    clip.normalize()
    out[0].set_cropbox(clip & out[0].mediabox)
    out.save(out_pdf)
    out.close()
    return out_pdf


def preview_png(pdf_path, png_path, dpi=110):
    d = pymupdf.open(pdf_path)
    d[0].get_pixmap(dpi=dpi).save(png_path)
    d.close()
