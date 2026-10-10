# WIT: CLO trustee report extraction

Read `HANDOVER.md` (what and how), then `CODE_GUIDE.md` (every file and rule, with its test).

## Goal
Born-digital trustee PDFs → 3 Excel outputs per deal (Balance, Performance, Collateral).
About 9 trustees, ~233 deals per period, CPU only, 16 GB RAM, Windows / Git Bash.

## Design (do not change without asking)
- **PyMuPDF on the main path.** XLarge (Docling) only behind `--fallback`, only for crops whose
  checks fail.
- **Look up what the schema needs, by words:**
  - Performance = header line with result/test words, rows below it.
  - Balance = label → number right / below, or the total of a column on a named page.
  - Collateral = crops → one table each → joined across page breaks → sums checked → headers
    mapped → joined on the security ID.
- **Never silently guess:** uncertain values get a status or check in `_run_report.xlsx`.
- **No coordinates** in code or config; trustee differences only in `config/trustees/*.yaml`.
- Use `pdfpage.page_model()` for words (fixes rotation, treats thin images as rules) and
  `pdfpage.to_num()` for every number.

## Writing code here
- **Never name a deal, issuer or real figure** in code, comments, tests or docs. Describe the
  pattern ("centred 2-line cells", "total printed one column right of its rows").
- A new rule = a small named function or step + a test in `tests/` built from synthetic words
  (`tests/helpers.py`) + a line in the rules table of `CODE_GUIDE.md`.
- Keep functions short; prefer a config change over code.

## After every change
1. `python tests/run_tests.py`: all pass.
2. Output from before vs after the change:
   `python run.py --period 2026-08 --out out_before` (before) /
   `--out out_after` (after), then `python tools/compare_outputs.py out_before out_after`.
   Every FILLED / CHANGED / LOST cell must be explained; LOST and CHANGED need a look at the PDF.
3. `python tools/crop_test.py <problem pdfs> --no-docling`: cross-page sums still ok.

## Commands
- `python demo/make_demo.py`, then `python run.py --period 2026-08`
- `python run.py some.pdf [--debug 3,5 | --dump 3 | --fallback]`
- `python tools/crop_test.py some.pdf --no-docling`
