# WIT: full walkthrough

This document explains **everything** in the repository: what problem it solves, how a PDF
travels through the code, every file and function in reading order, every rule and threshold
(and why it exists), how certainty is reported, the known limits, how to change the code
safely, how to set it up on the org laptop, and what to do next.

It is meant to be read **next to the code**, top to bottom. Section 4 follows the files in the
order you should open them. Every function name in `backticks` exists in the code with that
exact name, so you can search for it.

Other docs:
- `HANDOVER.md`: the short version (what it does, how to run it, status).
- `CODE_GUIDE.md`: the rules table (rule → why → where → test). Use it as an index.
- `CLAUDE.md`: the working rules for anyone (person or AI) changing the code.

---

## Contents

0. How to read this
1. The problem
2. Vocabulary
3. The big picture: one run, start to finish
4. File by file, function by function
   - 4.1 `run.py` and `src/wit/run.py`: command line and orchestration
   - 4.2 `config.py` and the YAML files: which rules apply
   - 4.3 `sources.py`: which PDF belongs to which deal
   - 4.4 `pages.py`: which pages feed which output
   - 4.5 `pdfpage.py`: reading a page (words, lines, phrases, numbers)
   - 4.6 `performance.py`: test rows
   - 4.7 `balance.py`: balance values
   - 4.8 `crops.py`: cutting a page into tables
   - 4.9 `table.py`: reading one table
   - 4.10 `totals.py`: subtotals, totals, groups, page breaks
   - 4.11 `collateral.py`: one row per security
   - 4.12 `fallback.py`: the optional model
   - 4.13 `tools/`, `demo/`, `tests/`
5. Worked examples
6. Every threshold, and what it is measured against
7. How certainty is reported (`_run_report.xlsx`)
8. Known limits and risks
9. How to change the code safely
10. Setting up on the org laptop
11. How to proceed from here
12. Review checklist

---

## 0. How to read this

Suggested order:

1. Sections 1–3 (about 20 minutes). You need the vocabulary and the flow before the code
   makes sense.
2. Section 4, **with the file open next to it**. Read the section, then the function, then go
   back to the section. Allow about one hour per big file (`table.py`, `totals.py`,
   `performance.py`). The small files take minutes.
3. Section 5: run the worked examples in your head; they exercise the hardest rules.
4. Sections 6–8 are reference material. Come back to them when reviewing a specific rule.
5. Sections 9–11 before you change anything or go to the org laptop.

Size of the code (lines, including comments and docstrings):

| File | Lines | Difficulty |
|---|---|---|
| `src/wit/run.py` | ~260 | easy (plumbing) |
| `src/wit/config.py`, `sources.py`, `pages.py` | ~190 | easy |
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
| `Performance.xlsx` | compliance test | test name, current value, trigger, result (pass/fail), category |
| `Collateral.xlsx` | security (loan / bond) | 29 schema columns: ID, issuer, ratings, balance, spread, maturity ... |

Plus one `_run_report.xlsx` per run that says, for every deal, what was found and how sure we
are (section 7).

### Constraints
- CPU only, 16 GB RAM, Windows + Git Bash + poetry.
- About 233 deals per period: it must be fast (seconds per report, not minutes).
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
3. **Never silently guess.** Uncertain → status/check in `_run_report.xlsx`.
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
python run.py --period 2026-08
│
├─ config.load_trustees()            defaults.yaml + every trustees/*.yaml (merged)
├─ sources.plan("2026-08")           deal list Excel → active deals → find each deal's PDF
│
└─ for every deal with a PDF:  run.process(pdf, ...)
     │
     ├─ config.pick_config(doc, ...)  which trustee config applies (deal list + detect patterns)
     │
     ├─ PERFORMANCE   read_performance()
     │     pages.select_pages(…, "performance")      pages whose title matches config
     │     performance.performance(page) per page    header line with 'result' → rows below
     │     drop duplicate tests
     │
     ├─ BALANCE       read_balance()
     │     pages.select_pages(…, "balance")
     │     balance.candidates(page) per page         label → number right of / below it
     │     balance.resolve()                          one value per field + status
     │     balance.table_total()                      or: total of a column on a named page
     │
     ├─ COLLATERAL    collateral.collateral()
     │     pages.select_pages(…, "collateral")
     │     read_pages():  crops.page_tables(page)     page → crops → one table per crop
     │                      ├─ crops.find_crops         title/footer out, bands, merge, split
     │                      └─ table.build_table        words → DataFrame (6 steps)
     │     totals.stitch_pages()                      tables over page breaks joined
     │     totals.mark_totals()                       detail / subtotal / total + checks
     │     join_on_id()                                headers → fields; one row per security ID
     │
     └─ DealResult (report line + 3 tables + checks)

write_outputs()  →  out/2026-08/<deal>/Balance.xlsx, Performance.xlsx, Collateral.xlsx
                    out/2026-08/_run_report.xlsx  (summary + every check)
```

Key points:
- The three outputs are read **independently**. A failure in collateral doesn't affect
  performance.
- **Deal name, trustee and month come from the org's metadata** (deal list + folder + file
  name), not from the PDF text, so they are reliable. Only ad-hoc runs (`run.py some.pdf`)
  read them from the PDF.
- Only **collateral** uses crops and table reading. Performance and balance read the page's
  lines directly, because they look for specific words.

---

## 4. File by file, function by function

### 4.1 `run.py` and `src/wit/run.py`: command line and orchestration

`run.py` (repo root) only puts `src/` on the Python path and calls `wit.run.main()`.

`src/wit/run.py`:

**Constants**
- `PERF_COLS`, `BAL_FIELDS`, `BAL_COLS`: the output schema columns for Performance and Balance.
  Collateral's schema is in config (`collateral.output_columns`).

**`DealResult`** (dataclass): everything known about one deal after processing: the summary
line (`report`), the three tables, where balance values came from (`bal_sources`), the
collateral checks (`coll_checks`), empty collateral columns, fallback events.

**`deal_info_from_text(doc, cfg)`**: ad-hoc runs only. Looks in the first 5 pages for:
- a deal name: a line in the top 25% of a page, matching `deal.deal_name` (default `\bCLO\b`),
  shorter than 70 characters, cut at `deal.deal_name_stop` (e.g. " Monthly", " As of");
- a month: the first match of `deal.report_month` (a date after "as of").

**`read_performance(doc, cfg, deal, month)`**: for each performance page, calls
`performance.performance(page, cfg)`, adds deal/month/asset class, then
`drop_duplicates(subset=["test", "current", "trigger"])`. Why: the same test is often printed
twice (summary dashboard + detail page). Identical name, value and trigger = the same test.
*Nuance*: two genuinely different tests with identical name, value and trigger would be
merged. That is why wrapped names matter (section 4.6): sub-tests that differ only in their
second line ("rated Aa1 …", "rated Aa2 …") would otherwise collapse into one.

**`read_balance(doc, cfg, deal, month)`**: collects candidates from every balance page,
resolves them (`balance.resolve`), then fills table-total fields (`balance.table_total`).
Returns the Balance row and, per field, `{value, status, how, label, page, n}`.

**`process(pdf, defaults, trustees, meta, xl)`**: one report → `DealResult`.
1. Opens the PDF, picks the config (`pick_config`).
2. Deal/month from `meta` (period run) or from the text (ad-hoc).
3. Reads the three outputs.
4. Lists collateral columns that stayed completely empty (`empty_cols`).
5. Builds the summary line: counts, balance statuses, sums ok / to check, seconds.
6. `needs_attention` = unknown layout, OR no tests, OR any test not ok, OR any balance status
   not ok, OR no collateral rows. (Today almost every deal "needs attention" because the
   balance labels are placeholders.)

**`write_outputs(results, out, period)`**: writes the 3 clean files per deal (internal columns
starting with `_` dropped) and `_run_report.xlsx` with 6 sheets (section 7). The deal folder
name is the deal name with characters Windows forbids replaced by `_`.

**`dump_pages` / `debug_pages`**: diagnostics.
- `--dump 3`: for page 3, every crop's table after `mark_totals` (first 8 rows), then every
  "label  value" pair on the page (a line with exactly two phrases, the first not a number).
  Use it to see what the collateral and balance readers see.
- `--debug 3`: for page 3, the test rows performance finds and the balance candidates.

**`main()`**: parses arguments:
`pdfs`, `--period`, `--trustee`, `--out`, `--debug`, `--dump`, `--fallback`, `--artifacts`.
With `--dump/--debug` it inspects the first PDF and stops. Otherwise it runs either the period
plan (prints `MISSING` for deals without a report) or the given PDFs, then writes outputs.

---

### 4.2 `config.py` and the YAML files: which rules apply

**The idea.** All trustee-specific knowledge is text in YAML: page titles, labels, header
synonyms, detection patterns. Adding a trustee = adding one YAML file, no code.

**`config/defaults.yaml`**: the shared vocabulary:
- `layout.title_band` (0.2): the top 20% of a page is searched for its section title.
- `pages.*`: page-title regexes per output. Empty list = scan every page.
- `deal.*`: regexes for ad-hoc runs (above).
- `performance.header_roles`: header text → role. **Order matters, first match wins**:
  `skip` (numerator, denominator, cushion …) → `test` → `trigger` → `prior` → `current` →
  `result` → `test2`. Why prior/current before result: a header "Current Result" holds the
  *value*, "Prior Result" the *previous value*; only a header that is just "Result" is the
  pass/fail column.
- `performance.categories`: section label / page title → output category ("Coverage test",
  "Collateral Quality", "Concentration limitation").
- `performance.test_name_categories`: fallback, classify by the test name itself.
- `balance.labels`: **placeholders** until filled from the legacy repo.
- `collateral.id_patterns`: what a security ID looks like: LoanX `LX\d{6}`, ISIN
  `[A-Z]{2}[A-Z0-9]{9}\d`, FIGI `BBG[A-Z0-9]{9}`, CUSIP `[A-Z0-9]{9}`.
- `collateral.columns`: header synonyms per output field. **Order matters**: a header goes to
  the first field whose regex matches. That's why "moody.*recovery" comes before
  "moody.*rating": a header "Moody's Recovery Rate" must not become the Moody's rating.
- `collateral.numeric_columns`: fields converted to numbers in the output.
- `collateral.output_columns`: the 29+2 output columns, in order.

**`config/trustees/<name>.yaml`**: only what differs: `names` (regex on the deal list's
trustee column), `detect` (patterns in the PDF text), `layout`, `pages`, `balance.labels`,
sometimes `deal.report_month`. `_template.yaml` documents every option (files starting with
`_` are ignored).

**`_merge(base, over)`**: dicts merge recursively; lists and scalars in the trustee file
*replace* the default. Consequence: if a trustee file sets `pages.performance`, it replaces
the whole default list, not appends to it.

**`load_trustees()`**: reads defaults, then every enabled trustee file merged onto the
defaults. Returns `(defaults, {name: merged config})`.

**`doc_text(doc, n_pages=3)`**: text of the first 3 pages + PDF metadata (used for detection).

**`layouts_for(trustee_name, trustees)`**: configs whose `names` regex matches the trustee
value from the deal list.

**`pick_config(doc, defaults, trustees, trustee_name)`**:
- trustee known and exactly one layout → that one;
- several layouts (e.g. two BNY layouts) → `detect_trustee` among them; if none matches, the
  first one;
- trustee unknown (ad-hoc run) → `detect_trustee` across all configs.

**`detect_trustee(doc, defaults, trustees)`**: a config qualifies only if **all** its
`detect.all` patterns are found; among those, the score is the number of `detect.any` patterns
found (+ the count of `all` patterns). Highest score wins; nothing qualifies → `"unknown"` with
the defaults (and `needs_attention`).

---

### 4.3 `sources.py`: which PDF belongs to which deal

All names and paths are in `config/sources.yaml`.

- **`load_sources()`**: reads `sources.yaml`.
- **`active_deals(src, trustee)`**: reads the deal-list Excel, applies `filter`
  (e.g. `{Status: Active}`, compared case-insensitively), optionally keeps only deals whose
  trustee contains `--trustee`. Returns `{deal, trustee, folder}` per deal.
- **`period_regex(src, period)`**: turns `file_period_regex` into a regex for one period.
  Default `(?<!\d){yyyy}[_-]0?{m}(?!\d)` → for 2026-08 it matches `2026_8`, `2026-08`,
  `2026_08`, but not `2026_18` (the lookarounds stop it from matching inside longer numbers).
- **`find_report(src, deal_folder, period)`**: looks in
  `<reports_root>/<deal folder>/<report type>/` for each report type **in priority order**
  (Monthly, then Quarterly, then Intra); the first folder with a matching PDF wins.
- **`plan(period, trustee)`**: one job per active deal: `{deal, trustee, folder, pdf,
  report_type, period}`; `pdf=None` when nothing was found (printed as `MISSING`).

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

**`category_of(section, test, page_title, pcfg)`**: category from the section label, else the
page title (config `categories`), else from the test name (`test_name_categories`), else the
raw section label.

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
   Also the **section** title just above the header (within 5·lh, no digits), e.g. a coloured
   bar "Collateral Quality Tests".
10. **Per body line**, keep its words inside the group's x range, split into phrases (0.9·lh):
    - **One phrase, no digits**: either the **wrapped second line of the previous test**
      (glued) or a **section label** (sets `section`). It's a wrap only if `_wraps(...)`:
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
layer kept) and as a PNG. Used by the fallback and `tools/crop_test.py`.

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

**`collateral(doc, page_idx, cfg, deal, month, xl)`**
1. `read_pages` → `stitch_pages` → `mark_totals` per joined table.
2. Every subtotal/total row → a line in `checks` (pages, first 3 headers, row kind, label, check).
3. Detail rows only, split back per page → `join_on_id`.

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

### 4.13 `tools/`, `demo/`, `tests/`

- **`tools/crop_test.py`**: for each page: the crops as PNG + PDF, each crop read by PyMuPDF
  (with checks), optionally XLarge on the page and on each crop; per PDF, the tables over page
  breaks joined and checked. Output in `out/crop_test/`. Use `--no-docling` for the fast path.
- **`tools/compare_outputs.py`**: compares two output folders cell by cell (Collateral matched
  on loan id; timing ignored). Each difference: FILLED / LOST / CHANGED. Exit code 1 if anything
  differs. This is the regression check after every change.
- **`demo/make_demo.py`**: builds a fake deal list (`Demo Deal 1–7`) and folder tree from the
  sample PDFs in `reports/`, so `run.py --period 2026-08` works without org data. Deal 3 sits in
  the Quarterly folder (folder priority); deal 7 has no report (MISSING).
- **`tests/`**: 40 tests, one per rule, built from **synthetic words** (`helpers.line(y, (x,
  "text"))` makes words 5 pt per character, 10 pt high, 3 pt word spaces), or in-memory PDF pages
  for performance. No PDFs needed. `python tests/run_tests.py` runs them without pytest.

| Test file | Covers |
|---|---|
| `test_page.py` | `to_num`, title block, footer (gap and page numbering) |
| `test_table.py` | data lines, columns from data, empty columns, wraps, centred cells, totals never glued, sections, no-data messages, totals above header, ruled records, seams, bottom header line |
| `test_totals.py` | grouped subtotals, failing sums, single-row groups, section subtotals, earlier-page totals, key-value figures, stitching (join / carry section / don't join), group total on first line, total above header checked |
| `test_collateral.py` | header mapping, header rank, IDs, row table choice, column source choice |
| `test_performance.py` | role order, header line below the result line, wrapped names vs section labels |

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

## 7. How certainty is reported (`_run_report.xlsx`)

Open it first after every run.

| Sheet | One row per | What to look at |
|---|---|---|
| `summary` | deal | `layout` (unknown = no config matched), `tests`, `tests_to_check`, `bal:*` statuses, `collateral_rows`, `collateral_empty_columns`, `collateral_sums_ok` / `_to_check`, `needs_attention`, `seconds` |
| `balance_sources` | deal × field | `value`, `status` (ok / ambiguous / conflict / missing / ok (no rows)), `how` (right, right/column, below, ambiguous, table …), `label`, `page`, `n` candidates |
| `performance_flags` | test row not ok | `_status`: no current / result? / test name?, with page |
| `collateral_gaps` | deal × empty column | no synonym yet, or the column isn't printed by this trustee, or it's inside a stacked column |
| `collateral_sums` | printed subtotal/total | `ok`, `ok (group total printed above its rows)`, `check: …` |
| `xlarge_fallback` | crop re-read (only with `--fallback`) | reason, and whether XLarge was used |

How to read `collateral_sums`:
- `ok` → the rows of that table were read completely in that column.
- `check: printed X vs rows Y` → a row was lost, merged or misread (or the total covers rows
  printed elsewhere). Look at that page with `--dump`.
- `check: its rows are on an earlier page` → a total whose group began before the first page
  read. Usually harmless; confirm that page selection includes the previous page.
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
7. **Performance de-duplication** merges tests with identical name, current value and trigger.
8. **Tables without printed totals** cannot be verified (no `collateral_sums` rows).
9. **A one-word line right under a row**, with no subtotal before it, is read as a wrapped cell,
   not a new section (`test_lone_word_right_after_a_row_is_a_wrapped_cell`).
10. **Page selection** depends on the title regexes; a section whose title isn't listed is not
    read (silent for that section). The legacy key terms fix this; an empty list scans every page.
11. **Scanned PDFs** have no text layer; this code returns nothing for them (flagged: 0 tests,
    0 rows). Out of scope (born-digital only).
12. **Thresholds** were tuned on about 10 reports from 4 trustees. New layouts may need new rules;
    that is the expected way forward (section 9).

---

## 9. How to change the code safely

1. **Describe the failure as a pattern**, never by deal: "total printed one column right of its
   rows", "header line of dates under the result line".
2. **Reproduce on one page**: `python run.py some.pdf --dump N` (collateral/balance) or
   `--debug N` (performance); `tools/crop_test.py some.pdf --pages N --no-docling` for crops.
3. **Prefer config over code** (a page title, a synonym, a label).
4. If code: a **small named function or step**, a docstring saying the pattern and why, a
   **test** from synthetic words in `tests/`, a line in `CODE_GUIDE.md`'s rules table.
5. **Regression**:
   ```bash
   python run.py --period 2026-08 --out out_before        # before the change
   # change
   python tests/run_tests.py                              # all pass
   python run.py --period 2026-08 --out out_after
   python tools/compare_outputs.py out_before out_after
   ```
   Every FILLED / CHANGED / LOST cell must be explained. LOST and CHANGED need a look at the PDF.
   Also check that the number of `collateral_sums` rows didn't drop: a drop usually means two
   pages of a table no longer have identical columns and were not joined.
6. `python tools/crop_test.py <problem pdfs> --no-docling`: cross-page sums still ok.

---

## 10. Setting up on the org laptop

### 10.1 Getting the code there
The GitHub repo is **public**. Before pushing:
- Make it **private** (GitHub → Settings → General → Danger Zone → Change visibility), or use the
  org's own Git server. The code holds no deal data, but it is work done for the org; check the
  org's policy on code hosting.
- Check what Git tracks: `git ls-files` must show **no** `.pdf`, nothing under `out/`,
  `reports/`, `probs/`, `demo/reports/`, and no `demo/active_deals.xlsx`.
  Recommended `.gitignore` lines:
  ```
  .venv/
  __pycache__/
  *.pdf
  out/
  out_*/
  reports/
  probs/
  demo/reports/
  demo/active_deals.xlsx
  ```

### 10.2 Install
```bash
git clone <repo url> WIT && cd WIT
poetry install
poetry run python tests/run_tests.py        # 40 passed
```
If PyPI is blocked on the org laptop, ask for `pymupdf`, `pandas`, `openpyxl`, `pyyaml` (the
main path needs only these). Docling is only for `--fallback`.

### 10.3 Config (no code)
1. `config/sources.yaml`: deal-list path, sheet, column names (deal, trustee, folder), `filter`
   (e.g. `{Status: Active}`), `reports_root`, `report_folders` in priority order,
   `file_period_regex` for the real file names.
2. Per trustee, from the legacy repo:
   - `names`: regex matching the trustee as the deal list spells it;
   - `pages.performance / balance / collateral`: the legacy key terms (page titles);
   - `balance.labels`: the real labels (form a/b/c, section 4.7);
   - `collateral.columns`: only headers that differ from the defaults.
   - New trustee: copy `_template.yaml` to `<trustee>.yaml`.
   - Keep real labels in the org copy only if they are sensitive; the public copy keeps
     `<<PLACEHOLDER>>`.
3. Dry run of the plan: `poetry run python run.py --period 2026-08 --trustee "<one trustee>"`.

### 10.4 First real run
```bash
poetry run python run.py --period 2026-08 --trustee "<trustee>"     # one trustee first
poetry run python run.py --period 2026-08                            # then everything
```
Then `_run_report.xlsx`, in this order: `summary` (unknown layouts, 0 tests, 0 rows) →
`collateral_sums` (`check:` rows) → `balance_sources` → `performance_flags` → `collateral_gaps`.

---

## 11. How to proceed from here

In order of value:

1. **Cover the remaining trustees** (about 5 of 9 not yet seen). For each, one report:
   run it, look at `_run_report.xlsx`, describe failures as patterns, fix generically (config
   first, code + test if needed). New layouts are where the rules get tested; every round so far
   has found 1–3 generic patterns.
2. **Fill config from the legacy repo** (org laptop): page key terms, balance labels, collateral
   synonyms, which agency's industry to prefer. This turns most `missing` balances into values
   and fills more collateral columns.
3. **Full run of all deals** on the org laptop; triage `_run_report.xlsx` by trustee; fix the most
   frequent pattern first.
4. **Validation** (after parsing is stable): compare against the legacy outputs for one period,
   field by field, with `compare_outputs`-style reports. Decide tolerances with the business.
5. **Business rules** that aren't parsing: splitting stacked fields, splitting "Issuer -
   Facility", choosing between agencies, mapping category names.
6. **Operational**: a scheduled monthly run, a summary email or sheet, keeping
   `out_<period>` for comparisons between months.

What not to do yet: add models to the main path, build a review UI, or tune thresholds on a single
report without the regression run.

---

## 12. Review checklist

Use it per file while reading:

- [ ] `pdfpage.py`: rotation, rules from drawings + images, `rows_of` tolerance, `to_num` cases.
- [ ] `config.py`: merge semantics (lists replace), `detect` scoring, unknown layout.
- [ ] `sources.py`: period regex, folder priority, MISSING.
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
- [ ] For each rule in `CODE_GUIDE.md`: does its test describe the pattern, and would it fail
      without the rule?
