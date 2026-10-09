"""Parse report numbers: 1,234.5 / (1.0) / 12.3% (ported from prototype)."""

from __future__ import annotations

import re


NUM_RE = re.compile(r"^\(?-?[\d,]*\.?\d+%?\)?$")


def to_number(v):
    """'1,234.50' -> 1234.5 ; '(5,740,986.87)' -> -5740986.87 ; '1,884.29 EUR [A]' -> 1884.29"""
    if v is None:
        return None
    s = re.sub(r"\s*(EUR|USD|GBP)\b|\[[A-Z]\]|\s", "", str(v))
    if not s or not NUM_RE.match(s) or s.endswith("%"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return None


TOTAL_RE = re.compile(r"\b(?:sub)?total\b", re.I)
