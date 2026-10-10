"""Build a demo of the org's folder layout from the sample PDFs in reports/:

  demo/active_deals.xlsx                                   (the deal list: deal name, trustee)
  demo/reports/<deal>/<Monthly|Quarterly> Trustee Report/2026_8 <deal>.pdf

Then:  python run.py --period 2026-08
Every sample pretends to be the 2026-08 report. One sample sits in the Quarterly folder (to show
the folder fallback) and one deal has no report (to show how a missing report is reported).
"""
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "reports"
SAMPLES = [  # sample file in reports/, trustee as the deal list spells it, report folder
    ("bny_1.pdf", "BNY Mellon", "Monthly Trustee Report"),
    ("bny_2.pdf", "BNY Mellon", "Monthly Trustee Report"),
    ("bny_3.pdf", "BNY Mellon", "Quarterly Trustee Report"),
    ("citi_1.pdf", "Citibank", "Monthly Trustee Report"),
    ("us_1.pdf", "U.S. Bank", "Monthly Trustee Report"),
    ("us_2.pdf", "U.S. Bank", "Monthly Trustee Report"),
    (None, "Wilmington Trust", None),
]
rows = []
for n, (f, trustee, folder) in enumerate(SAMPLES, 1):
    deal = f"Demo Deal {n}"
    rows.append({"Deal Name": deal, "Trustee": trustee, "Status": "Active"})
    if f and (SRC / f).exists():
        d = ROOT / "reports" / deal / folder
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(SRC / f, d / f"2026_8 {deal}.pdf")
pd.DataFrame(rows).to_excel(ROOT / "active_deals.xlsx", index=False)
print("demo tree ready:", ROOT / "reports")
