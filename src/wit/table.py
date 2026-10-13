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
    gut = sorted(gut + _seams(body if len(body) >= 3 else lines, x0, x1, gut, head))

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


def _seams(lines, x0, x1, gut, head=(), share=0.8):
    """Narrow gutters between two columns printed almost touching: a right-aligned column (all
    its values END at the same x) right before a left-aligned one (all values START at the same
    x). Taken only when, on most lines with a value right of it, the gap is clearly wider than a word space and both edges
    line up within 1 pt; and the text on one side changes from line to line, or a header line
    shows the same two edges (a repeated two-word cell like 'Senior Secured' is not two columns)."""
    if len(lines) < 3:
        return []
    lh = line_height([w for r in lines for w in r["ws"]])
    gaps = [(u["x1"], v["x0"]) for r in lines for u, v in zip(r["ws"], r["ws"][1:])
            if 0 < v["x0"] - u["x1"] < 0.6 * lh]                 # word spaces (and narrow seams)
    out = []
    for a, b in find_gutters(lines, x0, x1, min_w=0.5, tolerance=0.0):
        if any(min(b, gb) > max(a, ga) for ga, gb in gut):
            continue                               # already a gutter
        other = [q - p for p, q in gaps if q < a or p > b]   # word spaces elsewhere
        space = st.median(other) if other else 0.25 * lh
        pairs = []
        for r in lines:
            left = [w for w in r["ws"] if a - 1.5 <= w["x1"] <= a + 0.5]      # touching the gap
            right = [w for w in r["ws"] if b - 0.5 <= w["x0"] <= b + 1.5]
            if left and right and right[0]["x0"] - left[-1]["x1"] >= 1.6 * space:
                pairs.append((left[-1], right[0]))
        # lines with a value in the right-hand column (subtotal lines may only fill the left one)
        n_right = sum(any(a - 0.5 <= w["x0"] <= b + 1.5 for w in r["ws"]) for r in lines)
        if len(pairs) < max(2, share * n_right):
            continue
        ends = [lw["x1"] for lw, _ in pairs]
        starts = [rw["x0"] for _, rw in pairs]
        e, s0 = st.median(ends), st.median(starts)
        varies = len({lw["t"] for lw, _ in pairs}) > 1 or len({rw["t"] for _, rw in pairs}) > 1
        in_header = any(any(abs(w["x1"] - e) <= 1 for w in r["ws"]) and any(abs(w["x0"] - s0) <= 1 for w in r["ws"])
                        for r in head)
        if max(ends) - min(ends) <= 1 and max(starts) - min(starts) <= 1 and (varies or in_header):
            out.append((max(ends), min(starts)))
    return out


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
    # the bottom header line; a last line holding only a column-0 label is a section label
    # ('Loan'), not header (split_sections takes it), so the line above it is the bottom one
    bottom = n_hdr - 1
    if n_hdr > 1 and all(cx(w) < cuts[1] for w in rows[bottom]["ws"]):
        bottom -= 1
    for r in rows[:n_hdr]:
        if r is rows[bottom]:
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
            k = col_of(cx(w))      # (or there is none: the word is that column's whole name)
            below = [v for rr in rows[:n_hdr] if rr["c"] > r["c"] for v in rr["ws"] if col_of(cx(v)) == k]
            if not below:
                return True
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
def totals_above_header(rows):
    """Lines with a 'Total' word and amounts that sit above the column header: some layouts print
    the grand total on top of the table. Only when a header line (no data) separates them from
    the first real data line - a key-value box that starts with 'Totals:' is left alone."""
    first_real = next((i for i, r in enumerate(rows)
                       if is_data_line(r["ws"]) and not TOTAL_WORD.search(r["text"])), None)
    if first_real is None:
        return []
    header_between = [i for i in range(first_real) if not is_data_line(rows[i]["ws"])]
    return [rows[i] for i in range(first_real)
            if TOTAL_WORD.search(rows[i]["text"]) and is_data_line(rows[i]["ws"])
            and any(h > i for h in header_between)]


def build_table(words, vocab=(), rules=()):
    """Words of one table -> DataFrame (all cells text), or None.
    Columns are named by their header ('col<k>' if none); `_section` is added when the table has
    section labels. vocab = header regexes from config, only used to split touching headers.
    rules = y of the full-width rules inside the table (only used for ruled records)."""
    rec = ruled_records(text_rows(words), rules)
    if rec:
        return record_table(*rec, vocab)
    rows0 = text_rows(words)
    # not part of the table: "There are no ... to report" messages, and totals printed ABOVE the
    # column header ("Grand Totals: ..." on top of the table)
    above = totals_above_header(rows0)
    drop = [r for r in rows0 if r["text"].lower().startswith("there are no")] + above
    ws = [w for w in words if not any(w in r["ws"] for r in drop)] or words
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
    # a total printed above the header is kept aside (totals.stitch_pages puts it after the
    # table's last row, so it is checked against all rows, over every page)
    df.attrs["totals_above"] = [dict(zip(cols, _cells(r["ws"], cuts) + [""])) for r in above]
    return df


def _cells(ws, cuts):
    ncol = len(cuts) - 1
    cells = [""] * ncol
    for w in ws:
        k = min(max(next((k for k in range(ncol) if cuts[k] <= cx(w) < cuts[k + 1]), 0), 0), ncol - 1)
        cells[k] = join(cells[k], w["t"])
    return cells


# ---------------------------------------------------------------------------------------------
# ruled records: one record per band between rules, its first lines STACKED fields
# ---------------------------------------------------------------------------------------------
STACKED = "stacked: "                              # column name prefix of a stacked column


def amounts(ws):
    return sum(bool(MONEY.match(w["t"].strip("€$£"))) for w in ws)


def first_full_line(lines):
    """Index of the first line holding at least half as many amounts as the fullest line (a
    number inside a name, 'Holdings 2.50', does not make a line full), or None."""
    most = max((amounts(r["ws"]) for r in lines), default=0)
    return next((i for i, r in enumerate(lines) if most and amounts(r["ws"]) >= max(1, most / 2)), None)


def ruled_records(rows, rules):
    """Some layouts print every security as a RECORD between two rules: a few text lines first
    (several fields stacked in one column, e.g. issuer / country / ID, or four industries), then
    the line(s) with the amounts. The header repeats the stacking.
    -> (header lines, [(stacked lines, amount lines) per record]) when every band below the first
    rule starts with text and holds amounts (2+ records), else None. The last band may be a
    line of amounts only (the total printed under the records)."""
    ys = sorted(y for y in rules if rows and rows[0]["c"] < y < rows[-1]["c"])
    if len(ys) < 2:
        return None
    bands = [[r for r in rows if a < r["c"] < b] for a, b in zip([-1e9] + ys, ys + [1e9])]
    header, records = bands[0], [b for b in bands[1:] if b]
    if not header or len(records) < 2:
        return None
    out = []
    for n, b in enumerate(records):
        k = first_full_line(b)
        last_total = n == len(records) - 1 and k == 0 and all(amounts(r["ws"]) == len(r["ws"]) for r in b)
        if not k and not last_total:               # no amounts, or no text before them
            return None
        out.append((b[:k], b[k:]))                 # a total under the last record: no text
    return header, out


def _stacks(records, lh):
    """x where stacked fields start: phrases of the text lines, left edges clustered."""
    xs = sorted(p[0]["x0"] for st_lines, _ in records for r in st_lines for p in phrases(r["ws"], lh * 0.9))
    starts = []
    for x in xs:
        if not starts or x - starts[-1][-1] > 1.5 * lh:
            starts.append([x])
        else:
            starts[-1].append(x)
    return [min(g) for g in starts]


def record_table(header, records, vocab=()):
    """Ruled records -> DataFrame. The amount lines are read like any table (columns measured on
    them, header named from the header lines). Each stack becomes ONE column holding its lines
    joined with ' | ' (top to bottom), named 'stacked: ' + the header names stacked there joined
    with ' / '. Which line is which field is not decided (a field can be missing or wrap), so
    collateral does not map stacked columns."""
    lh = line_height([w for _, lines in records for r in lines for w in r["ws"]])   # amount lines
    starts = _stacks(records, lh)

    def stack_of(x0):
        k = min(range(len(starts)), key=lambda i: abs(starts[i] - x0))
        return k if abs(starts[k] - x0) <= 1.5 * lh else None

    names = [[] for _ in starts]
    rest = []                                       # header words of the amount columns
    for r in header:
        for p in phrases(r["ws"], lh * 0.9):
            k = stack_of(p[0]["x0"])
            if k is None:
                rest += p
            else:
                names[k].append(" ".join(w["t"] for w in p))
    data = [r for _, lines in records for r in lines]
    hrows = text_rows(rest) if rest else []
    rows = hrows + data
    ws = [w for r in rows for w in r["ws"]]
    cuts, gut = column_cuts(rows, ws, len(hrows), lh)
    head = header_names(rows, len(hrows), cuts, gut, lh, vocab)
    table = []
    for st_lines, lines in records:
        stacked = [[] for _ in starts]
        for r in st_lines:
            for p in phrases(r["ws"], lh * 0.9):
                k = stack_of(p[0]["x0"])
                k = k if k is not None else min(range(len(starts)), key=lambda i: abs(starts[i] - p[0]["x0"]))
                stacked[k].append(" ".join(w["t"] for w in p))
        for cells in body_rows(lines, cuts, lh):
            table.append([" | ".join(v) for v in stacked] + cells)
    cols = [STACKED + (" / ".join(n) or f"col{k}") for k, n in enumerate(names)] + \
        [h or f"col{k}" for k, h in enumerate(head)]
    cols = [c if cols.count(c) == 1 else f"{c}_{k}" for k, c in enumerate(cols)]
    df = pd.DataFrame(table, columns=cols)
    df.attrs["totals_above"] = []
    return df
