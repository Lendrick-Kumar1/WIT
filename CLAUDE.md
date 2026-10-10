# WIT — CLO trustee report field extraction

## Goal
Read monthly CLO trustee reports (born-digital PDFs) and fill **3 standardized Excel outputs**:

| Output | Content | Shape |
|---|---|---|
| **Balance** | ~5 summary values (aggregate principal balance, CCC balance, …) | 1 row per report |
| **Performance** | Compliance/coverage/collateral-quality tests. The list of tests **varies by trustee and deal**; columns are generic (Test, Current, Threshold/Trigger, Result, …) | N rows per report |
| **Collateral** | 31 issuer-level columns (ratings, industry, balances, …) **joined from several long tables**, which may span many pages | 1 row per issuer/security |

Exact field lists and stakeholder validation ranges will be added to `config/` later. Until then, extract the source tables generically.

## Constraints
- CPU only, **16 GB RAM (about 5–6 GB free)**, 4 cores. Develop here, deploy by cloning a **private GitHub repo** onto an identical org laptop. Windows / Git Bash.
- Real reports are on the org server; `reports/` holds 7 public samples: bny_1-3, citi_1, us_1-3.
- **About 233 reports per cycle, ~20 relevant pages each.** Speed matters.
- Docling models are cached in `C:/Users/hp/.cache/docling/models` (egret-large, heron, TableFormer). Run offline.

## What failed before (do not repeat)
- `page.find_tables()` as the first pass splits single borderless tables in two, so about 85% of pages went to Docling. Too slow.
- Docling egret-large + TableFormer ACCURATE: good on normal tables, about 22 s/page. On **dashboard pages it detects no tables at all**. TableFormer FAST merges cells unpredictably.
- Camelot with hard-coded coordinates: breaks whenever the layout shifts.

## Approach
1. **PyMuPDF first, always.** Words and drawings from the text layer. Never OCR.
2. **Per output:**
   - **Balance:** find fields by **label text and synonyms from config** (never coordinates), and read the value in the same row or under the right column header.
   - **Performance:** find the tests table(s) by header words (Test / Current / Trigger|Threshold / Result synonyms) and take **all rows**. No fixed test list.
   - **Collateral:** long-table geometry (gutters inside a region) + **cross-page stitching** (`prototype/pipeline.py`), then **join tables on security ID** (LX…/ISIN).
3. **Validate everything:**
   - totals and subtotals equal their rows;
   - Result (Pass/Fail) agrees with Current vs Threshold;
   - collateral balances sum to the aggregate principal balance;
   - stakeholder ranges, when provided.
   - Do **not** use two-source agreement; the same field can legitimately differ between pages.
4. **Docling (egret-large, OCR off, TableFormer ACCURATE) is a fallback only:** for a page whose required table or field is missing or fails validation. Load it once per process. 1 worker by default.

## Known PDF quirks
- **us_1 and us_2 pages are `/Rotate 90`.** Transform all words and drawings with `page.rotation_matrix`.
- Visual separators differ by layout. Use them for segmentation along with whitespace:
  - Citi: filled title bars;
  - us_3: stroked boxes;
  - bny_1/bny_2: shaded alternating rows and bold section headings.
- Layouts seen so far: BNY-A (bny_1, bny_2), BNY-B (bny_3), Citi/Virtus (citi_1), US-A (us_1, us_2), US-B (us_3).

## Rules
- No page coordinates in config or code. Match on text; compute geometry per page.
- Every extracted value keeps provenance (report, page, bbox).
- Keep it simple: no YOLO, no Label Studio, no review UI for now.
- Config and paths live in `config/` + `config/local.yaml` (git-ignored). Never commit PDFs, outputs or models.
- Small steps. After each step, show real output on the sample reports before moving on.

## Plan
1. **Collateral long tables (biggest speed win):**
   - Port the prototype's geometry, stitching and totals validation into `src/wit/`, with the rotation and separator fixes.
   - Run it on all 7 reports and output the stitched tables + validation to `out/<report>/`.
   - Report: pages handled without Docling, validation pass/fail, and seconds per report.
2. **Performance:** detect tests tables by header words on dashboard and test pages, across all 7 reports.
3. **Balance:** label-based field lookup (draft labels from the samples; real field list comes later).
4. **Docling fallback** wired in for failures only; measure the total time per report.
5. Excel writers for the 3 outputs (once the field lists arrive) + stakeholder range checks.
6. Batch runner + `cli doctor` + `docs/SETUP.md` for the org laptop.
