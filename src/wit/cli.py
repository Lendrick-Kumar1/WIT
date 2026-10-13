"""Command line (the window in gui.py does the same).

  python app.py run --months 2026-08                              every active deal, one month
  python app.py run --months 2026-01:2026-06 --deal "Deal A"      one deal, several months
  python app.py run --months 2025-06,2026-03:2026-05              any mix of months and ranges
  python app.py run --months 2026-08 --deal "Deal A" --deal "Deal B" --outputs balance,performance
  python app.py run --months 2026-08 --trustee "BNY"              one trustee's deals
  python app.py run --months 2026-08 --check                      only list which PDFs would be read
  python app.py run --months 2026-08 --out out_test               all outputs under one test folder
  python app.py inspect <pdf> --pages 12,13 [--trustee "BNY"]     what the reader sees on pages
"""
import argparse
import sys

from .config import load_settings, redirect_outputs
from .run import OUTPUTS, run
from .sources import months_between, plan


def months_arg(text):
    """'2026-08', '2026-01:2026-06', or a comma list of both: '2025-12,2026-03:2026-05'."""
    out = []
    for part in text.split(","):
        first, _, last = part.strip().partition(":")
        out += [ym for ym in months_between(first, last or first) if ym not in out]
    return sorted(out)


def print_plan(jobs):
    for j in jobs:
        where = j["pdf"] or "-"
        print(f"{j['year']}-{j['month']:02d}  {j['deal'][:40]:40s} {j['file_status']:8s} {where}"
              + (f"\n{'':56s}{j['file_note']}" if j["file_note"] else ""))
    found = sum(1 for j in jobs if j["pdf"])
    print(f"\n{found} of {len(jobs)} reports found")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="extract a selection of deals and months")
    r.add_argument("--months", required=True, type=months_arg,
                   help="2026-08, 2026-01:2026-06, or a comma list like 2025-06,2026-03:2026-05")
    r.add_argument("--deal", action="append", help="deal name as in the deal list (repeatable); default all")
    r.add_argument("--trustee", help="only deals whose trustee contains this text")
    r.add_argument("--outputs", default=",".join(OUTPUTS), help="any of balance,performance,collateral")
    r.add_argument("--settings", help="another settings.yaml (default config/settings.yaml)")
    r.add_argument("--out", help="put all outputs under this folder instead of the configured ones "
                                 "(for comparing two versions of the code)")
    r.add_argument("--check", action="store_true", help="only list the PDFs that would be read")
    r.add_argument("--fallback", action="store_true", help="XLarge for tables whose checks fail (slow)")

    i = sub.add_parser("inspect", help="show what the reader sees on some pages of one PDF")
    i.add_argument("pdf")
    i.add_argument("--pages", required=True, help="e.g. 12 or 12,13")
    i.add_argument("--trustee", help="trustee name as in the deal list (else detected)")

    a = ap.parse_args(argv)
    if a.cmd == "inspect":
        from .inspect_pdf import inspect
        inspect(a.pdf, [int(x) for x in a.pages.split(",")], a.trustee)
        return 0

    outputs = [o.strip() for o in a.outputs.split(",") if o.strip()]
    bad = [o for o in outputs if o not in OUTPUTS]
    if bad:
        ap.error(f"unknown output(s): {', '.join(bad)}; use {', '.join(OUTPUTS)}")
    settings = load_settings(a.settings)
    if a.out:
        redirect_outputs(settings, a.out)
    try:
        jobs = plan(settings, a.months, a.deal, a.trustee)
    except (ValueError, OSError) as e:          # unknown deal, deal list not found ...
        ap.error(f"{e}  (check config/settings.yaml)")
    if a.check:
        print_plan(jobs)
        return 0
    xl = None
    if a.fallback:
        from .fallback import XLarge
        xl = XLarge()
    run(jobs, outputs, settings, print, xl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
