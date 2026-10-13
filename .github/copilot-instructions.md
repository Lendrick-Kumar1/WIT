# Working rules for this repository (read by GitHub Copilot)

WIT reads born-digital CLO trustee report PDFs and writes Balance, Performance and Collateral
Excel files per deal and month. `README.md` = how to run; `GUIDE.md` = what it does and why,
every rule (Appendix A); `CODE_TOUR.md` = every function block by block, and the call map.
When you change a function, update its section in CODE_TOUR.md (and the line numbers).

## Design (do not change without the owner agreeing)
- PyMuPDF on the main path. No model on the main path (`fallback.py` is optional, `--fallback`).
- Deal, trustee and month come from the deal list and the user's selection, never from PDF text.
- Find what the output needs by its WORDS (header words, labels, column headers), and use the
  PDF's own structure (separator lines, alignment, line spacing).
- No coordinates in code or config: every distance is relative to the text (line height `lh`,
  normal line step, normal word space).
- Trustee differences live in `config/trustees/*.yaml`, never `if trustee == ...` in code.
- Never silently guess: an uncertain value gets a status / check that ends up in the run report.
- Use `pdfpage.page_model()` for words and rules, `pdfpage.rows_of()` for lines,
  `pdfpage.to_num()` for every number.

## Sensitive data
- Never write a deal name, issuer name or real figure into code, comments, tests or docs.
  Describe the pattern instead ("total printed above its rows", "header names touching").
- Never commit PDFs, outputs (`out*/`), the deal list, or config holding real paths and labels.

## Changing code
- Prefer a config change (page title, label, header synonym, test name) over code.
- A new rule = a small named function or step, a docstring saying the pattern and why, a test in
  `dev/tests/` built from synthetic words (`dev/tests/helpers.py`), and a row in GUIDE.md
  Appendix A.
- Keep functions short; no new dependencies without asking.

## After every change
1. `python dev/tests/run_tests.py`: all pass.
2. `python app.py run --months <m> --out out_before` (before) and `--out out_after` (after), then
   `python dev/compare_outputs.py out_before out_after`. Explain every FILLED / CHANGED / LOST
   cell; LOST and CHANGED need a look at the PDF (`python app.py inspect <pdf> --pages N`).
3. The number of `collateral_sums` rows in the run report must not drop.
