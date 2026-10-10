"""Balance: label -> value, with explicit rules and an explicit status. Never a silent guess.

Three forms per field (config `balance.labels`):
  [regex, ...]                       label lookup
  {labels: [...], column: regex}     label lookup; with several numbers, take the one under `column`
  {page: regex, column: regex}       TOTAL of a column on the page(s) titled `page` (table_total)

Label lookup, for every phrase on a page that matches a label:
  1. RIGHT : the run of numbers immediately right of the label on the same line, stopping at the
             next text or a vertical rule. One number -> taken. Several (Current | Prior) -> the one
             under the header matching `column`, else the first one, flagged 'ambiguous'.
  2. BELOW : nothing to the right -> exactly one number directly under the label.
Status per field: ok | ambiguous | conflict (same label, different values) | missing.
Across pages the first match in `pages.balance` order wins.
"""
import re
import statistics as st

from .crops import page_tables
from .pages import page_texts
from .pdfpage import page_model, phrases, rows_of, to_num
from .totals import amount, mark_totals


def fields(cfg):
    """-> (label fields {field: {labels, column}}, table fields {field: {page, column}})"""
    label_fields, table_fields = {}, {}
    for field, spec in cfg["balance"]["labels"].items():
        if isinstance(spec, dict) and spec.get("page"):
            table_fields[field] = spec
        elif isinstance(spec, dict):
            label_fields[field] = dict(labels=spec.get("labels", []), column=spec.get("column"))
        else:
            label_fields[field] = dict(labels=spec, column=None)
    return label_fields, table_fields


def _is_num(t):
    return to_num(t) is not None


def candidates(page, cfg):
    """All (field, value, how, label, page) candidates on one page."""
    label_fields, _ = fields(cfg)
    words, _, V = page_model(page)
    if not words:
        return []
    rows = rows_of(words)
    lh = st.median(w["y1"] - w["y0"] for w in words)
    out = []
    for ri, r in enumerate(rows):
        ps = phrases(r["ws"], lh * 0.9)
        for k, p in enumerate(ps):
            label = p["t"].strip()
            if _is_num(label):
                continue
            for field, spec in label_fields.items():
                if not any(re.search(pt, label, re.I) for pt in spec["labels"]):
                    continue
                # 1) RIGHT: contiguous numbers right of the label, until text or a vertical rule
                nums = []
                for q in ps[k + 1:]:
                    if any(p["x1"] < v.x0 < q["x0"] and v.y0 <= r["c"] <= v.y1 for v in V):
                        break
                    if _is_num(q["t"]):
                        nums.append(q)
                    elif re.fullmatch(r"(EUR|USD|GBP|€|\$|%)", q["t"].strip()):
                        continue
                    else:
                        break
                if len(nums) == 1:
                    out.append((field, to_num(nums[0]["t"]), "right", label, page.number + 1))
                    continue
                if len(nums) > 1:
                    pick, how = nums[0], "ambiguous"
                    if spec["column"]:
                        # header row above with a phrase matching `column` over one of the numbers
                        for hr in reversed(rows[max(0, ri - 25):ri]):
                            hs = [h for h in phrases(hr["ws"], lh * 0.9) if re.search(spec["column"], h["t"], re.I)]
                            hit = [n for n in nums for h in hs if min(n["x1"], h["x1"]) - max(n["x0"], h["x0"]) > 0]
                            if hit:
                                pick, how = hit[0], "right/column"
                                break
                    out.append((field, to_num(pick["t"]), how, label, page.number + 1))
                    continue
                # 2) BELOW: number on the next line under the label
                if ri + 1 < len(rows) and rows[ri + 1]["c"] - r["c"] < 1.8 * lh:
                    below = [q for q in phrases(rows[ri + 1]["ws"], lh * 0.9) if _is_num(q["t"])
                             and min(q["x1"], p["x1"]) - max(q["x0"], p["x0"]) > 0]
                    if len(below) == 1:
                        out.append((field, to_num(below[0]["t"]), "below", label, page.number + 1))
    return out


def table_total(doc, cfg, spec):
    """Total of one column on the page(s) whose title matches spec['page'].

    value  = the printed total under that column if there is one, else the sum of the rows
    status = ok             printed total == sum of rows (or only one of them exists)
             conflict       printed total != sum of rows (the printed total is used)
             ok (no rows)   the page exists but has no rows ("There are no ...") -> 0
             missing        no page with that title in the report"""
    titles = page_texts(doc, cfg.get("layout", {}).get("title_band", 0.2))
    pages = [i for i, t in enumerate(titles) if re.search(spec["page"], t["title"], re.I)]
    if not pages:
        return dict(value=None, status="missing", how="table", label=spec["page"], page=None, n=0)
    rows_sum, n_rows, printed = 0.0, 0, None
    for i in pages:
        for _, raw in page_tables(doc[i]):
            cols = [c for c in raw.columns if re.search(spec["column"], str(c), re.I)]
            if not cols:
                continue
            marked = mark_totals(raw)
            for kind, v in zip(marked.get("_row", ["detail"] * len(marked)), marked[cols[0]]):
                x = amount(v)
                if x is None:
                    continue
                if kind == "detail":
                    rows_sum += x
                    n_rows += 1
                else:
                    printed = x
    page_no = pages[0] + 1
    if n_rows == 0 and printed is None:
        return dict(value=0.0, status="ok (no rows)", how="table", label=spec["page"], page=page_no, n=0)
    if printed is not None and n_rows and abs(printed - rows_sum) > 0.01:
        return dict(value=printed, status="conflict", how="table: printed total vs sum",
                    label=spec["page"], page=page_no, n=n_rows)
    value = printed if printed is not None else round(rows_sum, 2)
    how = ("table: printed total" + (" = sum of rows" if n_rows else "")) if printed is not None \
        else "table: sum of rows"
    return dict(value=value, status="ok", how=how, label=spec["page"], page=page_no, n=n_rows)


def resolve(cands, cfg):
    """Pick one value per label field and say how sure we are."""
    result = {}
    for field in fields(cfg)[0]:
        cs = [c for c in cands if c[0] == field]
        if not cs:
            result[field] = dict(value=None, status="missing", how="", label="", page=None, n=0)
            continue
        first = cs[0]
        same_label = [c for c in cs if c[3].lower() == first[3].lower()]
        values = {c[1] for c in same_label}
        status = "conflict" if len(values) > 1 else ("ambiguous" if first[2] == "ambiguous" else "ok")
        result[field] = dict(value=first[1], status=status, how=first[2], label=first[3],
                             page=first[4], n=len(cs))
    return result
