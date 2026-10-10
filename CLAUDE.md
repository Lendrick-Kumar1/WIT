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

## Current state (v3_8)
- Collateral = crops (`crops.find_crops`, title/footer measured) -> one table per crop
  (`croptable.page_crop_tables`, `group_rows`) -> tables stitched across consecutive pages
  (`collateral._stitch`) -> header mapping -> join on ID. Each column comes from the table whose
  header names it most directly (`collateral.header_rank`).
- Every subtotal / total is checked against its rows -> `_run_report.xlsx` sheet `collateral_sums`.
  A failing check means rows were lost / merged: investigate, don't hide it.
- `--fallback`: XLarge (`fallback.py`) only for crops with IDs < 50% or failing sums; its table is
  used only if it passes where PyMuPDF failed (sheet `xlarge_fallback`).
- Regression: compare Collateral cell by cell **keyed on loan id** (row order can change).

## Commands
- `python demo/make_demo.py` (builds `demo/` from `reports/`), then `python run.py --period 2026-08`
- `python run.py some.pdf` (ad-hoc), `python run.py some.pdf --debug 3,5` (per page),
  `--dump 3` (every crop table on page 3), `--fallback` (XLarge for failing crops)
- `python tools/crop_test.py probs/*.pdf --no-docling` (crops + per-crop and cross-page checks)

## Working rules
- After every change, re-run all samples and compare with HANDOVER §5. No count may go down.
- Prefer config changes over code. Real labels and paths stay on the org laptop; keep `<<PLACEHOLDER>>` here.
