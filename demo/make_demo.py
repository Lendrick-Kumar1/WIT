"""Builds a demo org-style tree from the 7 sample PDFs in reports/:

  demo/active_deals.xlsx
  demo/reports/<Deal Name>/<Monthly|Quarterly> Trustee Report/2026_8 <deal>.pdf

Then try:  python run.py --period 2026-08
(The demo pretends every sample is the 2026-08 report, so report_month shows 2026-08.)
"""
import shutil
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "reports"
DEALS = [  # deal name, trustee (as the org deal list would spell it), sample file, report folder
    ("Capital Four CLO I DAC", "BNY Mellon", "bny_1.pdf", "Monthly Trustee Report"),
    ("Providus CLO VII DAC", "BNY Mellon", "bny_2.pdf", "Monthly Trustee Report"),
    ("Providus CLO II DAC", "BNY Mellon", "bny_3.pdf", "Quarterly Trustee Report"),   # fallback folder
    ("Arini European CLO I DAC", "Citibank", "citi_1.pdf", "Monthly Trustee Report"),
    ("Anchorage Capital Europe CLO 5 DAC", "U.S. Bank", "us_1.pdf", "Monthly Trustee Report"),
    ("Segovia European CLO 3-2017 DAC", "U.S. Bank", "us_2.pdf", "Monthly Trustee Report"),
    ("Example Wilmington CLO", "Wilmington Trust", None, None),                         # no report
]
rows = []
for deal, trustee, f, folder in DEALS:
    rows.append({"Deal Name": deal, "Trustee": trustee, "Status": "Active"})
    if f and (SRC / f).exists():
        d = ROOT / "reports" / deal / folder
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(SRC / f, d / f"2026_8 {deal}.pdf")
pd.DataFrame(rows).to_excel(ROOT / "active_deals.xlsx", index=False)
print("demo tree ready:", ROOT / "reports")
