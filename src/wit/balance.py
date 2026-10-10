"""Balance: label -> value, with explicit rules and an explicit status. Never a silent guess.

For every label match (the label must be its own phrase on the line, see config regexes):
  1. RIGHT : the run of numbers immediately to the right of the label on the same line,
             stopping at the next text or a vertical rule.
             - exactly 1 number                  -> taken
             - several numbers (Current | Prior) -> the one under the header matching the
                                                    field's `column` regex; otherwise the
                                                    first one, flagged 'ambiguous'
  2. BELOW : if nothing is to the right, a number directly under the label (next line,
             horizontally overlapping it). This handles stacked label-over-value layouts.
Across pages, candidates are kept in page order (the order of `pages.balance`).
Status per field: ok | ambiguous | conflict (same label, different values) | missing.
"""
import re
import statistics as st

from .pdfpage import page_model, phrases, rows_of, to_num

FIELDS = {}


def configure(cfg):
    """cfg['balance']['labels'][field] = list of regexes OR {labels: [...], column: regex}."""
    global FIELDS
    FIELDS = {}
    for field, spec in cfg["balance"]["labels"].items():
        if isinstance(spec, dict):
            FIELDS[field] = dict(labels=spec.get("labels", []), column=spec.get("column"))
        else:
            FIELDS[field] = dict(labels=spec, column=None)


def _is_num(t):
    return to_num(t) is not None


def candidates(page):
    """All (field, value, how, label, page) candidates on one page."""
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
            for field, spec in FIELDS.items():
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


def resolve(cands):
    """Pick one value per field and say how sure we are."""
    result = {}
    for field in FIELDS:
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


def balance(page):
    """Back-compat helper for --debug: field -> (value, page, label)."""
    return {f: (r["value"], r["page"], r["label"]) for f, r in resolve(candidates(page)).items()
            if r["status"] != "missing"}
