# trustee-extract

Extract tables from born-digital trustee reports (US Bank, Wilmington, BNY Mellon, Citi, …)
into validated, canonical data. About 233 PDFs × ~20 captured pages per cycle.
**CPU only, no GPU, Windows, 16 GB RAM with only ~5–6 GB free in practice.**
Developed on this laptop, deployed by cloning a **private GitHub repo** onto an org laptop with the same limits.
Setup on a new machine: `docs/SETUP.md`.

Full design and decisions: @docs/ARCHITECTURE.md
How the geometry engine works (stages S1–S10, thresholds): `docs/PIPELINE_GUIDE.md` (read when working on geometry)
Reference prototype (do not import, port it): `prototype/pipeline.py`, `prototype/explain.py`.
It was tuned on `reports/bny_3.pdf` (its "pages 4, 9, 10, 37" are bny_3 pages).

## Architecture in one line
Existing keyword page capture → **detector** (egret-large layout, OCR off; fine-tuned YOLO11 later)
→ **geometry split of each Table box** (XY-cut + row-alignment; fixes dashboards)
→ **geometry structure** (default, incl. long multi-page tables) → stitch → YAML mapping → validation.
**TableFormer ACCURATE runs only on dashboard pages and on tables that fail validation**, on the
(sub-)box crop → re-validate → review queue. See ARCHITECTURE.md §2c and §2d.

## Rules
- Text always comes from the PDF text layer (PyMuPDF). Never OCR born-digital pages. Docling: `do_ocr=False`.
- Never put page coordinates in config. Trustee YAML matches on text (titles, header words) only.
- Every table must pass validation (totals, cross-table, formulas, domain) to be auto-accepted.
- Expensive models (TableFormer, LLM) run only on dashboard pages or tables that failed validation, and only on that crop
  (`routing.tableformer_on` in config).
- Every extracted cell keeps provenance: pdf sha256, page (1-based), cell bbox.
- Stages are pure and cached by `sha256 + page + stage + version + config_hash`.
- Memory: **default 1 Docling worker** (`runtime.workers`); 2 only when `cli doctor` recommends it
  (free RAM ≥ ~8 GB after measuring per-worker peak). Never more than 2. Load models once per worker.
  Process one page (or one document) at a time; never load whole reports or all page images into memory.
- **No machine-specific values in code or `defaults.yaml`.** Workers, threads, models path, reports path,
  YOLO weights go in `config/local.yaml` (git-ignored) or env vars (`DOCLING_ARTIFACTS_PATH`, `TE_REPORTS_DIR`,
  `TE_WORKERS`, `TE_THREADS`, `TE_YOLO_WEIGHTS`). Read them via `core/config.py`.
- **Never commit** PDFs, outputs, caches or model weights (`.gitignore` enforces it). YOLO weights ship as
  GitHub Release assets. Dependencies are pinned by `poetry.lock`; change them only with `poetry add` on the dev machine.
- Detectors are pluggable behind `Detector` (`detect/docling_layout.py` egret, `detect/yolo.py` YOLO11).
- The golden set never goes into detector training data (split by document, golden docs excluded by sha256).
- Do not change thresholds or logic without running `cli eval` on the golden set; no golden regression allowed.

## Layout
- `src/trustee_extract/` (core, detect, structure, assemble, validate, route, review, io)
- `config/` (defaults.yaml, local.example.yaml → local.yaml git-ignored, trustees/*.yaml, schema.yaml)
- `reports/` (default `paths.reports`): the sample PDFs (git-ignored): `bny_1..3.pdf` (BNY Mellon), `citi_1.pdf` (Citi),
  `us_1..3.pdf` (US Bank; us_1/us_2 share one template, us_3 uses a different "Summary" template)
- `data/golden/` (manifest.yaml + expected tables), `data/cache/`
- `train/yolo/` (later: Label Studio → YOLO conversion, YOLO11s training); weights in `models/yolo/` (git-ignored)
- `tests/`

## Commands (Poetry; add deps with `poetry add`, dev deps with `poetry add --group dev`)
- `poetry run python -m trustee_extract.cli doctor [--measure]` → checks machine, recommends worker count
- `poetry run python -m trustee_extract.cli extract <pdf> --pages 1,4 --out out/` → CSVs + report.json (Docling for now)
- `poetry run python -m trustee_extract.cli review-export reports/x.pdf --pages 3-5` → Label Studio tasks with egret pre-annotations
- `poetry run python -m trustee_extract.cli bench reports/ --pages-from capture` → bench/results.csv (s/page, peak RAM)
- `poetry run python -m trustee_extract.cli explain <pdf> <page>`                 → stage-by-stage PNG
- `poetry run python -m trustee_extract.cli eval data/golden/`                    → per-trustee metrics
- `poetry run pytest -q` (fast) · `poetry run pytest -q -m slow` (runs real Docling models)

## Environment notes
- Developer machine: Windows (Git Bash / MINGW64). Use `pathlib`, no shell-specific paths.
- Docling 2.135 models: default `~/.cache/docling/models` (`docling.artifacts_path`; override per machine).
  Work offline: `HF_HUB_OFFLINE=1` is set by `detect/docling_layout.set_offline_env()`; never download at runtime.
- Docling 2.135 options: `PdfPipelineOptions(artifacts_path, do_ocr, do_table_structure,
  layout_options=LayoutObjectDetectionOptions.from_preset("layout_egret_large"),  # LayoutOptions is deprecated
  table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
  accelerator_options=AcceleratorOptions(num_threads, device))`. Names change across versions; check before use.
- Measured on the dev laptop (bny_1, 1 worker × 2 threads, full Docling): model load ~8 s; table pages 25–31 s/page;
  peak RAM ~1.05 GB/worker. Egret layout-only: ~2–3 s/page.
- YOLO11s training on Windows CPU: `imgsz≈1024`, `batch=4`, `workers=0`, `device="cpu"`.

## Current task (in order)
1. Golden set + eval harness (ARCHITECTURE.md §8 Task 1). Include the dashboard pages that fail today.
2. Baseline: egret-large + TableFormer ACCURATE (OCR off) on the golden set; record metrics, s/page, peak RAM per worker.
3. Port geometry (Task 2) + dashboard splitter: XY-cut inside each egret Table box, geometry structure per sub-box.
4. Validation + mapping for the first 3 trustees; TableFormer on failing sub-box crops only (mini-PDF).
5. Batch runner: `runtime.workers` (default 1, max 2), page-at-a-time, cache, resumable.
6. Detector track (Task 8): Label Studio export (done) → corrections → `train/yolo/` → YOLO11s; compare on golden.
