"""Performance: tests tables found by their HEADER WORDS, every row mapped to the schema.

Works on dashboards, side-by-side tables and banded pages because it never counts tables: it
anchors on a header line that holds a 'result' word (plus test/ratio/current) and reads the rows
below it, until a separator line, a big gap or the next header.

Header words -> roles (test, current, trigger, result, prior, skip) come from config
`performance.header_roles`; categories (Coverage test / Collateral Quality / Concentration
limitation) from `performance.categories` and `test_name_categories`.
"""
import re
import statistics as st

from .pdfpage import page_model, phrases, rows_of, to_num
from .crops import footer_top
from .table import is_data_line

RESULT_WORDS = r"^(pass(ed)?|fail(ed)?|n/?a|yes|no|true|false|met|not met|breach)$"
ITEM = re.compile(r"^\(?([a-z]{1,3}|[ivx]+)\)|^class\b", re.I)    # "(s) ...", "(ii) ...", "Class A ...": a new test


def category_of(section, test, page_title, pcfg):
    """Category from the section label, else the page title, else the test name itself."""
    for src in (section, page_title):
        for cat, pat in pcfg["categories"].items():
            if src and re.search(pat, src, re.I):
                return cat
    for cat, pat in pcfg.get("test_name_categories", {}).items():
        if re.search(pat, test, re.I):
            return cat
    return section or ""


def first_num(text):
    """'100.1% / 2,000,000.00' -> 100.1 ; '>= 120.00%' -> 120.0 ; plain numbers as-is."""
    v = to_num(text)
    if v is not None:
        return v
    for tok in re.split(r"\s+|/", text):
        v = to_num(tok)
        if v is not None:
            return v
    return None


def role_of(text, roles):
    """Header text -> role; roles are checked in config order, first match wins."""
    t = text.lower()
    for role, pat in roles.items():
        if re.search(pat, t):
            return role
    return None


def performance(page, cfg):
    """All test rows on one page: dicts with test, current, trigger, result, original tests,
    _status ('ok' or 'check: ...') and _page."""
    pcfg = cfg["performance"]
    roles = pcfg["header_roles"]
    result_words = pcfg.get("result_vocab", RESULT_WORDS)
    words, H, V = page_model(page)
    if not words:
        return []
    footer = footer_top(words, page.rect.height)          # page footer is never part of a table
    words = [w for w in words if w["y0"] < footer] or words
    rows = rows_of(words)
    lh = st.median(w["y1"] - w["y0"] for w in words)
    page_title = " ".join(r["text"] for r in rows if r["c"] < page.rect.height * 0.2)
    out = []
    for i, r in enumerate(rows):
        low = r["text"].lower()
        if not (re.search(roles["result"], low) and re.search(r"test|ratio|current", low)):
            continue
        # header = this row + the row(s) just above it that are part of the same header block
        hdr_rows = [r]
        j = i - 1
        while j >= 0 and r["c"] - rows[j]["c"] < 2.2 * lh and len(hdr_rows) < 3:
            hdr_rows.insert(0, rows[j])
            j -= 1
        # header lines can continue BELOW the result line (a line of dates, or the last line of
        # a 3-line header): lines right under it with no data belong to the header
        k = i + 1
        while k < len(rows) and rows[k]["c"] - rows[k - 1]["c"] < 2.2 * lh and not is_data_line(rows[k]["ws"]):
            k += 1
        hdr_rows += rows[i + 1:k]
        # anchor columns = phrases of the header line with the most phrases (the most complete
        # one, usually the bottom line); words of the other header lines attach to the anchor
        # they overlap (or are nearest to)
        anchor = max(hdr_rows, key=lambda hr: (len(phrases(hr["ws"], lh * 0.6)), hr is r))
        cols = [dict(p) for p in phrases(anchor["ws"], lh * 0.6)]
        for hr in hdr_rows:
            if hr is anchor:
                continue
            for w in hr["ws"]:
                wc = (w["x0"] + w["x1"]) / 2
                c = min(cols, key=lambda c: 0 if c["x0"] - 2 <= wc <= c["x1"] + 2 else
                        min(abs(wc - c["x0"]), abs(wc - c["x1"])))
                c["t"] = (w["t"] + " " + c["t"]) if hr["c"] < anchor["c"] else (c["t"] + " " + w["t"])
        cols.sort(key=lambda c: c["x0"])
        for c in cols:
            c["role"] = role_of(c["t"], roles)
        # 3) side-by-side tables: every 'test' column starts a new sub-table
        starts = [k for k, c in enumerate(cols) if c["role"] in ("test", "test2")
                  and not (k and cols[k - 1]["role"] in ("test", "test2"))] or [0]
        groups = [cols[a:b] for a, b in zip(starts, starts[1:] + [len(cols)])]
        # body: rows below header until a horizontal separator / big gap / next header
        body = []
        last_c = rows[k - 1]["c"]
        for nr in rows[k:]:
            sep = any(last_c < s.y0 < nr["c"] and s.width > 200 for s in H)
            if (sep and body) or nr["c"] - last_c > (3.0 if body else 8.0) * lh:
                break
            if re.search(roles["result"], nr["text"].lower()) and "test" in nr["text"].lower():
                break
            if any(s.y0 < nr["c"] < s.y1 for s in H):
                continue
            body.append(nr)
            last_c = nr["c"]
        for g_idx, g in enumerate(groups):
            gx0 = (groups[g_idx - 1][-1]["x1"] + 5) if g_idx else 0
            if g[0]["role"] in ("test", "test2"):
                gx0 = max(gx0, g[0]["x0"] - 15)
            nxt = groups[g_idx + 1][0]["x0"] - 5 if g_idx + 1 < len(groups) else 10_000
            gx1 = min(nxt, g[-1]["x1"] + 2 * lh)     # don't swallow an unrelated table on the right
            # the section title just above the header (e.g. a coloured bar 'Collateral Quality Tests')
            section = ""
            if j >= 0 and r["c"] - rows[j]["c"] < 5 * lh:
                above = [w for w in rows[j]["ws"] if gx0 <= (w["x0"] + w["x1"]) / 2 < gx1]
                if above and not any(ch.isdigit() for w in above for ch in w["t"]):
                    section = " ".join(w["t"] for w in above)
            last = None                                    # (last test row, its line's y)
            for br in body:
                ws = [w for w in br["ws"] if gx0 <= (w["x0"] + w["x1"]) / 2 < gx1]
                if not ws:
                    continue
                ps = phrases(ws, lh * 0.9)
                # one phrase, no numbers: the wrapped line of the test just above when it sits
                # right under it in the test column, else a section label
                if len(ps) == 1 and not any(ch.isdigit() for ch in ps[0]["t"]):
                    if _wraps(last, out, br, lh, ps[0]) and not ITEM.match(ps[0]["t"]):
                        out[-1]["test"] += " " + ps[0]["t"]
                        last = (out[-1], br["c"], last[2])
                    else:
                        section = ps[0]["t"]
                    continue
                name = None                                # first phrase of the test name
                rec = {"test": "", "current": None,
                       "trigger": None, "result": "", "original tests": section, "_page": page.number + 1}
                for p in ps:
                    pc = (p["x0"] + p["x1"]) / 2
                    # nearest header column by horizontal overlap / centre distance
                    best = min(g, key=lambda c: 0 if c["x0"] - 3 <= pc <= c["x1"] + 3 else
                               min(abs(pc - c["x0"]), abs(pc - c["x1"])))
                    role = best["role"]
                    if role == "skip":
                        continue
                    if role in ("test", "test2") or (role is None and not rec["test"] and to_num(p["t"]) is None):
                        rec["test"] = (rec["test"] + " " + p["t"]).strip()
                        name = name or p
                    elif role in ("current", "trigger"):
                        rec[role] = first_num(p["t"]) if rec[role] is None else rec[role]
                    elif role == "result":
                        rec["result"] = p["t"]
                if re.search(roles["test"] + "|" + roles["result"], rec["result"], re.I):
                    continue                               # a header line, not data
                has_result = bool(re.search(result_words, rec["result"] or "", re.I))
                if rec["current"] is None and not has_result:
                    # the wrapped second line of the test just above (name continues, and some
                    # layouts print the trigger there): glue it on; otherwise not a test row
                    if _wraps(last, out, br, lh) and \
                            (rec["test"] or rec["trigger"] is not None) and not ITEM.match(rec["test"]):
                        prev = out[-1]
                        prev["test"] = (prev["test"] + " " + rec["test"]).strip()
                        if prev["trigger"] is None:
                            prev["trigger"] = rec["trigger"]
                        last = (prev, br["c"], last[2])
                    continue
                if rec["test"] and (rec["current"] is not None or rec["result"]):
                    issues = []
                    if rec["current"] is None:
                        issues.append("no current")
                    if not re.search(result_words, rec["result"] or "", re.I):
                        issues.append("result?")
                    if to_num(rec["test"]) is not None or len(rec["test"]) < 4:
                        issues.append("test name?")
                    rec["_status"] = "ok" if not issues else "check: " + ", ".join(issues)
                    rec["original tests"] = category_of(section, rec["test"], page_title, pcfg)
                    out.append(rec)
                    last = (rec, br["c"], name)
    return out




def _wraps(last, out, br, lh, phrase=None):
    """Line br sits right under the last test row (< 1.6 line heights). A lone phrase must also
    look like the test name it continues: same text height, not starting left of it (a section
    label is printed larger and/or further left)."""
    if not (last and out and last[0] is out[-1] and br["c"] - last[1] < 1.6 * lh):
        return False
    name = last[2]
    if phrase is None or name is None:
        return phrase is None
    return phrase["h"] <= 1.1 * name["h"] and phrase["x0"] >= name["x0"] - 0.5 * lh
