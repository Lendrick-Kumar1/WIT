"""Collateral: one row per security, joined from several long tables (assets, ratings, ...).

  1. every collateral page is cut into crops, each read as one table          (crops.page_tables)
  2. a table running over a page break is joined into one table             (totals.stitch_pages)
  3. subtotals / totals are checked against their rows, groups copied down   (totals.mark_totals)
  4. column headers are mapped to the output schema via synonyms             (config collateral.columns)
  5. tables with an ID column are joined on the security ID:
       - rows come from the table with the most distinct securities
       - each column comes from the table whose header names it most directly
  6. optional (--fallback): a crop whose IDs or sums fail is re-read by XLarge (fallback.py);
     XLarge's table is used only if it passes where PyMuPDF's failed

collateral() returns (rows, checks, fallback_events); run.py writes the checks to the run report.
"""
import re

import pandas as pd

from .crops import page_tables
from .pdfpage import to_num
from .table import STACKED
from .totals import mark_totals, stitch_pages

ID_FIELD = "loan id"


# ---------------------------------------------------------------------------------------------
# header -> schema field
# ---------------------------------------------------------------------------------------------
def _synonyms(pat):
    """Top-level '|' alternatives of a synonym regex, in config order (specific first)."""
    out, depth, cur = [], 0, ""
    for ch in pat:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "|" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def _is_field_name(header, field):
    return re.sub(r"[^a-z0-9&']+", " ", header.lower()).strip() == field


def header_rank(header, field, columns_cfg):
    """How directly a header names a field: 0 = it IS the field name, else 1 + the position of the
    first synonym it matches ('Issuer Name' -> 1, 'Description' -> 4 for the issuer field)."""
    if _is_field_name(header, field):
        return 0
    hl = header.lower()
    return 1 + next((k for k, alt in enumerate(_synonyms(columns_cfg.get(field) or ""))
                     if alt and re.search(alt, hl)), 98)


def map_headers(headers, columns_cfg):
    """{header: field}. Each header goes to the first field whose synonyms match it (config order
    matters). If several headers want the same field, a header that IS the field's name wins
    ('Principal Balance' over 'Par/Quantity'); otherwise the first one."""
    best = {}                                      # field -> (rank, position, header)
    for pos, h in enumerate(headers):
        if h.startswith(STACKED):
            continue                               # several fields in one column: not mapped
        for field, pat in columns_cfg.items():
            if not pat or not re.search(pat, h.lower()):
                continue
            rank = 0 if _is_field_name(h, field) else 1
            if field not in best or (rank, pos) < best[field][:2]:
                best[field] = (rank, pos, h)
            break
    return {h: f for f, (_, pos, h) in sorted(best.items(), key=lambda kv: kv[1][1])}


def norm_id(v, patterns):
    """The token that LOOKS like a security ID (patterns from config: LoanX, ISIN, FIGI, CUSIP),
    so text that overflowed from a neighbouring column doesn't pollute the key."""
    s = str(v or "").upper()
    toks = re.findall(r"[A-Z0-9]+", s)
    for pat in patterns:
        for tok in toks:
            if re.fullmatch(pat, tok):
                return tok
    s = re.sub(r"\s+", "", s)
    return s if re.fullmatch(r"[A-Z0-9]{6,14}", s) and re.search(r"\d", s) else ""   # IDs carry digits


# ---------------------------------------------------------------------------------------------
# reading the pages
# ---------------------------------------------------------------------------------------------
def header_vocab(cfg):
    """Known header names (regexes), used to split two header names that touch."""
    return [v for v in cfg["collateral"]["columns"].values() if v] + \
        [v for v in cfg.get("performance", {}).get("header_roles", {}).values() if v]


def _id_share(df, cfg):
    """(has an ID column, share of detail rows with a valid ID)."""
    m = map_headers([str(c) for c in df.columns if not str(c).startswith("_")], cfg["collateral"]["columns"])
    id_cols = [h for h, f in m.items() if f == ID_FIELD]
    if not id_cols:
        return False, 0.0
    det = df[df["_row"] == "detail"] if "_row" in df else df
    if not len(det):
        return True, 0.0
    pats = cfg["collateral"]["id_patterns"]
    return True, sum(bool(norm_id(v, pats)) for v in det[id_cols[0]]) / len(det)


def _failed_sums(marked):
    """Checks that point at a READING problem (not 'rows are on an earlier page')."""
    if "_check" not in marked:
        return []
    return [c for c in marked["_check"] if c.startswith("check:") and "earlier page" not in c]


def read_pages(doc, page_idx, cfg, xl=None, events=None):
    """[(page_index, table)] for every crop of the given pages, in reading order.
    With xl (fallback.XLarge): crops whose IDs (< 50% of rows) or sums fail are re-read."""
    vocab = header_vocab(cfg)
    out = []
    for i in page_idx:
        for rect, raw in page_tables(doc[i], vocab, min_words=10):
            if raw.shape[1] < 3:
                continue
            if xl is not None:
                marked = mark_totals(raw)
                has_id, share = _id_share(marked, cfg)
                why = (f"IDs on only {round(100 * share)}% of rows" if has_id and share < 0.5
                       else "; ".join(_failed_sums(marked))[:120])
                if why:
                    raw, used = _try_xlarge(xl, doc, i, rect, raw, marked, has_id, share, cfg)
                    if events is not None:
                        events.append(dict(page=i + 1, crop=[round(v) for v in rect], reason=why,
                                           result="XLarge used" if used else "XLarge not better, PyMuPDF kept"))
            out.append((i, raw.assign(_page=i + 1)))
    return out


def _try_xlarge(xl, doc, i, rect, raw, marked, has_id, share, cfg):
    """XLarge's table replaces PyMuPDF's only if it has more valid IDs, or passes the sums
    PyMuPDF failed (without losing IDs or columns)."""
    try:
        dfs = xl.tables(doc, i, rect)
    except Exception as e:                       # model missing etc.: keep PyMuPDF, say why
        print(f"  XLarge fallback failed on page {i + 1}: {e}")
        return raw, False
    for df in dfs:
        m2 = mark_totals(df)
        has2, share2 = _id_share(m2, cfg)
        better_ids = has_id and has2 and share2 >= 0.5 and share2 > share
        fixed_sums = bool(_failed_sums(marked)) and not _failed_sums(m2) and \
            m2.shape[1] >= marked.shape[1] - 1 and (not has_id or (has2 and share2 >= share))
        if better_ids or fixed_sums:
            return df, True
    return raw, False


# ---------------------------------------------------------------------------------------------
# the whole thing
# ---------------------------------------------------------------------------------------------
def collateral(doc, page_idx, cfg, xl=None):
    """-> (collateral rows, checks, fallback events). Rows hold every mapped field + _pages."""
    checks, events, tables = [], [], []
    for pages, df in stitch_pages(read_pages(doc, page_idx, cfg, xl, events)):
        marked = mark_totals(df)
        heads = [c for c in marked.columns if not str(c).startswith("_")]
        span = f"{pages[0] + 1}-{pages[-1] + 1}" if len(pages) > 1 else str(pages[0] + 1)
        for _, r in marked[marked["_row"] != "detail"].iterrows():
            label = next((r[c] for c in heads if r[c].strip() and to_num(r[c]) is None), "")
            checks.append(dict(pages=span, table=" | ".join(heads[:3])[:80], row=r["_row"],
                               label=label[:60], check=r["_check"] or "not checked (amount in another column)"))
        det = marked[marked["_row"] == "detail"]
        for page, part in det.groupby("_page", sort=False):
            tables.append((page, part.drop(columns=[c for c in part.columns if str(c).startswith("_")])))
    checks = pd.DataFrame(checks, columns=["pages", "table", "row", "label", "check"])
    rows = join_on_id(tables, cfg)
    return (rows if rows is not None else pd.DataFrame(columns=[ID_FIELD])), checks, events


def join_on_id(tables, cfg):
    """[(page, table)] -> one row per security ID, or None if no table has an ID column."""
    ccfg = cfg["collateral"]
    cols_cfg = ccfg["columns"]
    groups = {}                                    # set of mapped fields -> parts
    for page, df in tables:
        m = map_headers([str(c) for c in df.columns], cols_cfg)
        if ID_FIELD not in m.values() or len(m) < ccfg.get("min_mapped_fields", 3):
            continue
        part = df[list(m)].rename(columns=m).copy()
        part[ID_FIELD] = part[ID_FIELD].map(lambda v: norm_id(v, ccfg["id_patterns"]))
        part = part[part[ID_FIELD] != ""]
        if len(part):
            part = part.mask(part.astype(str).apply(lambda c: c.str.strip()) == "")    # '' = missing
            part["_pages"] = str(page)
            part.attrs["ranks"] = {f: header_rank(h, f, cols_cfg) for h, f in m.items()}
            groups.setdefault(frozenset(m.values()), []).append(part)
    if not groups:
        return None
    stacked = []
    for parts in groups.values():
        t = pd.concat(parts, ignore_index=True)
        t.attrs["ranks"] = {f: min(p.attrs["ranks"].get(f, 99) for p in parts)
                            for f in t.columns if not str(f).startswith("_")}
        stacked.append(t)
    # rows: the table with an issuer column and the most DISTINCT securities; on a tie, the table
    # that lists each security ONCE (a table that splits a security into lots - interest accrual -
    # has no single value per security), then the one with most columns
    stacked.sort(key=lambda t: ("issuer" in t.columns, t[ID_FIELD].nunique(),
                                -t[ID_FIELD].duplicated().sum(), t.shape[1]), reverse=True)
    keyed = [t.drop_duplicates(subset=[ID_FIELD], keep="first").set_index(ID_FIELD) for t in stacked]
    base = keyed[0][[]].copy()
    # each column from the table whose header names it most directly; gaps from the next one
    fields = list(dict.fromkeys(c for k in keyed for c in k.columns))
    for f in fields:
        order = sorted(range(len(keyed)), key=lambda i: (stacked[i].attrs["ranks"].get(f, 99), i))
        col = pd.Series(index=base.index, dtype=object)
        for i in order:
            if f in keyed[i].columns:
                col = col.combine_first(keyed[i][f].reindex(base.index))
        base[f] = col
    base = base.reset_index()
    for c in ccfg.get("numeric_columns", []):
        if c in base:
            base[c] = base[c].map(lambda v: to_num(str(v)) if pd.notna(v) and str(v).strip() else None)
    return base
