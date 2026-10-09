# Setup: a new machine (dev laptop or org laptop)

Both machines: Windows, CPU only, 16 GB RAM (about 5–6 GB free in practice).
The code ships through a **private GitHub repo**. PDFs, outputs, caches and model weights
never go in git; they are set up per machine as described below.

## 1. Prerequisites

- **Python 3.12.x.** `pyproject.toml` requires `>=3.12,<3.13`; the dev machine uses 3.12.10.
- **Poetry 2.x** (`pipx install poetry`, or the official installer).
- **git.** **GitHub CLI `gh`** is optional but makes downloading YOLO weights easier.

## 2. Clone and install (exact versions from `poetry.lock`)

```bash
git clone https://github.com/<org>/<repo>.git trustee-extract
cd trustee-extract
poetry env use py -3.12                     # or the full path to python 3.12
poetry config virtualenvs.in-project true   # keeps the venv in .venv/ (git-ignored)
poetry sync                                 # installs exactly what poetry.lock pins, removes extras
```

- `poetry.lock` is committed and is the single source of dependency versions.
- Never run `poetry lock` or `poetry update` on the org laptop. Change dependencies on the dev
  machine with `poetry add`, commit `pyproject.toml` and `poetry.lock` together, then pull.
- On Windows the PyPI torch wheel is CPU-only. Nothing extra is needed.

## 3. Docling models (offline at runtime)

The code sets `HF_HUB_OFFLINE=1` and never downloads models while running. It needs these folders
under the models directory (default `~/.cache/docling/models`):

```
docling-project--docling-layout-egret-large/   config.json, model.safetensors, preprocessor_config.json
docling-project--docling-models/               model_artifacts/tableformer/{accurate,fast}/...
```

Choose one option.

**A. Download once (machine with internet):**

```bash
poetry run docling-tools models download-hf-repo docling-project/docling-layout-egret-large docling-project/docling-models
```

Add `-o <dir>` to choose the folder. This needs huggingface.co access through the org proxy.
If the proxy blocks it, use option B.

**B. Copy from a machine that has them.** Copy the whole `C:/Users/<you>/.cache/docling/models`
folder (about 1 GB) by USB or a network share, to the same path or any other path.

If the folder is not `~/.cache/docling/models`, set it in `config/local.yaml`:

```yaml
docling:
  artifacts_path: D:/models/docling
```

Or set env `DOCLING_ARTIFACTS_PATH`.

## 4. YOLO weights (optional, from a GitHub Release)

Trained YOLO11 weights are published as **GitHub Release assets** on the private repo, never committed.

```bash
gh auth login                                   # once; needs access to the private repo
gh release download yolo-v1 --repo <org>/<repo> --pattern "best.pt" --dir models/yolo
```

Without `gh`: open the repo's Releases page in a browser, download `best.pt` into
`models/yolo/`, or set `yolo.weights` / env `TE_YOLO_WEIGHTS` to wherever you saved it.

To publish new weights from the dev machine:

```bash
gh release create yolo-v2 runs/detect/train/weights/best.pt --repo <org>/<repo> --notes "golden: ..."
```

## 5. Reports

Put the PDFs in `reports/` (git-ignored), or point `paths.reports` / env `TE_REPORTS_DIR` at them.

## 6. Per-machine config

```bash
cp config/local.example.yaml config/local.yaml   # git-ignored; keep only what differs on this machine
```

Precedence: `config/defaults.yaml` < `config/local.yaml` < env vars:

| Env var | Config key |
|---|---|
| `DOCLING_ARTIFACTS_PATH` | `docling.artifacts_path` |
| `TE_REPORTS_DIR` | `paths.reports` |
| `TE_WORKERS` | `runtime.workers` |
| `TE_THREADS` | `runtime.threads_per_worker` |
| `TE_YOLO_WEIGHTS` | `yolo.weights` |

## 7. Check the machine

```bash
poetry run python -m trustee_extract.cli doctor            # fast checks
poetry run python -m trustee_extract.cli doctor --measure  # also converts one real page to measure peak RAM per worker
poetry run pytest -q                                       # unit tests
poetry run pytest -q -m slow                               # real Docling run with network blocked (needs reports/bny_1.pdf)
```

`doctor` checks Python, installed versions vs `poetry.lock`, model files, offline mode, reports,
free RAM and CPU cores, and prints the recommended worker count:

- The default is **1 Docling worker** with `threads = physical cores`.
- It recommends **2** only when free RAM is at least 8 GB *and* at least 2 × the measured per-worker
  peak + 4 GB, on 4 or more physical cores.
- To use 2, set `runtime.workers: 2` in `config/local.yaml`.

## 8. Updating

```bash
git pull
poetry sync
poetry run python -m trustee_extract.cli doctor
```

## Never commit

PDFs (`*.pdf`, `reports/`), outputs (`out/`, `bench/*.csv`), caches (`data/cache/`), model weights
(`models/`, `*.pt`, `*.onnx`, `*.safetensors`, `runs/`), `config/local.yaml`. `.gitignore` enforces this.
