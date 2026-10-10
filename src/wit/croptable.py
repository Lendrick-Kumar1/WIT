"""Read ONE crop as ONE table (crops come from crops.find_crops, so they hold exactly one table).

    df = read_crop(page)          # page = the crop page (CropBox already set)

On top of geometry.build_table this:
  1. never re-segments the crop (that split 1-row tables and total rows off before);
  2. takes as DATA only rows that hold a real number, so header lines with dates
     ("Current 5/2/2024 | Prior 4/3/2024") stay header;
  3. GROUPED tables (Industry | score | issuer...): copies the group columns down to every row of
     the group, and turns "<group name>" + "<amount>" lines into one SUBTOTAL row;
  4. CHECKS every subtotal / total against the sum of its rows.

Extra output columns:
  _row    detail | subtotal | total
  _check  ""  |  "ok"  |  "check: <why>"        (only on subtotal / total rows)
Nothing is invented: copied-down values come from the group's own first row on the same crop.
"""
import re

from . import geometry as G
from .pdfpage import page_model

NUMBER = re.compile(r"^\(?-?[\d,]*\.?\d+%?\)?$")       # 1,234.50  (5.2)  4.19%  57   (no dates)
TOTAL = re.compile(r"^(sub-?)?totals?\b", re.I)          # "Total", "Totals:", "Total for B:", "Subtotal"


def is_data_row(ws):
    """Data = the row holds a real number, or it is a 'Label: value' pair (key-value boxes).
    Header lines with dates only ("Current 5/2/2024 | Prior 4/3/2024") are NOT data."""
    if any(NUMBER.match(w["t"]) for w in ws):
        return True
    return any(w["t"].endswith(":") for w in ws[:-1]) and not ws[-1]["t"].endswith(":")


def crop_words(page):
    """Words whose centre lies inside the crop (PyMuPDF also returns words clipped by the edge)."""
    words, H, V = page_model(page)
    W, Ht = page.rect.width, page.rect.height
    inside = [w for w in words if 0 <= (w["x0"] + w["x1"]) / 2 <= W and 0 <= (w["y0"] + w["y1"]) / 2 <= Ht]
    return inside, H, V


def _num(v):
    if v is None or str(v).strip() == "":
        return None
    s = str(v).strip()
    if s.endswith("%"):
        return None                     # percentages are never summed
    return G.to_number(s)


def read_crop(page):
    ws, _, _ = crop_words(page)
    if len(ws) < 3:
        return None
    r = G.Region(page=page.number + 1, words=ws, bbox=G.bbox(ws))
    G.build_table(r, data_row=is_data_row)
    if r.df is None or not len(r.df) or r.df.shape[1] < 2:
        return None
    return group_rows(r.df)


def group_rows(df):
    df = df.fillna("").astype(str).reset_index(drop=True)
    cols = [c for c in df.columns if not c.startswith("_")]
    if not cols:
        return df
    first = cols[0]

    def is_num(v):
        return bool(NUMBER.match(v.strip())) and _num(v.strip().rstrip("%")) is not None

    # text columns = columns whose filled cells are mostly not numbers
    text_cols = []
    for c in cols:
        filled = [v for v in df[c] if v.strip()]
        if filled and sum(is_num(v) for v in filled) / len(filled) < 0.5:
            text_cols.append(c)

    def label_only(row):
        return bool(row[first].strip()) and not any(row[c].strip() for c in cols[1:]) \
            and not is_num(row[first])

    def num_only(row):
        """subtotal / total line: amounts, and no text except a 'Total ...' label"""
        if not any(is_num(row[c]) for c in cols):
            return False
        texts = [row[c].strip() for c in text_cols if row[c].strip() and not is_num(row[c])]
        return not texts or (len(texts) == 1 and bool(TOTAL.match(texts[0])))

    # 1) merge "<label>" + "<amounts>" lines into one subtotal row
    rows, kinds, i = [], [], 0
    recs = df.to_dict("records")
    while i < len(recs):
        row = dict(recs[i])
        if label_only(row) and i + 1 < len(recs) and num_only(recs[i + 1]):
            nxt = dict(recs[i + 1])
            nxt[first] = row[first]
            rows.append(nxt)
            kinds.append("sum")
            i += 2
            continue
        rows.append(row)
        kinds.append("sum" if num_only(row) else "detail")
        i += 1

    out = df.iloc[0:0].copy()
    out = out.reindex(range(len(rows)))
    for k, row in enumerate(rows):
        for c in df.columns:
            out.at[k, c] = row.get(c, "")
    out["_row"] = ["detail" if k == "detail" else "total" for k in kinds]
    out["_check"] = ""
    if "sum" not in kinds:
        return out

    # 2) group columns = sparse columns LEFT of the first densely filled column
    det = out[out["_row"] == "detail"]
    fill = {c: (det[c].str.strip() != "").mean() if len(det) else 0 for c in cols}
    dense_idx = next((k for k, c in enumerate(cols) if fill[c] >= 0.6), 0)
    group_cols = [c for c in cols[:dense_idx] if fill[c] < 0.6]

    # 3) walk the rows: copy group values down, check every subtotal/total
    num_cols = [c for c in cols if c not in text_cols]
    current, members, all_members = None, [], []
    for k in range(len(out)):
        row = out.loc[k]
        if out.at[k, "_row"] == "detail":
            if group_cols and row[group_cols[0]].strip():
                current = {c: row[c] for c in group_cols}
                members = []
            elif group_cols and current:
                for c in group_cols:
                    if not out.at[k, c].strip():
                        out.at[k, c] = current[c]
            members.append(k)
            all_members.append(k)
            continue
        # subtotal or total row
        carried = bool(group_cols) and current is None and not all_members   # group began earlier
        is_sub = carried or (bool(group_cols) and current is not None and
                             (not row[first].strip() or row[first].strip() == current[group_cols[0]].strip()))
        rows_k = members if (is_sub and not carried) else ([] if carried else all_members)
        out.at[k, "_row"] = "subtotal" if is_sub else "total"
        if carried and not row[first].strip() and "_section" in out and out.at[k, "_section"].strip():
            out.at[k, first] = out.at[k, "_section"]      # its label sat above, as a 'section' line
        elif is_sub and not row[first].strip() and current:
            out.at[k, first] = current[group_cols[0]]
        labelled = any(TOTAL.match(row[c].strip()) for c in text_cols if row[c].strip())
        if not rows_k:
            if labelled:                 # "Total Number of Upgrades | 4": a reported figure, not a sum
                out.at[k, "_row"] = "detail"
            else:
                out.at[k, "_check"] = "check: its rows are on an earlier page"
            continue
        problems, compared = [], 0
        for c in num_cols:
            printed = _num(row[c])
            if printed is None:
                continue
            vals = [_num(out.at[m, c]) for m in rows_k]
            vals = [v for v in vals if v is not None]
            if not vals:
                continue
            s = sum(vals)
            compared += 1
            if abs(s - printed) > 0.011 * max(1, len(vals)):
                problems.append(f"{c}: printed {printed:,.2f} vs rows {s:,.2f}")
        if not compared:
            # its amount sits in a column the rows don't use ("Total for B:" one column right)
            out.at[k, "_check"] = "" if labelled else "check: nothing to compare with"
        elif not problems:
            out.at[k, "_check"] = "ok"
        elif labelled:
            out.at[k, "_row"] = "detail"     # "Total Principal Balance | 446m" in a key-value box
        elif not is_sub or (rows_k and rows_k[0] == all_members[0]):
            # first group / grand total on the crop: its rows may continue from an earlier page
            out.at[k, "_check"] = "check: " + "; ".join(problems) + " (rows may start on an earlier page)"
        else:
            out.at[k, "_check"] = "check: " + "; ".join(problems)
        if is_sub:
            members, current = [], None
        else:
            all_members = []
    # in a grouped table, 'section' lines are group labels (already used above)
    if group_cols and "_section" in out:
        out = out.drop(columns="_section")
    return out
