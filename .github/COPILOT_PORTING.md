# Porting the legacy naming into WIT: instructions for GitHub Copilot

**Who reads this:** GitHub Copilot (Chat / agent mode), working in a workspace that holds BOTH:
- the **legacy repo** (the old extraction project): the workspace root;
- the **new repo, WIT**: a clone inside an ignored folder of the legacy repo, next to this file:
  ```
  <legacy repo>/
  ├── ... legacy code, configs, mappings ...
  └── <ignored folder>/
      ├── COPILOT_PORTING.md          (this file)
      └── WIT/                        (the new repo)
  ```

**The job:** find every name the legacy repo uses to locate, recognise, standardise and write
data (folders, file names, deal list columns, trustee names, page titles, labels, column
headers, test names, output files and columns) and write it into **WIT's config files**, in the
formats described below, so WIT produces the same kind of output right away.

**Read first:** `WIT/README.md` (how WIT runs) and `WIT/.github/copilot-instructions.md`
(rules). `WIT/Notes/GUIDE.md` §4.2–4.11 explains what each config key does inside the code.

**Where this file comes from:** it is kept in the WIT repo at `WIT/.github/COPILOT_PORTING.md`.
Copy it next to the WIT clone (into the ignored folder) before starting.

---

## 0. Ground rules (read carefully)

1. **Only edit files in `WIT/config/`.** Do not change anything in `WIT/src/`, `WIT/dev/` or
   `WIT/app.py`. Do not change the legacy repo. If something cannot be expressed in config,
   write it in the inventory (step 1) under "needs code", and stop there for that item.
2. **Do not invent.** Every value you write must come from the legacy repo. For each one, record
   where it came from (file and line) in the inventory. If the legacy repo doesn't say, write
   `"<<TODO: what is needed>>"` and list it in the inventory.
3. **Do not port legacy parsing logic** (coordinates, page numbers, table-extraction settings,
   Camelot/Tabula/pdfplumber parameters, pixel boxes). WIT finds things by words; only the
   **words and names** are needed.
4. **Never commit or push WIT.** The filled-in config contains real paths and labels and stays on
   this laptop. (If `git status` in WIT shows config changes, that is expected; leave them
   uncommitted.)
5. **Keep WIT's internal names.** Config keys like `principal balance`, `loan id`,
   `original tests` are WIT's internal field names and must not be renamed. Legacy column
   headers go into `output.rename` (internal name → header written).
6. **Regex**: every pattern in WIT config is a Python regex, matched **case-insensitively**. In
   YAML double-quoted strings, a backslash must be doubled: `"\\bCLO\\b"`, `"\\d{6}"`. See §4.
7. **No coordinates, no page numbers** anywhere in WIT config.

---

## 1. Step 1: inventory the legacy repo (write `porting_inventory.md`)

Create `porting_inventory.md` next to this file (ignored folder). Search the legacy repo and fill
one table per topic below: **what**, **legacy value(s)**, **legacy file:line**, **WIT target**
(file + key), **notes** (conflicts, per-trustee differences, things that need code).

Where to look (search terms; adapt to what you find):

| Topic | Search the legacy repo for |
|---|---|
| A. Reports folder | the reports root path (drive letters, `\\`, `Reports`), `glob`, `os.walk`, `rglob`, `listdir`, `.pdf` |
| B. Report types | folder names like "Monthly", "Quarterly", "Intra", "Trustee Report", and their priority/order |
| C. Month folders / file names | `strftime`, `%Y`, `%m`, `_%m`, date parsing of folder or file names, "period", "month", "as of" |
| D. Deal list | `read_excel`, `read_csv`, the deal list path, sheet name, column names (deal, trustee, status/active, folder), filters on status |
| E. Trustees | trustee names and spellings (BNY, Bank of New York, U.S. Bank, Citi, Deutsche, Wilmington, ...), how a trustee/layout is chosen, distinguishing text in the PDFs (websites, department names) |
| F. Page selection | lists of page titles / "key terms" per output (performance, balance, collateral), per trustee |
| G. Balance | labels for principal balance, defaulted balance, principal proceeds, CCC balance (and any other balance fields), per trustee; whether a value is "the number next to a label" or "the total of a column on a page" |
| H. Performance | header words used to find test tables; the **test name standardisation** (dicts / mapping tables / CSVs from printed name to standard name); result words (Pass/Fail); category handling |
| I. Collateral | column-name mappings (dicts like `{"LoanX ID": "loan id", ...}`, `rename(columns=...)`), ID types (LoanX, ISIN, CUSIP, FIGI), numeric columns, per-trustee header differences |
| J. Output | output folder structure and file names (`to_excel`, `ExcelWriter`, `os.path.join`), sheet names, column names and ORDER per output, how `report_month` / dates are formatted, `asset class` values |
| K. Anything else standardised | value mappings (e.g. rating or seniority normalisation, country codes, yes/no flags), units (percent vs decimal), rounding |

For K: WIT does not yet transform values (it writes what is printed). List these under
"needs code" with the exact mapping; they become a later change.

---

## 2. Step 2: fill `WIT/config/settings.yaml`

Current structure (keep every key; replace values):

```yaml
reports_root: "E:/CDOA/Reports"          # A. root folder; forward slashes
report_types:                            # B. folder names, PRIORITY order (first with the month wins)
  - "Monthly Trustee Report"
  - "Quarterly Trustee Report"
  - "Intra Trustee Report"
deal_list:                               # D.
  path: "<<path to the active deals Excel>>"
  sheet: 0                               # sheet name (string) or index
  columns:
    deal: "Deal Name"                    # column with the deal name (written into outputs)
    trustee: "Trustee"                   # column with the trustee name
    folder: "Deal Name"                  # column whose value IS the deal's folder name under reports_root
  filter: {}                             # e.g. {Status: Active}  (column: value, case-insensitive equality)
output:                                  # J. one FIXED folder per output
  balance:
    dir: "out/Balance"                   # folder; may use {yyyy} {mm} {deal} for subfolders
    file: "{deal}_{yyyy}_{mm}.xlsx"      # file name; placeholders {deal} {yyyy} {mm}
  performance:
    dir: "out/Performance"
    file: "{deal}_{yyyy}_{mm}.xlsx"
  collateral:
    dir: "out/Collateral"
    file: "{deal}_{yyyy}_{mm}.xlsx"
  run_reports: "out/Run reports"         # one run report per run
  month_format: "%Y-%m"                  # strftime applied to the 1st day of the month
  columns:
    balance: [...]                       # internal names, in output order (see §5)
    performance: [...]
    collateral: [...]
  rename: {}                             # internal name -> header written in the file
```

Rules:
- **Month folders are recognised by code** (`2026_08`, `2026-08`, `2026_8`, `202608`,
  `2026_08_15`). If the legacy repo uses another month folder format (e.g. `Aug 2026`,
  `08-2026`), do NOT add a regex: list it under "needs code".
- **Deal folder ≠ deal name?** If the folder name differs from the display name, point
  `columns.folder` at the column holding the folder name. If no such column exists, list it
  under "needs code".
- **`dir` / `file` per output**: copy the legacy output locations and file names, using the
  placeholders `{deal}`, `{yyyy}`, `{mm}` (e.g. legacy `Balance/<deal>_<yyyymm>.xlsx` →
  `dir: "E:/.../Balance"`, `file: "{deal}_{yyyy}{mm}.xlsx"`). If the legacy name needs something
  else (a trustee name, a date in another format, a counter), list it under "needs code" and keep
  the closest placeholder form.
- **`month_format`**: what the legacy `report_month` looks like, as strftime (`"%Y-%m"`,
  `"%m/%d/%Y"`, `"%b-%Y"` ...). If legacy writes the LAST day of the month, note it under "needs
  code".
- **`columns`**: the legacy output columns, in legacy order, using WIT internal names (§5). A
  legacy column WIT does not produce: add it to the list ONLY if the legacy file must keep that
  shape (it will be written empty), and list it in the inventory.
- **`rename`**: every internal name whose legacy header differs, e.g.
  `{"loan id": "LoanX ID", "deal name": "Deal Name", "report_month": "Report Month"}`.

---

## 3. Step 3: fill the trustee files `WIT/config/trustees/<layout>.yaml`

One file per trustee **layout** (a trustee with two very different report layouts gets two
files; `detect` tells them apart). Existing files: `bny_mellon_a.yaml`, `bny_mellon_b.yaml`,
`citi.yaml`, `us_bank_a.yaml`, `deutsche_bank.yaml`. For a trustee without a file, copy
`_template.yaml` to `<trustee>.yaml` (lowercase, underscores). Put ONLY what differs from
`defaults.yaml`.

```yaml
names: "BNY|Bank of New York"     # E. regex matched against the deal list's trustee column
detect:                           # E. only needed when one trustee has several layouts
  all: ["bny ?mellon"]            #    text that ALWAYS appears in this layout's PDFs (first 3 pages)
  any: ["Compliance Summary"]     #    extra hints; the layout matching most wins
layout:
  title_band: 0.2                 # top share of a page that holds the section title (default 0.2)
pages:                            # F. page titles (regex) per output; empty list = every page
  match_on: title                 #    title (top band of the page) | text (anywhere on the page)
  performance: ["Compliance Tests", "Par Value Tests", "Interest Coverage Tests"]
  balance:     ["Compliance Summary"]
  collateral:  ["Asset Information I\\b", "Ratings and Recovery Detail"]
balance:
  labels:                         # G. one entry per balance field; see the three forms below
    principal balance: ["^aggregate principal balance$"]
    default balance:   {page: "Defaulted Obligations Detail", column: "^principal balance$"}
    proceeds balance:  ["^principal proceeds$"]
    ccc balance:       {labels: ["^ccc obligations$"], column: "current"}
performance:                      # H. only if this trustee differs
  test_names:                     #    added to the defaults' test_names
    "Senior Interest Coverage Test": ["^class a(/b)? interest coverage"]
collateral:                       # I. only headers that differ from defaults
  columns:
    loan id: "lxid|loanx|loan ?x|security id|isin|figi|cusip|asset id|identifier|<<their header>>"
```

**`names`**: must match how the DEAL LIST spells the trustee (not the PDF). Make it loose enough
for all spellings in the deal list.

**`pages`**: the legacy "key terms" that pick pages. They are matched against the page TITLE
(the top `title_band` of the page) unless `match_on: text`. Use regex: escape `( ) . / & ?`;
use `\\b` for word boundaries (`"Asset Information I\\b"` must not match "Asset Information II").

**`balance.labels`**: each field takes ONE of three forms:
- a) `["^aggregate principal balance$"]`: label printed next to (right of) its number, or with
  the number directly below it. Several labels allowed (first found wins).
- b) `{labels: [...], column: "current"}`: the label has several numbers right of it (Current |
  Prior); `column` picks the one under the header matching it.
- c) `{page: "<page title regex>", column: "<column header regex>"}`: the value is the TOTAL of a
  column on a page (e.g. the defaulted obligations page's principal balance column).

Labels should match the WHOLE label phrase as printed: `"^principal proceeds$"`, not
`"proceeds"` (which would also match "Interest Proceeds"). A new balance field (beyond the four)
can be added: add it here AND to `defaults.yaml` `balance.labels` AND to
`settings.yaml` `output.columns.balance`.

**Merging**: a trustee file is merged onto `defaults.yaml`: dicts merge key by key; **a list
replaces** the default list (so `pages.collateral: [...]` replaces, not appends). A
`collateral.columns.<field>` string REPLACES that field's default synonyms: include the default
synonyms in it plus the trustee's own.

---

## 4. Regex cheat sheet (legacy strings → WIT patterns)

| Legacy | WIT pattern | Why |
|---|---|---|
| exact label `"Aggregate Principal Balance"` | `"^aggregate principal balance$"` | whole phrase, case doesn't matter |
| `"Principal Proceeds" in text` | `"principal proceeds"` | contains |
| `startswith("Class A")` | `"^class a\\b"` | `\\b` stops "Class AA" |
| label with `(`, `)`, `.`, `/`, `$`, `?`, `+`, `*`, `[` | escape: `"\\(a\\) senior"` | regex special characters |
| several spellings `["Par Value Test", "OC Test"]` | `["^par value test$", "^oc test$"]` or `"^(par value\|oc) test$"` | lists are alternatives |
| variable spaces / line wrap | `"principal\\s+balance"` | `\\s+` = any whitespace |
| `&` vs `and` | `"s(&\|and)p"` | both spellings |
| `'` (Moody's) | `"moody'?s"` | apostrophe optional |

In YAML: double-quoted strings, backslashes doubled. Test a pattern before writing it:
`python -c "import re; print(bool(re.search(r'^par value test$', 'Par Value Test', re.I)))"`.

---

## 5. WIT internal names (use exactly these as keys)

**Balance** (keys of `balance.labels`; output columns):
`deal name`, `report_month`, `principal balance`, `default balance`, `proceeds balance`,
`ccc balance`, `asset class`.

**Performance** (output columns):
`deal name`, `test`, `report_month`, `current`, `trigger`, `result`, `original tests`,
`asset class`.
- `original tests` = the test name exactly as printed in the PDF.
- `test` = the standard name from `performance.test_names`.

**Collateral** (keys of `collateral.columns`; output columns):
`issuer`, `loan id`, `dbrsm_ind`, `country_code`, `seniority`, `cov_lite`, `defaulted`,
`coupon type`, `current coupon`, `current spread`, `libor`, `maturity date`, `moody's rating`,
`s&p rating`, `fitch rating`, `dbrs rating`, `dbrs_ce`, `rec_rate_moody`, `rec_rate_sp`,
`rtg_watch_mdy`, `rtg_watch_sp`, `rtg_watch_fitch`, `rtg_watch_dbrs`, `principal balance`,
`unfunded`, `dbrsm_ind_code`, `payment period`, `issue`, `industry classification`,
`report_month`, `deal name`.

If the legacy output has a collateral column that maps to none of these, list it under "needs
code" (a new field needs a synonym entry in `defaults.yaml` `collateral.columns` AND an entry in
`settings.yaml` `output.columns.collateral`; that IS config, so you may add it, but say so in
the inventory).

---

## 6. Step 4: `WIT/config/defaults.yaml` (shared by all trustees)

Only these parts:

**`performance.test_names`** (H): standard test name → list of patterns of the names as
printed. The legacy mapping is usually `printed → standard`; INVERT it:
```yaml
performance:
  test_names:
    "Class A/B Par Value Test": ["^class a/b par value", "^class a/b oc\\b", "^a/b overcollateral"]
    "Weighted Average Life Test": ["weighted average life", "^wal\\b"]
```
- Among the patterns that match a printed name, the one matching the LONGEST part wins, so a
  specific pattern ("class a/b par value") beats a generic one ("par value") regardless of
  order.
- Trustee-specific spellings may go in the trustee file's `performance.test_names` instead.
- Printed names with no match keep the printed name in `test` and are listed in the run report
  (sheet `unmapped_tests`): that list is the to-do list for this mapping.

**`collateral.columns`** (I): header synonyms per field, ONE regex string per field, `|`
between alternatives. **Order of the fields matters**: a header goes to the FIRST field whose
regex matches it, which is why "moody.*recovery" (rec_rate_moody) comes before "moody.*rating".
Add legacy header spellings to the right field's string; keep specific alternatives before
generic ones. Example: legacy maps "Par Amt" → principal balance:
```yaml
    principal balance: "principal balance|par amount|par amt|par value|par/quantity|principal amount|current balance"
```

**`collateral.id_patterns`**: only if the legacy repo uses an ID format not covered (LoanX
`LX\d{6}`, ISIN, FIGI `BBG...`, CUSIP).

**`performance.header_roles`**: only if the legacy repo finds test tables by header words that
WIT doesn't know (e.g. a trigger column called "Covenant"): add the word to the right role's
regex (`trigger: "threshold|trigger|...|covenant"`). Keep the order of the roles.

**`asset_class`**: the value legacy writes in `asset class`.

Do not change anything else in `defaults.yaml`.

---

## 7. Step 5: check the result

Run from the `WIT/` folder (with poetry: prefix `poetry run`):

1. Config loads and rules still hold:
   ```
   python dev/tests/run_tests.py
   ```
   All tests must pass (they don't depend on your config values except `defaults.yaml`
   structure). The window needs `ttkbootstrap==1.10.1` installed (`poetry add "ttkbootstrap==1.10.1"`).
2. Which PDFs would be read for one month:
   ```
   python app.py run --months 2026-08 --check
   ```
   Every active deal should show a PDF, or `missing` with a plausible "latest is ..." note.
   Many `missing` → check `reports_root`, `report_types`, `deal_list.columns.folder`.
3. One trustee:
   ```
   python app.py run --months 2026-08 --trustee "BNY"
   ```
   Open the newest `out/run_report_*.xlsx`:
   - `summary`: `layout` must not be `unknown` (else fix `names` / `detect`); `tests` > 0;
     `collateral_rows` > 0.
   - `balance_sources`: every field `ok`. `missing` → label not found (check spelling, page
     titles); `ambiguous` → add `column`; `conflict` → the same label shows different values.
   - `unmapped_tests`: add patterns to `test_names` until empty.
   - `collateral_gaps`: add header synonyms for columns legacy fills.
   - `collateral_sums`: `check:` rows are reading problems, NOT config problems → list them in
     the inventory as patterns (no deal names) for the code owner.
4. Look at one page when unsure: `python app.py inspect "<pdf>" --pages 12 --trustee "BNY"`
   (shows the test rows with standard and printed names, balance candidates, tables, labels).
5. Compare with the legacy output for the same deal and month (write a throwaway script in the
   ignored folder, not in WIT): same columns (after `rename`), same row counts, same values.
   Record differences in the inventory.

Repeat 3–5 per trustee.

---

## 8. Deliverables

- [ ] `porting_inventory.md`: every topic A–K with legacy source (file:line), WIT target, and
      the lists "TODO (legacy doesn't say)" and "needs code (cannot be config)".
- [ ] `WIT/config/settings.yaml` filled (input paths, deal list, the three output folders and
      file names, run-report folder, month format, columns, rename).
- [ ] `WIT/config/trustees/*.yaml`: one per trustee layout in the deal list, `names`,
      `pages`, `balance.labels` filled; no `<<PLACEHOLDER>>` left (or listed as TODO).
- [ ] `WIT/config/defaults.yaml`: `performance.test_names`, extra `collateral.columns` synonyms.
- [ ] `python dev/tests/run_tests.py` passes; one run per trustee done; run report reviewed.
- [ ] Nothing in `WIT/src/`, `WIT/dev/`, `WIT/app.py` changed; nothing committed or pushed.

---

## 9. Starter prompt (paste into Copilot Chat, agent mode)

> Read `<ignored folder>/COPILOT_PORTING.md` completely, then `<ignored folder>/WIT/README.md`
> and `<ignored folder>/WIT/.github/copilot-instructions.md`. Follow COPILOT_PORTING.md step by
> step. Start with step 1: search the legacy repo (everything outside `<ignored folder>`) for
> topics A–K and write `<ignored folder>/porting_inventory.md` with file:line sources. Show me
> the inventory before editing any WIT config file. Only edit files in
> `<ignored folder>/WIT/config/`. Never invent values; use `<<TODO: ...>>` when the legacy repo
> doesn't say. Do not commit or push.

After reviewing the inventory:

> Inventory looks right. Do steps 2–4 (settings.yaml, trustee files, defaults.yaml), then step
> 5 for trustee "<name>". Report what the run report shows and what you changed.
