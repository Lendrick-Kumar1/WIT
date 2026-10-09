"""S5 region -> table (rows, gutter columns, header, wraps, sections) + S6 classify (ported from prototype)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pymupdf

from trustee_extract.core.geom import bbox, cx, group_rows, has_digit, line_height
from trustee_extract.core.numbers import to_number

Word = dict  # {"x0","y0","x1","y1","t"}


@dataclass
class Region:
    page: int                     # 1-based PDF page number
    words: list[Word]
    bbox: tuple = ()
    col_cuts: list[float] = field(default_factory=list)   # x positions of column separators
    row_ys: list[float] = field(default_factory=list)     # y centre of every text row
    df: pd.DataFrame | None = None
    kind: str = ""
    title: str = ""               # page section title, e.g. "Asset Information I"
    n_header_rows: int = 0


def ink_coverage(rows, x0, x1, step=0.5):
    """For every x (in `step` pt bins) count how many rows have a word covering it.
    Columns of a table show up as tall plateaus, gutters as valleys near zero."""
    n = int((x1 - x0) / step) + 2
    cover = [0] * n
    for r in rows:
        hit = set()
        for w in r["ws"]:
            hit.update(range(int((w["x0"] - x0) / step), int((w["x1"] - x0) / step) + 1))
        for i in hit:
            if 0 <= i < n:
                cover[i] += 1
    return cover


def find_gutters(rows, x0, x1, min_w, tolerance, step=0.5):
    """Valleys of the coverage profile: x-ranges with ink in <= tolerance*rows rows."""
    cover = ink_coverage(rows, x0, x1, step)

    def runs(limit):
        res, start = [], None
        for i, c in enumerate(cover + [10**9]):
            if c <= limit and start is None:
                start = i
            elif c > limit and start is not None:
                res.append((x0 + start * step, x0 + i * step))
                start = None
        return res

    out = []
    for a, b in runs(tolerance * len(rows)):
        if b - a >= min_w and a > x0 and b < x1:
            out.append((a, b))
        elif (a <= x0 or b >= x1) and tolerance > 0:
            # the tolerant valley runs into the region edge: that "valley" is really a
            # sparse first/last column (e.g. 'Reason for Trade' filled in 2 of 24 rows).
            # Inside it, use strictly empty gaps instead.
            out += [(p, q) for p, q in runs(0) if p >= a and q <= b and q - p >= min_w
                    and p > x0 and q < x1]
    return sorted(out)


def build_table(region: Region):
    msg = [r for r in group_rows(region.words)
           if " ".join(w["t"] for w in r["ws"]).lower().startswith("there are no")]
    ws = [w for w in region.words if not any(w in r["ws"] for r in msg)] or region.words
    rows = group_rows(ws)
    lh = line_height(ws)
    x0, _, x1, _ = bbox(ws)

    # 1) COLUMNS: gutters = x-ranges empty in ~all rows. 12% tolerance lets a spanning title,
    #    a section label or a wrapped line cross a gutter without destroying it.
    def single_phrase(r):   # titles, section labels, "There are no ... to report on."
        ws_ = r["ws"]
        return all(b["x0"] - a["x1"] < lh * 0.6 for a, b in zip(ws_, ws_[1:]))
    grows = [r for r in rows if not single_phrase(r)]
    if len(grows) < 2:
        grows = rows
    tol = 0.12 if len(grows) >= 8 else 0.0
    gut = find_gutters(grows, x0, x1, min_w=lh * 0.55, tolerance=tol)
    cuts = [x0 - 1] + [(a + b) / 2 for a, b in gut] + [x1 + 1]     # separator = gutter middle
    ncol = len(cuts) - 1

    def col_of(x):
        return next(k for k in range(ncol) if cuts[k] <= x < cuts[k + 1])

    def to_cells(row_ws):
        cells = [""] * ncol
        for w in row_ws:
            k = col_of(cx(w))
            cells[k] = (cells[k] + " " + w["t"]).strip()
        return cells

    # 2) HEADER: the rows above the first row that contains a digit
    n_hdr = next((i for i, r in enumerate(rows) if has_digit(r["ws"])), len(rows))
    if n_hdr == len(rows) and ncol < 3 and len(rows) > 2:
        n_hdr = 0          # digit-free block with 1-2 columns = plain text, not a header
    header = [""] * ncol
    for r in rows[:n_hdr]:
        # split the header line into phrases; a phrase that spans several columns
        # ("Fitch Rating" over Original | Current) is added to every column it covers
        phrases, cur = [], []
        for w in r["ws"]:
            if cur and w["x0"] - cur[-1]["x1"] > lh * 0.6:
                phrases.append(cur)
                cur = []
            cur.append(w)
        if cur:
            phrases.append(cur)
        for ph in phrases:
            a, b = ph[0]["x0"], ph[-1]["x1"]
            txt = " ".join(w["t"] for w in ph)
            spans = [k for k in range(ncol) if min(b, cuts[k + 1]) - max(a, cuts[k]) > 0.25 * (b - a)]
            for k in spans or [col_of((a + b) / 2)]:
                header[k] = (header[k] + " " + txt).strip()

    # 3) BODY: a line with no digits, few cells, right under the previous row = wrapped text
    body, prev_c = [], None
    for r in rows[n_hdr:]:
        cells = to_cells(r["ws"])
        filled = sum(bool(c) for c in cells)
        if (body and not has_digit(r["ws"]) and filled <= max(1, 0.3 * ncol)
                and r["c"] - prev_c < 1.6 * lh):
            body[-1] = [(p + " " + c).strip() for p, c in zip(body[-1], cells)]
            prev_c = r["c"]
            continue
        body.append(cells)
        prev_c = r["c"]

    # 4) SECTION LABELS: a last header line that only fills column 0 is really a section label
    if n_hdr > 1 and all(cx(w) < cuts[1] for w in rows[n_hdr - 1]["ws"]):
        sec = " ".join(w["t"] for w in rows[n_hdr - 1]["ws"])
        header[0] = header[0].replace(sec, "").strip()
        body.insert(0, [sec] + [""] * (ncol - 1))
    #    rows with only column 0 filled and no digits -> become a "_section" column
    table, section = [], ""
    for cells in body:
        if cells[0] and not any(cells[1:]) and not any(ch.isdigit() for ch in cells[0]):
            section = cells[0]
            continue
        table.append(cells + [section])

    cols = [h or f"col{k}" for k, h in enumerate(header)] + ["_section"]
    cols = [c if cols.count(c) == 1 else f"{c}_{k}" for k, c in enumerate(cols)]   # unique
    df = pd.DataFrame(table, columns=cols)
    if not df["_section"].any():
        df = df.drop(columns="_section")
    region.df, region.col_cuts, region.n_header_rows = df, cuts, n_hdr
    region.row_ys = [r["c"] for r in rows]
    return region


def classify(region: Region, fills, boxes=()):
    df = region.df
    x0, y0, x1, y1 = region.bbox
    centre = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
    near = pymupdf.Rect(x0 - 40, y0 - 40, x1 + 40, y1 + 40)
    in_chart_box = any(b.contains(centre) and sum(b.contains(f) for f in fills) >= 4 for b in boxes)
    if in_chart_box or sum(near.contains(f) for f in fills) >= 4:
        return "chart-labels"            # sits on / inside lots of coloured shapes (bars, slices)
    text = " ".join(w["t"] for w in region.words).lower()
    if "there are no" in text:
        return "empty-table"
    vals = [v for v in df.values.ravel() if v]
    if df.shape[0] >= 1 and df.shape[1] >= 2:
        nums = sum(to_number(v) is not None or str(v).endswith("%") for v in vals)
        return "table" if nums / max(len(vals), 1) > 0.15 else "text-table"
    return "text"
