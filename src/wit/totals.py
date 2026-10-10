"""Subtotals, totals and groups of a table, and joining a table that runs over a page break.

    parts  = [(page_index, df), ...]          raw tables from crops.page_tables, in reading order
    joined = stitch_pages(parts)              -> [(pages, df)]  one df per table, pages joined
    marked = mark_totals(df)                  -> df + columns _row and _check

mark_totals() adds:
  _row    detail | subtotal | total
  _check  ""  |  "ok"  |  "check: <why>"      (only on subtotal / total rows)

and, in GROUPED tables (group columns printed only on a group's first row, e.g. an industry name
and its scores, followed by that industry's issuers), copies the group values down to every row
of the group. Nothing is invented: copied values come from the group's own first row.

A subtotal / total that equals the sum of its rows proves no row was lost or merged.
"""
import pandas as pd

from .pdfpage import NUM, to_num
from .table import TOTAL_WORD


def amount(v):
    """Cell text -> number, or None. Percentages are never summed."""
    return to_num(v, percent=False)


def is_number(v):
    """Cell holds one number (percentages included)."""
    s = v.strip()
    return bool(NUM.match(s)) and amount(s.rstrip("%")) is not None


# ---------------------------------------------------------------------------------------------
# tables over page breaks
# ---------------------------------------------------------------------------------------------
def stitch_pages(parts):
    """Join raw tables that run over a page break into one table.

    A table continues on the next page only if it is the LAST table on its page, the next part is
    the FIRST table on the following page, and both have the same columns. A section ('Loan',
    'Bond') also carries over: leading rows of a continued page that have no section yet belong
    to the previous page's last section. Returns [(pages, df)] in reading order."""
    first, last = {}, {}
    for k, (i, _) in enumerate(parts):
        first.setdefault(i, k)
        last[i] = k
    runs = []                                             # (pages, dfs, columns, index of last part)
    for k, (i, raw) in enumerate(parts):
        sig = tuple(c for c in raw.columns if not str(c).startswith("_"))
        if runs:
            pages, dfs, psig, pk = runs[-1]
            if psig == sig and i == pages[-1] + 1 and pk == last[pages[-1]] and k == first[i]:
                runs[-1] = (pages + [i], dfs + [raw], sig, k)
                continue
        runs.append(([i], [raw], sig, k))
    out = []
    for pages, dfs, _, _ in runs:
        sec = ""
        for k, d in enumerate(dfs):
            if "_section" not in d and not sec:
                continue
            d = d.copy()
            col = d["_section"].fillna("").astype(str) if "_section" in d else pd.Series("", index=d.index)
            if sec:
                lead = col.eq("").cumprod().astype(bool)          # rows before the page's first label
                col[lead] = sec
            d["_section"] = col
            dfs[k] = d
            if col.str.strip().any():
                sec = col[col.str.strip() != ""].iloc[-1]
        out.append((pages, pd.concat(dfs, ignore_index=True).fillna("").astype(str)))
    return out


# ---------------------------------------------------------------------------------------------
# subtotals and totals
# ---------------------------------------------------------------------------------------------
def mark_totals(df):
    """See module docstring. Steps:
      1. classify lines: a SUM line holds amounts and no text except a 'Total ...' label; a
         '<label>' line directly followed by a sum line is that sum's label (merged into it)
      2. group columns = sparse columns LEFT of the first densely filled column
      3. walk the rows: copy group values down; check every sum against the rows it closes:
           group subtotal  -> rows of the current group
           section subtotal ('Bond Subtotal:') -> rows of that section
           total           -> all rows since the previous total"""
    df = df.fillna("").astype(str).reset_index(drop=True)
    cols = [c for c in df.columns if not c.startswith("_")]
    if not cols:
        return df
    first = cols[0]
    text_cols = [c for c in cols if _mostly_text(df[c])]
    out, kinds = _classify_lines(df, cols, text_cols, first)
    if "sum" not in kinds:
        return out
    det = out[out["_row"] == "detail"]
    fill = {c: (det[c].str.strip() != "").mean() if len(det) else 0 for c in cols}
    dense = next((k for k, c in enumerate(cols) if fill[c] >= 0.6), 0)
    group_cols = [c for c in cols[:dense] if fill[c] < 0.6]
    _walk(out, cols, text_cols, group_cols, first)
    if group_cols and "_section" in out:
        out = out.drop(columns="_section")      # in a grouped table, section lines are group labels
    return out


def _mostly_text(col):
    filled = [v for v in col if v.strip()]
    return bool(filled) and sum(is_number(v) for v in filled) / len(filled) < 0.5


def _classify_lines(df, cols, text_cols, first):
    def label_only(row):
        return bool(row[first].strip()) and not any(row[c].strip() for c in cols[1:]) and not is_number(row[first])

    def sum_line(row):
        if not any(is_number(row[c]) for c in cols):
            return False
        texts = [row[c].strip() for c in text_cols if row[c].strip() and not is_number(row[c])]
        return not texts or (len(texts) == 1 and bool(TOTAL_WORD.search(texts[0])))

    rows, kinds, i = [], [], 0
    recs = df.to_dict("records")
    while i < len(recs):
        row = dict(recs[i])
        if label_only(row) and i + 1 < len(recs) and sum_line(recs[i + 1]):
            nxt = dict(recs[i + 1])
            nxt[first] = row[first]
            rows.append(nxt)
            kinds.append("sum")
            i += 2
            continue
        rows.append(row)
        kinds.append("sum" if sum_line(row) else "detail")
        i += 1
    out = df.iloc[0:0].copy().reindex(range(len(rows)))
    for k, row in enumerate(rows):
        for c in df.columns:
            out.at[k, c] = row.get(c, "")
    out["_row"] = ["detail" if k == "detail" else "total" for k in kinds]
    out["_check"] = ""
    return out, kinds


def _walk(out, cols, text_cols, group_cols, first):
    num_cols = [c for c in cols if c not in text_cols]
    current, members, all_members = None, [], []
    has_sec = "_section" in out and not group_cols and out["_section"].str.strip().any()
    sec_members = {}                                     # section label -> its detail rows so far
    for k in range(len(out)):
        row = out.loc[k]
        if out.at[k, "_row"] == "detail":
            if has_sec:
                sec_members.setdefault(row["_section"], []).append(k)
            if group_cols and row[group_cols[0]].strip():
                same = current is not None and \
                    " ".join(row[group_cols[0]].split()) == " ".join(current[group_cols[0]].split())
                if not same:                             # a group repeated on a new page continues
                    current = {c: row[c] for c in group_cols}
                    members = []
            elif group_cols and current:
                for c in group_cols:
                    if not out.at[k, c].strip():
                        out.at[k, c] = current[c]
            members.append(k)
            all_members.append(k)
            continue

        # a sum line: which rows does it close?
        carried = bool(group_cols) and current is None and not all_members     # group began earlier
        is_sub = carried or (bool(group_cols) and current is not None and
                             (not row[first].strip() or row[first].strip() == current[group_cols[0]].strip()))
        rows_k = members if (is_sub and not carried) else ([] if carried else all_members)
        label = " ".join(row[c] for c in cols if row[c].strip() and not is_number(row[c])).lower()
        sec = row["_section"].strip() if has_sec else ""
        sec_sub = has_sec and sec and ("subtotal" in label or sec.lower() in label)
        if sec_sub:
            is_sub, rows_k = True, sec_members.get(row["_section"], [])
        out.at[k, "_row"] = "subtotal" if is_sub else "total"
        if carried and not row[first].strip() and "_section" in out and out.at[k, "_section"].strip():
            out.at[k, first] = out.at[k, "_section"]     # its label was read as a section line
        elif is_sub and not row[first].strip() and current:
            out.at[k, first] = current[group_cols[0]]
        labelled = bool(TOTAL_WORD.search(label))
        if not rows_k:
            if labelled:          # "Total Number of Upgrades | 4": a reported figure, not a sum
                out.at[k, "_row"] = "detail"
            else:
                out.at[k, "_check"] = "check: its rows are on an earlier page"
            continue

        problems, compared = [], 0
        for c in num_cols:
            printed = amount(row[c])
            if printed is None:
                continue
            vals = [v for v in (amount(out.at[m, c]) for m in rows_k) if v is not None]
            if not vals:
                continue
            compared += 1
            s = sum(vals)
            if abs(s - printed) > 0.011 * max(1, len(vals)):
                problems.append(f"{c}: printed {printed:,.2f} vs rows {s:,.2f}")
        if not compared:          # its amount sits in a column the rows don't use
            out.at[k, "_check"] = "" if labelled else "check: nothing to compare with"
        elif not problems:
            out.at[k, "_check"] = "ok"
        elif labelled:            # "Total Principal Balance | ..." in a key-value box: a figure
            out.at[k, "_row"] = "detail"
        elif not is_sub or (rows_k and rows_k[0] == all_members[0]):
            out.at[k, "_check"] = "check: " + "; ".join(problems) + " (rows may start on an earlier page)"
        else:
            out.at[k, "_check"] = "check: " + "; ".join(problems)
        if sec_sub:
            sec_members[row["_section"]] = []
        elif is_sub:
            members, current = [], None
        else:
            all_members = []
