# Experiment: does XLarge work when it sees ONE table at a time?

## Why
Every XLarge failure so far was on a **full page**, where the model also has to decide where
tables start and end:
- 3 bands read as 3 tables on one page, and merged into 1 on a near-identical page;
- dashboards collapsed;
- sparse grouped tables broken up.

Those are **segmentation** errors. If XLarge + TableFormer is reliable once it's handed a single
table, the fallback design is simple:

```
PyMuPDF (first pass) ─► checks ─► ok: accept
                          └─ fail ─► SAME crop ─► XLarge + TableFormer ─► checks ─► ok: accept
                                                                          └─ fail: flag for review
```
There's no new model, and the crops come from the PDF itself, so identical pages always give
identical crops.

## How the crops are made (`src/wit/crops.py`, no model involved)
1. Cut the page at **full-width section bars**: drawn lines and US Bank's coloured image bars.
   Thin dotted rules between groups or above totals are **not** cuts.
2. A band that is only a header (no amounts) is joined to the band below, so every crop has its
   own header.
3. Inside a band, a **vertical rule** covering most of the body height splits side-by-side
   tables.
4. Each crop is the original page with its **CropBox** set to the crop. Rotation, vector graphics
   and the text layer are untouched, so Docling still matches cells to the real PDF text. There is
   no OCR and no re-drawing.

## Run it
```bash
# 1) fast sanity check, no Docling: look at the crop PNGs (are the crops the right tables?)
poetry run python tools/crop_test.py probs/*.pdf --no-docling

# 2) the real test: XLarge on full pages AND on crops
poetry run python tools/crop_test.py probs/*.pdf
#    one file at a time if you prefer:  ... probs/dashboard_bands.pdf --pages 1,2
#    models not in ~/.cache/docling/models?  add  --artifacts "C:/path/to/models"
```
Step 2 runs roughly 60 Docling conversions (21 full pages + 39 crops). Expect **10–30 minutes**
on CPU. Close other apps first.

## Output
```
out/crop_test/summary.xlsx            one row per (pdf, page, unit, engine)
out/crop_test/<pdf>/p<N>/page.png     the full page
                        crop<k>.png   each crop as Docling sees it
                        tables.xlsx   sheets: full_t1..      (XLarge on the full page)
                                              c<k>_docling_t1.. (XLarge on crop k)
                                              c<k>_pymupdf_t1.. (PyMuPDF on crop k)
```

## What to fill in and send back
In `summary.xlsx`, fill **`correct? (fill in)`** for each row:
- `Y`: rows and columns right;
- `N`: wrong, with a short note such as "merged 2 cols", "split into 2", "missed table" or "values shifted";
- `P`: partly right, with a note.

Send back:
1. `summary.xlsx`, filled in;
2. for 2–3 of the worst rows, the matching `crop<k>.png` and its sheet from `tables.xlsx`;
3. any crop that is **itself wrong** (cuts a table in half, or two tables in one crop). That's a
   crop-rule problem, not a model problem.

## How we'll read it
| Result | Decision |
|---|---|
| Crops fix most XLarge failures | Fallback = PyMuPDF, then XLarge on crops, then flag. No new model. |
| A specific pattern still fails on crops | That pattern gets a PyMuPDF rule (e.g. grouped tables), or a second model as last resort for that pattern only |
| PyMuPDF already correct where XLarge fails | Confirms PyMuPDF as first pass; XLarge only behind checks |
