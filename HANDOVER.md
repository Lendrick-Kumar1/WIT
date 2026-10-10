# WIT: handover

CLO trustee reports (born-digital PDFs) → 3 Excel files per deal: **Balance**, **Performance**,
**Collateral**. CPU only, no model on the main path, about 2–10 s per report.

Read this, then `CODE_GUIDE.md` (file by file, every rule, its test).

## 1. How it works

Other tools (Camelot, `find_tables()`, Docling) first **guess where the tables are**. On dashboards
and banded pages that guess goes wrong, and everything downstream breaks. This code does not guess:

| Output | It looks for | Then |
|---|---|---|
| Performance | a header line with a *result* word plus test/current/trigger words | reads the rows under it; side-by-side tables are split at each test column |
| Balance | each field's **label** as its own phrase | the number right of it, else directly below it; or the **total of a column** on a named page |
| Collateral | pages cut into **crops** (one table each, from the page's own separator lines) | each crop read as one table; tables joined across page breaks; subtotals/totals **checked**; headers mapped to the schema; tables joined on the security ID |

Pages that are stored rotated, and separator lines drawn as images, are handled in `pdfpage.py`.

## 2. How sure is it

- Every printed subtotal and total in the collateral tables is compared with the sum of the rows
  read (sheet `collateral_sums`). If they match, no row on those pages was lost or merged.
- Uncertain values get a status instead of a guess: `_status` on test rows, `status` on balance
  values (ok / ambiguous / conflict / missing), `check: ...` on sums.
- `_run_report.xlsx` gathers all of it. Open it first after every run.

## 3. Inputs

```
deal list Excel  ──► active deals + trustee          config/sources.yaml (path, column names)
reports root     ──► <deal>/<Monthly|Quarterly|Intra Trustee Report>/<file named 2026_8 ...>
--period 2026-08 ──► first report-type folder (in priority order) that has the file
```
Deal name, trustee and month come from this metadata. The trustee picks
`config/trustees/<name>.yaml`; if a trustee has several layouts, its `detect:` patterns choose.

## 4. Run

```bash
poetry run python demo/make_demo.py                 # demo tree from the sample PDFs in reports/
poetry run python run.py --period 2026-08           # all active deals
poetry run python run.py --period 2026-08 --trustee "U.S. Bank"
poetry run python run.py some.pdf                   # one PDF, trustee detected from its text
poetry run python run.py some.pdf --dump 3          # page 3: every crop table + label/value pairs
poetry run python run.py ... --fallback             # XLarge for crops whose checks fail (slow)
poetry run python tools/crop_test.py some.pdf --no-docling   # see how pages are cropped and read
poetry run python tests/run_tests.py                # 30 rule tests, no PDFs needed
```
Output: `out/<period>/<deal>/Balance.xlsx, Performance.xlsx, Collateral.xlsx` and
`out/<period>/_run_report.xlsx` (sheets: summary, balance_sources, performance_flags,
collateral_gaps, collateral_sums, xlarge_fallback).

## 5. Status on the 6 sample reports (demo deals 1–6)

| Demo deal | Layout | Tests | Collateral rows | Sums ok / to check |
|---|---|---|---|---|
| 1 | bny_mellon_a | 78 | 140 | 7 / 0 |
| 2 | bny_mellon_a | 76 | 204 | 6 / 1 (amount in a column the rows don't use) |
| 3 (Quarterly folder) | bny_mellon_b | 63 | 158 | 2 / 0 |
| 4 | citi | 18 | 192 | 0 / 0 (no printed totals) |
| 5 | us_bank_a | 62 | 123 | 1 / 0 |
| 6 | us_bank_a | 16 | 170 | 1 / 0 |
| 7 | (no report) | reported as MISSING | | |

- **Performance:** solid on all layouts, including dashboards and banded pages.
- **Balance:** the mechanism works. The labels are placeholders until filled in from the legacy repo.
- **Collateral:** rows, IDs and principal balances are verified by the sums. 6–15 of the 29 columns
  fill; the rest needs page key terms and header synonyms from the legacy repo.

## 6. On the org laptop: config only

1. `config/sources.yaml`: the real deal-list path and column names, reports root, folder names.
2. Per trustee: copy `config/trustees/_template.yaml` to `<trustee>.yaml` and fill in `names`,
   `pages` (legacy key terms), `balance.labels`, and `collateral.columns` where headers differ.
3. Run one trustee: `python run.py --period 2026-08 --trustee "<name>"`.
4. Open `_run_report.xlsx`:
   - `collateral_sums` rows starting with `check:` mark pages where rows were lost or merged;
   - `collateral_gaps` lists columns with no synonym yet;
   - `balance_sources` shows balances with status other than ok.
5. Record what went wrong as a **pattern** (no deal names), e.g. "total printed one column right of
   its rows", then fix it in code with a test, or in config.

## 7. Folder map

```
WIT/
├── run.py                      entry point (calls src/wit/run.py)
├── config/
│   ├── sources.yaml            deal list + reports root + folder priority + file naming
│   ├── defaults.yaml           shared vocabulary: header roles, categories, column synonyms
│   └── trustees/*.yaml         one per trustee layout (_template.yaml to add one)
├── src/wit/                    the code (see CODE_GUIDE.md)
├── tools/crop_test.py          how a PDF is cropped and read (+ optional XLarge comparison)
├── tools/compare_outputs.py    cell-by-cell comparison of two output folders
├── tests/                      rule tests on synthetic words (python tests/run_tests.py)
└── demo/make_demo.py           builds a demo deal list + folder tree from reports/
```
Never commit PDFs, outputs (`out/`) or models.
