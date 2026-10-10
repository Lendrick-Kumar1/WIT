"""Collateral: issuer-level rows joined from several long tables.

  1. every collateral page is cut into CROPS (one table each, crops.py) and each crop is read as
     ONE table (croptable.py). collateral.reader: regions = the older page-wide reader.
  2. the same table continuing over consecutive pages is STITCHED into one table first, so groups
     and totals that cross a page break are copied down / checked correctly
  3. map every table's column headers to schema columns via synonyms (config collateral.columns)
  4. keep tables that have an ID column; join the different table types on the security ID
  5. every subtotal / total is checked against the sum of its rows -> returned as `checks`
  6. optional: a crop that fails its checks is re-read by XLarge (fallback.py); XLarge's table is
     used only if it passes the checks that PyMuPDF's failed
"""
import re

import pandas as pd

from . import geometry as G
from .croptable import group_rows, page_crop_tables
from .pdfpage import page_model, to_num

ID_FIELD = "loan id"


def _alternatives(pat):
    """top-level '|' alternatives of a synonym regex, in config order (specific first)"""
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


def header_rank(header, field, columns_cfg):
    """How directly a header names a field: 0 = it IS the field name, then the position of the
    first synonym it matches ('Issuer Name' -> issuer 0+1, 'Description' -> issuer 3+1)."""
    hl = header.lower()
    if re.sub(r"[^a-z0-9&']+", " ", hl).strip() == field:
        return 0
    pat = columns_cfg.get(field) or ""
    return 1 + next((k for k, alt in enumerate(_alternatives(pat)) if alt and re.search(alt, hl)), 98)


def map_headers(headers, columns_cfg):
    """headers (list[str]) -> {header: schema_field}. Each header goes to the first field whose
    synonyms match it (field order matters). If several headers want the same field, a header that
    is literally the field's name wins ('Principal Balance' beats 'Par/Quantity'), else the first."""
    best = {}                                      # field -> (alternative index, header position, header)
    for pos, h in enumerate(headers):
        hl = h.lower()
        for field, pat in columns_cfg.items():
            if not pat or not re.search(pat, hl):
                continue
            # a header that IS the field's name ("Principal Balance") beats one that only matches a
            # synonym ("Par/Quantity"); otherwise the first header wins, as before
            rank = 0 if re.sub(r"[^a-z0-9&']+", " ", hl).strip() == field else 1
            if field not in best or (rank, pos) < best[field][:2]:
                best[field] = (rank, pos, h)
            break
    return {h: f for f, (_, pos, h) in sorted(best.items(), key=lambda kv: kv[1][1])}


def page_tables(page, cfg):
    G.HEADER_VOCAB = [v for v in cfg.get("collateral", {}).get("columns", {}).values() if v] + \
        [v for v in cfg.get("performance", {}).get("header_roles", {}).values() if v]
    lay = cfg.get("layout", {})
    words, H, V = page_model(page)
    h = page.rect.height
    words = [w for w in words if w["y0"] > h * lay.get("table_top", 0.1)
             and w["y1"] < h * lay.get("footer_band", 0.93)]
    if len(words) < 10:
        return []
    out = []
    for blk in G.attach_headers(G.xy_cut(words, H, V)):
        r = G.Region(page=page.number + 1, words=blk, bbox=G.bbox(blk))
        G.build_table(r)
        if r.df is not None and len(r.df) and r.df.shape[1] >= 3:
            out.append(r.df)
    return out


ID_PATTERNS = [r"LX\d{6}", r"[A-Z]{2}[A-Z0-9]{9}\d", r"BBG[A-Z0-9]{9}", r"[A-Z0-9]{9}"]


def norm_id(v, patterns=None):
    """Pick the token that LOOKS like a security ID (LoanX, ISIN, FIGI, CUSIP), so text that
    overflowed from a neighbouring column ('NEW B2D LX218697') doesn't pollute the key."""
    s = str(v or "").upper()
    toks = re.findall(r"[A-Z0-9]+", s)
    for pat in patterns or ID_PATTERNS:
        for tok in toks:
            if re.fullmatch(pat, tok):
                return tok
    s = re.sub(r"\s+", "", s)
    return s if re.fullmatch(r"[A-Z0-9]{6,14}", s) else ""


def _id_share(df, cfg):
    """(has an ID column, share of detail rows with a valid ID) for one table."""
    m = map_headers([str(c) for c in df.columns if not str(c).startswith("_")], cfg["collateral"]["columns"])
    id_cols = [h for h, f in m.items() if f == ID_FIELD]
    if not id_cols:
        return False, 0.0
    det = df[df["_row"] == "detail"] if "_row" in df else df
    if not len(det):
        return True, 0.0
    pats = cfg["collateral"].get("id_patterns")
    ok = sum(bool(norm_id(v, pats)) for v in det[id_cols[0]])
    return True, ok / len(det)


def _bad_checks(g):
    """checks that point at a READING problem (not 'rows are on an earlier page')"""
    if "_check" not in g:
        return []
    return [c for c in g["_check"] if c.startswith("check:") and "earlier page" not in c]


def _crop_raw_tables(doc, page_idx, cfg, xl=None, events=None):
    """[(page_index, raw_df)] for every crop of the collateral pages; optional XLarge fallback."""
    G.HEADER_VOCAB = [v for v in cfg["collateral"]["columns"].values() if v] + \
        [v for v in cfg.get("performance", {}).get("header_roles", {}).values() if v]
    footer = cfg.get("collateral", {}).get("footer_band")     # None = measured on each page
    out = []
    for i in page_idx:
        for rect, raw in page_crop_tables(doc[i], footer_band=footer, min_words=10):
            if raw.shape[1] < 3:
                continue
            if xl is not None:
                g = group_rows(raw)
                has_id, share = _id_share(g, cfg)
                why = ("IDs on only %d%% of rows" % round(100 * share)) if has_id and share < 0.5 else \
                      ("; ".join(_bad_checks(g))[:120] if _bad_checks(g) else "")
                if why:
                    raw, used = _try_xlarge(xl, doc, i, rect, raw, g, has_id, share, cfg)
                    if events is not None:
                        events.append(dict(page=i + 1, crop=[round(v) for v in rect], reason=why,
                                           result="XLarge used" if used else "XLarge not better, PyMuPDF kept"))
            out.append((i, raw.assign(_page=i + 1)))
    return out


def _try_xlarge(xl, doc, i, rect, raw, g, has_id, share, cfg):
    try:
        dfs = xl.tables(doc, i, rect)
    except Exception as e:                       # model missing etc.: keep PyMuPDF, say why
        print(f"  XLarge fallback failed on page {i + 1}: {e}")
        return raw, False
    for df in dfs:
        g2 = group_rows(df)
        has2, share2 = _id_share(g2, cfg)
        better_ids = has_id and has2 and share2 >= 0.5 and share2 > share
        fixed_checks = bool(_bad_checks(g)) and not _bad_checks(g2) and \
            g2.shape[1] >= g.shape[1] - 1 and (not has_id or (has2 and share2 >= share))
        if better_ids or fixed_checks:
            return df, True
    return raw, False


def _stitch(parts):
    """Join raw tables that run over a page break into one table. `parts` = [(page_index, df)] in
    reading order. A table continues on the next page only if it is the LAST table on its page,
    the next part is the FIRST table on the following page, and both have the same columns.
    Returns [(pages, df)] in reading order."""
    first, last = {}, {}
    for k, (i, _) in enumerate(parts):
        first.setdefault(i, k)
        last[i] = k
    out = []
    for k, (i, raw) in enumerate(parts):
        sig = tuple(c for c in raw.columns if not str(c).startswith("_"))
        if out:
            pages, dfs, psig, pk = out[-1]
            if psig == sig and i == pages[-1] + 1 and pk == last[pages[-1]] and k == first[i]:
                out[-1] = (pages + [i], dfs + [raw], sig, k)
                continue
        out.append(([i], [raw], sig, k))
    res = []
    for p, dfs, _, _ in out:
        # a section ("Loan", "Bond") carries over the page break: the leading rows of a continued
        # page that have no section yet belong to the previous page's last section
        sec = ""
        for k, d in enumerate(dfs):
            if "_section" not in d and not sec:
                continue
            d = d.copy()
            col = d["_section"].fillna("").astype(str) if "_section" in d else pd.Series("", index=d.index)
            if sec:
                lead = col.eq("").cumprod().astype(bool)     # rows before the page's first label
                col[lead] = sec
            d["_section"] = col
            dfs[k] = d
            if col.str.strip().any():
                sec = col[col.str.strip() != ""].iloc[-1]
        res.append((p, pd.concat(dfs, ignore_index=True).fillna("").astype(str)))
    return res


def collateral(doc, page_idx, cfg, deal="", month="", xl=None):
    """-> (collateral DataFrame, checks DataFrame, fallback events list)"""
    cols_cfg = cfg["collateral"]["columns"]
    min_fields = cfg["collateral"].get("min_mapped_fields", 3)
    pats = cfg["collateral"].get("id_patterns")
    groups = {}                                   # frozenset(fields) -> list of DataFrames
    checks, events = [], []
    if cfg["collateral"].get("reader", "crops") == "regions":
        tables = [(str(i + 1), df) for i in page_idx for df in page_tables(doc[i], cfg)]
    else:
        tables = []
        for pages, df in _stitch(_crop_raw_tables(doc, page_idx, cfg, xl, events)):
            g = group_rows(df)
            heads = [c for c in g.columns if not str(c).startswith("_")]
            for _, r in g[g["_row"] != "detail"].iterrows():
                label = next((r[c] for c in heads if r[c].strip() and G.to_number(r[c]) is None), "")
                checks.append(dict(pages=f"{pages[0] + 1}-{pages[-1] + 1}" if len(pages) > 1 else str(pages[0] + 1),
                                   table=" | ".join(heads[:3])[:80], row=r["_row"], label=label[:60],
                                   check=r["_check"] or "not checked (amount in another column)"))
            det = g[g["_row"] == "detail"]
            for page, part in det.groupby("_page", sort=False):
                tables.append((page, part.drop(columns=[c for c in part.columns if str(c).startswith("_")])))
    for page, df in tables:
        m = map_headers([str(c) for c in df.columns], cols_cfg)
        if ID_FIELD not in m.values() or len(m) < min_fields:
            continue
        ranks = {f: header_rank(h, f, cols_cfg) for h, f in m.items()}
        part = df[list(m)].rename(columns=m).copy()
        part[ID_FIELD] = part[ID_FIELD].map(lambda v: norm_id(v, pats))
        part = part[part[ID_FIELD] != ""]
        if len(part):
            part = part.mask(part.astype(str).apply(lambda c: c.str.strip()) == "")   # '' = missing
            part["_pages"] = str(page)
            part.attrs["ranks"] = ranks
            groups.setdefault(frozenset(m.values()), []).append(part)
    checks = pd.DataFrame(checks, columns=["pages", "table", "row", "label", "check"])
    if not groups:
        return pd.DataFrame(columns=cfg["collateral"]["output_columns"]), checks, events
    tables = []
    for v in groups.values():
        t = pd.concat(v, ignore_index=True)
        t.attrs["ranks"] = {f: min(p.attrs["ranks"].get(f, 99) for p in v) for f in t.columns
                            if not str(f).startswith("_")}
        tables.append(t)
    # rows: the table with an issuer column and the most DISTINCT securities (then most columns).
    # Counting rows instead would favour tables that list one security in several lots
    # (interest accrual: 445,979.01 + 863,180.89) over the asset table's single 1,309,159.90.
    tables.sort(key=lambda t: ("issuer" in t.columns, t[ID_FIELD].nunique(), t.shape[1]), reverse=True)
    keyed = [t.drop_duplicates(subset=[ID_FIELD], keep="first").set_index(ID_FIELD) for t in tables]
    base = keyed[0][[]].copy()
    # each column from the table whose header names it most directly ('Issuer' before
    # 'Description', 'Principal Balance' before 'Par/Quantity'); gaps filled from the next one
    fields = [c for c in cfg["collateral"]["output_columns"] + ["_pages"]
              if any(c in k.columns for k in keyed)]
    for f in fields:
        order = sorted(range(len(keyed)), key=lambda i: (tables[i].attrs["ranks"].get(f, 99), i))
        col = pd.Series(index=base.index, dtype=object)
        for i in order:
            if f in keyed[i].columns:
                col = col.combine_first(keyed[i][f].reindex(base.index))
        base[f] = col
    base = base.reset_index()
    # types: numbers for double columns, as-printed text otherwise
    for c in cfg["collateral"].get("numeric_columns", []):
        if c in base:
            base[c] = base[c].map(lambda v: to_num(str(v)) if pd.notna(v) and str(v).strip() else None)
    base["deal name"], base["report_month"] = deal, month
    return base.reindex(columns=cfg["collateral"]["output_columns"] + ["_pages"]), checks, events
