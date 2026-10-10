"""Collateral: issuer-level rows joined from several long tables.

  1. on each collateral page: rotation-corrected words -> regions (XY-cut) -> table (gutter columns,
     multi-line headers merged, wrapped rows glued)            [geometry.py, from the prototype]
  2. map every table's column headers to schema columns via synonyms (config collateral.columns)
  3. keep tables that have an ID column; stack tables with the same mapped columns across pages
  4. join the different table types (assets, ratings, industries, ...) on the security ID
"""
import re

import pandas as pd

from . import geometry as G
from .pdfpage import page_model, to_num

ID_FIELD = "loan id"


def map_headers(headers, columns_cfg):
    """headers (list[str]) -> {header: schema_field}. Ordered synonyms, each field used once."""
    used, out = set(), {}
    for h in headers:
        hl = h.lower()
        for field, pat in columns_cfg.items():
            if field in used or not pat:
                continue
            if re.search(pat, hl):
                out[h] = field
                used.add(field)
                break
    return out


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


def collateral(doc, page_idx, cfg, deal="", month=""):
    cols_cfg = cfg["collateral"]["columns"]
    min_fields = cfg["collateral"].get("min_mapped_fields", 3)
    groups = {}                                   # frozenset(fields) -> list of DataFrames
    for i in page_idx:
        for df in page_tables(doc[i], cfg):
            m = map_headers([str(c) for c in df.columns], cols_cfg)
            if ID_FIELD not in m.values() or len(m) < min_fields:
                continue
            part = df[list(m)].rename(columns=m).copy()
            pats = cfg["collateral"].get("id_patterns")
            part[ID_FIELD] = part[ID_FIELD].map(lambda v: norm_id(v, pats))
            part = part[part[ID_FIELD] != ""]
            if len(part):
                part["_pages"] = str(i + 1)
                groups.setdefault(frozenset(m.values()), []).append(part)
    if not groups:
        return pd.DataFrame(columns=cfg["collateral"]["output_columns"])
    tables = [pd.concat(v, ignore_index=True) for v in groups.values()]
    # base = the table with the most rows that has an issuer column, else the largest
    tables.sort(key=lambda t: ("issuer" in t.columns, len(t)), reverse=True)
    base = tables[0].drop_duplicates(subset=[ID_FIELD], keep="first").set_index(ID_FIELD)
    for t in tables[1:]:
        t = t.drop_duplicates(subset=[ID_FIELD], keep="first").set_index(ID_FIELD)
        base = base.combine_first(t)               # fills missing columns/values by ID
    base = base.reset_index()
    # types: numbers for double columns, as-printed text otherwise
    for c in cfg["collateral"].get("numeric_columns", []):
        if c in base:
            base[c] = base[c].map(lambda v: to_num(str(v)) if pd.notna(v) else None)
    base["deal name"], base["report_month"] = deal, month
    return base.reindex(columns=cfg["collateral"]["output_columns"] + ["_pages"])
