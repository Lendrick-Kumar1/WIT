# WIT

Reads CLO trustee reports (born-digital PDFs) and writes, per deal and month, three Excel files:
**Balance**, **Performance**, **Collateral**, plus one **run report** per run that says what was
found and how sure it is. CPU only; about 3–6 seconds per report.

**Start here.** This file explains how to set up, run and build. `GUIDE.md` explains how it works,
file by file and rule by rule.

---

## Folders

```
WIT/
├── app.py              start: the window (no arguments, ttkbootstrap) or the command line
├── build_exe.bat       builds dist\WIT\WIT.exe
├── config/             EVERYTHING you adjust (no code changes needed)
│   ├── settings.yaml       where the reports and deal list are; output names and columns
│   ├── defaults.yaml       words the reader looks for (shared by all trustees)
│   └── trustees/*.yaml     what differs per trustee (page titles, labels, header names)
├── src/wit/            the code
├── dev/                only for checking code changes (not needed to run, not in the .exe)
│   ├── tests/              46 rule tests:  python dev/tests/run_tests.py
│   ├── compare_outputs.py  before/after comparison of two output folders
│   └── crop_view.py        pictures of how a page is cut into tables
├── README.md           this file
└── GUIDE.md            how it works
```

Folders you may see locally but that are never in git: `out/` (results), `reports/`, `probs/`
(sample PDFs), `.venv/`, `dist/`, `build/`.

---

## How reports are found

```
<reports_root>/<deal folder>/<report type>/<month folder>/<any name>.pdf
E:/CDOA/Reports/Deal A/Monthly Trustee Report/2026_08/Trustee Report.pdf
```

- Deals and their trustees come from the **deal list** Excel; nothing is read from the PDF to
  find out which deal or month it is.
- Report types are tried in the order of `report_types` in `settings.yaml` (Monthly first, ...).
- A month folder is recognised by its name: `2026_08`, `2026-08`, `2026_8`, `202608`,
  `2026_08_15`. A PDF named with the month directly inside the report-type folder works too.
- Every PDF is checked before it is read: empty, not a PDF, cut off, damaged, password protected,
  no text (scanned). Broken files are skipped and reported.
- Two or more PDFs for the same month: identical copies → one is used; different files → the
  newest is used and the run report says so.
- No report for that month → `missing`, with the latest month that does exist (e.g. a quarterly
  deal: "latest is 2026-06 (Quarterly Trustee Report)").

---

## Running

### The window (WIT.exe, or `python app.py`)
1. **Period**: pick any years and any months; every chosen year is combined with every chosen
   month (2025 + 2026 with Mar + Sep = 4 months). Future months are left out. Last month is
   selected at start.
2. **Outputs**: Balance / Performance / Collateral, any combination.
3. **Deals**: *All deals*, or switch it off and select deals (Ctrl/Shift-click; the search box
   filters; *Select shown* / *Clear*; selections are kept while you search). Only the deals the
   deal list's `filter` keeps (e.g. active ones) are listed.
4. **Check reports** lists which PDF would be read for every deal and month (nothing is
   extracted). **Run** extracts. **Stop** ends after the current deal. Results are written deal by
   deal, so a stopped run keeps what was finished. Output folders are fixed in `settings.yaml`.

### The command line
```
python app.py run --months 2026-08                                  all deals, one month
python app.py run --months 2026-08 --deal "Deal A"                  one deal, one month
python app.py run --months 2026-01:2026-06 --deal "Deal A"          one deal, several months
python app.py run --months 2025-06,2026-03:2026-05                  any mix of months and ranges
python app.py run --months 2026-08 --deal "Deal A" --deal "Deal B"  several deals
python app.py run --months 2026-08 --trustee "BNY"                  one trustee's deals
python app.py run --months 2026-08 --outputs balance,performance    only some outputs
python app.py run --months 2026-08 --check                          only list the PDFs found
python app.py run --months 2026-08 --out out_test                   all outputs under one test folder
python app.py inspect "<pdf>" --pages 12,13                         what the reader sees on pages
```
(With poetry: `poetry run python app.py ...`.)

### Output
One fixed folder per output, set in `settings.yaml` (`output.balance.dir`, ...). File names
there use `{deal}`, `{yyyy}`, `{mm}`:
```
<Balance folder>/Deal A_2026_08.xlsx
<Performance folder>/Deal A_2026_08.xlsx
<Collateral folder>/Deal A_2026_08.xlsx
<Run reports folder>/run_report_2026-10-13_141502.xlsx        one per run
```
Running the same deal and month again overwrites its files.
Run report sheets: `summary` (one line per deal and month: file found?, counts, statuses),
`balance_sources`, `performance_flags`, `unmapped_tests`, `collateral_gaps`, `collateral_sums`.
What each means: `GUIDE.md` §7. Open it after every run; rows with `needs_attention` = True first.

---

## Setting up (org laptop)

```
git clone https://github.com/Lendrick-Kumar1/WIT.git
cd WIT
poetry install                       (or: pip install pymupdf pandas openpyxl pyyaml "ttkbootstrap==1.10.1")
poetry add "ttkbootstrap==1.10.1"    (once, if pyproject.toml doesn't list it yet: the window needs it)
python dev/tests/run_tests.py        46 passed, 0 failed
```

Then fill in `config/` (no code):

1. `config/settings.yaml`: `reports_root`, `report_types`, `deal_list` (path, sheet, column
   names, filter), and under `output` the folder and file name of each output, the run-report
   folder, month format, columns and `rename` (internal column name → header written).
2. `config/trustees/<trustee>.yaml` per trustee layout: `names` (as the deal list spells the
   trustee), `pages` (page titles per output), `balance.labels`, and only the header names that
   differ from `defaults.yaml`. New trustee: copy `_template.yaml`.
3. `config/defaults.yaml` → `performance.test_names`: standard test name → patterns of the names
   as printed. Unmapped names stay as printed and are listed in the run report (`unmapped_tests`).
4. `python app.py run --months 2026-08 --trustee "<one trustee>" --check`, then without `--check`.

The legacy repo already holds most of these names; `COPILOT_PORTING.md` (kept with the legacy
repo, not here) tells Copilot how to copy them over.

### Getting code updates (org laptop only pulls, never pushes)
```
git stash && git pull && git stash pop
```
`stash` keeps your filled-in config aside while the new code comes in. If the same lines
changed on both sides, git marks them in the file: keep your real values.

---

## Building WIT.exe

On a Windows machine with the repo and poetry:
```
build_exe.bat
```
Result: `dist\WIT\` holding `WIT.exe`, its libraries, and a `config\` folder. The window uses
ttkbootstrap (themed tkinter), pinned to 1.10.1 because version 2 renamed its modules. Copy the whole
`dist\WIT` folder to the machine that will run it and edit `dist\WIT\config\settings.yaml` there.
Relative paths in `settings.yaml` are relative to the folder of `WIT.exe`. The XLarge fallback
(Docling) is not included in the .exe.

---

## When something is wrong

1. Find it in the run report (sheet and page).
2. `python app.py inspect "<pdf>" --pages <n>` shows what the reader sees on that page.
3. A wrong page title, label or header name → fix it in `config/` (no code).
4. A layout the reader can't handle → describe the **pattern** (no deal names, issuer names or
   figures), e.g. "collateral: total printed one column right of its rows", and fix it in code
   with a test (`GUIDE.md` §9).
