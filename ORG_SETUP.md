# Org laptop: setup and working routine

The code flows **one way**: changes are made on the personal laptop, pushed to GitHub, and the
org laptop only **pulls**. Nothing is ever pushed from the org laptop: real paths, labels,
reports and outputs stay there.

All commands are for Git Bash, one line at a time.

---

## 1. Get the code (once)

```
cd ~ && git clone https://github.com/Lendrick-Kumar1/WIT.git
```
If the repo is private, git asks you to sign in (choose "Sign in with your browser").

```
cd ~/WIT && poetry install
```
If poetry or PyPI is blocked, install the four packages the main path needs:
```
pip install pymupdf pandas openpyxl pyyaml
```
(Docling is only needed for `--fallback`; skip it.)

Check that everything works:
```
poetry run python tests/run_tests.py
```
It must end with `40 passed, 0 failed` (the number grows as rules are added).

---

## 2. Point it at the real data: `config/sources.yaml`

| Key | Set it to |
|---|---|
| `deal_list.path` | the real active-deals Excel |
| `deal_list.sheet` | sheet name or index |
| `deal_list.columns.deal` | column holding the deal name |
| `deal_list.columns.trustee` | column holding the trustee |
| `deal_list.columns.folder` | column whose value equals the deal's folder name |
| `deal_list.filter` | e.g. `{Status: Active}` |
| `reports_root` | the real reports root folder |
| `report_folders` | the real report-type folder names, in priority order |
| `file_period_regex` | only if file names don't look like `2026_8 ...` |

Use forward slashes in paths (`D:/Reports/...`), or put Windows paths in single quotes.

---

## 3. Fill in one trustee from the legacy repo

Start with one trustee, e.g. `config/trustees/bny_mellon_a.yaml`:

| Key | What goes in |
|---|---|
| `names` | regex matching the trustee as the deal list spells it |
| `pages.performance / balance / collateral` | the legacy key terms (page titles, regex) |
| `balance.labels` | the real labels, replacing every `<<PLACEHOLDER>>` (forms in WALKTHROUGH.md §4.7) |
| `collateral.columns` | only headers that differ from `config/defaults.yaml` |

A trustee with no config yet: copy `config/trustees/_template.yaml` to `config/trustees/<trustee>.yaml`.
A trustee with several layouts: one file per layout, with `detect:` patterns to tell them apart.

---

## 4. Run that trustee only

```
poetry run python run.py --period 2026-08 --trustee "BNY"
```
(Use a period whose reports exist. `--trustee` matches any part of the deal list's trustee value.)

Output: `out/<period>/<deal>/Balance.xlsx, Performance.xlsx, Collateral.xlsx` and
`out/<period>/_run_report.xlsx`.

---

## 5. Check `_run_report.xlsx`, in this order

1. **summary**: any `layout` = unknown, `tests` = 0, `collateral_rows` = 0.
2. **collateral_sums**: any row starting with `check:` (rows lost, merged or misread).
3. **balance_sources**: any status other than `ok`.
4. **performance_flags**: test rows with `check: ...`.
5. **collateral_gaps**: columns that stayed empty (usually a missing header synonym).

What each status means: WALKTHROUGH.md §7.

---

## 6. Look at a problem page

```
poetry run python run.py "<path to pdf>" --dump 12
```
Every table read on page 12, with its subtotal/total checks, plus every label/value pair.

```
poetry run python run.py "<path to pdf>" --debug 12
```
The test rows and balance candidates found on page 12.

```
poetry run python tools/crop_test.py "<path to pdf>" --pages 12 --no-docling
```
How page 12 is cut into tables (PNG per crop in `out/crop_test/`).

---

## 7. Repeat for every trustee

Steps 3–6, one trustee at a time. When all are filled:
```
poetry run python run.py --period 2026-08
```

---

## 8. Reporting a problem back (to fix on the personal laptop)

Describe the **pattern only**: no deal names, no issuer names, no figures, no screenshots of real
data. Say which trustee config, which output, what the page does, what went wrong.

Examples:
- "bny_mellon_a, collateral: total printed one column right of its rows; check fails"
- "citi, collateral: header 'Par Amt' not mapped to principal balance"
- "us_bank_a, performance: test names wrap onto 3 lines; third line lost"
- "new trustee: every page has the section title at the bottom, not the top"

Config-only problems (a label, a page title, a header synonym) can be fixed directly on the org
laptop, no code change needed.

---

## 9. Getting a code update

```
cd ~/WIT && git stash && git pull && git stash pop
```
`stash` puts your local config edits aside, `pull` brings the new code, `stash pop` puts your
edits back. If the same lines changed on both sides, git marks them in the file
(`<<<<<<<` / `>>>>>>>`): keep your real values, delete the markers.

Then:
```
poetry run python tests/run_tests.py
```

Before and after an update, to see exactly what the update changed:
```
poetry run python run.py --period 2026-08 --out out_before
```
(update)
```
poetry run python run.py --period 2026-08 --out out_after
```
```
poetry run python tools/compare_outputs.py out_before/2026-08 out_after/2026-08
```

---

## 10. Never on the org laptop

- `git push`, `git commit` of config with real values.
- Copying reports, outputs or real labels to the personal laptop or into chats.
- Deleting `out_*` folders you still need for comparisons.
