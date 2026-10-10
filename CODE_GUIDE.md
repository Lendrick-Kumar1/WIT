# Code guide

How the code is organised, the order to read it in, and every rule it applies (what the rule
does, why it exists, where it lives and which test covers it).

## Reading order

| # | File | Lines | What it does |
|---|---|---|---|
| 1 | `src/wit/run.py` | ~260 | Command line: for each deal, reads Performance, Balance and Collateral, then writes the Excel files |
| 2 | `src/wit/config.py`, `sources.py`, `pages.py` | ~190 | Which config applies (trustee), which PDF per deal (deal list + folders), which pages feed which output |
| 3 | `src/wit/pdfpage.py` | ~100 | Basic page reading: words (rotation fixed), separator lines, text lines, phrases, numbers |
| 4 | `src/wit/performance.py` | ~160 | Test rows found by header words |
| 5 | `src/wit/balance.py` | ~150 | Balance values: label to number, or the total of a column |
| 6 | `src/wit/crops.py` | ~170 | Cuts a page into crops, one table per crop |
| 7 | `src/wit/table.py` | ~440 | Words of one crop to a table, in 6 named steps |
| 8 | `src/wit/totals.py` | ~220 | Subtotals and totals checked; groups copied down; tables joined across page breaks |
| 9 | `src/wit/collateral.py` | ~230 | Collateral: crop tables to one row per security, joined on the ID |
| 10 | `src/wit/fallback.py` | ~70 | XLarge (Docling), optional, only for crops that fail their checks |

Tools: `tools/crop_test.py` (see how a PDF is cropped and read), `tools/compare_outputs.py`
(compare two output folders cell by cell). Tests: `tests/` (synthetic words, no PDFs).

## The flow

```
deal list + folders ──► PDF ──► config (trustee YAML) ──► pages per output (by page title)
   Performance: header line with result/test words  ──► rows below it
   Balance:     label phrase ──► number right of it / below it   (or total of a column)
   Collateral:  page ──► crops ──► one table per crop ──► join across page breaks
                     ──► subtotals/totals checked ──► headers mapped ──► join on security ID
──► out/<period>/<deal>/{Balance,Performance,Collateral}.xlsx + _run_report.xlsx
```

## Principles (apply to every change)

1. **No coordinates in code or config.** Every distance is measured on the page relative to the
   text (line height, row step, gap between words).
2. **Trustee differences go in YAML** (`config/trustees/`), never as `if trustee == ...`.
3. **Never silently guess.** If the code is unsure, it writes a status / check into
   `_run_report.xlsx` instead of a number that looks right.
4. **Comments describe the pattern, never the deal.** For example, write "centred 2-line cells"
   and leave out the deal or issuer it was seen in.
5. **After every change:** `python tests/run_tests.py`, then `tools/compare_outputs.py` against the
   output from before the change. Every difference must be explained.

## Rules

### Cropping a page (`crops.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| Title block measured: leading single-phrase lines printed larger than body text | A fixed "top 12%" line cut off column headers on some layouts | `title_bottom` | `test_title_block_is_measured` |
| Rotated (vertical) header words stop the title block | Vertical column headers are tall and were mistaken for title text | `title_bottom` | n/a |
| Footer measured: bottom lines separated by a clearly larger gap, holding no amounts | A fixed "bottom 7%" line cut off the last row of a page | `footer_top` | `test_footer_is_measured_and_last_row_is_kept` |
| Section separators: full-width lines ≤ 2.5 pt, or images 3–12 pt high | Row shading and 2 pt dotted rules are not section breaks | `section_separators` | n/a |
| A header-only band is glued to the band below | Every crop must carry its own header | `find_crops` step 2 | n/a |
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
| Bottom header line placed by the data under it; touching names split at the gap nearest the data gutter (known header names preferred) | Header names wider than their values; touching names | `_bottom_header_line` | `test_columns_come_from_data_not_header` |
| Upper header phrase over several columns goes to all of them, unless its words line up with the words below | Group headers ("Rating" over Original / Current) vs close, separate names | `_upper_header_line` | n/a |
| Wrapped line glued to the row above (few cells, few anchor columns, within 1.25 row steps) | Top-aligned multi-line cells | `body_rows` | `test_wrapped_cell_below_is_glued`, `test_lone_word_right_after_a_row_is_a_wrapped_cell` |
| Centred cells: when the table shows the signature, text lines go to the nearer full row | Cells printed above and below their row | `_centred_cells` | `test_centred_cell_lines_above_and_below_are_glued` |
| A line with "Total" / "Subtotal" is never glued to a row | A total line was being read as the last security's wrapped text | `body_rows` | `test_total_line_is_never_glued_to_the_last_row` |
| A lone column-0 label after a subtotal line starts a section | Section labels ("Loan", "Bond") after a subtotal | `body_rows`, `split_sections` | `test_section_labels_become_a_column` |
| "There are no ..." messages are dropped | Empty tables print a sentence instead of rows | `build_table` | `test_no_data_message_is_ignored` |

### Subtotals, totals and groups (`totals.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| A sum line = amounts and no text except a "Total" label; a label line directly above it is its label | Subtotals printed as "<group>" then "<amount>" on two lines | `_classify_lines` | `test_grouped_table_copies_group_down_and_checks_subtotal` |
| Group columns = sparse columns left of the first dense column; their values are copied down | Grouped tables print the group only on its first row | `mark_totals`, `_walk` | same |
| Each sum is compared with the rows it closes (group, section or everything since the last total) | Proves no row was lost or merged | `_walk` | `test_section_subtotals_and_grand_total`, `test_subtotal_that_does_not_add_up_is_flagged` |
| A labelled figure that is not a sum of the rows above stays a normal row | Key-value boxes like "Total Number of ..." | `_walk` | `test_labelled_figure_in_a_key_value_box_is_not_a_total` |
| A sum whose rows are on an earlier page is flagged, not failed | First group on a page continued from the page before | `_walk` | `test_total_whose_rows_are_on_an_earlier_page` |
| Tables joined across a page break only from the last table on a page to the first on the next, with the same columns | Separate small tables on consecutive pages must not be joined | `stitch_pages` | `test_stitch_joins_last_table_with_first_table_of_next_page`, `test_separate_tables_on_consecutive_pages_are_not_joined` |
| Section carries over the page break | A page continuing a section has no label at its top | `stitch_pages` | `test_stitch_carries_section_over_page_break` |

### Collateral (`collateral.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| Header goes to the first field whose synonyms match (config order) | Specific synonyms before generic ones | `map_headers` | `test_first_header_wins_otherwise` |
| A header that IS the field name wins over a synonym | "Principal Balance" next to "Par/Quantity" | `map_headers` | `test_header_that_is_the_field_name_wins` |
| ID = the token matching the ID patterns (LoanX, ISIN, FIGI, CUSIP); other IDs must contain a digit | Text overflowing into the ID column | `norm_id` | `test_norm_id_picks_the_id_token` |
| Rows from the table with the most distinct securities; on a tie, the one listing each security once | Tables splitting a security into lots have no single value per security | `join_on_id` | `test_rows_from_table_with_most_distinct_securities` |
| Each column from the table whose header names it most directly | "Issuer Name" before "Description" | `join_on_id`, `header_rank` | `test_each_column_from_the_most_specific_header` |
| XLarge fallback only for crops with IDs on < 50% of rows or failing sums; used only if it does better | Keep the fast path; the model is a last resort | `read_pages`, `_try_xlarge` | n/a (needs Docling) |

### Numbers (`pdfpage.py`)

| Rule | Why | Where | Test |
|---|---|---|---|
| One parser: thousands separators, (negative), >= / <=, €/$/£, EUR/USD/GBP, [A] markers; percentages optional | Every module reads numbers the same way | `to_num` | `test_to_num` |

## Known limits (flagged, not silent)

- A one-word line directly under a row, with no subtotal before it, is read as wrapped text, not
  a new section (`test_lone_word_right_after_a_row_is_a_wrapped_cell`).
- A total printed in a different column from its rows cannot be checked; it is reported as
  "not checked" / "nothing to compare with".
- The *issuer* field takes whatever the best-matching column prints. If a trustee prints
  "Issuer - Facility" in one column, splitting it is a business rule still to add.
