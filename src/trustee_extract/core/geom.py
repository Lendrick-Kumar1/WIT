"""Word-geometry helpers (ported verbatim from prototype/pipeline.py).

Words are dicts {"x0","y0","x1","y1","t"} in PDF points, top-left origin, *visual* (rotated) page space.
"""

from __future__ import annotations

import statistics as st


def bbox(ws):
    return (min(w["x0"] for w in ws), min(w["y0"] for w in ws),
            max(w["x1"] for w in ws), max(w["y1"] for w in ws))


def cy(w):  # vertical centre of a word
    return (w["y0"] + w["y1"]) / 2


def cx(w):  # horizontal centre of a word
    return (w["x0"] + w["x1"]) / 2


def line_height(ws):
    return st.median(w["y1"] - w["y0"] for w in ws)


def empty_runs(intervals, lo, hi):
    """Given [(start,end),...] on one axis, return the EMPTY stretches strictly inside (lo,hi).
    Projecting every word onto the y-axis and asking for empty runs = horizontal white bands.
    Projecting onto the x-axis = vertical white gutters."""
    out, cur = [], lo
    for a, b in sorted(intervals):
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    return [(a, b) for a, b in out if a > lo and b < hi]


def group_rows(ws):
    """Cluster words into text rows: words whose vertical centres are within half a line."""
    if not ws:
        return []
    tol = line_height(ws) * 0.5
    rows = []
    for w in sorted(ws, key=cy):
        if rows and abs(cy(w) - rows[-1]["c"]) <= tol:
            rows[-1]["ws"].append(w)
            rows[-1]["c"] = st.mean(cy(v) for v in rows[-1]["ws"])
        else:
            rows.append({"c": cy(w), "ws": [w]})
    for r in rows:
        r["ws"].sort(key=lambda w: w["x0"])
    return rows


def row_alignment(left, right, tol):
    """Fraction of rows on the smaller side that have a row at the same height on the other side.
    ~1.0 -> the two sides are columns of ONE table.   low -> two different blocks side by side."""
    a = [r["c"] for r in group_rows(left)]
    b = [r["c"] for r in group_rows(right)]
    if not a or not b:
        return 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    return sum(any(abs(x - y) <= tol for y in big) for x in small) / len(small)


def has_digit(ws):
    return any(ch.isdigit() for w in ws for ch in w["t"])
