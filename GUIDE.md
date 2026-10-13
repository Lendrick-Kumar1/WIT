# WIT: how it works

This document explains how WIT works: the problem it solves, how a PDF travels through the
code, every file and function in reading order, every rule and threshold (and why it exists),
how certainty is reported, the known limits, and how to change the code safely.

Read it **next to the code**, top to bottom. Section 4 follows the files in the order you should
open them. Every function name in `backticks` exists in the code with that exact name.
Setting up and running: `README.md`. The rules in one table: Appendix A.

---

## Contents

0. How to read this
1. The problem
2. Vocabulary
3. The big picture: one run, start to finish
4. File by file, function by function
   - 4.1 `app.py`, `cli.py`, `gui.py`, `run.py`, `inspect_pdf.py`: starting and running
   - 4.2 `config.py` and the YAML files: which rules apply
   - 4.3 `sources.py`: which PDF belongs to which deal and month
   - 4.4 `pages.py`: which pages feed which output
   - 4.5 `pdfpage.py`: reading a page (words, lines, phrases, numbers)
   - 4.6 `performance.py`: test rows
   - 4.7 `balance.py`: balance values
   - 4.8 `crops.py`: cutting a page into tables
   - 4.9 `table.py`: reading one table
   - 4.10 `totals.py`: subtotals, totals, groups, page breaks
   - 4.11 `collateral.py`: one row per security
   - 4.12 `fallback.py`: the optional model
   - 4.13 `dev/`: tests and checking tools
5. Worked examples
6. Every threshold, and what it is measured against
7. How certainty is reported (the run report)
8. Known limits and risks
9. How to change the code safely
10. What to do next
11. Review checklist

Appendix A: every rule, why, where, and its test

---

## 0. How to read this

Suggested order:

1. Sections 1–3 (about 20 minutes). You need the vocabulary and the flow before the code
   makes sense.
2. Section 4, **with the file open next to it**. Read the section, then the function, then go
   back to the section. Allow about one hour per big file (`table.py`, `totals.py`,
   `performance.py`). The small files take minutes.
3. Section 5: run the worked examples in your head; they exercise the hardest rules.
4. Sections 6–8 and Appendix A are reference material. Come back to them when reviewing a rule.
5. Section 9 before you change anything.

Size of the code (lines, including comments and docstrings):

| File | Lines | Difficulty |
|---|---|---|
| `app.py`, `src/wit/cli.py`, `gui.py`, `run.py`, `inspect_pdf.py` | ~530 | easy (plumbing and window) |
| `src/wit/config.py`, `sources.py`, `pages.py` | ~330 | easy |
| `src/wit/pdfpage.py` | ~105 | easy, but everything depends on it |
| `src/wit/performance.py` | ~200 | medium |
| `src/wit/balance.py` | ~150 | medium |
| `src/wit/crops.py` | ~210 | medium |
| `src/wit/table.py` | ~610 | **hard**: the core of collateral reading |
| `src/wit/totals.py` | ~260 | **hard**: the proof that rows were read correctly |
| `src/wit/collateral.py` | ~230 | medium |
| `src/wit/fallback.py` | ~65 | easy (optional) |

---

## 1. The problem

### Input
Trustee reports for CLO deals: born-digital PDFs (made by software, not scanned), about 9
trustees, about 233 active deals per period. Each trustee has its own layout; some trustees
have more than one layout. Each report is 40–200 pages.

### Output, per deal
| File | One row per | Columns |
|---|---|---|
| `Balance.xlsx` | deal | principal balance, default balance, proceeds balance, CCC balance |
| `Performance.xlsx` | compliance test | standard test name, test name as printed, current value, trigger, result (pass/fail) |
| `Collateral.xlsx` | security (loan / bond) | 29 schema columns: ID, issuer, ratings, balance, spread, maturity ... |

Plus one run report per run that says, for every deal and month, what was found and how sure we
are (section 7).

### Constraints
- CPU only, 16 GB RAM, Windows. Delivered as `WIT.exe` (a window) for people without Python.
- About 233 deals per month: it must be fast (seconds per report, not minutes).
- Runs are chosen by month(s) × deal(s) × output(s): a whole month, one deal and month, one
  deal over several months, any of Balance / Performance / Collateral.
- The reports are sensitive: they live on the org laptop only. Code, comments, tests and docs
  never name a deal, issuer or real figure.

### Why not "just use a table-extraction model"
Generic tools (Camelot, PyMuPDF `find_tables()`, Docling/TableFormer) first **guess where the
tables are**. On these reports that guess often fails: dashboards with several small tables
next to each other, banded pages, totals printed above their rows, headers spread over three
lines, columns printed 4 pt apart. When the table boundary is wrong, everything after it is
wrong, and **nothing tells you**.

This code reverses the approach:
1. It looks for **what the output needs, by its words** (a header line containing "Result", a
   label "Aggregate Principal Balance", a column header "Security ID").
2. It uses the **PDF's own structure** (separator lines drawn by the trustee's software,
   alignment of numbers, line spacing), never fixed coordinates.
3. It **proves** what it read where it can: every printed subtotal and total is compared with
   the sum of the rows read. If they match, no row was lost or merged.
4. When it is not sure, it **says so** (a status / check), instead of writing a number that
   looks right.

The model (Docling "XLarge") is kept only as an optional fallback for single tables whose
checks fail (section 4.12).

### Design rules you will see everywhere
1. **No coordinates** in code or config. Every distance is relative to the text itself: line
   height, normal line step, normal word space.
2. **Trustee differences live in YAML** (`config/trustees/*.yaml`), never as
   `if trustee == ...` in code.
3. **Never silently guess.** Uncertain → status/check in the run report.
4. **Comments describe the pattern, not the deal** ("total printed above the header").
5. **Every rule has a test** built from synthetic words (no PDFs in the repo).

---

## 2. Vocabulary

These words are used with an exact meaning in the code and in this document.

| Term | Meaning | Where |
|---|---|---|
| **point (pt)** | PDF unit, 1/72 inch. All coordinates are points, origin top-left, y grows downward. | everywhere |
| **word** | `{x0, y0, x1, y1, t}`: one word as PyMuPDF returns it, after rotation correction. | `pdfpage.page_model` |
| **line** / **row** | Words whose vertical centres are close: `{c: centre y, ws: words left→right, text}`. | `pdfpage.rows_of` |
| **lh** | "line height": the median height of the words being looked at. The unit for most distances. | many places |
| **phrase** | Words on one line that are closer than a gap (e.g. 0.9·lh). "Senior Secured" is one phrase; "Senior Secured   B2" is two. | `pdfpage.phrases` |
| **rule** | A thin drawn line or thin image. Horizontal rules (≤ 10 pt high, > 60 pt wide), vertical rules (≤ 3 pt wide, > 30 pt high). | `pdfpage.page_model` |
| **section separator** | A *full-width* horizontal rule (≥ 60% of page width), ≤ 2.5 pt (drawing) or 3–12 pt (image). Cuts a page into bands. | `crops.section_separators` |
| **title block** | Lines at the top of the page printed larger than body text (deal name, section title, "as of"). | `crops.title_bottom` |
| **footer** | Lines at the bottom with no amounts, after a clearly larger gap or carrying page numbering. | `crops.footer_top` |
| **band** | The words between two section separators. | `crops.find_crops` |
| **crop** | A rectangle on the page holding exactly ONE table. Bands are merged / split into crops. | `crops.find_crops` |
| **amount** | A word that looks like money, a decimal or a percent (`1,234.56`, `0.00`, `4.5%`). Dates don't count. | `crops.AMOUNT`, `table.MONEY` |
| **data line** | A line with a digit that is not part of a date, or a `Label: value` pair. Everything above the first data line is header. | `table.is_data_line` |
| **header** | The lines of a table above its first data line. Can be 1–8 lines. | `table.header_size` |
| **gutter** | A vertical strip with (almost) no ink across the data lines: the white space between two columns. | `table.find_gutters` |
| **cut** | The x position chosen inside a gutter as the column boundary. | `table.column_cuts` |
| **seam** | A *narrow* gutter (a few pt) between a right-aligned column and a left-aligned one. | `table._seams` |
| **wrapped cell** | A cell printed on two lines; the second line is glued back to its row. | `table.body_rows` |
| **centred cell** | A 2–3 line cell printed vertically centred on its row (text above AND below the amounts). | `table._centred_cells` |
| **section label** | A lone label in column 0 ("Loan", "Bond") that starts a section; becomes the `_section` column. | `table.split_sections` |
| **group** | Rows that share a value printed only on the group's first row (an industry, an issuer). | `totals.mark_totals` |
| **sum line** | A line with amounts and no text except a "Total" label. A subtotal or total. | `totals._classify_lines` |
| **ruled record** | A layout where every security sits between two rules, as a small block of lines. | `table.ruled_records` |
| **stacked field** | Several fields printed under each other in one column inside a record (issuer / country / ID). | `table.record_table` |
| **stitching** | Joining a table that continues on the next page. | `totals.stitch_pages` |
| **role** | What a performance header column means: test, current, trigger, result, prior, skip. | `performance.role_of` |
| **field** | A column of the output schema ("loan id", "principal balance"). | config `collateral.columns` |

---

## 3. The big picture: one run, start to finish

```
WIT.exe / python app.py          (window)        python app.py run --months ... (command line)
            │                                                │
            └──────────── months × deals × outputs ──────────┘
                                   │
sources.plan(settings, months, deals)      deal list Excel → active deals (+ trustee)
   for every (month, deal): find_report     <root>/<deal>/<report type>/<YYYY_MM>/*.pdf
                                             check every PDF, pick one, or missing / broken
                                   │
run.run(jobs, outputs, settings)
   for every job with a PDF:  process(job, outputs)
     │
     ├─ config.pick_config(doc, trustee from deal list)   which trustee layout applies
     │
     ├─ PERFORMANCE (if selected)   pages.select_pages → performance.performance(page)
     │                               printed name → standard name; duplicates dropped
     ├─ BALANCE (if selected)       balance.candidates → resolve; or table_total
     ├─ COLLATERAL (if selected)    crops.page_tables → stitch_pages → mark_totals → join_on_id
     │
     └─ write_deal()  →  <out>/<YYYY-MM>/<deal>/Balance.xlsx, Performance.xlsx, Collateral.xlsx
   write_run_report() →  <out>/run_report_<date>_<time>.xlsx
```

Key points:
- **Deal, trustee and month come from the deal list and the user's selection**, never from the
  PDF text. The PDF is only searched for the data.
- The three outputs are read **independently** and only when selected. A failure in collateral
  doesn't affect performance; a deal that fails is reported and the run continues.
- Each deal is written as soon as it is done, so a stopped run keeps what was finished.
- Only **collateral** (and balance column totals) uses crops and table reading. Performance and
  balance labels read the page's lines directly, because they look for specific words.

---

## 4. File by file, function by function

### 4.1 `app.py`, `cli.py`, `gui.py`, `run.py`, `inspect_pdf.py`: starting and running

**`app.py`** (repo root): puts `src/` on the path; no arguments → the window (`gui.main`),
arguments → the command line (`cli.main`). `WIT.exe` is this file packaged by PyInstaller
(`build_exe.bat`).

**`src/wit/cli.py`**: two commands.
- `run --months 2026-08 | 2026-01:2026-06 | 2025-06,2026-03:2026-05 [--deal NAME ...] [--trustee TEXT]
  [--outputs balance,performance,collateral] [--out FOLDER] [--settings FILE] [--check]
  [--fallback]`. `months_arg` turns the text into a list of (year, month). `--check` only prints
  the plan (`print_plan`): which PDF would be read for every deal and month. Unknown deal names
  and an unreadable deal list stop with a clear message.
- `inspect PDF --pages 12,13 [--trustee TEXT]` → `inspect_pdf.inspect`.

**`src/wit/gui.py`**: the window, built with **ttkbootstrap** (themed tkinter; pinned to 1.10.1,
because version 2 renamed its modules). Only standard widgets are used (Labelframe, Combobox,
Checkbutton as switches, Button, Progressbar, plus a plain Listbox and Text coloured from the
theme), so it packages cleanly with PyInstaller.
- `App._build`: Period (year buttons and month buttons, each multi-select; `_selected_months`
  = every chosen year × every chosen month, future months left out; last month selected at
  start), Outputs (three switches), Deals (All deals switch, search box, Select shown / Clear,
  multi-select list; the deal list's `filter` is applied in the background), Check reports /
  Run / Stop, progress bar, log. Output folders are not shown: they are fixed in
  `settings.yaml`.
- Deals: `self.picked` keeps the selected deal names while the search text changes
  (`_fill_list` re-selects them, `_on_select` updates them).
- `_start` validates the choice, then `_work` runs in a **background thread** so the window
  stays responsive. The thread never touches the window: it puts log lines on a queue
  (`_say`), and `_poll` (every 100 ms, on the window's thread) writes them to the log.
- **Stop** sets a flag that `run.run` checks before each deal; the progress bar is fed through
  the same queue (`progress` callback).

**`src/wit/run.py`**: the engine, used by both.
- `OUTPUTS` = balance, performance, collateral.
- `DealResult`: the job, its summary line (`report`), the output tables (internal column names),
  and everything for the run report (`bal_sources`, `perf_flags`, `unmapped`, `coll_checks`,
  `empty_cols`, `fallback`).
- `month_label(job, settings)`: `report_month` as written, `output.month_format` applied to the
  1st of the month.
- `read_performance(doc, cfg)`: test rows of every performance page; duplicates (same printed
  name, current value and trigger) dropped, because many reports print each test twice
  (summary + detail). *Nuance*: two genuinely different tests with the same printed name, value
  and trigger would merge; that's why wrapped names matter (4.6).
- `read_balance(doc, cfg)`: candidates from every balance page → `resolve`; table-total fields →
  `table_total`.
- `process(job, outputs, ...)`: one deal and month. No PDF → only the summary line. Otherwise:
  pick the config, read only the selected outputs, add `deal name`, `report_month`,
  `asset class`, and decide `needs_attention` (unknown layout, file not ok, no tests, a test
  not ok, a balance not ok, no collateral rows).
- `output_path`, `write_deal`: each output goes to its own fixed folder
  (`output.<name>.dir`) with its file name (`output.<name>.file`); both may use `{deal}`,
  `{yyyy}`, `{mm}` (characters Windows forbids in the deal name are replaced). Columns from
  `output.columns` (missing ones stay empty), headers renamed by `output.rename`.
- `write_run_report`: one Excel per run with 7 sheets (section 7); every sheet has `deal` and
  `month` first.
- `run(jobs, outputs, settings, log, xl, stop)`: loops over the jobs; each deal is written as
  soon as it's done; an exception in one deal is logged and reported (`error` column) and the
  run continues; the run report is written at the end.

**`src/wit/inspect_pdf.py`**: `inspect(pdf, pages, trustee)` prints, per page, the test rows
(standard name | printed name | values | status), the balance candidates, every crop's table
after `mark_totals`, and every "label  value" pair. The first thing to run when a page is read
wrong.

---

### 4.2 `config.py` and the YAML files: which rules apply

**The idea.** All trustee-specific knowledge is text in YAML: page titles, labels, header
synonyms, detection patterns. Adding a trustee = adding one YAML file, no code.

**`config/settings.yaml`** (read by `load_settings`): `reports_root`, `report_types` (priority
order), `deal_list` (path, sheet, column names for deal / trustee / folder, filter) and `output`
(folder and file name per output, run-report folder, month format, the columns of each file,
`rename`). `redirect_outputs` puts all of them under one folder (command line `--out`, used for
before/after comparisons). Relative
paths are relative to the app folder (`app_dir()`: the folder of `WIT.exe` when packaged, else
the repo root), so a copied `dist\WIT` folder works anywhere.

**`config/defaults.yaml`**: the shared vocabulary:
- `layout.title_band` (0.2): the top 20% of a page is searched for its section title.
- `pages.*`: page-title regexes per output. Empty list = scan every page.
- `performance.header_roles`: header text → role. **Order matters, first match wins**:
  `skip` (numerator, denominator, cushion …) → `test` → `trigger` → `prior` → `current` →
  `result` → `test2`. Why prior/current before result: a header "Current Result" holds the
  *value*, "Prior Result" the *previous value*; only a header that is just "Result" is the
  pass/fail column.
- `performance.test_names`: standard test name → patterns of the names as printed (4.6).
- `balance.labels`: **placeholders** until filled from the legacy repo.
- `collateral.id_patterns`: what a security ID looks like: LoanX `LX\d{6}`, ISIN
  `[A-Z]{2}[A-Z0-9]{9}\d`, FIGI `BBG[A-Z0-9]{9}`, CUSIP `[A-Z0-9]{9}`.
- `collateral.columns`: header synonyms per output field. **Order matters**: a header goes to
  the first field whose regex matches. That's why "moody.*recovery" comes before
  "moody.*rating": a header "Moody's Recovery Rate" must not become the Moody's rating.
- `collateral.numeric_columns`: fields converted to numbers in the output.

**`config/trustees/<name>.yaml`**: only what differs: `names` (regex on the deal list's
trustee column), `detect` (patterns in the PDF text), `layout`, `pages`, `balance.labels`,
sometimes header synonyms or test names. `_template.yaml` documents every option (files starting with
`_` are ignored).

**`_merge(base, over)`**: dicts merge recursively; lists and scalars in the trustee file
*replace* the default. Consequence: if a trustee file sets `pages.performance`, it replaces
the whole default list, not appends to it.

**`load_settings(path)`**: reads `settings.yaml` and makes its paths absolute.

**`load_trustees()`**: reads defaults, then every enabled trustee file merged onto the
defaults. Returns `(defaults, {name: merged config})`.

**`doc_text(doc, n_pages=3)`**: text of the first 3 pages + PDF metadata (used for detection).

**`layouts_for(trustee_name, trustees)`**: configs whose `names` regex matches the trustee
value from the deal list.

**`pick_config(doc, defaults, trustees, trustee_name)`**:
- trustee known and exactly one layout → that one;
- several layouts (e.g. two BNY layouts) → `detect_trustee` among them; if none matches, the
  first one;
- no trustee given (`inspect` without `--trustee`) → `detect_trustee` across all configs.

**`detect_trustee(doc, defaults, trustees)`**: a config qualifies only if **all** its
`detect.all` patterns are found; among those, the score is the number of `detect.any` patterns
found (+ the count of `all` patterns). Highest score wins; nothing qualifies → `"unknown"` with
the defaults (and `needs_attention`).

---

### 4.3 `sources.py`: which PDF belongs to which deal and month

```
<reports_root>/<deal folder>/<report type>/<month folder>/<any name>.pdf
```

**Months**
- `month_of(name)`: a 4-digit year followed by a 1–2 digit month, separated by `_`, `-`, `.`, a
  space or nothing: `2026_08`, `2026-8`, `202608`, `2026_08_15` → (2026, 8). The digits must not
  be part of a longer number. If a name holds several, the **last** counts ("Deal 2019-1
  2026_08" → 2026-08). Years 1991–2099, months 1–12 only. This is code, not a config regex,
  because the rule is the same everywhere.
- `parse_month`, `months_between(first, last)`: the list of months from first to last.

**Deals**
- `active_deals(settings)`: the deal list Excel, `filter` applied (case-insensitive), →
  `{deal, trustee, folder}`.
- `select_deals(deals, names, trustee)`: by exact name (case-insensitive; an unknown name is an
  error, not silently skipped) and/or trustee text.

**Checking a PDF: `check_pdf(path)`** → `ok` or the reason:
1. size 0 → `empty file`;
2. the first 1 KB has no `%PDF-` → `not a PDF`;
3. the last 2 KB have no `%%EOF` → `damaged (file is cut off)` (a download or copy that stopped
   half-way);
4. PyMuPDF can't open it → `cannot be opened`; password → `password protected`; 0 pages →
   `no pages`; PyMuPDF had to repair it → `damaged (had to be repaired)`;
5. no text on the first 10 pages → `no text (scanned image?)` (a cover page that is an image
   is fine as long as a later page has text).
Steps 1–3 read only a few bytes (fast); step 4 is the real test.

**Finding the report: `find_report(settings, deal_folder, ym)`**
- No deal folder → `missing`.
- For each report type in priority order: `_pdfs_for_month` = PDFs anywhere inside month
  folders of that month, plus PDFs whose own name carries the month directly in the type
  folder. The first type with candidates wins → `_pick`.
- Nothing → `missing`, with `_latest_month` (the latest month any type has) in the note.

**`_pick(cands, rtype)`**: every candidate is checked; broken ones are skipped (named in the
note, status `check`). None good → `broken`. Several good: shortest name first ("Report.pdf"
before "Report (1).pdf"); identical content (MD5) → one used, noted; different files → the
**newest** (modification time) is used, the others are named, status `check`.

**`plan(settings, months, deal_names, trustee)`**: one job per (month, deal):
`{deal, trustee, folder, year, month, pdf, report_type, file_status, file_note}`.

---

### 4.4 `pages.py`: which pages feed which output

- **`page_texts(doc, title_band)`**: for every page, its **title** (text in the top
  `title_band` of the page) and its full text. Cached for the current document, because
  performance, balance and collateral all ask for it.
- **`select_pages(doc, cfg, output)`**: page indexes whose title (or text, when
  `pages.match_on: text`) matches any of the config regexes for that output. Empty list →
  every page.

Why titles: trustee reports name every section at the top of the page ("Detail of Assets",
"Par Value Tests"). Matching titles is fast and precise. These regexes are where the legacy
repo's "key terms" go.

---

### 4.5 `pdfpage.py`: reading a page

Every other module reads pages through this file.

**`NUM`**: `^\(?-?[\d,]*\.?\d+%?\)?$`, the shape of a printed number after cleaning.

**`page_model(page)` → (words, horizontal rules, vertical rules)**
1. Words from `page.get_text("words")`, each multiplied by `page.rotation_matrix`. Some
   trustees store pages rotated (`/Rotate 90`); after this every module sees the page upright,
   as printed.
2. Rules = thin drawings **and thin images**, because some trustees draw separator lines as
   images (gradient bars). Horizontal: ≤ 10 pt high and > 60 pt wide. Vertical: ≤ 3 pt wide
   and > 30 pt high.

**`rows_of(ws)` → lines** (the only line-grouping function in the code)
- Words sorted by vertical centre. A word joins the current line if its centre is within
  **half a line height** (median word height × 0.5) of the line's **running mean** centre;
  otherwise it starts a new line.
- Why a running mean: the line's centre adjusts as words join, so a slightly taller word
  (superscript, bold) doesn't start a new line.
- Each line: `{c, ws (left→right), text}`.

**`split_phrases(ws, gap)`** / **`phrases(ws, gap)`**: split a line's words wherever two
neighbours are more than `gap` apart. `phrases` returns `{x0, x1, t, h}` (h = tallest word,
used to tell a section label, which is printed larger, from a wrapped test name).

**`to_num(s, percent=True)`: the single number parser**
1. `percent=False` and ends with `%` → None (used when summing amounts: percentages are never
   added up).
2. Strips a leading `>=`, `<=`, `>`, `<`, `≥`, `≤` (triggers print as ">= 120.00%").
3. Strips `EUR/USD/GBP`, markers like `[A]`, the signs `€$£`, and spaces.
4. Must match `NUM`; `(1,234.50)` and `-1,234.50` → negative; commas removed.

Examples: `'1,234.50'` → 1234.5; `'(1,234.50)'` → −1234.5; `'>= 120.00%'` → 120.0;
`'€2,000,000.00'` → 2000000.0; `'4.19%'` with `percent=False` → None; `'5/2/2024'` → None.

**`page_title(page, words, band)`**: the text of the lines in the top `band` of the page.

---

### 4.6 `performance.py`: test rows

**What a test table looks like.** A header line with words like Test / Current / Trigger /
Result, then one row per test: name, numbers, Passed/Failed. Layouts vary: dashboards with
two tables side by side, headers over 2–3 lines, a line of dates under the header, names that
wrap onto a second line, section labels between groups of tests.

**Constants**
- `RESULT_WORDS`: what a result cell may say: pass(ed), fail(ed), n/a, yes, no, true, false,
  met, not met, breach. Overridable via `performance.result_vocab`.
- `ITEM`: `(a)`, `(ii)`, `Class …` at the start of a line = a new test, never a continuation.

**`standard_name(printed, test_names)`**: the printed name → (standard name, mapped?). Every
pattern of every standard name is tried; among those that match, the one matching the
**longest part** of the printed name wins ("class a/b par value" beats "par value" for "Class
A/B Par Value Test"), so the order in config doesn't matter. No match → the printed name, not
mapped (listed in the run report's `unmapped_tests`).

**`first_num(text)`**: the first number in a cell ("100.1% / 2,000,000.00" → 100.1).

**`role_of(text, roles)`**: header text → role; config order, first match wins.

**`performance(page, cfg)`: step by step**

1. **Words without the footer.** `footer_top` (from crops) measures the footer; words below
   it are dropped. Why: footer text ("Report produced …") was being glued onto the last test
   name.
2. **Lines** (`rows_of`) and `lh` = median word height.
3. **Find header lines**: a line containing the `result` role regex AND one of
   test / ratio / current. Each such line anchors one table.
4. **Collect the header block**:
   - up to 2 lines **above** it, each within 2.2·lh of the next;
   - lines **below** it that are close (< 2.2·lh) and are not data lines. Why: some layouts
     print the header's dates *under* the "Result" line, or the last line of a 3-line header
     sits below it.
5. **Anchor columns**: the header line with the **most phrases** (gap 0.6·lh) is the anchor;
   its phrases are the columns. Words of the other header lines attach to the column they
   overlap (or are nearest to), as prefix (line above) or suffix (line below).
   Why the most complete line: on a 3-line header, the "Result" line alone has only a few
   phrases; anchoring on it would lose columns, and tests would silently be missed.
6. **Roles** for every column (`role_of`).
7. **Side-by-side tables**: every column with role test/test2 (not directly after another test
   column) starts a sub-table (a `group` of columns). A dashboard with two tables next to each
   other becomes two groups.
8. **Body lines**: the lines below the header block until:
   - a horizontal rule wider than 200 pt (once there is at least one body line), or
   - a gap larger than 3·lh (8·lh before the first body line), or
   - the next header line (result + "test" words).
   Lines lying inside a rule's band are skipped.
9. **Per group**, the x range `[gx0, gx1)` it owns: from the previous group's end (+5) or a bit
   left of its test column (−15), to the next group's start (−5) or its last column + 2·lh.
10. **Per body line**, keep its words inside the group's x range, split into phrases (0.9·lh):
    - **One phrase, no digits**: either the **wrapped second line of the previous test**
      (glued) or a **section label** (skipped). It's a wrap only if `_wraps(...)`:
      directly under the last test row (< 1.6·lh), same text height (≤ 1.1×), and not starting
      left of the test name (≥ name x0 − 0.5·lh); and it doesn't start with an item marker.
      Why height/indent: section labels are printed larger and/or further left; wraps are
      printed exactly like the name they continue.
    - Otherwise, each phrase goes to the **nearest header column** (overlap, else distance)
      and fills that role: test name (or the first non-number phrase in an unnamed column),
      current/trigger (first number), result.
    - A line whose "result" looks like a header word is skipped (a repeated header).
    - **No current value and no result word**: a continuation line (wrapped name, sometimes
      with the trigger on the second line). Glued onto the previous test if `_wraps` (distance
      only) holds and it isn't a new item; otherwise ignored.
    - A **test row** = has a name AND (a current value OR a result). It gets a `_status`:
      `ok`, or `check: no current / result? / test name?`.
11. Finally every row: `original tests` = the name as printed; `test` = `standard_name(...)`.

**`_wraps(last, out, br, lh, phrase=None)`**: `last` = (last test record, its line's y, its
name phrase). True when line `br` is < 1.6·lh below it; for a lone phrase, also same height
and not further left.

---

### 4.7 `balance.py`: balance values

Each balance field has one of three config forms (`balance.labels`):

```yaml
principal balance: ["^aggregate principal balance$"]                 # a) label → number
principal balance: {labels: ["^aggregate principal balance$"], column: "current"}   # b) several numbers
default balance:   {page: "Defaulted Obligations Detail", column: "^principal balance$"}  # c) column total
```

**`fields(cfg)`**: splits the fields into label fields (forms a, b) and table fields (form c).

**`candidates(page, cfg)`**: for every phrase on the page (gap 0.9·lh) that matches a field's
label:
1. **RIGHT**: the run of numbers immediately right of the label on the same line. It stops at
   the next text phrase or at a vertical rule between them. Currency/percent tokens are
   skipped.
   - one number → candidate, how = `right`;
   - several numbers (Current | Prior) → if `column` is set, look up to 25 lines up for a
     header phrase matching it that overlaps one of the numbers → `right/column`; else the
     first number, how = `ambiguous`.
2. **BELOW**: nothing to the right → exactly one number on the next line (< 1.8·lh) that
   overlaps the label horizontally → how = `below`.

Each candidate: `(field, value, how, label, page)`.

**`resolve(cands, cfg)`**: per field, the **first** candidate (pages in `pages.balance` order,
top to bottom) wins. Status:
- `missing`: no candidate;
- `conflict`: the same label text gave different values somewhere in the report;
- `ambiguous`: the first candidate was ambiguous;
- `ok` otherwise.
`n` = how many candidates there were.

**`table_total(doc, cfg, spec)`**: for form c. Pages whose title matches `spec.page`; for every
crop table with a column matching `spec.column`, sums the detail rows and takes the printed
total (via `mark_totals`):
- no such page → `missing`;
- page exists, no rows ("There are no …") → 0, `ok (no rows)`;
- printed total ≠ sum of rows → printed value, `conflict`;
- else → printed (or summed) value, `ok`.

---

### 4.8 `crops.py`: cutting a page into tables

**Why crops.** `table.build_table` reads *one* table at a time. A collateral page can hold
several tables (stacked, or side by side). `find_crops` cuts the page so that each crop holds
exactly one table, using the separator lines the trustee's software drew.

**`AMOUNT`**, **`has_amount(ws)`**: money/decimal/percent words. Dates don't count.

**`section_separators(page, min_width)`**: y of full-width separators: drawings ≥ `min_width`
wide and ≤ 2.5 pt high; images ≥ `min_width` wide and 3–12 pt high. Why the limits: filled row
shading (~12 pt drawings) and 2 pt dotted images (between groups, above totals) are *not*
section boundaries.

**`title_bottom(words, page_height)`**: bottom of the title block. Walks the lines from the
top (only within the top 20%) while each line is a **single phrase** (no gap ≥ 1.5·body height)
AND **larger than body text** (≥ 1.1× the median word height) or the same size as the title line
above it. Stops at the first table-like line, or at rotated column-header words (taller than
twice their width). Why measured: a fixed "top 12%" cut off column headers on some layouts.

**`PAGE_NUMBER`**, **`footer_top(words, page_height)`**: top of the footer. Looks only at lines
in the bottom 15% holding no amounts, from the bottom up:
- a line with page numbering ("Page 9 of 48", "4 of 9") → that line and everything below it;
- a gap larger than 1.25× the normal line step → the lines below the gap.
The higher of the two wins; neither → no footer. Why the page-number signal: some footers sit
at the normal line step right under the last row, with no gap.

**`find_crops(page)`: the steps**
1. Drop the title block and footer.
2. **Bands** between the section separators.
3. **Merge**:
   - a header band followed by **ruled records** takes all of them (`_records_after`, below);
   - otherwise a band with no amounts and ≤ 4 lines (a header alone) is glued to the band
     below. Why: every crop must carry its own header.
4. **Split** each merged band at **vertical rules** that cover ≥ 80% of the height of its amount
   lines (side-by-side tables on dashboards).
5. A crop with fewer than 3 words is dropped. Each crop = the words' bounding box + 4 pt.

**`_records_after(bands, i)`**: if band i is a header (no amounts, ≤ 10 lines), counts the
following bands that are records (`first_full_line` > 0: text lines first, then the line with
the amounts). Then one more band if it holds only amounts (the grand total under the last
record). Needs ≥ 2 records.

**`_amounts_only(band)`**: ≤ 2 lines and every word an amount.

**`crop_table(words, rect, vocab, min_words, rules)`**: the words whose centre lies inside the
crop → `build_table`, with the separators inside the crop passed as `rules` (only used for
ruled records). Returns None for < `min_words` words, no rows, or < 2 columns.

**`page_tables(page, vocab, min_words)`**: `[(crop rect, DataFrame)]` for every crop. Used by
collateral (min_words=10), balance `table_total`, and the diagnostics.

**`write_crop_pdf`, `preview_png`**: one crop as a one-page PDF (original page, CropBox set, text
layer kept) and as a PNG. Used by the fallback and `dev/crop_view.py`.

---

### 4.9 `table.py`: reading one table

The hardest file. `build_table(words, vocab, rules)` turns the words of one crop into a
DataFrame of text cells, in **six named steps** (plus the ruled-record path).

**Helpers**
- `DATE`: `5/2/2024`, `2024-05-02`, `02-May-2024`, `2 May 24`.
- `MONEY`: `1,234.56`, `0.00`, `(1,234.56)`.
- `TOTAL_WORD`: total(s), subtotal(s), sub-total(s).
- `is_data_line(ws)`: a digit that isn't part of a date, or a `Label: value` pair. Why dates are
  excluded: header lines often carry dates ("Current 5/2/2024") and must stay header.
- `has_digit`, `cx` (centre x of a word), `line_height` (median word height), `join`.

#### Step 1: lines
`text_rows` = `pdfpage.rows_of`.

**Before step 2**, `build_table` removes two kinds of lines:
- "There are no … to report" messages (empty tables print a sentence instead of rows);
- **totals printed above the header** (`totals_above_header`): a line with a Total word and
  amounts that sits above a header line (a non-data line), which sits above the first real data
  line. These are kept in `df.attrs["totals_above"]` and later checked against all rows
  (`stitch_pages`). A key-value box that *starts* with "Totals:" is not affected (no header
  between).

#### Step 2: `header_size(rows, lh)`
Index of the first data line = number of header lines. **Centred first cell** correction: if the
line just above the first data line is much closer to it (< lh and < half the gap above), it
belongs to the row (an issuer name printed over two lines around the row), not to the header.

#### Step 3: `column_cuts(rows, ws, n_hdr, lh)` → (cuts, gutters)
1. Lines that are a single phrase (titles, section labels) are ignored: they never define
   columns.
2. **Gutters are measured on the data lines, not the header.** Why: header names are often wider
   than their values and printed touching each other; letting the header decide would merge two
   real columns.
3. `find_gutters`: `ink_coverage` counts, for every 0.5 pt x bin, how many lines have ink there.
   Gutters = runs with ink on at most 12% of the lines (when 8+ lines; 0% otherwise), at least
   0.55·lh wide. Why 12%: a spanning title, a section label or one long wrapped cell must not
   destroy a column boundary. A tolerant valley that runs into the table edge is a sparse
   first/last column; inside it only strictly empty gaps count.
4. `_rescue_empty_columns`: a header phrase lying **entirely inside** a data gutter is a column
   with no values this month; the gutter is split around it so it gets its own column. Why: an
   empty "Watch" column would otherwise vanish or merge with a neighbour.
5. `_seams`: **narrow gutters** (section 4.9.1 below).
6. `cut_in(a, b)`: the cut is placed in the middle of the **widest ink-free part** of the gutter.
   Why: one long cell poking into a wide gutter must not be cut in two.

##### 4.9.1 `_seams`: columns printed almost touching
Some layouts print a right-aligned number column only ~4 pt before a left-aligned text column
("5.77 Germany"). That is narrower than a normal gutter (0.55·lh), so without this rule both are
one column. A seam is accepted when:
- it's a strictly ink-free strip that doesn't overlap an existing gutter;
- on most lines that have a value right of it (≥ 80%, at least 2), the word left of it ends
  right at the strip and the word right of it starts right at the strip, and the gap is
  ≥ 1.6× the **normal word space** (median of word spaces elsewhere, not across this strip);
- the left edges line up within 1 pt and the right edges line up within 1 pt;
- and either the text on one side changes from line to line, or a header line shows the same
  two edges.

Why each condition:
- *both edges aligned*: that is what a right-aligned column next to a left-aligned one looks like;
  normal text never has both edges fixed on every line;
- *wider than a word space*: inside one cell ("Senior Secured") the gap is a word space;
- *varies or header confirms*: a cell that repeats identically on every line could be one
  two-word value. But a page where every row says "0.00 | Senior Secured" must still split like
  the page before it (or the two pages' columns differ and the table is not joined across the
  page break). The header shows the same seam, so it is accepted.
- *count only lines with a right-hand value*: subtotal lines often fill only the left column.

#### Step 4: `header_names(rows, n_hdr, cuts, gut, lh, vocab)`
- The **bottom header line** is placed by the **data under it** (`_bottom_header_line`): each
  phrase goes to the column whose data it overlaps most. Two header names that touch (one phrase
  spanning a gutter) are split at the word gap nearest that gutter; if several gaps qualify,
  prefer the split where both halves are known header names (`vocab` = config regexes), then the
  widest gap.
- If the last header line holds only a column-0 label (a section label such as "Loan"), the line
  above it is the bottom header line. Why: otherwise the real bottom line is handled as an upper
  line and its names are spread over two columns.
- **Upper lines** (`_upper_header_line`): a phrase over several columns ("Rating" over Original |
  Current) goes to every column it covers, unless its words each sit inside one column and line
  up with the header word below them (or have no word below): then they are separate names that
  happen to be close.

#### Step 5: `body_rows(lines, cuts, lh)`
Data lines → rows of cells. A cell printed over several lines is glued back:
- **Top-aligned wraps** (the usual case): a line is glued to the row above when it is within
  1.25 normal line steps AND fills at most 2 cells AND few "anchor" columns (columns filled in
  ≥ 60% of lines; at most 30% of them); or (older rule) has no digits, fills few cells, and is
  < 1.6·lh below.
- **Centred cells** (`_centred_cells`): only if the table shows the signature: a full row with a
  text-only line directly above AND below at equal distance (< 0.8·lh). Then every text-only line
  goes to the **nearer** full row (above → prefix of the row below; below → suffix of the row
  above).
- **Never glued**: a line with a Total word (its own row); a lone column-0 label after a row whose
  column 0 is empty (the previous row is a subtotal; the label starts a section).

#### Step 6: `split_sections(body, header, rows, n_hdr, cuts)`
Lines with only a label in column 0 and no digits are **section labels** ("Loan", "Bond"): they
become the `_section` value of the rows below instead of rows of their own. A label that repeats
the current group value ("Automotive" again before its subtotal) is the subtotal's label and
stays a row. A last header line that fills only column 0 is such a label too.

#### Ruled records: `ruled_records`, `record_table`, `first_full_line`
Some layouts print every security as a **record between two rules**:

```
──────────────────────────────────────────────────────────────── rule
ISSUER NAME                    Industry A
Country                        Industry B
FIGI                           Industry C
            Asset  Level   Tranche   LX000000   date   1.98   B   B2   1,000.00
──────────────────────────────────────────────────────────────── rule
```

The header repeats the stacking ("Issuer / Country / FIGI" in one column, four industries in
another). Reading this like a normal table fails: the text lines cross the data columns.

- `ruled_records(rows, rules)`: uses the rules passed from the crop. Needs ≥ 2 rules inside the
  table; band 0 = header; every other band must have text lines first, then its full line
  (`first_full_line` > 0). The last band may hold only amounts (the grand total). Otherwise None
  (normal path).
- `first_full_line(lines)`: the first line with at least half as many amounts as the fullest
  line. Why "half as many": a number inside a name ("Holdings 2.5") must not make the name line
  the amount line.
- `_stacks(records, lh)`: x where stacked fields start (left edges of the text phrases,
  clustered within 1.5·lh).
- `record_table(header, records, vocab)`:
  1. `lh` measured on the amount lines.
  2. Header phrases starting at a stack's x → that stack's names; the rest → normal header.
  3. Columns measured on the amount lines (`column_cuts`), named by `header_names`.
  4. Each amount line → a row (`body_rows`), prefixed with one cell per stack: the stack's lines
     joined with `" | "`. A record with two amount lines (two facilities of one issuer) → two rows
     with the same stacked cells.
  5. Stacked columns are named `"stacked: " + names joined with " / "`.
- **Stacked columns are never mapped to output fields** (`collateral.map_headers` skips them).
  Why: which line is which field cannot be decided safely: a field can be missing (no FIGI) or a
  value can wrap onto two lines (a long issuer name). Rather than guess, they stay together and
  the fields show up as empty in `collateral_gaps`.

---

### 4.10 `totals.py`: subtotals, totals, groups, page breaks

This file is the **proof**: if every printed subtotal and total equals the sum of the rows read,
no row was lost, merged or misread in those columns.

**`amount(v)`**: number for summing (percentages excluded). **`is_number(v)`**: any number,
percentages and currency included.

#### `stitch_pages(parts)`
`parts` = `[(page index, table)]` in reading order. A table continues on the next page **only
if**: it is the LAST table on its page, the next part is the FIRST table on the following page,
and both have exactly the same columns. Why so strict: separate small tables on consecutive pages
must not be joined.
- The **section carries over**: rows at the top of a continued page without a section label get
  the previous page's last section.
- **Totals above the header** (from `build_table`) are appended after the joined table's last
  row, so they are checked against all its rows, over every page.

#### `mark_totals(df)` → df + `_row` (detail | subtotal | total) + `_check`
1. `text_cols`: columns where fewer than half the filled cells are numbers.
2. `_classify_lines`: a **sum line** holds numbers and no text except one "Total" label. A label
   line ("Automotive") directly followed by a sum line is that sum's label (merged into it).
3. No sum line at all → everything is detail; done.
4. **Group columns** = sparse columns (filled in < 60% of detail rows) LEFT of the first dense
   column. These hold values printed only on a group's first row.
5. `_group_totals_above`: some layouts print a group's total **on its first line** (issuer line
   with the issuer total, facilities below). A group's first line is its subtotal when its
   amounts equal the sum of the group's other lines AND it leaves empty a column all those lines
   fill (it looks like a summary line, not a real row that happens to match).
6. `_walk`: goes down the rows:
   - detail rows: when the group column has a new value, a new group starts; empty group cells
     are **copied down** from the group's first row (nothing invented);
   - a sum line closes:
     - a **group subtotal** → the current group's rows;
     - a **section subtotal** ("Bond Subtotal:") → the rows of that section;
     - a **total** → all rows since the previous total;
     - a sum whose group began on an earlier page (`carried`) → no rows to compare with.
   - the check, per numeric column where both the printed value and row values exist:
     |sum − printed| ≤ 0.011 × number of rows (cent rounding per row);
     - all compared columns match → `ok`;
     - nothing comparable → `check: nothing to compare with` (amount in a column the rows don't
       use);
     - no rows and not labelled → `check: its rows are on an earlier page` (flagged, not failed);
     - a labelled figure that is not a sum ("Total Number of Upgrades | 4", "Total Principal
       Balance" in a key-value box) → stays a normal `detail` row;
     - mismatch → `check: <column>: printed X vs rows Y` (plus "rows may start on an earlier
       page" when the first group of the table is involved).
7. In a grouped table the `_section` column is dropped (section lines there are group labels).

`_mostly_text(col)`: helper for step 1.

---

### 4.11 `collateral.py`: one row per security

Collateral is spread over several long tables (asset info, ratings, interest accrual …), each
with an ID column. The output needs one row per security with all fields.

**Header → field**
- `_synonyms(pat)`: the top-level `|` alternatives of a synonym regex, in config order.
- `_is_field_name(header, field)`: the header IS the field name ("Principal Balance").
- `header_rank(header, field, cfg)`: 0 if it is the field name, else 1 + the index of the first
  synonym it matches. Lower = names the field more directly ("Issuer Name" before "Description").
- `map_headers(headers, cfg)`: each header goes to the **first field** (config order) whose
  regex matches it. If several headers want the same field: a header that IS the field name
  wins, otherwise the first one (left-most). Stacked columns are skipped.

**IDs**
- `norm_id(v, patterns)`: the token that matches an ID pattern (so text overflowing from the
  neighbouring column doesn't pollute the key); otherwise the whole value without spaces if it is
  6–14 letters/digits **and contains a digit** (words like "TERMLOAN" are not IDs).

**Reading**
- `header_vocab(cfg)`: known header regexes (collateral synonyms + performance roles), used to
  split touching header names.
- `read_pages(doc, page_idx, cfg, xl, events)`: every crop table (≥ 10 words, ≥ 3 columns) of
  every collateral page, tagged with `_page`. With `--fallback`: a crop whose IDs are on < 50% of
  its rows, or whose sums fail for a reading reason, is re-read by XLarge (`_try_xlarge`).
- `_id_share`, `_failed_sums`: those two triggers ("rows are on an earlier page" doesn't count as
  failed).
- `_try_xlarge`: XLarge's table replaces PyMuPDF's only if it has more valid IDs (≥ 50%), or
  passes the sums PyMuPDF failed without losing IDs or more than one column.

**`collateral(doc, page_idx, cfg, xl)`**
1. `read_pages` → `stitch_pages` → `mark_totals` per joined table.
2. Every subtotal/total row → a line in `checks` (pages, first 3 headers, row kind, label, check).
3. Detail rows only, split back per page → `join_on_id`. The output columns and their order are
   applied later, when writing (`settings.yaml` `output.columns.collateral`).

**`join_on_id(tables, cfg)`**
1. Per table: map headers; skip tables without an ID field or with fewer than
   `min_mapped_fields` (3) mapped fields; normalise IDs; drop rows without an ID; empty cells →
   missing; remember each field's `header_rank`.
2. Tables with the same set of mapped fields (the same table over several pages) are stacked.
3. **Rows** come from the table that has an issuer column, then the most distinct IDs, then the
   fewest duplicates (a table listing each security once beats a table splitting securities into
   lots), then the most columns.
4. **Each column** comes from the table whose header names it most directly (lowest rank); gaps
   are filled from the next one (`combine_first`).
5. Numeric columns → numbers (`to_num`).

Nuance: a security that appears only in a secondary table (not in the row table) is not in the
output. The row table is chosen to be the most complete one, and the sums prove that table was
read fully.

---

### 4.12 `fallback.py`: the optional model

`XLarge`: Docling with the egret-xlarge layout model and TableFormer ACCURATE, OCR off, offline
models (`~/.cache/docling/models` or `DOCLING_ARTIFACTS_PATH`). Loaded once, only when needed.
`tables(doc, pno, rect)` writes the crop as a one-page PDF (text layer kept) and returns
Docling's tables. Used only with `--fallback`, and only when its table does better (4.11). On the
org laptop the models must be downloaded beforehand; without them the fallback prints the error
and keeps the PyMuPDF result.

---

### 4.13 `dev/`: tests and checking tools

Not needed to run WIT and not part of `WIT.exe`; used when the code changes.

- **`dev/tests/`**: 46 tests, one per rule, built from **synthetic words** (`helpers.line(y, (x,
  "text"))` makes words 5 pt per character, 10 pt high, 3 pt word spaces), in-memory PDF pages
  (performance), or temporary folders with tiny generated PDFs (sources). No real PDFs.
  `python dev/tests/run_tests.py` runs them without pytest.
- **`dev/compare_outputs.py`**: compares two output folders cell by cell (Collateral matched on
  the ID column; the time-stamped run reports matched with each other; timing ignored). Each
  difference: FILLED / LOST / CHANGED. Exit code 1 if anything differs.
- **`dev/crop_view.py`**: for each page, the crops as PNG + PDF and each crop's table (optionally
  XLarge for comparison); per PDF, the tables over page breaks joined and checked.

| Test file | Covers |
|---|---|
| `test_page.py` | `to_num`, title block, footer (gap and page numbering) |
| `test_table.py` | data lines, columns from data, empty columns, wraps, centred cells, totals never glued, sections, no-data messages, totals above header, ruled records, seams, bottom header line |
| `test_totals.py` | grouped subtotals, failing sums, single-row groups, section subtotals, earlier-page totals, key-value figures, stitching (join / carry section / don't join), group total on first line, total above header checked |
| `test_collateral.py` | header mapping, header rank, IDs, row table choice, column source choice |
| `test_performance.py` | role order, header line below the result line, wrapped names vs section labels, standard names |
| `test_sources.py` | month folder names, months range, broken PDFs, report-type priority, duplicates, missing months |
| `test_run.py` | output file paths |

---

## 5. Worked examples

### 5.1 A grouped table through `mark_totals`

```
Industry     Score  Issuer   Balance
Automotive   2.23   Alpha    1,000.00
                    Beta     2,000.00
Automotive                               ← label line
                             3,000.00    ← sum line
```
1. `_classify_lines`: the last two lines merge into one sum line labelled "Automotive".
2. Fill per column in detail rows: Industry 1/2 = 50%, Score 50%, Issuer 100%. The first dense
   column is Issuer → group columns = Industry, Score.
3. `_walk`: row 1 starts group "Automotive"; row 2 gets Industry and Score copied down; the sum
   line is a group subtotal (its first cell equals the group) → rows 1–2 → 1,000 + 2,000 = 3,000
   → `ok`.

### 5.2 Total printed above the header
```
Grand Totals:            3,000.00
Issuer     ID            Balance
Alpha      LX100001      1,000.00
Beta       LX100002      2,000.00
```
`totals_above_header` sees a Total line with amounts above a header line above the first data
line → removed from the table and kept in `attrs`. `stitch_pages` appends it after the last row
(after all pages of that table) → `mark_totals` checks 3,000 against every row → `ok`.

### 5.3 A wrapped test name vs a section label (performance)
```
Test                                     Trigger  Current  Result
(a) Exposure to a Selling Institution    5.0%     0.0%     Passed
    rated Aaa or below                                          ← same size, same indent, 10 pt below
(b) Exposure to a Selling Institution    5.0%     0.0%     Passed
    rated AA or below
Other Tests                                                     ← larger, further left
(c) Weighted Average Life                5.0      4.1      Passed
```
"rated Aaa or below" is one phrase without digits. `_wraps`: < 1.6·lh below the last test,
height ≤ 1.1× the name's, starts at/after the name → glued: "(a) Exposure to a Selling
Institution rated Aaa or below". "Other Tests" is taller → section label. Without this rule (a)
and (b) would both be named "(a)/(b) Exposure …" and sub-tests with identical names would be
de-duplicated away.

### 5.4 A seam
```
Life   Country
5.77   Germany
12.5   United Kingdom
6.1    France
```
Values of Life all END at x=300; Country values all START at x=305; normal word space 3 pt;
gap 5 pt ≥ 1.6 × 3; values vary; header shows the same edges → seam (300, 305) → two columns.
A normal gutter needs 0.55·lh = 5.5 pt, so without the seam rule this is one column.

### 5.5 Ruled records
See the picture in 4.9. Header band + ≥ 2 record bands (+ a total band) → one crop. Columns
measured on the amount lines only; the issuer stack and the industry stack become two
`stacked:` columns; the ID, ratings and balances map normally; the trailing total is checked
against all records over every page.

---

## 6. Every threshold, and what it is measured against

No threshold is an absolute position. Most are multiples of `lh` (median word height on the
page or table), of the normal line step, or of the normal word space.

| Where | Value | Meaning |
|---|---|---|
| `pdfpage.page_model` | ≤ 10 pt high & > 60 pt wide / ≤ 3 pt wide & > 30 pt high | what counts as a horizontal / vertical rule |
| `pdfpage.rows_of` | 0.5 × median word height | same line |
| `crops.section_separators` | ≥ 60% page width; drawing ≤ 2.5 pt; image 3–12 pt | section separator |
| `crops.title_bottom` | top 20%; ≥ 1.1× body height; no gap ≥ 1.5× body height | title line |
| `crops.footer_top` | bottom 15%; gap > 1.25× median line step; page numbering | footer |
| `crops.find_crops` | header band ≤ 4 lines; vertical rule ≥ 80% of amount-line height; pad 4 pt | merge / split |
| `crops._records_after` | header ≤ 10 lines; ≥ 2 records; total band ≤ 2 lines | ruled records |
| `table.header_size` | gap < lh and < 0.5× gap above | centred first cell |
| `table.column_cuts` | phrase gap 0.6·lh; gutter ≥ 0.55·lh; ≤ 12% lines crossing (8+ lines) | gutters |
| `table._seams` | edges within 1 pt; gap ≥ 1.6× word space; ≥ 80% of lines with a right value, ≥ 2 | seams |
| `table._rescue_empty_columns` | phrase gap 0.45·lh; piece ≥ 0.3·lh | empty column |
| `table._bottom_header_line` | phrase gap 0.45·lh; split gap within lh of the gutter | touching names |
| `table._upper_header_line` | phrase gap 0.6·lh; ≥ 25% overlap; word ≥ 80% inside; aligned < 2 pt or centres < 0.5·lh | spanning names |
| `table.body_rows` | ≤ 1.25 line steps; ≤ 2 cells; anchors ≥ 60% fill, ≤ 30% hit; older rule < 1.6·lh | wraps |
| `table._centred_cells` | equal distance ± 0.6 pt, < 0.8·lh | centred cells |
| `table._stacks` | cluster within 1.5·lh | stack starts |
| `table.first_full_line` | ≥ half the amounts of the fullest line | amount line |
| `totals.mark_totals` | group column < 60% filled | group columns |
| `totals._walk` | tolerance 0.011 × rows | sum check |
| `performance` | header block 2.2·lh; body stops at 3·lh gap (8·lh first), rule > 200 pt; group bounds ±5 / −15 / +2·lh; section ≤ 5·lh above; phrases 0.9·lh / 0.6·lh | test tables |
| `performance._wraps` | < 1.6·lh; height ≤ 1.1×; x0 ≥ name x0 − 0.5·lh | wrapped names |
| `balance.candidates` | phrases 0.9·lh; below < 1.8·lh; header search 25 lines | labels |
| `collateral.read_pages` | ≥ 10 words; ≥ 3 columns; fallback when IDs < 50% | crops kept |
| `collateral.join_on_id` | ≥ 3 mapped fields | tables used |

If you change one of these, run the full regression (section 9): they interact.

---

## 7. How certainty is reported (the run report)

`<run reports folder>/run_report_<date>_<time>.xlsx`, one per run. Every sheet starts with `deal` and `month`.

| Sheet | One row per | What to look at |
|---|---|---|
| `summary` | deal and month | `file_status` (ok / check / missing / broken) and `file_note`; `layout` (unknown = no config matched); `tests`, `tests_to_check`, `tests_unmapped`; `bal:*` statuses; `collateral_rows`, `collateral_empty_columns`, `collateral_sums_ok` / `_to_check`; `error` (the deal failed); `needs_attention`; `seconds` |
| `balance_sources` | deal × field | `value`, `status` (ok / ambiguous / conflict / missing / ok (no rows)), `how` (right, right/column, below, ambiguous, table …), `label`, `page`, `n` candidates |
| `performance_flags` | test row not ok | `_status`: no current / result? / test name?, with page |
| `unmapped_tests` | printed test name without a standard name | add a pattern to `performance.test_names` |
| `collateral_gaps` | empty collateral column | no synonym yet, the trustee doesn't print it, or it's inside a stacked column |
| `collateral_sums` | printed subtotal/total | `ok`, `ok (group total printed above its rows)`, `check: …` |
| `xlarge_fallback` | crop re-read (only with `--fallback`) | reason, and whether XLarge was used |

How to read `collateral_sums`:
- `ok` → the rows of that table were read completely in that column.
- `check: printed X vs rows Y` → a row was lost, merged or misread (or the total covers rows
  printed elsewhere). Look at that page with `inspect`.
- `check: its rows are on an earlier page` → a total whose group began before the first page
  read. Usually harmless; check that page selection includes the previous page.
- `check: nothing to compare with` → the total sits in a column the rows don't use.
- No sums at all for a deal → that trustee prints no totals; the rows are unverified (say so when
  reporting).

---

## 8. Known limits and risks

Each is flagged, not silent, unless stated otherwise.

1. **Balance labels are placeholders.** Most `bal:*` statuses are `missing` until the legacy
   labels are filled in.
2. **Collateral columns**: 6–15 of 29 fill today. The rest need header synonyms from the legacy
   repo, or aren't printed by that trustee (visible in `collateral_gaps`).
3. **Stacked fields** (ruled records) stay joined; issuer / country / FIGI / industries are empty
   in Collateral.xlsx for that layout. Needs a business rule (FIGI pattern, country list).
4. **Several columns can match one field** (Fitch Industry and S&P Industry both match
   "industry"): the left-most wins. Put a more specific synonym first in config to prefer one.
5. **Issuer field** takes whatever the best-matching column prints; "Issuer - Facility" in one
   column is not split.
6. **Securities only in secondary tables** are not output rows (4.11).
7. **Performance de-duplication** merges tests with identical printed name, current value and
   trigger.
8. **Standard test names** come only from `performance.test_names`; until it's filled, `test`
   holds the printed name (listed in `unmapped_tests`).
9. **Duplicate PDFs that differ**: the newest is used (flagged `check`); if the older one was
   the right one, remove the wrong file and run again.
10. **Tables without printed totals** cannot be verified (no `collateral_sums` rows).
11. **A one-word line right under a row**, with no subtotal before it, is read as a wrapped cell,
   not a new section (`test_lone_word_right_after_a_row_is_a_wrapped_cell`).
12. **Page selection** depends on the title regexes; a section whose title isn't listed is not
    read (silent for that section). The legacy key terms fix this; an empty list scans every page.
13. **Scanned PDFs** have no text layer; the file check rejects them ("no text (scanned image?)")
    and they are reported as `broken`. Out of scope (born-digital only).
14. **Thresholds** were tuned on about 10 reports from 4 trustees. New layouts may need new rules;
    that is the expected way forward (section 9).

---

## 9. How to change the code safely

1. **Describe the failure as a pattern**, never by deal: "total printed one column right of its
   rows", "header line of dates under the result line".
2. **Reproduce on one page**: `python app.py inspect "<pdf>" --pages N`;
   `python dev/crop_view.py "<pdf>" --pages N --no-docling` for how the page is cut.
3. **Prefer config over code** (a page title, a synonym, a label, a test name).
4. If code: a **small named function or step**, a docstring saying the pattern and why, a
   **test** in `dev/tests/` built from synthetic words, a line in Appendix A.
5. **Regression**:
   ```
   python app.py run --months 2026-08 --out out_before        (before the change)
   (change)
   python dev/tests/run_tests.py                              (all pass)
   python app.py run --months 2026-08 --out out_after
   python dev/compare_outputs.py out_before out_after
   ```
   Every FILLED / CHANGED / LOST cell must be explained; LOST and CHANGED need a look at the PDF.
   Also check that the number of `collateral_sums` rows didn't drop: a drop usually means two
   pages of a table no longer have identical columns and were not joined.

---

## 10. What to do next

1. **Fill the config from the legacy repo** (org laptop; `COPILOT_PORTING.md` helps): folder and
   report-type names, deal list columns, output folder / file / column names, page titles,
   balance labels, header synonyms, standard test names.
2. **Run one trustee, then everything** for one month; triage the run report by trustee; fix the
   most frequent pattern first (config first, code + test if needed).
3. **Cover the remaining trustees**: one report each; new layouts are where rules get tested.
4. **Validate against the legacy outputs** for one month, field by field; agree tolerances.
5. **Business rules** that aren't parsing: splitting stacked fields, "Issuer - Facility",
   choosing between agencies.
6. **Build `WIT.exe`** and hand it over with a filled `config/`.

Not yet: models on the main path, a review UI, tuning thresholds on one report without the
regression run.

---

## 11. Review checklist

Use it per file while reading:

- [ ] `pdfpage.py`: rotation, rules from drawings + images, `rows_of` tolerance, `to_num` cases.
- [ ] `config.py`: merge semantics (lists replace), `detect` scoring, unknown layout.
- [ ] `sources.py`: month names, report-type priority, PDF checks, duplicates, missing.
- [ ] `run.py`, `cli.py`, `gui.py`: selection → jobs → outputs; errors don't stop a run.
- [ ] `pages.py`: title band, empty list = all pages.
- [ ] `performance.py`: header detection, header block above/below, anchor choice, roles order,
      side-by-side groups, body stop conditions, wraps vs section labels, `_status`.
- [ ] `balance.py`: right / below / column, statuses, `table_total`.
- [ ] `crops.py`: title and footer measured, separators, header glue, ruled records, vertical split.
- [ ] `table.py`: data line, header size, gutters (data not header), empty columns, seams, cut
      placement, bottom/upper header lines, wraps, centred cells, sections, ruled records.
- [ ] `totals.py`: sum lines, group columns, group total above, walk (group / section / total),
      tolerance, earlier-page and key-value cases, stitching conditions.
- [ ] `collateral.py`: map order, field-name wins, stacked skipped, `norm_id`, row-table choice,
      column-source choice.
- [ ] For each rule in Appendix A: does its test describe the pattern, and would it fail
      without the rule?

---

## Appendix A: every rule, why, where, and its test

### Cropping a page (`crops.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| Title block measured: leading single-phrase lines printed larger than body text | A fixed "top 12%" line cut off column headers on some layouts | `title_bottom` | `test_title_block_is_measured` |
| Rotated (vertical) header words stop the title block | Vertical column headers are tall and were mistaken for title text | `title_bottom` | n/a |
| Footer measured: bottom lines separated by a clearly larger gap, holding no amounts | A fixed "bottom 7%" line cut off the last row of a page | `footer_top` | `test_footer_is_measured_and_last_row_is_kept` |
| Footer also found by its page numbering ("Page 9 of 48", "12 - 35"), even at the normal line step | Footers printed right under the last row have no gap | `footer_top` | `test_footer_found_by_its_page_number_without_a_gap` |
| Section separators: full-width lines ≤ 2.5 pt, or images 3–12 pt high | Row shading and 2 pt dotted rules are not section breaks | `section_separators` | n/a |
| A header-only band is glued to the band below | Every crop must carry its own header | `find_crops` step 2 | n/a |
| A header band followed by 2+ ruled records (each band: text lines first, then amounts) takes them all, plus a total band right after | Layouts that print each security as a record between rules | `find_crops`, `_records_after` | `test_ruled_records_with_stacked_fields` |
| A vertical rule covering ≥ 80% of the amount lines splits side-by-side tables | Dashboards with two tables next to each other | `find_crops` step 3 | n/a |

### Reading one table (`table.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| Data line = has a digit that is not part of a date, or is a `Label: value` pair | Header lines with dates ("Current 5/2/2024") must stay header | `is_data_line` | `test_date_in_header_stays_header`, `test_key_value_lines_are_data` |
| A line just above the first data line, much closer to it than to the header, is not header | Centred first cell (issuer printed on two lines around the row) | `header_size` | covered by the centred-cell test |
| Columns measured on data lines, not the header | Two header names printed touching each other would merge two columns | `column_cuts` | `test_columns_come_from_data_not_header` |
| A gutter may be crossed by up to 12% of lines (8+ lines) | A spanning title or a long label must not destroy a column boundary | `column_cuts`, `find_gutters` | n/a |
| Header phrase inside a data gutter becomes its own column | Columns with no values this month | `_rescue_empty_columns` | `test_empty_column_keeps_its_header` |
| Cut in the middle of the widest ink-free part of a gutter | One long cell poking into a wide gutter was being cut in two | `column_cuts` (`cut_in`) | n/a |
| Narrow seam = column boundary: a right-aligned column right before a left-aligned one, both edges lined up within 1 pt on most lines, the gap clearly wider than a word space, and values that vary or a header showing the same edges | A number column printed 4 pt before a text column ("5.77 Germany" read as one cell) | `_seams` | `test_touching_columns_split_where_both_edges_line_up` |
| Bottom header line placed by the data under it; touching names split at the gap nearest the data gutter (known header names preferred) | Header names wider than their values; touching names | `_bottom_header_line` | `test_columns_come_from_data_not_header` |
| A last header line holding only a column-0 label (a section label) is skipped when picking the bottom header line | The real bottom line was handled as an upper line and its names spread over two columns | `header_names` | `test_section_label_under_the_header_is_not_the_bottom_header_line` |
| Upper header phrase over several columns goes to all of them, unless its words each sit in one column and line up with the words below (or have none below) | Group headers ("Rating" over Original / Current) vs close, separate names | `_upper_header_line` | n/a |
| Wrapped line glued to the row above (few cells, few anchor columns, within 1.25 row steps) | Top-aligned multi-line cells | `body_rows` | `test_wrapped_cell_below_is_glued`, `test_lone_word_right_after_a_row_is_a_wrapped_cell` |
| Centred cells: when the table shows the signature, text lines go to the nearer full row | Cells printed above and below their row | `_centred_cells` | `test_centred_cell_lines_above_and_below_are_glued` |
| A line with "Total" / "Subtotal" is never glued to a row | A total line was being read as the last security's wrapped text | `body_rows` | `test_total_line_is_never_glued_to_the_last_row` |
| A lone column-0 label after a subtotal line starts a section | Section labels ("Loan", "Bond") after a subtotal | `body_rows`, `split_sections` | `test_section_labels_become_a_column` |
| "There are no ..." messages are dropped | Empty tables print a sentence instead of rows | `build_table` | `test_no_data_message_is_ignored` |
| A "Total" line with amounts ABOVE the column header is kept aside and checked after the table's last row | Grand total printed on top of the table | `totals_above_header`, `stitch_pages` | `test_total_printed_above_the_header_is_kept_aside`, `test_total_printed_above_the_header_is_checked_after_the_last_row` |
| Ruled records: one row per amount line; the text lines above it are STACKED fields, one column per stack (lines joined with " \| "), named "stacked: " + the stacked header names | Issuer / country / ID and several industries printed under each other | `ruled_records`, `record_table` | `test_ruled_records_with_stacked_fields` |
| A line is "full" when it holds at least half the amounts of the fullest line | A number inside a name ("Holdings 2.5") does not make it the amount line | `first_full_line` | `test_ruled_records_with_stacked_fields` |

### Subtotals, totals and groups (`totals.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| A sum line = amounts and no text except a "Total" label; a label line directly above it is its label | Subtotals printed as "<group>" then "<amount>" on two lines | `_classify_lines` | `test_grouped_table_copies_group_down_and_checks_subtotal` |
| Group columns = sparse columns left of the first dense column; their values are copied down | Grouped tables print the group only on its first row | `mark_totals`, `_walk` | same |
| Each sum is compared with the rows it closes (group, section or everything since the last total) | Proves no row was lost or merged | `_walk` | `test_section_subtotals_and_grand_total`, `test_subtotal_that_does_not_add_up_is_flagged` |
| A labelled figure that is not a sum of the rows above stays a normal row | Key-value boxes like "Total Number of ..." | `_walk` | `test_labelled_figure_in_a_key_value_box_is_not_a_total` |
| A sum whose rows are on an earlier page is flagged, not failed | First group on a page continued from the page before | `_walk` | `test_total_whose_rows_are_on_an_earlier_page` |
| A group's first line whose amounts equal the sum of its other lines, and that leaves empty a column they all fill, is the group's subtotal | Issuer total printed on the issuer line, its facilities below | `_group_totals_above` | `test_group_total_printed_on_the_groups_first_line` |
| Tables joined across a page break only from the last table on a page to the first on the next, with the same columns | Separate small tables on consecutive pages must not be joined | `stitch_pages` | `test_stitch_joins_last_table_with_first_table_of_next_page`, `test_separate_tables_on_consecutive_pages_are_not_joined` |
| Section carries over the page break | A page continuing a section has no label at its top | `stitch_pages` | `test_stitch_carries_section_over_page_break` |

### Collateral (`collateral.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| Header goes to the first field whose synonyms match (config order) | Specific synonyms before generic ones | `map_headers` | `test_first_header_wins_otherwise` |
| A header that IS the field name wins over a synonym | "Principal Balance" next to "Par/Quantity" | `map_headers` | `test_header_that_is_the_field_name_wins` |
| Stacked columns are never mapped | Which stacked line is which field is not known (a field can be missing or wrap) | `map_headers` | n/a |
| ID = the token matching the ID patterns (LoanX, ISIN, FIGI, CUSIP); other IDs must contain a digit | Text overflowing into the ID column | `norm_id` | `test_norm_id_picks_the_id_token` |
| Rows from the table with the most distinct securities; on a tie, the one listing each security once | Tables splitting a security into lots have no single value per security | `join_on_id` | `test_rows_from_table_with_most_distinct_securities` |
| Each column from the table whose header names it most directly | "Issuer Name" before "Description" | `join_on_id`, `header_rank` | `test_each_column_from_the_most_specific_header` |
| XLarge fallback only for crops with IDs on < 50% of rows or failing sums; used only if it does better | Keep the fast path; the model is a last resort | `read_pages`, `_try_xlarge` | n/a (needs Docling) |

### Performance (`performance.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| Roles checked in config order: prior/current before result | "Current Result" holds the value, "Result" the pass/fail | `defaults.yaml` `header_roles` | `test_current_result_header_is_current_not_result` |
| Header lines can continue BELOW the result line (close, no data); the most complete header line anchors the columns | A line of dates under the header; 3-line headers | `performance` | `test_header_line_below_the_result_line` |
| The measured page footer is left out | Footer text was glued onto the last test name | `performance` | n/a |
| A line right under a test row (< 1.6 line heights) with no value continues its name, unless it starts a new item "(s)", "Class ..." | Test names wrapped onto a second line | `performance`, `_wraps` | `test_wrapped_test_name_is_glued_and_section_label_is_not` |
| A lone digit-free phrase is that wrap only if it has the same text height and does not start left of the name; otherwise it is a section label | Section labels are printed larger and further left | `_wraps` | same |

### Numbers (`pdfpage.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| One parser: thousands separators, (negative), >= / <=, €/$/£, EUR/USD/GBP, [A] markers; percentages optional | Every module reads numbers the same way | `to_num` | `test_to_num` |

### Finding reports (`sources.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| Month folder = 4-digit year + 1–2 digit month in its name; the last one in a name counts | Folder names vary (2026_08, 2026-8, 202608, 2026_08_15) | `month_of` | `test_month_of_folder_and_file_names` |
| Report types tried in priority order | A deal may have monthly and quarterly folders | `find_report` | `test_find_report_priority_duplicates_and_missing` |
| Every PDF checked by its bytes, then opened | A corrupted or cut-off file was once dropped in a month folder | `check_pdf` | `test_check_pdf_finds_broken_files` |
| Identical copies → one used; different files → newest used, flagged | Rarely a file is duplicated | `_pick` | `test_find_report_priority_duplicates_and_missing` |
| Missing month → reported with the latest month available | Quarterly deals have no monthly report | `_latest_month` | same |

### Performance names (`performance.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| `original tests` = name as printed; `test` = standard name, longest matching pattern wins; unmapped → printed name, listed | Trustees print the same test differently ("Senior IC" vs "Senior Interest Coverage Test") | `standard_name` | `test_standard_name_longest_match_wins_and_unmapped_keeps_printed_name` |
