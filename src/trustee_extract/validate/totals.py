"""S8 Total / Subtotal rows must equal the rows they close (ported from prototype)."""

from __future__ import annotations

import re

import pandas as pd

from trustee_extract.core.numbers import TOTAL_RE, to_number
from trustee_extract.core.types import LogicalTable


def validate(t: LogicalTable):
    df = t.df
    label_cols = [c for c in df.columns if df[c].astype(str).str.contains(TOTAL_RE).any()]
    if not label_cols:
        return
    is_total = df[label_cols].astype(str).apply(lambda s: s.str.contains(TOTAL_RE)).any(axis=1)
    for col in df.columns:
        nums = df[col].map(to_number)
        if nums.notna().sum() < 2 or col in label_cols:
            continue
        block, prev_totals = 0.0, []
        for i in df.index:
            v = nums[i]
            if is_total[i]:
                if v is None or pd.isna(v):
                    continue
                label = " ".join(str(df.at[i, c]) for c in label_cols).strip()
                options = {"rows since last total": block,
                           "previous total + rows since": (prev_totals[-1] if prev_totals else 0) + block,
                           "sum of earlier totals": sum(prev_totals)}
                ok = [k for k, s in options.items() if abs(s - v) < 0.015 and (s or v == 0)]
                if not ok and not re.search(r"sub|grand|:", label, re.I):
                    block += v            # e.g. "Total Cash" is a line item, not a total
                    continue
                t.checks.append(dict(table=t.name, column=col, row=label, printed=v,
                                     computed=round(options["rows since last total"], 2),
                                     status="PASS (" + ok[0] + ")" if ok else "FAIL"))
                prev_totals.append(v)
                block = 0.0
            elif v is not None and not pd.isna(v):
                block += v
