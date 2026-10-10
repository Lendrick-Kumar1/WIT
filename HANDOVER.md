# WIT: Handover (v3)

## 1. What was wrong before, in one paragraph
Every tool you tried (Camelot, `find_tables()`, Docling/egret) starts by **guessing where the tables are and how many there are**. On borderless dashboards, and on pages split into 2 or 3 bands, that guess is wrong: no table, one giant blob, or 4 tables where there are 3. Everything downstream then breaks, and falling back to a bigger model doesn't help, because the bigger model makes the **same kind of guess**.

## 2. What this code does instead
It never guesses tables. It reads the PDF's own text (exact words and their positions) and looks for **the words your output needs**:

| Output | It looks for | Then |
|---|---|---|
| **Performance** | a **header row** containing a result word (Result / Pass/Fail) plus test / current / trigger words | reads every row under that header until a separator line or a big gap. Two header sets side by side mean two tables. |
| **Balance** | the **label** of each field ("Aggregate Principal Balance") as its own phrase | takes the number right of it on the same line; else the number directly under it |
| **Collateral** | tables whose **column headers** map to your schema (Security ID, Principal Balance, Moody's Rating …) | stacks the same table across pages and joins different tables on the security ID |

It also fixes two PDF quirks that confused the other tools: US Bank pages are **stored rotated 90°**, and their band lines are **images**, not drawn lines.

## 3. How robust is "the number to the right of a label"? An honest answer
**Why it holds up:** trustees print reports from a **fixed template per deal**. Labels and header words are the template's own vocabulary, and they almost never change month to month. Positions are never stored; they're measured fresh on every page, relative to the words themselves. So layout shifts, extra rows and longer names don't break it.

**The rules are strict, not "grab anything nearby":**
- The label must be **its own phrase** (a separate text run), so a label can't be matched inside a sentence.
- Only the **numbers immediately after** the label, stopping at the next text or a vertical rule. This is how it avoided picking a number from the neighbouring table on your dashboard.
- If there are **several numbers** (Current | Prior), it uses the column header named in config. If there's none, it flags `ambiguous`.
- If there's nothing to the right, it looks **directly below**, and only if exactly one number sits under the label.

**Where it can still go wrong, and what happens then:**

| Situation | Result |
|---|---|
| Label not found (trustee changed the wording) | `missing`: **flagged, never invented** |
| Two different values for the same label | `conflict`: flagged; the first page in your `pages.balance` order wins |
| A test row whose current value is empty or a dash | row kept, `_status = check: no current` |
| Test name looks wrong (a number, too short) | `_status = check: test name?` |
| A header word this code doesn't know | that column is ignored. You add the word to config once; the "no current" flag tells you |

**The rule that matters most:** when it isn't sure, it **says so** in `_status`, `_balance_sources.status` and `_run_report.xlsx`, instead of writing a wrong number. A wrong value that looks right is the expensive failure, and the design avoids that. A flagged value costs you a look at one page.

**What it doesn't do:** read scanned PDFs (it needs the text layer, and all your samples have one), or read charts.

## 4. Inputs now come from your org's metadata, not the PDF
```
deal list Excel  ->  active deals + trustee            (config/sources.yaml: path, column names)
reports root     ->  <deal folder>/<Monthly|Quarterly|Intra Trustee Report>/<2026_8 ...pdf>
--period 2026-08 ->  first report-type folder (in priority order) that has the file
```
So **deal name, trustee and report month come from metadata**, which is reliable. The trustee from the deal list selects the config. If a trustee has more than one layout (US Bank A/B, BNY A/B), the `detect:` patterns pick between them.

## 5. Results on your 7 samples (one run, demo folder tree)

| Deal | Config | Tests | Tests flagged | Collateral rows | Time |
|---|---|---|---|---|---|
| Capital Four CLO I | bny_mellon_a | 78 | 0 | 140 | 2.1 s |
| Providus CLO VII | bny_mellon_a | 76 | 0 | 204 | 3.0 s |
| Providus CLO II (from the *Quarterly* folder) | bny_mellon_b | 63 | 0 | 158 | 2.7 s |
| Arini European CLO I | citi | 18 | 0 | 192 | 4.3 s |
| Anchorage CLO 5 (+ your problem PDF: 18/18 correct) | us_bank_a | 62 | 0 | 123 | 2.8 s |
| Segovia CLO 3 | us_bank_a | 16 | 0 | 170 | 1.5 s |
| Carlyle Euro 2013-1 | us_bank_b | 58 | 27 (the PDF prints "-") | 69 | 1.7 s |
| Example Wilmington | (no report) | MISSING reported | | | |

**Status:**
- **Performance:** solid.
- **Balance:** the mechanism works, but the labels are placeholders.
- **Collateral:** rows and IDs are right, but only 6–15 of the 29 columns fill. The rest needs page key terms and header synonyms from your legacy repo.

## 6. Folder map
```
WIT/
├── run.py                        python run.py --period 2026-08 [--trustee "US Bank"]
├── config/
│   ├── sources.yaml              deal-list path + columns, reports root, folder priority, file naming
│   ├── defaults.yaml             shared vocabulary (header words, categories, column synonyms)
│   └── trustees/*.yaml           one per trustee layout; _template.yaml to add more
├── src/wit/
│   ├── sources.py                deal list + folder walk -> which PDF per deal
│   ├── config.py                 merge defaults + trustee, pick the layout
│   ├── pages.py                  page selection by key terms
│   ├── pdfpage.py                rotation fix, separators (lines AND images), rows, numbers
│   ├── performance.py, balance.py, collateral.py, geometry.py
│   ├── crops.py                  page -> one crop per table (section bars, vertical rules)
│   ├── croptable.py              crop -> ONE table: grouped rows, subtotals, sum checks
│   └── run.py                    orchestration, statuses, Excel outputs
├── demo/make_demo.py             builds an org-style demo tree from reports/
└── out/<period>/<Deal>/{Balance,Performance,Collateral}.xlsx  +  out/<period>/_run_report.xlsx
```

## 7. What you do next

**A. Run it on your laptop (15 minutes)**
```bash
poetry add pymupdf pandas openpyxl pyyaml
poetry run python demo/make_demo.py            # builds demo/ from reports/
poetry run python run.py --period 2026-08      # -> out/
```
Open `out/_run_report.xlsx` first, then the 3 output files.

**B. On the org laptop: config only, no code**
1. `config/sources.yaml`: the real deal-list path and column names, the reports root, and the folder names.
2. For each trustee, fill in `config/trustees/<name>.yaml` from the legacy repo:
   - `names` (how the deal list spells the trustee)
   - `pages` (key terms)
   - `balance.labels`
   - `collateral.columns` (only where they differ from the defaults)
3. Run one period for one trustee: `python run.py --period 2026-08 --trustee "U.S. Bank"`.
4. Look at the flagged rows in `_run_report.xlsx`. Each one points to a config gap or a genuine oddity.

**C. Claude Code (new chat, in `WIT/`)**
> Read HANDOVER.md and CLAUDE.md. Do not restructure. Run `python demo/make_demo.py` and `python run.py --period 2026-08`, and confirm the numbers in HANDOVER §5. Then: for each trustee config, list the empty Collateral columns (`_gaps` sheet), find which pages hold that data (by page title), and add page key terms and header synonyms to the trustee YAML. After each change, re-run and show that no count in §5 went down.

**Later:** stakeholder range checks; Docling only as a last-resort fallback for a page where a *required* table yields nothing; a regression folder with one known-good Excel per trustee.

## 8. Rules that keep it from failing again
1. **No coordinates in config or code.** Only words; positions are measured on each page.
2. **A trustee difference goes in YAML**, never as `if trustee == ...` in code.
3. **Never silently guess:** an uncertain value gets a status, not a number.
4. **After any change, re-run every sample** and compare with §5. Nothing may go down.
