"""S9 draw computed regions, column separators and header lines onto the PDF (ported from prototype)."""

from __future__ import annotations

import pymupdf

from trustee_extract.structure.geometry import Region


COLORS = [(0.85, 0.1, 0.1), (0, 0.55, 0), (0, 0.2, 0.9), (0.85, 0.45, 0), (0.6, 0, 0.6), (0, 0.55, 0.6)]


def draw_overlay(page, regions: list[Region]):
    """Everything here is page.draw_*(coordinates we computed). Nothing is detected from pixels."""
    for i, r in enumerate(regions):
        col = COLORS[i % len(COLORS)]
        x0, y0, x1, y1 = r.bbox
        # region box (solid)
        page.draw_rect(pymupdf.Rect(x0 - 3, y0 - 3, x1 + 3, y1 + 3), color=col, width=1.4)
        # column separators (dashed) = middle of every gutter found by find_gutters()
        for c in r.col_cuts[1:-1]:
            page.draw_line((c, y0 - 2), (c, y1 + 2), color=col, width=0.5, dashes="[2] 2")
        # header / body boundary (dotted, horizontal)
        if r.n_header_rows and r.n_header_rows < len(r.row_ys):
            yb = (r.row_ys[r.n_header_rows - 1] + r.row_ys[r.n_header_rows]) / 2
            page.draw_line((x0 - 3, yb), (x1 + 3, yb), color=col, width=0.6, dashes="[1] 1")
        label = f"R{i} {r.kind} {r.df.shape[0]}x{r.df.shape[1]}"
        page.insert_text((x0, y0 - 5), label, fontsize=6.5, color=col)
