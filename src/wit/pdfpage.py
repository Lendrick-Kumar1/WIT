"""Basic reading of a PDF page, used by every other module.

  page_model(page)   words (rotation-corrected) + horizontal / vertical rules
  rows_of(words)     words -> text lines
  phrases(words)     a line's words -> phrases (split at wide gaps)
  to_num(text)       printed number -> float
  page_title(page)   text in the top band of the page (the section title)

Coordinates are PDF points (1/72 inch), origin top-left, y grows downward. Pages stored rotated
(/Rotate 90) are turned upright, so every module sees the page as it is printed.
"""
import re
import statistics as st

import pymupdf

NUM = re.compile(r"^\(?-?[\d,]*\.?\d+%?\)?$")        # 1,234.50  (5.2)  4.19%  57


def page_model(page):
    """-> (words, horizontal rules, vertical rules), all in upright page coordinates.
    words = [{x0, y0, x1, y1, t}]. Rules are thin drawings AND thin images (some trustees draw
    their separator lines as images): <= 10pt high and > 60pt wide, or <= 3pt wide and > 30pt high."""
    m = page.rotation_matrix                      # 1) rotation-normalised coordinates
    words = []
    for x0, y0, x1, y1, t, *_ in page.get_text("words"):
        r = pymupdf.Rect(x0, y0, x1, y1) * m
        words.append(dict(x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1, t=t))
    seps_h, seps_v = [], []                       # 2) thin drawings + thin images = rules
    rects = [d["rect"] for d in page.get_drawings()] + [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()]
    for r in rects:
        r = r * m
        if r.height <= 10 and r.width > 60:
            seps_h.append(r)
        elif r.width <= 3 and r.height > 30:
            seps_v.append(r)
    return words, seps_h, seps_v


def rows_of(ws):
    """Words -> text lines: a word joins the current line if its vertical centre is within half a
    line height of the line's (running mean) centre.
    Returns [{"c": centre y, "ws": words left to right, "text": the line's text}] top to bottom."""
    if not ws:
        return []
    tol = st.median(w["y1"] - w["y0"] for w in ws) * 0.5
    rows = []
    for w in sorted(ws, key=lambda w: (w["y0"] + w["y1"]) / 2):
        c = (w["y0"] + w["y1"]) / 2
        if rows and abs(c - rows[-1]["c"]) <= tol:
            rows[-1]["ws"].append(w)
            rows[-1]["c"] = st.mean((v["y0"] + v["y1"]) / 2 for v in rows[-1]["ws"])
        else:
            rows.append({"c": c, "ws": [w]})
    for r in rows:
        r["ws"].sort(key=lambda w: w["x0"])
        r["text"] = " ".join(w["t"] for w in r["ws"])
    return rows


def split_phrases(ws, gap):
    """A line's words -> phrases (lists of words), split wherever two words are > gap apart."""
    out, cur = [], []
    for w in ws:
        if cur and w["x0"] - cur[-1]["x1"] > gap:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def phrases(ws, gap):
    """Same as split_phrases, as {x0, x1, t} per phrase."""
    return [dict(x0=p[0]["x0"], x1=p[-1]["x1"], t=" ".join(w["t"] for w in p)) for p in split_phrases(ws, gap)]


def to_num(s, percent=True):
    """Printed number -> float, else None.
    '1,234.50' -> 1234.5 ; '(1,234.50)' -> -1234.5 ; '>= 120.00%' -> 120.0 ;
    '€2,000,000.00' / '1,000.00 EUR' / '12.5 [A]' -> the number. percent=False: '4.19%' -> None."""
    s = str(s if s is not None else "").strip()
    if not percent and s.endswith("%"):
        return None
    s = re.sub(r"^(>=|<=|>|<|≥|≤)\s*", "", s)
    s = re.sub(r"\s*(EUR|USD|GBP)\b|\[[A-Z]\]|[€$£]|\s", "", s)
    if not NUM.match(s):
        return None
    neg = s.startswith("(") or s.startswith("-")
    try:
        v = float(s.strip("()%-").replace(",", ""))
    except ValueError:
        return None
    return -v if neg else v


def page_title(page, words=None, band=0.2):
    """Text in the top band of the page (the report section title), rotation-corrected."""
    words = words if words is not None else page_model(page)[0]
    rows = rows_of([w for w in words if w["y1"] < page.rect.height * band])
    return " ".join(r["text"] for r in rows)


