"""Compare two output folders cell by cell (regression check after a code change).

    poetry run python run.py --period 2026-08 --out out_before      # before the change
    ... change code ...
    poetry run python run.py --period 2026-08 --out out_after
    poetry run python tools/compare_outputs.py out_before out_after

Every .xlsx, every sheet, every cell. Collateral rows are matched on loan id (row order may
change). Timing columns are ignored. For each difference it says FILLED (was empty), LOST
(now empty) or CHANGED. Exit code 1 if anything differs.
"""
import sys
from pathlib import Path

import pandas as pd

IGNORE = {"seconds"}


def load(path):
    return {s: df.fillna("").astype(str).drop(columns=[c for c in df.columns if c in IGNORE])
            for s, df in pd.read_excel(path, sheet_name=None).items()}


def compare(a_root, b_root, show=10):
    a_root, b_root = Path(a_root), Path(b_root)
    fa = {p.relative_to(a_root) for p in a_root.rglob("*.xlsx")}
    fb = {p.relative_to(b_root) for p in b_root.rglob("*.xlsx")}
    diffs = 0
    for rel in sorted(fa ^ fb):
        print(f"ONLY IN {'first' if rel in fa else 'second'}: {rel}")
        diffs += 1
    for rel in sorted(fa & fb):
        x, y = load(a_root / rel), load(b_root / rel)
        for sheet in sorted(set(x) | set(y)):
            if sheet not in x or sheet not in y:
                print(f"{rel} [{sheet}]: sheet only in one of them")
                diffs += 1
                continue
            p, q = x[sheet], y[sheet]
            if "loan id" in p.columns and "loan id" in q.columns:
                p = p.drop_duplicates("loan id").set_index("loan id")
                q = q.drop_duplicates("loan id").set_index("loan id")
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
    sys.exit(1 if compare(sys.argv[1], sys.argv[2]) else 0)
