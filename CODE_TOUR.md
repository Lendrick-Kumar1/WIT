# WIT: code tour

The code, read with you line by line. Open the file named in each section next to this one.

- `README.md`: how to set up and run.
- `GUIDE.md`: what WIT does and **why** (the problem, every rule, thresholds, limits).
- **This file**: **how** the code does it: which folder holds what, which function calls which,
  what data passes between them, and every function block by block.

Line numbers (`L24–37`) are those of the version this tour was written for (v5.2). If a file
changes, the numbers shift a little; search for the function name.

---

## Contents

- **Part A. Folders and files**: why each folder exists, which file depends on which
- **Part B. Call map and data shapes**: what flows through a run
- **Part C. Line by line**, in reading order
  - C1 `app.py` · C2 `config.py` · C3 `sources.py` · C4 `pdfpage.py` · C5 `pages.py`
  - C6 `run.py` · C7 `cli.py` · C8 `gui.py` · C9 `inspect_pdf.py`
  - C10 `performance.py` · C11 `balance.py`
  - C12 `crops.py` · C13 `table.py` · C14 `totals.py` · C15 `collateral.py`
  - C16 `fallback.py` · C17 `dev/`

Suggested order: Part A and B in one sitting (30 min). Then Part C in this order: C4 (every
other file uses it), C2, C3, C6 (you then know the whole frame), C10, C11, then the collateral
chain C12 → C13 → C14 → C15, which is the hardest part. C1, C5, C7–C9, C16, C17 whenever.

---

# Part A. Folders and files

## A.1 The folders, and why they are separate

```
WIT/
├── app.py            the single entry point
├── build_exe.bat     packaging
├── config/           WHAT to look for and WHERE things are       (data, edited by people)
├── src/wit/          HOW to read a PDF                          (code, edited by developers)
├── dev/              PROOF that the code still does what it did  (never shipped)
├── README.md, GUIDE.md, CODE_TOUR.md, COPILOT_PORTING.md
└── .github/copilot-instructions.md
```

**Why `config/` is separate from `src/`.** Everything that differs between trustees, deals or
organisations is *text*: page titles, labels, header names, folder names, output names. Keeping
it in YAML means:
- a new trustee or a renamed header is a config edit, not a code change;
- the code stays the same for every trustee (no `if trustee == ...`);
- the packaged `WIT.exe` reads `config/` next to it, so the org can change settings without
  rebuilding.

**Why `dev/` is separate.** Tests and comparison tools are needed only when the code changes.
They are not part of the program, not in the .exe, and nothing in `src/` imports them.

**Why one entry point (`app.py`).** The window and the command line are two faces of the same
engine. Both end up in `run.run()`, so they can never behave differently.

## A.2 The files in `src/wit/`, in layers

Each layer only uses the layers below it.

```
 Layer 4  START & RUN     cli.py   gui.py   inspect_pdf.py
                               \     |      /
 Layer 3  ORCHESTRATION       run.py   sources.py
                               /   |   \
 Layer 2  THE THREE READERS  performance.py  balance.py  collateral.py
                                   |            |    \        |
                                   |            |     \       |  (fallback.py, optional)
 Layer 1  TABLE READING            |          crops.py ── table.py ── totals.py
                                   |            |            |
 Layer 0  BASICS              pdfpage.py    pages.py    config.py
```

| File | Lines | Uses | Used by | In one sentence |
|---|---|---|---|---|
| `pdfpage.py` | 105 | PyMuPDF | everything | Words, rules, lines, phrases, numbers from a page. |
| `config.py` | 125 | `pdfpage` | `run`, `cli`, `gui`, `inspect_pdf` | Reads the YAML files; picks the trustee layout for a PDF. |
| `pages.py` | 44 | `pdfpage` | `run`, `balance` | Which pages belong to which output (by page title). |
| `sources.py` | 210 | PyMuPDF, pandas | `cli`, `gui` | Deal list → deals; folders → the PDF for a deal and month; PDF check. |
| `table.py` | 613 | `pdfpage` | `crops`, `totals`, `collateral`, `performance` | The words of ONE table → a DataFrame. |
| `crops.py` | 209 | `pdfpage`, `table` | `balance`, `collateral`, `performance`, `inspect_pdf` | A page → rectangles, one per table → DataFrames. |
| `totals.py` | 260 | `pdfpage`, `table` | `balance`, `collateral`, `inspect_pdf` | Marks subtotal/total rows and checks them; joins tables over page breaks. |
| `performance.py` | 197 | `pdfpage`, `crops`, `table` | `run`, `inspect_pdf` | Test rows of one page. |
| `balance.py` | 149 | `pdfpage`, `pages`, `crops`, `totals` | `run`, `inspect_pdf` | Balance values (label → number, or a column total). |
| `collateral.py` | 227 | `crops`, `table`, `totals`, `pdfpage` | `run` | All collateral tables of a report → one row per security. |
| `fallback.py` | 66 | `crops`, Docling | created by `cli` (`--fallback`), called by `collateral` | Re-reads one table with a model. |
| `run.py` | 226 | the readers, `config`, `pages` | `cli`, `gui` | Runs the jobs, writes the files and the run report. |
| `cli.py` | 88 | `config`, `run`, `sources` | `app.py` | Command line. |
| `gui.py` | 293 | `config`, `run`, `sources`, ttkbootstrap | `app.py` | The window. |
| `inspect_pdf.py` | 51 | the readers | `cli` | Prints what the readers see on chosen pages. |

## A.3 The config files and who reads them

| File | Read by | Holds |
|---|---|---|
| `config/settings.yaml` | `config.load_settings` → `sources`, `run`, `gui` | reports folder, report types, deal list (path, columns, filter), output folders, file names, columns, rename, month format |
| `config/defaults.yaml` | `config.load_trustees` | vocabulary shared by all trustees: page titles (empty = all pages), header roles, test names, balance labels, collateral synonyms, ID patterns |
| `config/trustees/*.yaml` | `config.load_trustees` (merged onto defaults) | per trustee layout: `names`, `detect`, `pages`, `balance.labels`, any override |

---

# Part B. Call map and data shapes

## B.1 The data that flows (learn these shapes first)

| Name in code | Shape | Made by | Example |
|---|---|---|---|
| **word** `w` | `{x0, y0, x1, y1, t}` (points, origin top-left) | `pdfpage.page_model` | `{x0: 72, y0: 100, x1: 110, y1: 108, t: "Balance"}` |
| **rule** | `pymupdf.Rect` (thin line or thin image) | `pdfpage.page_model` | horizontal: ≤ 10 pt high, > 60 pt wide |
| **line** / **row** `r` | `{c: centre y, ws: [words left→right], text}` | `pdfpage.rows_of` | `{c: 104, ws: [...], text: "Alpha Ltd LX100001 1,000.00"}` |
| **phrase** `p` | `{x0, x1, t, h}` (`phrases`) or a list of words (`split_phrases`) | `pdfpage` | `{x0: 72, x1: 140, t: "Senior Secured", h: 8}` |
| **lh** | a number: median word height | many | `8.0` |
| **crop** / **rect** | `pymupdf.Rect` around one table | `crops.find_crops` | `Rect(12, 57, 780, 588)` |
| **raw table** | DataFrame of text cells (+ `_section`), `attrs["totals_above"]` | `table.build_table` | columns `Issuer, ID, Balance` |
| **part** | `(page index, raw table + _page)` | `collateral.read_pages` | `(8, df)` |
| **marked table** | raw table + `_row` (detail/subtotal/total) + `_check` | `totals.mark_totals` | `_check = "ok"` |
| **cfg** | dict: defaults.yaml merged with one trustee file | `config.load_trustees` | `cfg["pages"]["collateral"]` |
| **settings** | dict from settings.yaml, paths absolute | `config.load_settings` | `settings["output"]["balance"]["dir"]` |
| **deal** | `{deal, trustee, folder}` | `sources.active_deals` | |
| **job** | deal + `{year, month, pdf, report_type, file_status, file_note}` | `sources.plan` | `file_status = "ok"` |
| **test record** | `{test, original tests, current, trigger, result, _status, _mapped, _page}` | `performance.performance` | |
| **balance candidate** | `(field, value, how, label, page)` | `balance.candidates` | `("principal balance", 4.1e8, "right", "Aggregate Principal Balance", 3)` |
| **DealResult** | job + report line + output tables + check tables | `run.process` | |

## B.2 One run, as a chain of calls

```
app.py
 ├─ (no arguments) gui.main() → App ─ Run button → App._start → thread App._work
 └─ (arguments)    cli.main()
                     │
                     ▼
        config.load_settings()                         → settings
        sources.plan(settings, months, deal names)     → [job]
           ├─ active_deals(settings)                    deal list Excel → [deal]
           ├─ select_deals(...)                         the chosen ones
           └─ for every month × deal: find_report()
                 ├─ _pdfs_for_month()                   month folders → candidate PDFs
                 └─ _pick() → check_pdf()               broken / duplicates → one PDF or none
                     │
                     ▼
        run.run(jobs, outputs, settings, log, ...)
           ├─ config.load_trustees()                    → defaults, {layout: cfg}
           └─ for every job:
                 run.process(job, outputs, ...)          → DealResult
                    ├─ config.pick_config(doc, trustee) → (layout, cfg)
                    ├─ [performance] run.read_performance → performance.performance(page)  (B.3)
                    ├─ [balance]     run.read_balance     → balance.candidates / resolve / table_total (B.4)
                    └─ [collateral]  collateral.collateral(doc, pages, cfg)                  (B.5)
                 run.write_deal(result, settings)        → one Excel file per selected output
           run.write_run_report(results, ...)           → run_report_<date>_<time>.xlsx
```

## B.3 Performance, one page

```
performance.performance(page, cfg)
  pdfpage.page_model(page)            → words, H rules, V rules
  crops.footer_top(words)             → drop the footer
  pdfpage.rows_of(words)              → lines
  for every line with a 'result' word and test/ratio/current:     (a header line)
      header block: lines above (≤ 2) and below (no data) → anchor line → columns
      role_of(column text)            → test / current / trigger / result / prior / skip
      groups of columns (side-by-side tables)
      body lines until a rule / big gap / next header
      per body line: phrases → nearest column → record; wraps glued (_wraps)
  standard_name(printed name)         → test, _mapped
  → [test record]
```

## B.4 Balance, one report

```
for every balance page: balance.candidates(page, cfg)
    phrases matching a label → number RIGHT of it (one, or the one under `column`) or BELOW it
    → [candidate]
balance.resolve(candidates)           → first candidate per field + status (ok/ambiguous/conflict/missing)
for every column-total field: balance.table_total(doc, cfg, spec)
    pages.page_texts → pages with that title → crops.page_tables → totals.mark_totals
    → printed total vs sum of rows
```

## B.5 Collateral, one report (the deepest chain)

```
collateral.collateral(doc, page_idx, cfg)
  read_pages(...)
    for every collateral page:
      crops.page_tables(page, vocab)
        pdfpage.page_model(page)                    words, rules
        crops.section_separators(page)              y of full-width rules
        crops.find_crops(page)                      → [rect]
          title_bottom / footer_top                 cut title and footer
          bands between separators
          merge: header band + band below; header + ruled records (_records_after)
          split at vertical rules
        for every rect: crops.crop_table(words, rect, vocab, rules)
          table.build_table(words, vocab, rules)    → raw table
            ruled_records? → record_table           (records between rules)
            else:
              totals_above_header                   set aside a total printed above the header
              header_size                           how many header lines
              column_cuts                           x of every column boundary
                find_gutters / _rescue_empty_columns / _seams / cut_in
              header_names                          header text per column
                _bottom_header_line / _upper_header_line
              body_rows                             data lines → rows (wraps, centred cells)
                _centred_cells
              split_sections                        'Loan' / 'Bond' labels → _section
      [--fallback: _try_xlarge → fallback.XLarge.tables]
    → [part]
  totals.stitch_pages(parts)                        tables over page breaks → [(pages, table)]
  for every joined table: totals.mark_totals(table) → marked table
      _classify_lines / _group_totals_above / _walk
      subtotal/total rows → checks (run report sheet collateral_sums)
      detail rows → per page
  join_on_id(detail tables, cfg)
      map_headers / norm_id / header_rank
      the row table (most distinct IDs), every column from the best-named header
  → rows (one per security), checks, fallback events
```

---

# Part C. Line by line

Each function: what goes in, what comes out, then its lines in blocks. **Why** a rule exists is
explained in GUIDE.md (search the function name); here the focus is what each line does.

---

## C1. `app.py` (17 lines): the entry point

- **L1–6** docstring: the three ways to start.
- **L10** puts `src/` on Python's import path, so `import wit...` works without installing the
  package. (In `WIT.exe`, PyInstaller has already bundled `src/wit`; the line is harmless.)
- **L12** runs only when the file is started, not when imported.
- **L13–15** any argument (`run`, `inspect`, `-h`) → the command line `wit.cli.main()`; its
  return value becomes the exit code.
- **L16–17** no argument → the window `wit.gui.main()`. That's what double-clicking `WIT.exe` does.

The imports sit inside the branches, so the command line never loads the window library and
vice versa.

---

## C2. `src/wit/config.py` (125 lines): settings and trustee configs

### `app_dir()`: L19–23
- **L21** `sys.frozen` is set only inside a PyInstaller build.
- **L22** packaged: the folder of `WIT.exe`.
- **L23** from source: two folders up from this file (`src/wit/config.py` → repo root).

**L26** `CONFIG_DIR`: `<app folder>/config`. Computed once at import.

### `_read(path)`: L29–31
Opens a YAML file as UTF-8 and returns a dict (`or {}` turns an empty file into an empty dict).

**L34** `OUTPUT_NAMES`: internal output names → display / folder names, used by the window and
by `redirect_outputs`.

### `load_settings(path=None)`: L37–49 → settings dict
- **L39** reads `settings.yaml` (or another file given with `--settings`).
- **L41–42** `absolute(p)`: a relative path is made relative to the app folder, so a copied
  `WIT` folder works anywhere.
- **L43–48** applies it to the reports root, the deal list path, the three output folders and
  the run-report folder.

### `redirect_outputs(settings, folder)`: L52–59
Used only by `--out`: rewrites the four output folders to `<folder>/Balance`,
`/Performance`, `/Collateral`, `/Run reports`. File names stay as configured, so two runs can be
compared with `dev/compare_outputs.py`.

### `_merge(base, over)`: L62–67 → merged dict
- **L64** deep copy, so the defaults are never changed in place.
- **L65–66** for every key of the trustee file: if both sides are dicts → merge recursively;
  otherwise the trustee value **replaces** the default (lists and strings replace, they don't
  append).

### `load_trustees(config_dir=None)`: L70–81 → (defaults, {layout: cfg})
- **L73** `defaults.yaml`.
- **L75** every `trustees/*.yaml`, alphabetical.
- **L76–77** files starting with `_` (the template) are skipped.
- **L79–80** `enabled: false` switches a file off; otherwise it is merged onto the defaults
  under its file name (`bny_mellon_a`).

### `doc_text(doc, n_pages=3)`: L84–89
The text of the first 3 pages (line by line) plus the PDF's metadata (title, author,
producer). Used only for detection.

### `layouts_for(trustee_name, trustees)`: L92–95
Every config whose `names` regex matches the trustee name from the deal list.

### `pick_config(doc, defaults, trustees, trustee_name)`: L98–108 → (layout name, cfg)
- **L101–104** trustee known and exactly one layout → that one.
- **L105–107** several layouts (BNY has two) → `detect_trustee` among those; if none of their
  patterns match, the first one.
- **L108** no trustee given (`inspect` without `--trustee`) or no layout matched the name →
  detect across all configs.

### `detect_trustee(doc, defaults, trustees)`: L111–125
- **L114** text of the first pages.
- **L118–119** a config qualifies only if ALL its `detect.all` patterns are in the text.
- **L120** score = number of `all` patterns + number of `any` patterns found.
- **L121–122** highest score wins; ties keep the first. A config with no `detect` patterns scores 0 and is never picked here (it is found through `names` instead).
- **L123–124** none qualifies → `"unknown"` with the defaults (the run report flags it).

---

## C3. `src/wit/sources.py` (210 lines): which PDF for which deal and month

**L27** `MONTH_IN_NAME`: `(?<!\d)` no digit before, `(\d{4})` a year, `[ _.-]?` an optional
separator, `(\d{1,2})` the month, `(?!\d)` no digit after. Matches `2026_08`, `2026-8`, `202608`.

### `month_of(name)`: L33–41 → (year, month) or None
- **L37** every match in the name, left to right.
- **L39** keeps only plausible ones (1991–2099, month 1–12).
- **L40** each plausible match overwrites the previous, so the **last** one wins
  ("Deal 2019-1 2026_08" → 2026-08).

### `parse_month(text)`: L44–49
`month_of`, but an error message instead of None (for typed input).

### `months_between(first, last)`: L52–61
- **L54** both ends parsed; **L55–56** first after last → error.
- **L58–60** counts month by month; December rolls over to January of the next year.

### `active_deals(settings)`: L67–76 → [deal]
- **L70** reads the deal-list sheet with pandas.
- **L71–72** every `filter` entry keeps the rows whose column equals the value
  (trimmed, case-insensitive), e.g. `Status: Active`.
- **L73–75** one dict per row with the deal name, trustee and folder name (folder column
  defaults to the deal column).
- **L76** drops empty rows (pandas reads empty cells as `nan`).

### `select_deals(deals, names, trustee)`: L79–90
- **L83** a lookup by lower-case name.
- **L84–86** any name not in the deal list → error listing them (never silently skipped).
- **L87** keeps the order the names were given in.
- **L88–89** optional trustee filter (substring, case-insensitive).

### `check_pdf(path)`: L96–124 → "ok" or the reason
- **L100–102** size 0 → empty file.
- **L103–106** reads only the first 1 KB and the last 2 KB (fast even for big files).
- **L107–108** every PDF starts with `%PDF-`; without it it's not a PDF (an HTML error page
  saved as .pdf, a renamed file).
- **L109–110** every complete PDF ends with `%%EOF`; without it the file was cut off.
- **L111–114** a real open; any exception → "cannot be opened".
- **L115** `with doc:` closes the file afterwards.
- **L116–121** password, no pages, or PyMuPDF had to repair the file.
- **L122–123** no text on the first 10 pages → a scan (out of scope).

### `_md5(path)`: L127–132
The file's fingerprint, read in 1 MB chunks. Two identical files have the same MD5.

### `_pdfs_for_month(type_dir, ym)`: L135–143
- **L138** every entry of the report-type folder.
- **L139–140** a folder whose name is that month → every PDF inside it (also in subfolders).
- **L141–142** a PDF directly in the type folder whose own name is that month.
- **L143** sorted, so the result doesn't depend on disk order.

### `_latest_month(deal_dir, report_types)`: L146–157
Looks at every month folder or month-named PDF of every report type and keeps the latest
`(month, type)`. Only used for the "missing" message.

### `find_report(settings, deal_folder, ym)`: L160–178 → {pdf, report_type, file_status, file_note}
- **L165–166** no deal folder → missing.
- **L167–173** report types in priority order; the first type that has candidate PDFs for the
  month decides (`_pick`).
- **L174–178** none → missing, with the latest month available in the note.

### `_pick(cands, rtype)`: L181–197
- **L182** checks every candidate.
- **L183–184** good ones, and a note per broken one.
- **L185–186** none good → `broken`.
- **L187** some broken but one good → `check` (it is used, but look at the note).
- **L188** shortest name first, so "Report.pdf" comes before "Report (1).pdf".
- **L189–191** several good and all identical (same MD5) → the first one, noted.
- **L192–196** several different → newest by modification time, the others named, `check`.

### `plan(settings, months, deal_names, trustee)`: L203–210 → [job]
For every month, for every selected deal: the deal's fields, the year and month, and what
`find_report` found. The order is month by month, deal by deal.

---

## C4. `src/wit/pdfpage.py` (105 lines): reading a page

**L17** `NUM`: the shape of a number after cleaning: optional `(` and `-`, digits with commas,
optional decimals, optional `%` and `)`.

### `page_model(page)`: L20–37 → (words, horizontal rules, vertical rules)
- **L24** `rotation_matrix`: turns coordinates of a page stored rotated (`/Rotate 90`) into
  upright coordinates.
- **L26–28** every word PyMuPDF finds (`x0, y0, x1, y1, text, ...`), rotated, as a dict.
- **L30** every drawing's rectangle plus every image's bounding box (some trustees draw their
  separator lines as images).
- **L32** rotated like the words.
- **L33–34** thin and wide (≤ 10 pt high, > 60 pt wide) → horizontal rule.
- **L35–36** narrow and tall (≤ 3 pt wide, > 30 pt high) → vertical rule.

### `rows_of(ws)`: L40–58 → [line]
- **L46** tolerance = half the median word height.
- **L48** words sorted by vertical centre.
- **L50–52** close enough to the current line's centre → joins it, and the line's centre is
  recomputed as the mean of its words (so one taller word doesn't pull the line).
- **L53–54** otherwise a new line starts.
- **L55–57** words left to right, and the line's text.

### `split_phrases(ws, gap)`: L61–71
Walks a line's words left to right; a gap wider than `gap` closes the current phrase.

### `phrases(ws, gap)`: L74–77
The same, returned as `{x0, x1, t, h}` (left, right, text, tallest word).

### `to_num(s, percent=True)`: L80–96 → float or None
- **L84** anything → trimmed text.
- **L85–86** with `percent=False` a percentage is not a number (amounts are summed;
  percentages must not be).
- **L87** drops a leading `>=`, `<=`, `>`, `<`, `≥`, `≤`.
- **L88** drops currency codes and signs, `[A]`-style markers and all spaces.
- **L89–90** what's left must look like a number.
- **L91** brackets or a minus → negative.
- **L93** strips brackets, `%` and `-`, removes commas, converts.

### `page_title(page, words, band)`: L99–103
The text of the lines in the top `band` (default 20%) of the page.

---

## C5. `src/wit/pages.py` (44 lines): which pages feed which output

**L16** `_CACHE`: keeps the page titles of the current PDF, because performance, balance and
collateral all ask for them.

### `page_texts(doc, title_band)`: L19–30
- **L20–22** same PDF and band as last time → the cached list.
- **L24–27** for every page: its title (top band) and its full text.
- **L28–29** only one PDF is cached at a time (memory stays flat over 233 deals).

### `select_pages(doc, cfg, output)`: L33–44 → [page index]
- **L34** the regex list for this output (`pages.performance`, ...).
- **L35–36** empty list → every page.
- **L37** `match_on: title` (default) or `text`.
- **L40–43** a page is kept if any regex matches its title (or text).

---

## C6. `src/wit/run.py` (226 lines): running the jobs, writing the files

**L37** `OUTPUTS`: the three outputs, always processed in this order.

### `DealResult`: L40–50
Everything known about one deal and month after `process`:
`job`; `report` (its line in the summary sheet); `tables` (output name → DataFrame with
internal column names); and the inputs of the run report: `bal_sources`, `perf_flags`,
`unmapped`, `coll_checks`, `empty_cols`, `fallback`. Empty defaults so a missing report still
gives a valid result.

### `month_label(job, settings)`: L53–54
`report_month` as written in the files: `month_format` (strftime) applied to the 1st of the
month, e.g. `"%Y-%m"` → `2026-08`.

### `read_performance(doc, cfg)`: L60–65 → DataFrame
- **L61** for every performance page, every test record `performance.performance` finds.
- **L62–63** a DataFrame with fixed columns (an empty one if nothing was found).
- **L65** drops repeated tests (same printed name, current value and trigger), because many
  reports print every test twice (a summary page and a detail page). The first one is kept.

### `read_balance(doc, cfg)`: L68–74 → ({field: value}, {field: details})
- **L70** candidates from every balance page.
- **L71** one value per label field, with a status.
- **L72–73** fields configured as "total of a column on a page" are computed separately.
- **L74** the values for the output file, and the details for the run report.

### `process(job, outputs, defaults, trustees, settings, xl)`: L77–124 → DealResult
- **L79–83** start the clock; the summary line starts with what is known from the job.
- **L85–87** no PDF (missing or broken) → nothing to read; flagged.
- **L88** opens the PDF.
- **L89** which trustee layout applies (from the deal list's trustee).
- **L91** `common`: the three columns every output file carries (deal name, month, asset class).
- **L92** `attention` starts True if the layout is unknown or the file status isn't `ok` (a broken copy was skipped, or several different PDFs were found).
- **L94–101** Performance (if selected): read; add the common columns; rows not `ok` →
  `perf_flags`; rows without a standard name → `unmapped`; counts into the summary;
  attention if no tests or any test not ok.
- **L103–108** Balance (if selected): read; one row; where each value came from →
  `bal_sources`; each field's status into the summary (`bal:principal balance` = ok ...);
  attention if any status is not ok.
- **L110–120** Collateral (if selected): read the collateral pages; add the common columns;
  keep the sum checks and fallback events; list the configured output columns that stayed
  completely empty; counts into the summary; attention if no rows.
- **L122–124** final flag and the time taken.

### `output_path(job, name, settings)`: L130–135 → file path
- **L132** this output's `dir` and `file` from settings.
- **L133** the deal name with characters Windows forbids in file names (`< > : " / \ | ? *`)
  replaced by `_`.
- **L134–135** fills `{deal}`, `{yyyy}`, `{mm}` in both the folder and the file name.

### `write_deal(res, settings)`: L138–147
For every output that was read: make the folder, keep only the configured columns in the
configured order (missing ones are added empty), rename headers (`rename`), write the Excel
file. Returns the paths.

### `write_run_report(results, settings, started)`: L150–181
- **L151–153** the file name carries the start time, so runs never overwrite each other.
- **L155–165** `sheet(attr)`: stacks one check table (e.g. `bal_sources`) from every result,
  adds `deal` and `month` as the first two columns; drops the internal `_mapped` flag.
- **L167–169** empty collateral columns and fallback events, one row each.
- **L170–172** unmapped test names, once per deal.
- **L173–180** writes the seven sheets.

### `run(jobs, outputs, settings, log, xl, stop, progress)`: L187–226 → run report path
- **L191** start time (for the report's file name).
- **L192** reads all trustee configs once per run.
- **L193** keeps the selected outputs in the fixed order.
- **L195** jobs one by one, numbered from 1.
- **L196–198** the window's Stop button → leave the loop (finished deals are already written).
- **L200–205** no PDF: log MISSING / BROKEN, keep its summary line, move on.
- **L206–213** process, write this deal's files **immediately**, log a one-line result
  (`CHECK` when it needs attention, plus the file note).
- **L214–220** any error in one deal: logged with its message, kept in the summary (`error`
  column), full traceback printed to the console, and the run **continues**.
- **L222–223** tells the window how far it is (progress bar).
- **L224–226** the run report, written once at the end.

---

## C7. `src/wit/cli.py` (88 lines): the command line

### `months_arg(text)`: L20–26
Splits on commas; each part is one month (`2026-08`) or a range (`2026-01:2026-06`);
duplicates dropped; sorted.

### `print_plan(jobs)`: L29–35
For `--check`: one line per job (month, deal, file status, path) and the note under it; then
"x of y reports found".

### `main(argv)`: L38–84
- **L39–57** two commands: `run` (months, deal, trustee, outputs, settings, out, check,
  fallback) and `inspect` (pdf, pages, trustee). `type=months_arg` turns `--months` into a list
  while parsing, so a bad month stops immediately with a message.
- **L60–63** `inspect` → `inspect_pdf.inspect`, imported only here.
- **L65–68** the outputs list; an unknown name stops with a message.
- **L69–71** settings; `--out` redirects all output folders.
- **L72–75** the plan; an unknown deal name or a missing deal list stops with a message
  pointing at `settings.yaml`.
- **L76–78** `--check` prints the plan and stops.
- **L79–82** `--fallback` creates the model wrapper (Docling must be installed).
- **L83** the run, logging with `print`.

---

## C8. `src/wit/gui.py` (293 lines): the window

How it works in one paragraph: the window is built once (`_build`). Clicking Run or Check
reports calls `_start`, which validates the choices and starts `_work` in a **background
thread**, so the window keeps responding. The thread never touches the window directly (Tk
doesn't allow that from another thread); it puts messages on a **queue** (`self.q`). Every
100 ms, `_poll` (running on the window's own thread) takes them off the queue and updates the
log, the progress bar and the buttons.

**L28** month labels; **L30** the ttkbootstrap theme (`flatly`).

### `App.__init__`: L34–47
- **L36** the queue between worker and window.
- **L37–38** `busy` (a run is going), `stop_flag` (Stop was pressed).
- **L39** `deals` (from the deal list), `shown` (after the search filter), `picked` (selected
  names).
- **L40–44** settings; if they can't be read, an error box and exit.
- **L45–47** build the window, load the deals, start polling the queue.

### `_build`: L50–61
Title line (L52–56), then the four parts in order: Period, Outputs, Deals, Actions.

### `_period`: L63–87
- **L66–67** `last` = the last day of the previous month (today's 1st minus one day).
- **L68** one on/off variable per year, from 5 years ago to this year; last month's year is on.
- **L69** one per month (1–12); last month's month is on.
- **L70–83** two rows ("Years", "Months"): a label, a toggle button per item
  (`outline-toolbutton` = a button that stays pressed), and All / None links. `lambda g=group`
  binds the right group to each link.
- **L84–86** the month counter next to the year buttons.

### `_set_all`: L89–92
Turns every button of a group on or off, then updates the counter.

### `_selected_months`: L94–98
Every chosen year × every chosen month, leaving out months after the current one (their
reports can't exist yet).

### `_update_period`: L100–102
Shows "n month(s)".

### `_outputs`: L104–110
One switch (`round-toggle`) per output, all on at start.

### `_deals_box`: L112–141
- **L117–119** the "All deals" switch (on at start).
- **L121–124** the search box; `trace_add("write", ...)` refills the list on every keystroke.
- **L125–128** Select shown / Clear.
- **L129–130** the "n deals selected" counter.
- **L133–136** a plain Tk listbox (ttkbootstrap has no multi-select list) coloured from the
  theme; `extended` = Ctrl/Shift multi-select; `exportselection=False` keeps the selection
  when focus moves to another widget.
- **L141** every selection change → `_on_select`.

### `_actions`: L143–166
Check reports / Run / Stop buttons (Stop disabled until a run starts), a status label, the
progress bar, the log (a Tk text box with a scrollbar). **L166** applies the "All deals" state
to the list.

### `_load_deals`: L169–175
Reads the deal list (with its filter, in the background); a failure is written to the log
instead of crashing the window.

### `_fill_list`: L177–188
- **L178–179** the deals whose name or trustee contains the search text.
- **L180–181, L187** a disabled listbox ignores changes, so it is enabled while refilling and
  then put back.
- **L183–186** one line per deal; deals already picked are selected again (the selection
  survives searching).

### `_on_select`: L190–194
For every shown deal: selected → added to `picked`, not selected → removed. Deals hidden by
the search are not touched.

### `_select_shown` / `_clear`: L196–202
Add all shown deals to `picked` / empty `picked`; then refill.

### `_toggle_all`: L204–208
"All deals" on → the list, search and buttons are disabled (greyed).

### `_update_count` / `_selected_deals`: L210–217
All deals → `None` (meaning all, to `plan`); otherwise the picked names in deal-list order.

### `_stop`: L220–222
Sets the flag `run.run` checks before each deal.

### `_start(check)`: L224–242
- **L225–226** ignore clicks while a run is going.
- **L227–238** validation: at least one month, one deal (unless All), one output (unless only
  checking); an error box otherwise.
- **L239–242** mark busy, switch buttons, reset the bar, start `_work` in a daemon thread
  (it ends with the window).

### `_work(months, names, outputs, check)`: L244–261 (background thread)
- **L246** the plan (finding and checking the PDFs).
- **L247–249** a summary line in the log.
- **L250–253** Check reports: one log line per deal and month, nothing extracted.
- **L254–257** Run: `run.run` with the log, the stop flag and a progress callback that puts
  `("progress", (n, total))` on the queue.
- **L258–261** any error is logged; `"done"` is always queued last, so the buttons come back.

### `_buttons(running)`: L263–267
Run/Check disabled and Stop enabled while running, and the other way round.

### `_say` / `_poll`: L270–286
`_say` puts a log line on the queue (safe from any thread). `_poll` empties the queue on the
window's thread: log lines are appended and scrolled into view; progress moves the bar and
the "n / total" label; `done` re-enables the buttons. **L286** schedules itself again in 100 ms.

### `main`: L289–293
Creates the ttkbootstrap window (title, theme, size, minimum size), the App, and starts Tk's
event loop.

---

## C9. `src/wit/inspect_pdf.py` (51 lines): what the readers see

### `inspect(pdf, pages, trustee)`: L21–51
- **L22–24** opens the PDF, loads configs, picks the layout (from `--trustee`, else detected).
- **L25–26** wide pandas printing.
- **L28–30** each requested page (1-based numbers from the user → 0-based index).
- **L31–36** the test rows `performance` finds on it: standard name, printed name, values,
  status.
- **L37–38** every balance candidate.
- **L39–42** every crop as a table, after `mark_totals` (first 8 rows, with `_row`/`_check`).
- **L43–51** every line made of exactly two phrases whose first isn't a number: the
  "label  value" pairs (useful to find the right balance label).

---

## C10. `src/wit/performance.py` (197 lines): test rows

**L20** `RESULT_WORDS`: what a result cell may say (the whole cell): pass/passed, fail/failed,
n/a, yes, no, true, false, met, not met, breach.
**L21** `ITEM`: a line starting with `(a)`, `(ii)`, `(bb)` or `Class ...` is a new test, never the
continuation of the previous one.

### `standard_name(printed, test_names)`: L24–34 → (standard name, mapped?)
- **L29–30** every standard name and each of its patterns (one string or a list).
- **L31–33** the pattern's match is measured; the longest match so far wins.
- **L34** a winner → (its standard name, True); none → (the printed name, False).

### `first_num(text)`: L37–46
The whole cell as a number; otherwise the first token (split on spaces or `/`) that is one
("100.1% / 2,000,000.00" → 100.1).

### `role_of(text, roles)`: L49–55
Lower-cases the header text and returns the first role (in config order) whose regex matches.

### `performance(page, cfg)`: L58–185 → [test record]

**Setup, L61–71**
- **L61–63** the performance config, the header roles, the result words.
- **L64–66** words and rules of the page; an empty page → nothing.
- **L67–68** words below the measured footer are dropped (footer text was being glued onto the
  last test name). `or words` keeps the page if everything would be dropped.
- **L69–70** lines, and `lh` (median word height) as the distance unit.
- **L71** `out` collects test records from every table on the page.

**Find a header line, L72–75**
A line is a header when it contains a `result` word AND one of test / ratio / current. Every such
line starts one table; the loop goes on to find the next ones.

**The header block, L76–87**
- **L77–81** up to 2 lines **above**, each less than 2.2·lh above the one below it.
- **L84–87** lines **below** it that are close (< 2.2·lh) and hold no data (e.g. a line of dates
  under the column names). `k` ends as the index of the first body line.

**The columns, L88–103**
- **L91** the anchor = the header line with the most phrases (the most complete line); on a tie,
  the result line itself.
- **L92** its phrases are the columns (`x0`, `x1`, text).
- **L93–100** every word of the other header lines joins the column it overlaps (or the nearest
  one): words from above go in front of the column text, words from below after it.
- **L101–103** columns left to right, each with its role.

**Side-by-side tables, L104–107**
Every test column that doesn't directly follow another test column starts a new group: a
dashboard with two tables next to each other gives two groups.

**The body, L108–120**
From line `k` down, a line ends the table when:
- **L112–113** a rule wider than 200 pt lies between it and the previous body line (once there
  is at least one body line), or the gap is larger than 3·lh (8·lh before the first body line);
- **L115–116** it is the next header line.
- **L117–118** lines lying inside a rule's own band (e.g. a shaded bar) are skipped.

**Per group, L121–126**
The x range this group owns: from the previous group's right edge (+5) or a bit left of its test
column (−15), to the next group's left edge (−5) or its last column + 2·lh (so an unrelated table
further right isn't swallowed).

**Per body line, L127–181**
- **L127** `last` = (last test record, its line's y, its name phrase), for wraps.
- **L129–131** the line's words inside the group's range; none → skip.
- **L132** phrases (gap 0.9·lh).
- **L135–139** one phrase without digits: if it sits right under the previous test like a
  continuation (`_wraps` with the phrase: close, same text height, not further left) and isn't a
  new item → appended to that test's name. Otherwise it's a section label → skipped.
- **L140–141** a new record.
- **L142–156** each phrase goes to the nearest column of the group (overlap first, else
  distance), by that column's role: `skip` ignored; test (or the first non-number in an
  unnamed column) → name (`name` remembers its first phrase); current / trigger → the first
  number (the first one wins); result → the text.
- **L157–158** a "result" that is itself a header word → a repeated header line, skipped.
- **L159** is the result one of the result words?
- **L160–170** no current value and no result word: a continuation line (rest of the name,
  sometimes with the trigger). Glued onto the previous test when `_wraps` (distance only) holds
  and it isn't a new item; the trigger is taken if the previous test had none.
- **L171–181** a name AND (a current value OR a result) → a test row. `_status` lists what's
  doubtful: no current value, a result that isn't a result word, a name that is a number or
  shorter than 4 characters. Kept, and remembered as `last`.

**Names, L182–185**
For every record: `original tests` = the name as printed; `test`, `_mapped` = `standard_name`.

### `_wraps(last, out, br, lh, phrase)`: L188–197
- **L192–193** False unless there is a previous test, it is the last record added, and this line
  is less than 1.6·lh below it.
- **L195–196** without a phrase (the numbers-line case) → True.
- **L197** with a phrase: its text is at most 10% taller than the test name's and it doesn't
  start more than 0.5·lh left of it.

---

## C11. `src/wit/balance.py` (149 lines): balance values

### `fields(cfg)`: L25–35 → (label fields, table fields)
Each entry of `balance.labels`:
- a dict with `page` → a table field (total of a column on a page);
- a dict without `page` → labels + `column`;
- a list → labels only.

### `_is_num(t)`: L38–39
Is this text a number (`to_num`)?

### `candidates(page, cfg)`: L42–92 → [candidate]
- **L44–49** label fields, words, vertical rules, lines, `lh`.
- **L51–56** every phrase of every line that isn't itself a number is a possible label.
- **L57–59** for every field whose label regexes match it.
- **RIGHT, L60–85**
  - **L62** the phrases right of the label, left to right.
  - **L63–64** a vertical rule between the label and the phrase → stop (that's another box).
  - **L65–66** a number → collected.
  - **L67–68** a lone currency or `%` → skipped.
  - **L69–70** any other text → stop.
  - **L71–73** exactly one number → candidate, how = `right`.
  - **L74–85** several (Current | Prior): the first one, how = `ambiguous`; if the field has a
    `column`, look up to 25 lines up for a header phrase matching it that overlaps one of the
    numbers → that number, how = `right/column`.
- **BELOW, L86–91** no number right of it: on the next line (< 1.8·lh below), exactly one number
  overlapping the label horizontally → how = `below`.

### `table_total(doc, cfg, spec)`: L95–132
- **L103–104** pages whose title matches `spec.page`.
- **L105–106** none → `missing`.
- **L108–122** every crop table on those pages with a column matching `spec.column`:
  `mark_totals`; detail rows are summed; a subtotal/total row's value is the printed total.
- **L124–125** page found, no rows and no total ("There are no ...") → 0, `ok (no rows)`.
- **L126–128** printed total ≠ sum of rows (by more than 0.01) → printed value, `conflict`.
- **L129–132** otherwise the printed total (or the sum when none is printed), `ok`, and `how`
  says which.

### `resolve(cands, cfg)`: L135–149 → {field: details}
- **L139–142** no candidate → `missing`.
- **L143** the first candidate wins (pages in config order, top to bottom).
- **L144–146** the same label text found again with a different value → `conflict`; a first
  candidate that was ambiguous → `ambiguous`; else `ok`.
- **L147–148** value, status, how, label, page, and how many candidates there were.

---

## C12. `src/wit/crops.py` (209 lines): a page → one rectangle per table

**L23** `AMOUNT`: a decimal (`1,234.56`, `0.5`, `(12.5)`), a number with thousands commas
(`1,234`), or a percentage (`4.5%`). Dates and plain integers are not amounts.

### `has_amount(ws)`: L26–28
Does any word look like an amount?

### `section_separators(page, min_width, min_image_height)`: L31–45 → [y]
- **L37–40** drawings at least `min_width` wide and at most 2.5 pt high (lines, hairline boxes).
- **L41–44** images at least `min_width` wide and 3–12 pt high (coloured bars drawn as images).
- Row shading (filled boxes ~12 pt high as drawings) and dotted 2 pt images are excluded by these
  limits. Returns the centre y of each, sorted.

### `title_bottom(words, page_height, max_band)`: L48–70 → y
- **L55** `body` = median word height on the page.
- **L57** lines from the top.
- **L59–60** stop below the top 20% of the page.
- **L61–62** stop at a rotated header word (taller than twice its width, 4+ letters).
- **L63–64** the line's height; `single` = no gap of 1.5·body between its words (one phrase).
- **L66** `big` = at least 10% taller than body text, or as tall as the title line above it.
- **L67–68** a line that isn't single and big ends the title block.
- **L69** otherwise the block extends to this line's bottom.

**L73** `PAGE_NUMBER`: "page 9", "Page9", "4 of 9", "4 of of 9".

### `footer_top(words, page_height, max_band)`: L76–96 → y
- **L84–85** fewer than 3 lines → no footer.
- **L86** `step` = median distance between consecutive lines.
- **L88** from the last line upwards:
- **L89–90** stop above the bottom 15%, or at a line with an amount (a subtotal, not footer).
- **L91–92** page numbering → the footer starts at this line at the latest.
- **L93–95** a gap above this line larger than 1.25 steps → the footer starts here; stop.
- **L96** the higher (smaller y) of the two signals; the page bottom when neither fired.

### `find_crops(page, model, min_sep_width, pad)`: L99–146 → [rect]
- **L101–102** words and rules (computed here unless passed in), page size.
- **L103–107** keep the words between the title block and the footer.
- **Step 1, L108–115** separators (≥ 60% of the page width) inside that range → bands of words
  between consecutive separators (empty bands dropped).
- **Step 2, L116–130** merge bands:
  - **L120–124** a header band followed by ruled records takes them all (`_records_after`);
  - **L125–128** otherwise a band without amounts and with ≤ 4 lines (a header alone) takes the
    band below it;
  - **L129–130** otherwise the band stays alone.
- **Step 3, L131–146** split each merged band side by side:
  - **L134–135** the vertical extent of its amount lines;
  - **L136–137** vertical rules covering at least 80% of that extent → split positions;
  - **L138–145** each slice with 3+ words becomes a rectangle around its words, plus 4 pt,
    clipped to the page.

### `_records_after(bands, i, max_header_lines)`: L149–160 → count
- **L151–152** band `i` must look like a header: no amounts, ≤ 10 lines.
- **L154–157** the following bands count while each has text lines first and then its full
  amount line (`first_full_line` returns > 0).
- **L158–159** one more if the next band holds only amounts (the total under the records).
- **L160** fewer than 2 records → 0 (not this layout).

### `_amounts_only(band)`: L163–166
At most 2 lines and every word is an amount.

### `crop_table(words, rect, vocab, min_words, rules)`: L169–176 → DataFrame or None
- **L171–172** the words whose centre is inside the rectangle.
- **L173–174** too few words → None.
- **L175** `table.build_table`, passing only the separators inside this rectangle (used by ruled
  records).
- **L176** a table with no rows or fewer than 2 columns → None.

### `page_tables(page, vocab, min_words)`: L179–189 → [(rect, DataFrame)]
Words and rules once; separators once; every crop → `crop_table`; the non-empty ones are kept.

### `write_crop_pdf` / `preview_png`: L192–209
A one-page PDF of the crop (the original page with its CropBox set, so the text layer stays) and
a PNG of it. Used by the fallback and `dev/crop_view.py`.

---

## C13. `src/wit/table.py` (613 lines): the words of one table → a DataFrame

The order inside the file follows the steps of `build_table` (L472): helpers → 2. header size →
3. columns → 4. header names → 5. body rows → 6. sections → the whole thing → ruled records.
Reading tip: start at `build_table` (L472), then go back to each step.

### Patterns and helpers, L29–58
- **L29** `DATE`: `5/2/2024`, `2024-05-02`, `02-May-2024`, `2 May 24`.
- **L30** `MONEY`: `1,234.56`, `(1,234)`, `0.00`.
- **L31** `TOTAL_WORD`: total(s), subtotal(s), sub-total(s).
- **L34–39** `is_data_line(ws)`: a word with a digit that isn't a date → data (amounts, IDs like
  LX123456). **L39** or a `Label: value` pair (a word ending in `:` that isn't the last word).
- **L42–43** `has_digit`; **L49–50** `cx` (centre x); **L53–54** `line_height` (median word
  height); **L57–58** `join` (two texts with one space).

### Step 2. `header_size(rows, lh)`: L64–80 → number of header lines
- **L70** the first data line.
- **L71–72** none → None (the table may be only text).
- **L73–79** centred first cell: while the line just above the first data line is much closer
  to it (< lh and < half the gap above), it belongs to the data, not the header → move the
  boundary up one line.

### Step 3. Columns

#### `ink_coverage(rows, x0, x1, step)`: L86–98
Divides the table width into 0.5 pt bins; for every bin, counts how many lines have a word over
it. Columns are plateaus; gutters are valleys.

#### `find_gutters(rows, x0, x1, min_w, tolerance)`: L101–124 → [(a, b)]
- **L105–113** `runs(limit)`: stretches where the count is ≤ `limit`.
- **L116–118** stretches with ink on at most `tolerance × lines` lines, at least `min_w` wide,
  not touching the table edges → gutters.
- **L119–123** a tolerant stretch that runs into the table edge is really a sparse first or last
  column; inside it, only strictly empty stretches count.

#### `column_cuts(rows, ws, n_hdr, lh)`: L127–169 → (cuts, gutters)
- **L139–140** the table's left and right edge.
- **L142–146** lines that are one phrase (titles, section labels) never define columns.
- **L147–148** header lines vs body lines.
- **L149–151** normal case: gutters measured on the **body** lines (headers are often wider
  than their values), 12% of lines may cross a gutter when there are 8+ lines; then header
  phrases lying inside a gutter become their own (empty) columns.
- **L152–153** no header or too few body lines: measured on all lines.
- **L154** plus narrow seams (below).
- **L156–168** `cut_in(a, b)`: inside a gutter, the cut goes in the middle of its widest
  stretch with no ink from any word (header words included), so one long cell poking into a
  wide gutter isn't split.
- **L169** cuts = left edge, one cut per gutter, right edge.

#### `_seams(lines, x0, x1, gut, head, share)`: L172–207 → extra gutters
- **L178–179** needs 3+ lines.
- **L180–182** `lh`, and every word space smaller than 0.6·lh (start, end).
- **L184** every strictly ink-free strip, however narrow (≥ 0.5 pt).
- **L185–186** skip it if it overlaps an existing gutter.
- **L187–188** the normal word space = median of the spaces NOT across this strip.
- **L189–194** per line: the word ending right at the strip's left edge and the word starting
  right at its right edge; kept as a pair if their gap is ≥ 1.6 × word space.
- **L196** lines that have a value right of the strip at all.
- **L197–198** need pairs on ≥ 80% of those lines (and at least 2).
- **L199–204** left ends and right starts; do the texts vary? does a header line show the same
  two edges?
- **L205–206** both edges aligned within 1 pt, and (varying values or header confirms) → a seam.

#### `_rescue_empty_columns(gut, head, lh)`: L210–225
- **L213** header phrases (gap 0.45·lh).
- **L216–220** for each gutter, the header phrases lying entirely inside it.
- **L221–224** the gutter is cut around them: the pieces left over (≥ 0.3·lh) stay gutters, so
  each such phrase gets its own column.

### Step 4. Header names

#### `header_names(rows, n_hdr, cuts, gut, lh, vocab)`: L231–257 → [name per column]
- **L236–237** `col_of(x)`: which column an x falls in.
- **L241–246** `extent[k]`: the leftmost and rightmost data word of every column.
- **L249–251** the bottom header line is the last header line, unless that line only fills
  column 0 (a section label such as "Loan"); then the one above.
- **L252–256** the bottom line is placed by the data; the lines above by position.

#### `_bottom_header_line(...)`: L260–292
- **L267** phrases of the line (gap 0.45·lh).
- **L268–286** splitting touching names: while a phrase spans a gutter (L272), find the word
  gaps near that gutter (L277); prefer a split where both halves match known header names
  (`vocab`), then the widest gap (L285); split and check both halves again (L286).
- **L287–292** each phrase goes to the column whose data it overlaps most; no overlap (an empty
  column) → the column under its centre.

#### `_upper_header_line(...)`: L295–323
- **L300** phrases (gap 0.6·lh).
- **L303** the columns the phrase covers (≥ 25% of the phrase).
- **L305–307** `inside(w)`: the word sits at least 80% inside one column.
- **L309–315** `aligned(w)`: the header word right below it in the same column starts, ends or
  centres with it, or there is none below.
- **L317–321** a phrase over several columns whose words each sit inside one column and are
  aligned → separate names, each word to its own column.
- **L322–323** otherwise the whole phrase goes to every column it covers ("Rating" over Moody's
  | S&P | Fitch).

### Step 5. `body_rows(lines, cuts, lh)`: L329–382 → [cells per row]
- **L343–348** `to_cells`: each word goes to the column its centre falls in.
- **L349** cells of every line.
- **L350–351** `anchors` = columns filled on ≥ 60% of lines.
- **L352–353** the normal line step (median).
- **L354** centred-cell analysis (below).
- **L356–359** lines that belong to the row BELOW them (centred cells) are collected per row.
- **L362–366** walk the lines; lines handed to a row below are skipped; that row gets them as a
  prefix.
- **L367–369** a line with a Total word, or a lone column-0 label right after a row with an
  empty column 0 (a subtotal), always stays its own row.
- **L371–376** a line is glued to the row above when it is within 1.25 steps, fills ≤ 2 cells
  and ≤ 30% of the anchor columns (and there are 2+ anchors); or (older rule) has no digits,
  fills few cells and is < 1.6·lh below; or the centred analysis says so.
- **L377–381** glued (cell by cell) or appended as a new row.

#### `_centred_cells(all_cells, ncol, lh)`: L385–424
- **L389–391** anchor columns measured on lines with digits only.
- **L393–399** `full` line (fills > 30% of anchors) / `text` line (1–2 cells, not full, no money)
  / other.
- **L402–404** the signature: a full line with a text line directly above AND below at equal
  distance (± 0.6 pt), closer than 0.8·lh.
- **L406–407** no signature → nothing changes.
- **L408–423** with it: every text line goes to the nearer full line (unless a section label or
  subtotal sits in between): nearer below → prefix of that row; nearer above → glued to it.

### Step 6. `split_sections(body, header, rows, n_hdr, cuts)`: L430–452
- **L436–439** a last header line that only fills column 0 is a section label: removed from the
  header and put in front of the body.
- **L442–448** a row with only column 0 filled and no digits → a section label: it sets
  `section` and is not a row; unless it repeats the current group value (then it's a subtotal's
  label and stays a row, L444–446).
- **L449–450** a row with column 0 and other cells sets the current `group`.
- **L451** every row gets the current section as an extra last cell.

### `totals_above_header(rows)`: L458–469
- **L462–463** the first data line that isn't a Total line.
- **L466** header lines (no data) before it.
- **L467–469** Total lines with amounts that have a header line below them → printed above the
  header; returned so they can be set aside.

### `build_table(words, vocab, rules)`: L472–505 → DataFrame
- **L477–479** ruled records? → `record_table` (end of file).
- **L480–486** lines; "There are no ..." messages and totals above the header are removed.
- **L487–489** `lh`, header size, column cuts.
- **L490–492** no data line at all: the whole thing is header; but with only 1–2 columns and 3+
  lines it is plain text, so there's no header (`n_hdr = 0`).
- **L493–495** header names, body rows, sections.
- **L497–498** column names: the header, `colK` when empty; duplicates get `_K`; plus
  `_section`.
- **L500–501** `_section` dropped when no section was found.
- **L504** totals printed above the header, as rows with the same columns, in
  `attrs["totals_above"]` (used by `stitch_pages`).

#### `_cells(ws, cuts)`: L508–514
Like `to_cells`, but tolerant of words outside the cuts (used for the set-aside totals).

### Ruled records, L520–613

**L520** `STACKED`: the prefix of a stacked column's name.

#### `amounts(ws)` / `first_full_line(lines)`: L523–531
`amounts` counts money words in a line. `first_full_line` = the index of the first line with at
least half as many amounts as the fullest line, so a name with a number in it ("Holdings 2.5")
isn't taken for the amount line. None when there are no amounts.

#### `ruled_records(rows, rules)`: L534–555 → (header lines, [(stacked lines, amount lines)]) or None
- **L541–543** rules inside the table; fewer than 2 → not this layout.
- **L544** lines between consecutive rules → bands.
- **L545–547** band 0 is the header; at least 2 non-empty bands after it.
- **L549–554** each band: text lines first (`first_full_line` > 0), then its amount lines; the
  last band may be amounts only (the total). Any other band → None (normal path).

#### `_stacks(records, lh)`: L558–567
Left edges of every text phrase in the records, sorted, grouped when closer than 1.5·lh: one
group per stack; returns each stack's leftmost x.

#### `record_table(header, records, vocab)`: L570–613
- **L576** `lh` from the amount lines.
- **L579–581** `stack_of(x0)`: the stack a phrase starting at x0 belongs to (within 1.5·lh).
- **L583–591** header phrases starting at a stack → that stack's names; the others → the normal
  header.
- **L592–597** columns and header names measured on the normal header + all amount lines, with
  the same functions as a normal table.
- **L599–607** per record: its stacked lines, phrase by phrase, into their stack (the nearest
  one if none is close); each amount line becomes a row: the stacks (lines joined with `" | "`)
  + the cells.
- **L608–610** stacked columns named `stacked: ` + names joined with `" / "`.
- **L612** no totals above the header in this layout.

---

## C14. `src/wit/totals.py` (260 lines): page breaks, subtotals, totals, groups

### `amount(v)` / `is_number(v)`: L23–30
`amount`: a number to sum (percentages excluded). `is_number`: any number, percentages
included (used to tell number cells from text cells).

### `stitch_pages(parts)`: L36–78 → [(pages, table)]
- **L45–48** for every page: the index of its first and last part.
- **L50–51** each part's column names (internal `_` columns ignored) = its signature.
- **L52–56** a part joins the current run when: same signature, the next page, the run ended
  with the LAST table of its page, and this is the FIRST table of its page.
- **L57** otherwise it starts a new run.
- **L59–72** sections carry over: on a continued page, the rows before the page's first section
  label get the previous page's last section (`cumprod` marks the leading empty ones).
- **L73** the parts of a run, one under the other.
- **L74–76** totals printed above the header (from `build_table`) are appended after the last
  row, so they're checked against every row of every page.
- **L77** all cells as text.

### `mark_totals(df)`: L84–111 → marked table
- **L93** text cells, fresh row numbers.
- **L94–97** data columns and the first column.
- **L98** `text_cols`: columns where less than half the filled cells are numbers.
- **L99** classify lines (detail / sum), merging a label line into the sum line below it.
- **L100–101** no sum line → everything is detail; done.
- **L102–105** fill rate of every column on detail rows; the first column filled ≥ 60% is
  dense; the sparse columns left of it are **group columns** (printed only on a group's first
  row).
- **L106–107** grouped table: look for group totals printed on the group's first line.
- **L108** walk the rows: copy groups down, check every sum.
- **L109–110** in a grouped table the section lines were group labels → `_section` dropped.

### `_mostly_text(col)`: L114–116
Less than half of the filled cells are numbers.

### `_classify_lines(df, cols, text_cols, first)`: L119–149
- **L120–121** `label_only`: only the first column filled, and not with a number.
- **L123–127** `sum_line`: has a number somewhere, and no text in text columns except at most
  one cell with a Total word.
- **L131–142** a label line directly followed by a sum line → one merged sum line carrying the
  label; otherwise each line is a sum or a detail.
- **L143–148** rebuilt table; `_row` = detail or total (refined later), `_check` empty.

**L152** `ABOVE`: the check text for a group total printed on its group's first line.

### `_group_totals_above(out, num_cols, group_cols)`: L155–179
- **L159** rows that start a group (group column filled).
- **L161–163** the group's other detail rows, up to the next sum line.
- **L165–171** in every number column: the first line's value vs the sum of the others (within
  0.011 per row).
- **L174–176** it must also look like a summary: it leaves empty a column that all the group's
  rows fill (name, ID), so a real first row that happens to match isn't taken.
- **L177–179** → marked as the group's subtotal with `ABOVE`.

### `_walk(out, cols, text_cols, group_cols, first)`: L182–260
State while walking down: `current` (current group values), `members` (its detail rows),
`all_members` (detail rows since the last total), `sec_members` (per section), `closed` (the
current group's total was printed above it).

- **L190–192** a group-total-above line: starts the group, isn't a row itself.
- **L193–208** a detail row:
  - **L194–195** remembered under its section;
  - **L196–201** a group value that differs from the current one (spaces ignored) starts a new
    group (the same value repeated on a new page continues it);
  - **L202–205** an empty group cell is **copied down** from the group's first row;
  - **L206–207** remembered in the group and since the last total.
- **L211–214** a sum line: which rows does it close?
  - `carried`: grouped table, no group yet, no rows yet → its rows are on an earlier page;
  - `is_sub`: a group subtotal (its first cell empty or equal to the group's value), unless the
    group's total was already printed above it;
  - `rows_k`: the group's rows for a subtotal, all rows since the last total for a total.
- **L215–219** a section subtotal ("Bond Subtotal:") closes the rows of that section instead.
- **L220–224** `_row` set; an empty label is filled in (from the section or the group).
- **L225–231** no rows to compare: a labelled line ("Total Number of ... | 4") is a figure,
  back to detail; otherwise "its rows are on an earlier page".
- **L233–244** every number column with a printed value and row values: sum vs printed (within
  0.011 per row, cent rounding).
- **L245–254** the verdict: nothing compared → "nothing to compare with" (or blank for a
  labelled figure); all match → `ok`; mismatch on a labelled line → it's a figure, back to
  detail; mismatch otherwise → `check: <column>: printed X vs rows Y` (+ "rows may start on an
  earlier page" when the first rows of the table are involved).
- **L255–260** reset what was closed: the section's rows, the group, or everything (total).

---

## C15. `src/wit/collateral.py` (227 lines): one row per security

**L24** `ID_FIELD`: the field rows are joined on.

### `_synonyms(pat)`: L30–41
Splits a synonym regex at its top-level `|` (not inside brackets), in order: the list of
alternatives.

### `_is_field_name(header, field)`: L44–45
The header, lower-cased with punctuation turned into spaces, equals the field name
("Principal Balance" → `principal balance`).

### `header_rank(header, field, columns_cfg)`: L48–55
0 if the header is the field name; else 1 + the position of the first synonym it matches; 99 if
none. Lower = names the field more directly.

### `map_headers(headers, columns_cfg)`: L58–73 → {header: field}
- **L64–65** stacked columns are skipped (several fields in one cell).
- **L66–72** each header goes to the FIRST field (config order) whose regex matches it.
- **L69–71** several headers for one field: a header that IS the field name wins, else the
  left-most.
- **L73** returned in column order.

### `norm_id(v, patterns)`: L76–86
- **L79–84** the first token matching an ID pattern (LoanX, ISIN, FIGI, CUSIP), so overflow text
  from the neighbouring column doesn't pollute the ID.
- **L85–86** otherwise the whole value without spaces, if it's 6–14 letters/digits with at least
  one digit; else empty (not an ID).

### `header_vocab(cfg)`: L92–95
All collateral synonyms and performance role regexes: the known header names used to split
touching header names.

### `_id_share(df, cfg)` / `_failed_sums(marked)`: L98–115
For the fallback only: does the table have an ID column and what share of its detail rows have
a valid ID; which checks failed for a reading reason (not "earlier page").

### `read_pages(doc, page_idx, cfg, xl, events)`: L118–138 → [part]
- **L124** every crop table (≥ 10 words) of every collateral page.
- **L125–126** fewer than 3 columns → skipped.
- **L127–136** with the fallback: IDs on < 50% of rows or a failed sum → `_try_xlarge`; the
  event is logged.
- **L137** each table tagged with its page.

### `_try_xlarge(...)`: L141–157
The model's tables replace PyMuPDF's only if they have more valid IDs (≥ 50%), or pass the sums
PyMuPDF failed without losing IDs or more than one column. A model error keeps PyMuPDF's table.

### `collateral(doc, page_idx, cfg, xl)`: L163–179 → (rows, checks, events)
- **L166** read the pages, join tables over page breaks.
- **L167** mark totals.
- **L170–173** every subtotal/total row → one line in `checks` (pages, first 3 headers, kind,
  label, verdict).
- **L174–176** detail rows, split back per page, internal columns dropped.
- **L178–179** join on the ID; no ID table → an empty frame.

### `join_on_id(tables, cfg)`: L182–227 → one row per security
- **L187–190** each table: headers → fields; skipped without an ID field or with fewer than 3
  mapped fields.
- **L191–193** keep the mapped columns under their field names; normalise IDs; drop rows
  without an ID.
- **L195** empty cells → missing (so they can be filled from another table).
- **L196–197** remember the page and each field's header rank.
- **L198** tables with the same set of fields (the same table on several pages) are grouped.
- **L201–206** each group stacked into one table; its rank per field = the best rank.
- **L210–211** the **row table**: has an issuer column, then most distinct IDs, then fewest
  duplicate IDs (a table that splits a security into lots isn't one row per security), then
  most columns.
- **L212** every table indexed by ID (first occurrence).
- **L213** the output rows = the row table's IDs.
- **L215–222** every field: tables ordered by how directly their header names it; the value
  comes from the best one, gaps filled from the next (`combine_first`).
- **L224–226** numeric fields → numbers.

---

## C16. `src/wit/fallback.py` (66 lines): the optional model

- **L18–19** where the offline Docling models are (`DOCLING_ARTIFACTS_PATH` or the default
  cache folder).
- **L23–28** `XLarge`: no model loaded yet; counters for calls and seconds; a temporary folder
  for crop PDFs.
- **L30–44** `_converter`: loads Docling once, on first use, offline: the egret-xlarge layout
  model and TableFormer in accurate mode, OCR off (the PDFs have text).
- **L46–61** `pdf_tables`: converts a PDF (or one page) and returns every table as a DataFrame
  of text.
- **L63–66** `tables`: writes the crop as a one-page PDF and reads it.

---

## C17. `dev/`: checking changes (not shipped)

- **`dev/tests/run_tests.py`**: imports every `test_*.py` and runs every `test_*` function;
  prints failures; exit code 1 if any fail. Works without pytest.
- **`dev/tests/helpers.py`**: `line(y, (x, "text"), ...)` builds words the way PyMuPDF returns
  them (5 pt per character, 10 pt high, 3 pt spaces), so every rule is tested without a PDF.
- **`dev/tests/test_*.py`**: one test per rule; GUIDE.md §4.13 lists what each file covers.
- **`dev/compare_outputs.py`**: two output folders → every differing cell, as FILLED / LOST /
  CHANGED (collateral rows matched on the ID).
- **`dev/crop_view.py`**: per page, PNGs of the crops and each crop's table; per PDF, the
  tables over page breaks with their checks.
