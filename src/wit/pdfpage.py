"""Page model: rotation-corrected words, separators (thin drawings AND thin images), rows, phrases, numbers."""
import re
import statistics as st
import pymupdf

NUM = re.compile(r"^\(?-?[\d,]*\.?\d+%?\)?$")


def page_model(page):
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
    if not ws:
        return []
    lh = st.median(w["y1"] - w["y0"] for w in ws)
    rows = []
    for w in sorted(ws, key=lambda w: (w["y0"] + w["y1"]) / 2):
        c = (w["y0"] + w["y1"]) / 2
        if rows and abs(c - rows[-1]["c"]) <= lh * 0.5:
            rows[-1]["ws"].append(w)
        else:
            rows.append({"c": c, "ws": [w]})
    for r in rows:
        r["ws"].sort(key=lambda w: w["x0"])
        r["text"] = " ".join(w["t"] for w in r["ws"])
    return rows


def phrases(row_ws, gap):
    out, cur = [], []
    for w in row_ws:
        if cur and w["x0"] - cur[-1]["x1"] > gap:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [dict(x0=p[0]["x0"], x1=p[-1]["x1"], t=" ".join(w["t"] for w in p)) for p in out]


def to_num(s):
    s = re.sub(r"^(>=|<=|>|<|≥|≤)\s*", "", s.replace("€", "").replace("$", "").replace("EUR", "").strip())
    if not NUM.match(s.replace(" ", "")):
        return None
    neg = s.startswith("(") or s.startswith("-")
    v = float(s.strip("()%-").replace(",", ""))
    return -v if neg else v


def page_title(page, words=None, band=0.2):
    """Text in the top band of the page (the report section title), rotation-corrected."""
    words = words if words is not None else page_model(page)[0]
    rows = rows_of([w for w in words if w["y1"] < page.rect.height * band])
    return " ".join(r["text"] for r in rows)


