# WIT: CLO trustee report extraction

Read `HANDOVER.md` first. It covers the design, robustness, results and next steps.

## Goal
Born-digital trustee PDFs → 3 Excel outputs (Balance, Performance, Collateral). About 9 trustees, ~233 deals per period, CPU only, 16 GB RAM.

## Inputs
- The deal list Excel gives active deals and the trustee for each.
- Reports live at `<root>/<deal>/<Monthly|Quarterly|Intra Trustee Report>/<file named by period>`. Use the first folder that has the period.
- Paths and names are in `config/sources.yaml`. Deal name, trustee and month come from this metadata, not from PDF text.

## Design (do not change without asking)
- **PyMuPDF only** on the main path.
- **Look up what the schema needs, by words:**
  - Performance = rows under a header row (result + test/current/trigger words).
  - Balance = label phrase → numbers immediately right, else directly below.
  - Collateral = tables whose headers map to schema columns, stacked across pages, joined on loan id.
- **Never silently guess:** uncertain values get `_status` / `status` flags, and `_run_report.xlsx` summarises them.
- All trustee differences live in `config/trustees/<name>.yaml`. No `if trustee ==` in code. No coordinates.
- Always use `pdfpage.page_model()` for text: it fixes `/Rotate 90` and treats thin images as separators.

## Current step (after the crop test)
Crop test result (XLarge on crops vs PyMuPDF): crops fix XLarge's segmentation errors, but XLarge
misses small crops (key-value boxes, 1-row tables) and takes 3-16 s per crop. PyMuPDF reading
**one crop = one table** (`src/wit/croptable.py`) matched or beat it on every crop.
- `crops.find_crops(page)` -> crop rects; `croptable.read_crop(crop_page)` -> one DataFrame with
  `_row` (detail|subtotal|total) and `_check` (ok | check: ...).
- Grouped tables: group columns copied down, "<group>" + "<amount>" lines = one subtotal row,
  every subtotal/total checked against the sum of its rows.
- Not yet wired into the main pipeline (`run.py`). Next: use crops + read_crop for Collateral,
  stitch groups/totals across pages (clears the "rows may start on an earlier page" flags),
  then XLarge only for crops whose checks fail.

## Commands
- `python demo/make_demo.py` (builds `demo/` from `reports/`), then `python run.py --period 2026-08`
- `python run.py some.pdf` (ad-hoc), `python run.py some.pdf --debug 3,5` (per page)

## Working rules
- After every change, re-run all samples and compare with HANDOVER §5. No count may go down.
- Prefer config changes over code. Real labels and paths stay on the org laptop; keep `<<PLACEHOLDER>>` here.
