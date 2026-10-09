"""S7 stitch regions continuing over pages/sections into logical tables (ported from prototype)."""

from __future__ import annotations

import re

import pandas as pd

from trustee_extract.core.types import LogicalTable
from trustee_extract.structure.geometry import Region


def header_similarity(a, b):
    generic = lambda cols: all(re.fullmatch(r"col\d+(_\d+)?|_section", c) for c in cols)
    if generic(a) or generic(b):
        return 1.0          # a continuation page without its own header matches anything
    a, b = set(a) - {"_section"}, set(b) - {"_section"}
    return len(a & b) / max(len(a | b), 1)


def data_cols(df):
    return [c for c in df.columns if c != "_section"]


def section_like(cols):
    """Header where only the first cell is real text, e.g. ['Coverage Tests','col1','col2']:
    that 'header' is actually a section label of the table above."""
    return len(cols) > 1 and all(re.fullmatch(r"col\d+(_\d+)?", c) for c in cols[1:]) \
        and not re.fullmatch(r"col\d+", cols[0])


def stitch(regions: list[Region]):
    """Join regions that are pieces of one logical table:
       - same page title, on the same page (section below) or on the next page, and
       - same number of data columns, and
       - same-ish header, or no real header (continuation page / section block)."""
    tables: list[LogicalTable] = []
    for r in regions:
        if r.kind not in ("table", "text-table", "empty-table"):
            continue
        same_title = [t for t in tables if t.name.split(" #")[0] == r.title]
        if r.df.empty and same_title and r.kind == "empty-table":   # "There are no ..." line
            same_title[-1].note = " ".join(w["t"] for w in r.words)
            continue
        rc = data_cols(r.df)
        cands = []
        for t in same_title:
            if len(data_cols(t.df)) != len(rc):
                continue
            # same page: only a section block below; side-by-side tables are never joined
            if not (t.pages[-1] == r.page - 1 or (t.pages[-1] == r.page and section_like(rc))):
                continue
            sim = 1.0 if section_like(rc) else header_similarity(data_cols(t.df), rc)
            if sim >= 0.5:
                cands.append((sim, t))
        if not cands:
            n = len(same_title)
            note = ""
            if r.kind == "empty-table":
                txt = " ".join(w["t"] for w in r.words)
                note = txt[txt.lower().find("there are no"):]
            tables.append(LogicalTable(r.title + (f" #{n + 1}" if n else ""), [r.page], r.df.copy(), note=note))
            continue
        t = max(cands, key=lambda c: c[0])[1]
        part = r.df.copy()
        if section_like(rc):
            sec = rc[0]
            part = part.rename(columns=dict(zip(rc, data_cols(t.df))))
            part["_section"] = sec
        else:
            part = part.rename(columns=dict(zip(rc, data_cols(t.df))))
            if "_section" not in part and "_section" in t.df:
                part["_section"] = t.df["_section"].iloc[-1]   # section carries over the page break
        if "_section" in part and "_section" not in t.df:
            t.df["_section"] = ""
        # identical repeated block (e.g. a summary box printed on every page) -> keep once
        tail = t.df.tail(len(part)).reset_index(drop=True)
        if len(tail) == len(part) and tail[data_cols(t.df)].equals(part[data_cols(t.df)].reset_index(drop=True)):
            continue
        t.df = pd.concat([t.df, part[t.df.columns]], ignore_index=True)
        if r.page not in t.pages:
            t.pages.append(r.page)
    return tables
