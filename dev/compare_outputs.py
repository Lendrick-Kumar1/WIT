"""Compare two output folders cell by cell (regression check after a code change).

    python app.py run --months 2026-08 --out out_before      # before the change
    ... change code ...
    python app.py run --months 2026-08 --out out_after
    python dev/compare_outputs.py out_before out_after

Every .xlsx, every sheet, every cell. The run reports (time-stamped names) are compared with
each other. Collateral rows are matched on the ID column (`--key`, default 'loan id'; use the
renamed header if settings.yaml renames it), so row order may change. Timing columns are ignored. For each difference it says FILLED (was empty), LOST
(now empty) or CHANGED. Exit code 1 if anything differs.
"""
import sys
from pathlib import Path

import re

import pandas as pd

IGNORE = {"seconds"}


def load(path):
    return {s: df.fillna("").astype(str).drop(columns=[c for c in df.columns if c in IGNORE])
            for s, df in pd.read_excel(path, sheet_name=None).items()}


def files(root):
    """relative name -> path; 'run_report_<date>_<time>.xlsx' -> 'run_report.xlsx'."""
    return {Path(re.sub(r"run_report_[\d_-]+\.xlsx$", "run_report.xlsx", str(p.relative_to(root)))): p
            for p in Path(root).rglob("*.xlsx")}


def compare(a_root, b_root, show=10, key="loan id"):
    pa, pb = files(a_root), files(b_root)
    fa, fb = set(pa), set(pb)
    diffs = 0
    for rel in sorted(fa ^ fb):
        print(f"ONLY IN {'first' if rel in fa else 'second'}: {rel}")
        diffs += 1
    for rel in sorted(fa & fb):
        x, y = load(pa[rel]), load(pb[rel])
        for sheet in sorted(set(x) | set(y)):
            if sheet not in x or sheet not in y:
                print(f"{rel} [{sheet}]: sheet only in one of them")
                diffs += 1
                continue
            p, q = x[sheet], y[sheet]
            if key in p.columns and key in q.columns:
                p = p.drop_duplicates(key).set_index(key)
                q = q.drop_duplicates(key).set_index(key)
                if set(p.index) != set(q.index):
                    print(f"{rel} [{sheet}]: loan ids differ: {len(set(p.index) - set(q.index))} only first, "
                          f"{len(set(q.index) - set(p.index))} only second")
                    diffs += 1
                q = q.reindex(p.index).fillna("")
            elif p.shape != q.shape:
                print(f"{rel} [{sheet}]: shape {p.shape} -> {q.shape}")
                diffs += 1
                continue
            if list(p.columns) != list(q.columns):
                print(f"{rel} [{sheet}]: columns differ")
                diffs += 1
                continue
            n = 0
            for i, j in zip(*(p.values != q.values).nonzero()):
                o, v = p.iat[i, j], q.iat[i, j]
                kind = "FILLED" if not o else ("LOST" if not v else "CHANGED")
                if n < show:
                    print(f"{rel} [{sheet}] {p.index[i]} | {p.columns[j]}: {kind}  {o[:50]!r} -> {v[:50]!r}")
                n += 1
            if n > show:
                print(f"{rel} [{sheet}]: ... {n - show} more")
            diffs += n
    print("IDENTICAL" if not diffs else f"{diffs} differences")
    return diffs


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--key=")]
    k = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--key=")), "loan id")
    sys.exit(1 if compare(args[0], args[1], key=k) else 0)
