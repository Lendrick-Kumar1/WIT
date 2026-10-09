"""S3 recursive XY-cut + S4 header/total attachment (ported from prototype)."""

from __future__ import annotations

import statistics as st

from trustee_extract.core.geom import bbox, cx, cy, empty_runs, group_rows, has_digit, line_height, row_alignment
from trustee_extract.core.numbers import TOTAL_RE


def covered(intervals, lo, hi):
    """Total length of the union of [(a, b), ...] clipped to [lo, hi]."""
    total, cur = 0.0, lo
    for a, b in sorted(intervals):
        a, b = max(a, cur), min(b, hi)
        if b > a:
            total += b - a
            cur = b
    return total


def hard_cuts(ws, HS, VS, bars, x0, y0, x1, y1, lh, normal_gap):
    """Fix (b): cuts forced by title bars and stroked boxes, even where whitespace is thin.

    - H: a white band holding hard separators (bar / box edges) that together cover >= 60% of
      the block width. Two half-width bars at the same height count together.
    - V: a white gutter holding a stroked-box side spanning >= 30% of the block height, or
      the gap between two title bars side by side (left bar ends in it, right bar starts in it).
    """
    out = []
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    for a, b in empty_runs([(v["y0"], v["y1"]) for v in ws], y0, y1):
        if b - a <= 0.2 * lh:
            continue
        cov = covered([(r.x0, r.x1) for r in HS if r.y0 >= a - 1 and r.y1 <= b + 1], x0, x1)
        if cov >= 0.6 * w:
            out.append(((b - a) / normal_gap + 4, "h", (a + b) / 2, f"H band {b - a:.0f}pt + hard separator {cov / w:.0%}"))
    in_block = [r for r in bars if min(r.y1, y1) - max(r.y0, y0) > -2 * lh]
    for a, b in empty_runs([(v["x0"], v["x1"]) for v in ws], x0, x1):
        if b - a < 0.3 * lh:
            continue
        box_side = any(a - 1 <= r.x0 <= b + 1 and min(r.y1, y1) - max(r.y0, y0) > 0.3 * h for r in VS)
        between_bars = (any(a - 1 <= r.x1 <= b + 1 for r in in_block)
                        and any(a - 1 <= r.x0 <= b + 1 for r in in_block))
        if box_side or between_bars:
            why = "box side" if box_side else "between title bars"
            out.append(((b - a) / lh + 6, "v", (a + b) / 2, f"V gutter {b - a:.0f}pt + {why}"))
    return out


def xy_cut(ws, H, V, depth=0, out=None, log=None, HS=(), VS=(), bars=()):
    """Split `ws` in two along the best whitespace cut, then recurse into both halves.
    `log` (optional list) records every cut so explain.py can draw them in order.
    HS / VS / bars (fix b): hard separators from stroked boxes and filled title bars."""
    out = [] if out is None else out
    if len(ws) < 2 or depth > 12:
        if ws:
            out.append(ws)
        return out
    x0, y0, x1, y1 = bbox(ws)
    lh = line_height(ws)
    rows = group_rows(ws)
    # "normal" whitespace between consecutive rows inside this block
    row_gaps = [min(w["y0"] for w in b["ws"]) - max(w["y1"] for w in a["ws"])
                for a, b in zip(rows, rows[1:])]
    normal_gap = max(st.median([g for g in row_gaps if g > 0] or [lh]), 1.0)

    candidates = []
    # --- horizontal cuts: a white band across the block, clearly taller than normal,
    #     or any white band that has a drawn rule spanning most of the block
    for a, b in empty_runs([(w["y0"], w["y1"]) for w in ws], y0, y1):
        ruled = any(r.y0 >= a - 1 and r.y1 <= b + 1 and r.x0 <= x0 + 0.3 * (x1 - x0)
                    and r.x1 >= x1 - 0.3 * (x1 - x0) for r in H)
        tall = (b - a) > max(2.2 * normal_gap, lh)
        if tall or (ruled and (b - a) > 0.8 * lh):
            score = (b - a) / normal_gap + (2 if ruled else 0)
            why = f"H gap {b - a:.0f}pt = {(b - a) / normal_gap:.1f}x normal" + (" + rule" if ruled else "")
            candidates.append((score, "h", (a + b) / 2, why))
    # --- vertical cuts: a white gutter top-to-bottom where rows on both sides DON'T line up
    #     (rows that line up = columns of the same table, so never cut there)
    header_band = not has_digit(ws) and len(rows) <= 4   # multi-line headers never line up
    for a, b in empty_runs([(w["x0"], w["x1"]) for w in ws], x0, x1):
        if b - a < 2 * lh or header_band:
            continue
        mid = (a + b) / 2
        L = [w for w in ws if w["x1"] <= mid]
        R = [w for w in ws if w["x0"] >= mid]
        ruled = any(a - 1 <= r.x0 <= b + 1 and min(r.y1, y1) - max(r.y0, y0) > 0.5 * (y1 - y0)
                    for r in V)
        align = row_alignment(L, R, tol=lh * 0.35)
        if ruled or align < 0.6:
            score = (b - a) / lh + (5 if ruled else 0) + (1 - align) * 5
            why = f"V gutter {b - a:.0f}pt, row-align {align:.2f}" + (" + rule" if ruled else "")
            candidates.append((score, "v", mid, why))

    if HS or VS or bars:
        candidates += hard_cuts(ws, HS, VS, bars, x0, y0, x1, y1, lh, normal_gap)

    if not candidates:
        out.append(ws)           # nothing left to cut: this is a final region
        return out
    _, kind, pos, why = max(candidates)
    if log is not None:
        log.append(dict(depth=depth, kind=kind, pos=pos, bbox=(x0, y0, x1, y1), why=why))
    key = cy if kind == "h" else cx
    first = [w for w in ws if key(w) < pos]
    second = [w for w in ws if key(w) >= pos]
    xy_cut(first, H, V, depth + 1, out, log, HS, VS, bars)
    xy_cut(second, H, V, depth + 1, out, log, HS, VS, bars)
    return out


def attach_headers(blocks):
    blocks = [b for b in blocks if b]
    changed = True
    while changed:
        changed = False
        blocks.sort(key=lambda b: bbox(b)[1])
        for i, a in enumerate(blocks):
            if len(group_rows(a)) > 5 or has_digit(a):   # titles / headers carry no numbers
                continue
            ax0, _, ax1, ay1 = bbox(a)
            lh = line_height(a)
            for j, b in enumerate(blocks):
                btxt = " ".join(w["t"] for w in b).lower()
                if j == i or not (len(group_rows(b)) > len(group_rows(a)) or has_digit(b)
                                  or btxt.startswith("there are no")):
                    continue
                bx0, by0, bx1, _ = bbox(b)
                overlap = max(0, min(ax1, bx1) - max(ax0, bx0)) / max(min(ax1 - ax0, bx1 - bx0), 1)
                # a sits above b, or beside b's first lines (a header cell split off), and over it
                if ay1 <= by0 + 4 * lh and by0 - ay1 < 5 * lh and overlap > 0.6:
                    blocks[j] = a + b
                    del blocks[i]
                    changed = True
                    break
            if changed:
                break
    # totals line(s) printed a bit below the table (often under a double rule) -> attach upward
    changed = True
    while changed:
        changed = False
        blocks.sort(key=lambda b: bbox(b)[1])
        for i, a in enumerate(blocks):
            text = " ".join(w["t"] for w in a)
            if len(group_rows(a)) > 2 or not TOTAL_RE.search(text):
                continue
            ax0, ay0, ax1, _ = bbox(a)
            lh = line_height(a)
            above = [j for j, b in enumerate(blocks) if j != i and len(group_rows(b)) > 2
                     and 0 <= ay0 - bbox(b)[3] < 4 * lh
                     and min(ax1, bbox(b)[2]) - max(ax0, bbox(b)[0]) > 0.5 * (ax1 - ax0)]
            if above:
                j = max(above, key=lambda j: bbox(blocks[j])[3])
                blocks[j] = blocks[j] + a
                del blocks[i]
                changed = True
                break
    return blocks
