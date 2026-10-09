# Trustee Report Extraction — Architecture & Decisions

Status: design agreed in chat, to be built in Claude Code.
Prototype to learn from: `prototype/pipeline.py`, `prototype/explain.py`, `docs/PIPELINE_GUIDE.md`
(geometry-only engine, validated on one BNY Mellon CLO report: 26 tables, 32/32 total checks pass).

---

## 1. Problem and constraints

| Item | Value |
|---|---|
| Documents | ~233 trustee reports per cycle, ~6–7 trustees (US Bank, Wilmington, BNY Mellon, Citi, …) |
| Pages to parse | ~20 per document after keyword page capture → **~4,700 pages per cycle** |
| PDFs | Born-digital (text layer present). Borderless, dense, dashboard layouts, adjacent tables, multi-page tables |
| Hardware | **CPU only, no GPU, Windows, 16 GB RAM (~5–6 GB free in practice)**, on both the dev laptop and the org laptop (see §2d) |
| Current state | PyMuPDF page capture (keep it) + Camelot with hand-written coordinates + ~10k lines of if/try |
| Best accuracy seen | Docling with `docling-layout-egret-large`, but ~4 min per 11 pages (~22 s/page) → ~28 CPU-hours per cycle |

---

## 2. The key finding: the slow part is not the part that makes Docling good

Docling runs several models per page:

1. **Layout detection** (heron / egret): finds Table, Text, Section-header, etc. boxes.
2. **TableFormer**: predicts rows and columns inside each table box.
3. **OCR** (on by default): re-reads text from pixels.

The egret-large win you observed is mostly **layout detection**: it correctly separates
adjacent borderless tables, which was exactly where everything else failed.

Published CPU latency of the layout models alone (Docling layout paper, AMD EPYC 7763, 4 threads):

| Model | Arch | Params | CPU s/page |
|---|---|---|---|
| heron | RT-DETRv2 R50 | 43 M | 0.64 |
| egret-medium | D-FINE-m | 20 M | 0.33 |
| **egret-large** | D-FINE-l | 31 M | **0.47** |
| egret-xlarge | D-FINE-x | 63 M | 0.81 |

So egret-large **layout alone** ≈ 0.5 s/page, about **40× faster** than the full Docling run you
timed. The other ~21 s/page is TableFormer (accurate mode) and OCR. On a born-digital PDF, OCR
is pure waste, and TableFormer is replaceable by geometry *once the table box is known*.

> **Task 0 is to confirm this on your machine** (section 8). Everything below assumes the
> benchmark agrees with the paper's numbers within ~2–3×.

### 2b. Update from your own test (supersedes the guess above)

The measured configuration was **OCR off, egret-large + TableFormer ACCURATE**:

- About 90% of tables came out correct.
- Failures were **dashboard pages** (adjacent borderless tables).
- The ~22 s/page is therefore **TableFormer ACCURATE + layout**, not OCR.

Consequences:

1. **Primary path = egret-large + TableFormer ACCURATE** (proven 90%). Geometry is no longer the primary structure engine.
2. **Fix dashboards with a geometry split *before* TableFormer.** For each egret Table box, run the prototype's XY-cut with the row-alignment test on the PDF words inside the box. If it yields 2+ table-like blocks, replace the box with those sub-boxes. This is the case the prototype already handles (BNY pages 4, 9, 10, 37).
3. **Feeding sub-boxes to TableFormer.**
   - Simplest: write each sub-box as a one-page mini-PDF (`page.show_pdf_page(rect, src, pno, clip=subbox)`) and run Docling on it. The text layer is preserved, and layout sees a single table.
   - Later, if needed: call the TableFormer predictor directly with explicit table boxes (docling-ibm-models; the API is version-specific).
4. **Validation decides** which tables are in the failing ~10%. Only those go to review.
5. **Runtime.** About 4,700 pages × 22 s ≈ 28 CPU-hours.
   - Spread across parallel workers this fits an overnight batch (e.g. 4 workers × 2 threads ≈ 7 h, to be measured).
   - If that's too slow, add the **fast path**: try geometry structure inside each box first, accept it if validation passes, and run TableFormer only on failures. Same components, ordered differently.
   - *Superseded by §2c: the fast path is now the default.*

### 2c. Update: the machines have 16 GB RAM (supersedes the runtime plan in 2b)

Hardware is CPU only, 16 GB RAM (~5–6 GB actually free), 4 physical cores on the dev laptop. Measured on `bny_1` pages 1/4/9, one worker
with 2 threads, full Docling (egret-large + TableFormer ACCURATE, OCR off): model load ~8 s, text-only
page ~7 s, table pages 25–31 s, **peak RAM ~1.05 GB per worker**.

1. **Default 1 Docling worker** with threads = physical cores. **Never more than 2.**
   `cli doctor --measure` measures peak RAM per worker and recommends 2 only if free RAM is
   ≥ ~8 GB and ≥ 2 × peak + 4 GB headroom. The benchmark also records peak RAM per worker.
2. **Streaming, not bulk.** Each worker loads its models once, then processes one page (or one
   document) at a time. Never hold a whole report, all page images, or all results in memory.
   Write each page's results to the cache and drop them.
3. **The fast path is the default.**
   - Detect (egret) → geometry split → **geometry structure** → stitch → map → validate.
     Long and multi-page tables (asset lists, rating detail, etc.) always use geometry.
   - **TableFormer ACCURATE runs only on (a) dashboard pages** (a page whose egret Table box
     splits into 2+ sub-tables, or with 2+ adjacent tables) **and (b) tables that fail validation**.
     It runs on that (sub-)box crop (mini-PDF), then re-validates; anything still failing goes to review.
     Config: `routing.tableformer_on: [dashboard_page, validation_failure]`.
   - Full-page TableFormer (the 2b primary path) is kept only as the **baseline** in eval and bench.
   - Why: at ~25 s/page, 4,700 pages × 1 worker ≈ 33 h, which is far too slow. Egret layout
     plus geometry is ~2–3 s/page measured (≈ 3–4 h per cycle on 1 worker), plus TableFormer on the
     dashboard/failed minority.

### 2d. Deployment: dev laptop → private GitHub repo → org laptop

- Code ships by `git clone` of a **private GitHub repo**. Both machines are Windows, CPU only, 16 GB.
- **Never in git:** PDFs, outputs, caches, model weights, `config/local.yaml` (`.gitignore` enforces it).
- **Pinned environment:** Python `>=3.12,<3.13`; every dependency is pinned by the committed
  `poetry.lock`. Install with `poetry sync`; change dependencies only on the dev machine (`poetry add`).
- **Config layering, no machine values in code:** `config/defaults.yaml` < `config/local.yaml`
  (git-ignored, from `local.example.yaml`) < env vars (`DOCLING_ARTIFACTS_PATH`, `TE_REPORTS_DIR`,
  `TE_WORKERS`, `TE_THREADS`, `TE_YOLO_WEIGHTS`).
- **Models:** Docling models are fetched once with
  `docling-tools models download-hf-repo docling-project/docling-layout-egret-large docling-project/docling-models`
  or copied from `~/.cache/docling/models`. YOLO weights are **GitHub Release assets**
  (`gh release download`). Runtime is always offline.
- **`cli doctor`** checks Python, installed deps vs `poetry.lock`, model files, offline mode, reports
  folder, free RAM and cores, and prints the recommended worker count. Step-by-step: `docs/SETUP.md`.

---

## 3. What each technique is actually good at

| | Finding **where** tables are (segmentation) | Finding **columns/rows inside one table** | Getting the **exact text/digits** |
|---|---|---|---|
| PyMuPDF geometry (prototype) | Weak-to-OK: fragile on dashboards, needs tuned thresholds | **Strong**: exact word boxes, gutters are unambiguous inside one table | **Exact** (text layer) |
| Layout model (egret / heron) | **Strong**: learned from 150k pages, handles adjacent borderless tables | Not its job | n/a (boxes only) |
| TableFormer | n/a | Strong but slow on CPU; still maps PDF words onto predicted cells | Exact if OCR off |
| YOLO / custom detector | Strong after training on your pages | Weak for tight borderless columns | n/a |
| Vision LLM | OK | OK | **Risk of wrong digits**, slow/costly; needs validation |

Your intuition that "PyMuPDF geometry is fragile" is right **for segmentation** and wrong
**for structure**. Inside a correct box, gutter-based columns on exact word coordinates are the
most precise method available. That is what Docling's own TableFormer does at the end: it maps
the PDF's word boxes onto predicted cells.

**So: use the model for *where*, geometry for *what's inside*, and validation to decide
whether to trust it.**

---

## 4. Decision: train YOLO11 with Label Studio (updated: now planned, Task 8)

**Decision: yes, as a second pluggable detector.** egret-large stays the baseline.
Licensing is not a concern for this project (owner's decision), so ultralytics YOLO11 is allowed.

Things to keep in mind:

1. **egret-large already is a trained table detector** (D-FINE, DocLayNet+ classes incl. Table),
   CPU-fast and cached locally. It is the baseline the YOLO model must beat on the golden set.
2. **Detectors don't solve the column problem.** The detector only finds boxes. Columns and rows
   inside a box still come from geometry (or TableFormer on failure).
3. **YOLO's value is our own classes and our own trustees**: one box per adjacent table, plus
   `table_title` and `key_value_block`, which egret doesn't separate the way we need.

How:

- `detect/docling_layout.py` (`EgretDetector`) and `detect/yolo.py` (`YoloDetector`) both implement `Detector`.
- `review/labelstudio_export.py` exports page images plus egret boxes as **Label Studio
  pre-annotations**, so annotators correct boxes rather than draw them (about 5–10× faster).
  - Classes: `table`, `table_title`, `section_header`, `key_value_block`.
  - Rule: **every adjacent table gets its own `table` box.**
- **The golden set never enters training.** Golden docs are listed in `data/golden/manifest.yaml`
  with their sha256, and the exporter skips them.
- A few hundred corrected pages per trustee is a realistic starting point.

---

## 5. Target architecture

```
PDF ──► [1 Ingest] ──► [2 Identify trustee + format] ──► [3 Page capture: KEEP existing keyword logic]
                                                                    │ pages of interest
                                                                    ▼
         ┌──────────────────────────── per page ─────────────────────────────┐
         │ [4 Page model]   words + rules + fills (PyMuPDF)  + 1 render @~100dpi│
         │        │                                                          │
         │ [5 Detect]  A) egret-large layout boxes (Table, Section-header...) │
         │             B) geometry XY-cut regions (prototype S3/S4)           │
         │        │                                                          │
         │ [6 Reconcile] agree → high confidence; split/merge rules; disagree │
         │               → flag. Attach title/header text above each box      │
         │        │                                                          │
         │ [7 Structure] geometry inside each box (prototype S5): rows,       │
         │               gutters, header, wraps, sections → TableGrid         │
         └────────┼──────────────────────────────────────────────────────────┘
                  ▼
   [8 Stitch] multi-page / multi-section tables (prototype S7)
                  ▼
   [9 Map] per-trustee YAML: which table is which + header → canonical field
                  ▼
   [10 Validate] totals, cross-table equalities, formulas, domain rules
         │PASS                                   │FAIL
         ▼                                       ▼
   [11 Store + provenance]        [12 Escalation ladder, re-validate after each step]
                                    a) geometry retry with alternate thresholds
                                    b) TableFormer (FAST, then ACCURATE) on that box only
                                    c) vision LLM on crop + word list + JSON schema (optional)
                                    d) human review → corrections become training data
```

### Why two detectors (5A + 5B)?

- They fail differently. The model sometimes merges or splits generic layouts; geometry fails
  on ragged dashboards. **Agreement is free confidence.**
- Reconcile rules (start simple):
  - The model box contains several geometry regions whose rows don't align → split it (adjacent tables).
  - A geometry region spans 2+ model boxes → trust the model.
  - A model Section-header directly above a Table → its text becomes the table title.
  - Neither covers numeric text → orphan region, log it.
- If the model is unavailable or too slow, the system still runs on geometry alone (degraded mode).

### Escalation ladder = cost control

Expensive models run only on tables that **failed validation**, and only on that table's crop.
Target: ≥ 85–90% of tables auto-accepted at stages 7–10.

---

## 6. Component contracts (build these as interfaces)

```python
# core/types.py
@dataclass
class Word:   x0: float; y0: float; x1: float; y1: float; text: str
@dataclass
class Box:    page: int; bbox: tuple; label: str; score: float; source: str  # "egret" | "geometry" | ...
@dataclass
class TableGrid:
    page: int; bbox: tuple; title: str
    col_cuts: list[float]; header_rows: int
    cells: list[list[str]]; cell_boxes: list[list[tuple]]   # provenance per cell
    source: str; debug: dict
@dataclass
class LogicalTable: name: str; pages: list[int]; df: "pd.DataFrame"; grids: list[TableGrid]

class Detector(Protocol):          # egret, heron-onnx, geometry, fine-tuned later
    def detect(self, page: "PageModel") -> list[Box]: ...
class StructureExtractor(Protocol):  # geometry (default), tableformer, llm
    def extract(self, page: "PageModel", box: Box) -> TableGrid: ...
class Validator(Protocol):
    def check(self, table: LogicalTable, ctx: "DocContext") -> list["CheckResult"]: ...
```

Every stage must be **pure + cacheable**: key = `sha256(pdf) + page + stage + stage_version + config_hash`.
Re-running after a config change recomputes only what changed.

---

## 7. Repository layout

```
trustee-extract/
├── CLAUDE.md                      # instructions for Claude Code (short)
├── pyproject.toml
├── docs/ARCHITECTURE.md, docs/PIPELINE_GUIDE.md, docs/SETUP.md (new machine setup)
├── prototype/                     # pipeline.py, explain.py: reference only, don't import
├── src/trustee_extract/
│   ├── core/        types.py, page_model.py, cache.py, numbers.py (parse 1,234.5 / (1.0) / %)
│   ├── detect/      geometry.py, docling_layout.py (egret), yolo.py (YOLO11), reconcile.py
│   ├── structure/   geometry.py, tableformer.py, llm.py (optional)
│   ├── assemble/    stitch.py, mapping.py
│   ├── validate/    totals.py, cross_table.py, formulas.py, domain.py
│   ├── route/       ladder.py           # escalation + confidence
│   ├── review/      overlay.py, labelstudio_export.py, apply_corrections.py
│   ├── io/          export_excel.py, export_parquet.py
│   ├── doctor.py    # machine checks + worker recommendation
│   └── cli.py       # extract | explain | bench | eval | doctor | review-export
├── config/  defaults.yaml, local.example.yaml (→ local.yaml, git-ignored), trustees/{bny,usbank,wilmington,...}.yaml, schema.yaml
├── reports/ sample PDFs bny_1..3, citi_1, us_1..3 (git-ignored)
├── data/    golden/manifest.yaml + golden/<trustee>/<doc>/{expected tables}, cache/
├── train/yolo/  Label Studio → YOLO conversion (split by document), YOLO11s training script
└── tests/   unit/, golden/test_regression.py
```

Per-trustee YAML holds **text-based** matching and mapping only, never coordinates
(examples in `PIPELINE_GUIDE.md` §11.3).

---

## 8. Build plan (each task is one Claude Code session/PR)

**Task 0: Benchmark (decides everything; do first).**
On 2 docs per trustee, captured pages only, time per page on your CPU:

1. Docling full (your current settings).
2. Docling with `do_ocr=False`, TableFormer ACCURATE.
3. Same with TableFormer FAST.
4. **Layout only** (`do_table_structure=False`, `do_ocr=False`), egret-large.
5. Same, heron-onnx and egret-medium.
6. Geometry prototype.

Record s/page and **peak RAM per worker**. Try 1 and 2 worker processes × 2 threads (16 GB: max 2 Docling workers).
Output: `bench/results.csv` plus a 1-page summary.
*(Check option names against your installed Docling version: layout model selection and
`page_range` have changed across releases.)*

**Task 1: Golden set + eval harness.**
- For 2–3 docs per trustee: label table boxes on captured pages (Label Studio, or a JSON written by hand), plus expected CSVs for ~5 key tables each.
- Use historical manually keyed data where it exists.
- `cli eval` reports, per trustee: box recall/precision (IoU ≥ 0.8), cell accuracy, validation pass rate.

**Task 2: Package the prototype** into `core/`, `detect/geometry.py`, `structure/geometry.py`, `assemble/stitch.py`, `validate/totals.py`, with `defaults.yaml` thresholds. Golden tests must pass.

**Task 3: Docling layout detector + reconcile.** Add `detect/docling_layout.py` (egret-large, layout only, batched, model loaded once per worker). Add `reconcile.py`. Compare on golden: geometry-only vs model-only vs reconciled.

**Task 4: Trustee configs + mapping + validation** (cross-table, formulas, domain) for the first 3 trustees.

**Task 5: Escalation ladder.** Threshold retry → TableFormer on crop → (optional LLM) → review queue. Track how often each rung is used.

**Task 6: Review loop.** Overlay PNG + table + failed checks. Export to Label Studio with predictions. Import corrections into the golden set and training data.

**Task 7: Batch runner.** `multiprocessing` pool with `runtime.workers` (**default 1, max 2**, per `cli doctor`), one model instance per worker, page-at-a-time streaming (never whole reports in memory), cache, resumable, per-document logs, run report (auto-accept % per trustee).

**Task 8: Pluggable detector + YOLO11 (unconditional; see §4).**
- `Detector` implementations: `EgretDetector` (baseline) and `YoloDetector` (fine-tuned YOLO11 via ultralytics).
- `review/labelstudio_export.py` (done): page PNGs + egret boxes as Label Studio pre-annotations.
  Classes `table`, `table_title`, `section_header`, `key_value_block`; each adjacent table gets its own box.
  Golden docs (by sha256 in `data/golden/manifest.yaml`) are skipped.
- Later, `train/yolo/`:
  - `convert.py`: Label Studio export → YOLO format, **split train/val by document, never by page**.
    Asserts no golden sha256 is present.
  - `train.py`: YOLO11s on CPU: `imgsz≈1024`, `batch=4`, `workers=0` (Windows), `device="cpu"`.
- Accept YOLO as the default detector only if it beats egret on golden box recall/precision and nothing regresses.

---

## 9. Throughput estimate (to be replaced by Task 0 numbers)

| Stage | Per page | 4,700 pages, 1 worker × 4 threads (default) | With 2 workers × 2 threads (only if doctor allows) |
|---|---|---|---|
| PyMuPDF words + render @100 dpi | ~0.05–0.1 s | ~6 min | ~2 min |
| egret-large layout | ~0.5 s (paper) | ~40 min | ~10–15 min* |
| Geometry structure + validation | ~0.1 s | ~8 min | ~2 min |
| TableFormer on failed tables only (~10%?) | a few s/table | minutes | minutes |
| **Total** | | **~1 h** | **~15–25 min** |

Compare: current full Docling run ≈ 28 CPU-hours.
\*Depends on core count; set `OMP_NUM_THREADS` / torch threads per worker so that
workers × threads ≤ physical cores (4). **RAM is a constraint at 16 GB with ~5–6 GB free: default 1 Docling worker, max 2** (see §2c).

---

## 10. Principles (non-negotiable)

1. **Text comes from the PDF text layer, never from OCR or an LLM,** for born-digital files.
2. **Nothing is accepted without validation;** model confidence is not validation.
3. **No coordinates in config.** Match on text (titles, headers); geometry is computed per page.
4. **Every number keeps provenance** (pdf, page, cell bbox) so any value can be traced and overlaid.
5. **Measure before adding a model.** Every new component must improve golden-set metrics.
6. **Cheap first, expensive only on failure.**
