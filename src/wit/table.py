"""Words of ONE table -> DataFrame.

Input: the words inside one crop (crops.py cuts a page so that every crop holds one table).
Each word is a dict {x0, y0, x1, y1, t} in page points, rotation already corrected.

build_table() runs these steps, one function each:

  1. text_rows        words -> text lines (pdfpage.rows_of)
  2. header_size      how many lines at the top are header (everything above the first data line)
  3. column_cuts      x positions that separate the columns, measured on the DATA lines
  4. header_names     the header text of every column
  5. body_rows        data lines -> table rows (wrapped and centred multi-line cells glued back)
  6. split_sections   lines that only carry a label in column 0 ("Loan", "Bond") -> `_section`

No coordinates are configured anywhere: every distance is measured relative to the text itself
(line height, row step, gap between words).
"""
import re
import statistics as st

import pandas as pd

from .pdfpage import rows_of as text_rows
from .pdfpage import split_phrases as phrases

# ---------------------------------------------------------------------------------------------
# what counts as a number / a date / a data line
# ---------------------------------------------------------------------------------------------
DATE = re.compile(r"^\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}$|^\d{1,2}[- ][A-Za-z]{3}[- ]\d{2,4}$")
MONEY = re.compile(r"^\(?-?\d{1,3}(,\d{3})+(\.\d+)?\)?$|^\(?-?\d+\.\d{2}\)?$")   # 1,234.56  0.00
TOTAL_WORD = re.compile(r"\b(sub-?)?totals?\b", re.I)


def is_data_line(ws):
    """A data line holds a digit that is not part of a date (amounts, IDs like LX123456), or is a
    'Label: value' pair. Header lines whose only digits are dates ('Current 5/2/2024') are not."""
    if any(any(ch.isdigit() for ch in w["t"]) and not DATE.match(w["t"]) for w in ws):
        return True
    return any(w["t"].endswith(":") for w in ws[:-1]) and not ws[-1]["t"].endswith(":")


def has_digit(ws):
    return any(ch.isdigit() for w in ws for ch in w["t"])


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def cx(w):
    return (w["x0"] + w["x1"]) / 2


def line_height(ws):
    return st.median(w["y1"] - w["y0"] for w in ws)


def join(a, b):
    return (a + " " + b).strip()


# ---------------------------------------------------------------------------------------------
# 2. header size
# ---------------------------------------------------------------------------------------------
def header_size(rows, lh):
    """Index of the first data line (= number of header lines), or None if there is no data line.

    Centred first cell: a text line can sit just ABOVE the first data line and belong to it
    (issuer name printed in two lines, centred on the row). It is not header: it is much closer
    to the data line below than to the header line above, so it is given back to the body."""
    n = next((i for i, r in enumerate(rows) if is_data_line(r["ws"])), None)
    if n is None:
        return None
    while 2 <= n < len(rows):
        gap_down = rows[n]["c"] - rows[n - 1]["c"]
        gap_up = rows[n - 1]["c"] - rows[n - 2]["c"]
        if gap_down < lh and gap_down < 0.5 * gap_up:
            n -= 1
        else:
            break
    return n


# ---------------------------------------------------------------------------------------------
# 3. columns
# ---------------------------------------------------------------------------------------------
def ink_coverage(rows, x0, x1, step=0.5):
    """For every x (in `step` pt bins): how many lines have a word covering it.
    Columns show up as plateaus, the white gutters between them as valleys."""
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
    """Gutters = x-ranges with ink in at most tolerance * lines lines, at least min_w wide."""
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
            # a tolerant valley that runs into the table edge is really a sparse first/last
            # column (filled in 2 of 24 lines): inside it, use strictly empty gaps instead
            out += [(p, q) for p, q in runs(0) if p >= a and q <= b and q - p >= min_w
                    and p > x0 and q < x1]
    return sorted(out)


def column_cuts(rows, ws, n_hdr, lh):
    """-> (cuts, gutters). cuts = x of every column boundary, incl. the table's left/right edge.

    - Columns are measured on the DATA lines. Header words often sit closer together than the
      values under them (two header names touching), so letting the header decide would merge
      two real columns.
    - A gutter may be crossed by up to 12% of the lines (a spanning title, a section label, a
      long wrapped cell) when there are 8+ lines.
    - EMPTY COLUMN: a header phrase lying entirely inside a data gutter is a column with no
      values this month; it gets its own slot.
    - The cut is placed in the middle of the widest INK-FREE part of the gutter, so one long
      cell poking into a wide gutter is not cut in two."""
    x0 = min(w["x0"] for w in ws)
    x1 = max(w["x1"] for w in ws)

    def single_phrase(r):            # titles, section labels: never define columns
        return all(b["x0"] - a["x1"] < lh * 0.6 for a, b in zip(r["ws"], r["ws"][1:]))
    lines = [r for r in rows if not single_phrase(r)]
    if len(lines) < 2:
        lines = rows
    head = rows[:n_hdr]
    body = [r for r in lines if r not in head]
    if len(body) >= 2 and head:
        gut = find_gutters(body, x0, x1, min_w=lh * 0.55, tolerance=0.12 if len(body) >= 8 else 0.0)
        gut = _rescue_empty_columns(gut, head, lh)
    else:
        gut = find_gutters(lines, x0, x1, min_w=lh * 0.55, tolerance=0.12 if len(lines) >= 8 else 0.0)

    def cut_in(a, b):
        spans = sorted((w["x0"], w["x1"]) for w in ws if w["x1"] > a and w["x0"] < b)
        free, cur = [], a
        for p, q in spans:
            if p > cur:
                free.append((cur, p))
            cur = max(cur, q)
        if cur < b:
            free.append((cur, b))
        if not free:
            return (a + b) / 2
        p, q = max(free, key=lambda t: t[1] - t[0])
        return (p + q) / 2
    return [x0 - 1] + [cut_in(a, b) for a, b in gut] + [x1 + 1], gut


def _rescue_empty_columns(gut, head, lh):
    """Split a data gutter around every header phrase that lies entirely inside it. A phrase that
    continues past the gutter is a wide header of a neighbouring column, not an empty column."""
    hdr_phrases = [ph for r in head for ph in phrases(r["ws"], lh * 0.45)]
    out = []
    for a, b in gut:
        inside = sorted((ph for ph in hdr_phrases if ph[0]["x0"] >= a - 0.5 and ph[-1]["x1"] <= b + 0.5),
                        key=lambda ph: ph[0]["x0"])
        if not inside:
            out.append((a, b))
            continue
        edges = [a] + [e for ph in inside for e in (ph[0]["x0"], ph[-1]["x1"])] + [b]
        for left, right in zip(edges[0::2], edges[1::2]):
            if right - left >= lh * 0.3:
                out.append((left, right))
    return out


# ---------------------------------------------------------------------------------------------
# 4. header names
# ---------------------------------------------------------------------------------------------
def header_names(rows, n_hdr, cuts, gut, lh, vocab=()):
    """Header text per column. The BOTTOM header line is placed by the data under it; the lines
    above it are placed by position (a phrase over several columns goes to all of them)."""
    ncol = len(cuts) - 1

    def col_of(x):
        return next(k for k in range(ncol) if cuts[k] <= x < cuts[k + 1])

    header = [""] * ncol
    # data extent of each column -> where the bottom header line's phrases belong
    extent = [None] * ncol
    for r in rows[n_hdr:]:
        for w in r["ws"]:
            k = col_of(cx(w))
            e = extent[k]
            extent[k] = (w["x0"], w["x1"]) if e is None else (min(e[0], w["x0"]), max(e[1], w["x1"]))
    for r in rows[:n_hdr]:
        if r is rows[n_hdr - 1]:
            _bottom_header_line(r, header, extent, gut, lh, vocab, col_of)
        else:
            _upper_header_line(r, rows, n_hdr, header, cuts, lh, col_of)
    return header


def _bottom_header_line(r, header, extent, gut, lh, vocab, col_of):
    """Each phrase goes to the column whose DATA it overlaps most (headers are often wider than
    their values). Empty columns have no data -> the column under the phrase centre.
    Two header names that TOUCH (one phrase spanning a data gutter) are split at the word gap
    nearest that gutter; if several gaps qualify, prefer a split where both halves are known
    header names (vocab = header regexes from config), then the widest gap."""
    split = []
    for ph in phrases(r["ws"], lh * 0.45):
        todo = [ph]
        while todo:
            p = todo.pop()
            a, b = p[0]["x0"], p[-1]["x1"]
            g = next(((ga, gb) for ga, gb in gut if a < ga - 1 and b > gb + 1 - (gb - ga)), None)
            if g is None or len(p) < 2:
                split.append(p)
                continue
            ga, gb = g
            near = [i for i in range(len(p) - 1) if max(0, ga - p[i]["x1"], p[i + 1]["x0"] - gb) <= lh]
            if not near:
                split.append(p)
                continue

            def known(ws_):
                t = " ".join(w["t"] for w in ws_).lower()
                return any(re.search(v, t) for v in vocab)
            i = max(near, key=lambda i: (known(p[:i + 1]) + known(p[i + 1:]), p[i + 1]["x0"] - p[i]["x1"]))
            todo += [p[:i + 1], p[i + 1:]]
    for ph in sorted(split, key=lambda p: p[0]["x0"]):
        a, b = ph[0]["x0"], ph[-1]["x1"]
        ov = [(min(b, e[1]) - max(a, e[0]), k) for k, e in enumerate(extent) if e]
        best = max(ov) if ov else (0, None)
        k = best[1] if best[0] > 0 else col_of((a + b) / 2)
        header[k] = join(header[k], " ".join(w["t"] for w in ph))


def _upper_header_line(r, rows, n_hdr, header, cuts, lh, col_of):
    """A phrase spanning several columns ('Rating' over Original | Current) is added to every
    column it covers - unless its words each sit inside ONE column and line up with the header
    word below them: then they are separate headers that happen to be close together."""
    ncol = len(cuts) - 1
    for ph in phrases(r["ws"], lh * 0.6):
        a, b = ph[0]["x0"], ph[-1]["x1"]
        txt = " ".join(w["t"] for w in ph)
        spans = [k for k in range(ncol) if min(b, cuts[k + 1]) - max(a, cuts[k]) > 0.25 * (b - a)]

        def inside(w):
            k = col_of(cx(w))
            return min(w["x1"], cuts[k + 1]) - max(w["x0"], cuts[k]) >= 0.8 * (w["x1"] - w["x0"])

        def aligned(w):            # the header word right below starts, ends or centres with it
            k = col_of(cx(w))
            below = [v for rr in rows[:n_hdr] if rr["c"] > r["c"] for v in rr["ws"] if col_of(cx(v)) == k]
            if not below:
                return False
            v = min(below, key=lambda v: v["y0"])
            return abs(v["x0"] - w["x0"]) < 2 or abs(v["x1"] - w["x1"]) < 2 or abs(cx(v) - cx(w)) < 0.5 * lh
        word_cols = {col_of(cx(w)) for w in ph}
        if len(spans) > 1 and len(word_cols) > 1 and all(inside(w) for w in ph) and all(aligned(w) for w in ph):
            for w in ph:
                k = col_of(cx(w))
                header[k] = join(header[k], w["t"])
            continue
        for k in spans or [col_of((a + b) / 2)]:
            header[k] = join(header[k], txt)


# ---------------------------------------------------------------------------------------------
# 5. body rows
# ---------------------------------------------------------------------------------------------
def body_rows(lines, cuts, lh):
    """Data lines -> table rows. A cell printed on several lines is glued back into one row:

    - TOP-ALIGNED cells (the usual case): a continuation line is glued to the row ABOVE when it
      fills at most 1-2 cells, few of the 'anchor' columns (columns filled in most lines), and
      sits within 1.25 normal line steps; or (older rule) has no digits and is close.
    - CENTRED cells: some reports centre a 2-3 line cell vertically on its row, so text lines sit
      both above AND below the line with the amounts. Detected per table (a full row with a
      text-only line directly above and below at equal distance); then every text-only line goes
      to the NEARER full row.
    - Never glued: a line containing 'Total'/'Subtotal' (its own row), and a lone column-0 label
      after a row whose column 0 is empty (that row is a subtotal; the label starts a section)."""
    ncol = len(cuts) - 1

    def to_cells(ws):
        cells = [""] * ncol
        for w in ws:
            k = next(k for k in range(ncol) if cuts[k] <= cx(w) < cuts[k + 1])
            cells[k] = join(cells[k], w["t"])
        return cells
    all_cells = [(r, to_cells(r["ws"])) for r in lines]
    fill = [sum(bool(c[k]) for _, c in all_cells) / max(len(all_cells), 1) for k in range(ncol)]
    anchors = [k for k in range(ncol) if fill[k] >= 0.6]
    steps = [b["c"] - a["c"] for (a, _), (b, _) in zip(all_cells, all_cells[1:])]
    normal_step = st.median(steps) if steps else 2 * lh
    prefix_of, suffix_ok = _centred_cells(all_cells, ncol, lh)

    pending = {}                                  # row index -> prefix lines waiting for it
    for j, nxt in prefix_of.items():
        cells = all_cells[j][1]
        pending[nxt] = cells if nxt not in pending else [join(a, b) for a, b in zip(pending[nxt], cells)]

    body, prev_c = [], None
    for j, (r, cells) in enumerate(all_cells):
        if j in prefix_of:
            continue
        if j in pending:
            cells = [join(a, b) for a, b in zip(pending[j], cells)]
        filled = sum(bool(c) for c in cells)
        only_first = filled == 1 and bool(cells[0])
        separate = TOTAL_WORD.search(" ".join(w["t"] for w in r["ws"])) or (only_first and body and not body[-1][0])
        if not separate and body:
            tight = prev_c is not None and r["c"] - prev_c <= 1.25 * normal_step
            no_anchor = (bool(anchors) and not only_first and filled <= 2
                         and sum(bool(cells[k]) for k in anchors) <= 0.3 * len(anchors))
            old_rule = not has_digit(r["ws"]) and filled <= max(1, 0.3 * ncol) and prev_c is not None \
                and r["c"] - prev_c < 1.6 * lh
            if (no_anchor and tight and len(anchors) >= 2) or old_rule or j in suffix_ok:
                body[-1] = [join(p, c) for p, c in zip(body[-1], cells)]
                prev_c = r["c"]
                continue
        body.append(cells)
        prev_c = r["c"]
    return body


def _centred_cells(all_cells, ncol, lh):
    """-> (prefix_of {line: row it belongs to, below it}, suffix_ok {lines glued to the row above}).
    Both empty unless the table shows the centred-cell signature."""
    # anchor columns measured on lines with digits (in centred layouts half the lines are text)
    digit_cells = [c for r, c in all_cells if has_digit(r["ws"])]
    anchors = [k for k in range(ncol)
               if digit_cells and sum(bool(c[k]) for c in digit_cells) / len(digit_cells) >= 0.6]

    def is_full(cells):
        return bool(anchors) and sum(bool(cells[k]) for k in anchors) > 0.3 * len(anchors)

    def text_only(r, cells):                     # partial line of text; no money amounts
        filled = sum(bool(c) for c in cells)
        return 0 < filled <= max(2, 0.35 * ncol) and not is_full(cells) and len(anchors) >= 2 and \
            not any(MONEY.match(w["t"].strip("€$£")) for w in r["ws"])
    kinds = ["full" if is_full(c) else ("text" if text_only(r, c) else "other") for r, c in all_cells]
    y = [r["c"] for r, _ in all_cells]
    centred = any(kinds[j] == "full" and kinds[j - 1] == "text" and kinds[j + 1] == "text"
                  and abs((y[j] - y[j - 1]) - (y[j + 1] - y[j])) <= 0.6 and y[j] - y[j - 1] < 0.8 * lh
                  for j in range(1, len(all_cells) - 1))
    prefix_of, suffix_ok = {}, set()
    if not centred:
        return prefix_of, suffix_ok
    fulls = [j for j, k in enumerate(kinds) if k == "full"]
    for j, k in enumerate(kinds):
        if k != "text":
            continue
        prv = next((f for f in reversed(fulls) if f < j), None)
        nxt = next((f for f in fulls if f > j), None)
        lo = (prv if prv is not None else -1) + 1
        hi = nxt if nxt is not None else len(kinds)
        if any(kinds[m] == "other" for m in range(lo, hi)):
            continue                              # a section label / subtotal in between
        d_prev = y[j] - y[prv] if prv is not None else float("inf")
        d_next = y[nxt] - y[j] if nxt is not None else float("inf")
        if d_next + 0.5 < d_prev:
            prefix_of[j] = nxt
        elif prv is not None:
            suffix_ok.add(j)
    return prefix_of, suffix_ok


# ---------------------------------------------------------------------------------------------
# 6. sections
# ---------------------------------------------------------------------------------------------
def split_sections(body, header, rows, n_hdr, cuts):
    """Lines with only a label in column 0 and no digits ("Loan", "Bond") are section labels:
    they become the `_section` value of the rows below instead of rows of their own.
    - a last header line that only fills column 0 is such a label too;
    - a label that REPEATS the current group value ("Automotive" again before its subtotal) is the
      subtotal's label and stays a row."""
    if n_hdr > 1 and all(cx(w) < cuts[1] for w in rows[n_hdr - 1]["ws"]):
        sec = " ".join(w["t"] for w in rows[n_hdr - 1]["ws"])
        header[0] = header[0].replace(sec, "").strip()
        body = [[sec] + [""] * (len(cuts) - 2)] + body
    norm = lambda t: " ".join(t.split()).lower()          # noqa: E731
    out, section, group = [], "", ""
    for cells in body:
        if cells[0] and not any(cells[1:]) and not any(ch.isdigit() for ch in cells[0]):
            if group and norm(cells[0]) == norm(group):
                out.append(cells + [section])
                continue
            section = cells[0]
            continue
        if cells[0] and any(cells[1:]):
            group = cells[0]
        out.append(cells + [section])
    return out


# ---------------------------------------------------------------------------------------------
# the whole thing
# ---------------------------------------------------------------------------------------------
def build_table(words, vocab=()):
    """Words of one table -> DataFrame (all cells text), or None.
    Columns are named by their header ('col<k>' if none); `_section` is added when the table has
    section labels. vocab = header regexes from config, only used to split touching headers."""
    rows0 = text_rows(words)
    # "There are no ... to report" messages are not part of the table
    msg = [r for r in rows0 if " ".join(w["t"] for w in r["ws"]).lower().startswith("there are no")]
    ws = [w for w in words if not any(w in r["ws"] for r in msg)] or words
    rows = text_rows(ws)
    lh = line_height(ws)
    first_data = header_size(rows, lh)
    cuts, gut = column_cuts(rows, ws, first_data or 0, lh)
    n_hdr = first_data if first_data is not None else len(rows)
    if n_hdr == len(rows) and len(cuts) - 1 < 3 and len(rows) > 2:
        n_hdr = 0                     # no data line and only 1-2 columns: plain text, not a header
    header = header_names(rows, n_hdr, cuts, gut, lh, vocab)
    body = body_rows(rows[n_hdr:], cuts, lh)
    table = split_sections(body, header, rows, n_hdr, cuts)

    cols = [h or f"col{k}" for k, h in enumerate(header)] + ["_section"]
    cols = [c if cols.count(c) == 1 else f"{c}_{k}" for k, c in enumerate(cols)]
    df = pd.DataFrame(table, columns=cols)
    if not df["_section"].any():
        df = df.drop(columns="_section")
    return df
