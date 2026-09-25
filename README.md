# Auto Comic Translator

An open-source, **local-first / self-hosted** OCR + translation pipeline for
webcomic, manga, and manhwa pages. It extracts Korean (ko), Japanese (ja), and
Chinese (zh) text from comic images, translates it to English using local
MarianMT models, and returns structured results with bounding boxes.

The long-term goal is a browser extension that performs translation seamlessly
while readers scroll through raw chapters on official sources. The current
implementation covers the complete local processing backend: image
preprocessing, OCR extraction, translation, and structured output delivery.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Image preprocessing, OCR, structured text extraction | Complete |
| Phase 2 | Local MarianMT translation, CLI tooling, API endpoints | Complete |
| Phase 2.5.1 | Stable `/translate` contract and OCR-based auto language handling | Complete |
| Phase 2.5.2 | Readiness, structured errors, CORS, request limits and IDs | Complete |
| Phase 2.5.3 | Local persistent SQLite cache | Complete |
| Phase 2.5.4 | Pipeline timing instrumentation and local benchmark | Complete |
| Phase 2.5.5 | Real-model integration and final backend hardening | In progress — see `docs/ROADMAP.md` |
| Phase 3 | Browser extension with DOM scanning and overlay rendering | Planned — see `docs/ROADMAP.md` |
| Phase 4 | Advanced typesetting, chapter-wide caching, faster inference | Planned |

## Architecture

```
Image Input (JPG/PNG)
       |
       v
Image Preprocessing (grayscale, denoise, CLAHE, adaptive threshold)
       |
       v
OCREngine (PaddleOCR — ko, ja, ch_sim, ch_tra)
       |
       v
OCRResponse (text, confidence, bounding box per region)
       |
       v
TranslationEngine (MarianMT — local pretrained models: ko->en, ja->en, zh->en)
       |
       v
FullPipelineResult (original + translated text, bbox, timing per region)
```

> Note: production OCR uses **PaddleOCR**. EasyOCR and `torchvision` are only
> referenced opportunistically and are not part of the production path; they
> are kept under `requirements-dev.txt` for experiments.

## Repository layout

```
backend/            Production application code (FastAPI + pipeline modules)
cli.py              Command-line entry point
scripts/            Development / setup utilities and local benchmark
experiments/        Prototypes, ML experiments, exploration code
tests/              Test scripts
docs/               architecture.md, technical_document.md, ROADMAP.md
extension/          Browser extension (Phase 3 — not yet implemented)
datas/              Sample comic screenshots for testing (gitignored)
models/             Local MarianMT models (gitignored)
```

### Production modules

| Module | Purpose |
|--------|---------|
| `backend/config.py` | Language mappings, model paths, preprocessing/translation/pipeline configs |
| `backend/preprocessing.py` | `ImagePreprocessor` — grayscale, bilateral denoise, CLAHE, adaptive threshold |
| `backend/ocr.py` | `OCREngine` — wraps PaddleOCR with IoU-based deduplication across language groups |
| `backend/pipeline.py` | `OCRPipeline` — preprocessing to OCR with vertical-proximity text grouping |
| `backend/translate.py` | `TranslationEngine` + `MarianMTProvider` — loads local models from `./models/` |
| `backend/full_pipeline.py` | `FullPipeline` — OCR to translation end-to-end, structured `FullPipelineResult` |
| `backend/cache.py` | Local SQLite cache, processing fingerprints, and cache management CLI |
| `backend/utils.py` | Image validation, bytes/ndarray conversion, result serialization |
| `backend/main.py` | FastAPI app (v0.2.0) — `/health`, `/ready`, `/ocr`, `/translate` |

### Pretrained models

Translation models are stored locally in `./models/` (gitignored) and are
downloaded once with:

```bash
python scripts/download_models.py
```

| Directory | Language Pair | Model |
|-----------|--------------|-------|
| `models/marian-ko-en/` | Korean to English | Helsinki-NLP/opus-mt-ko-en |
| `models/marian-ja-en/` | Japanese to English | Helsinki-NLP/opus-mt-ja-en |
| `models/marian-zh-en/` | Chinese to English | Helsinki-NLP/opus-mt-zh-en |

## Privacy & cost

- **Local-first.** OCR, translation, and image processing run on your own
  machine. Comic images never leave your machine unless you choose otherwise.
- **Free.** No paid translation API is required for core functionality. All
  components are open-source and locally hosted.
- Optional online translation providers (Google Translate via
  `deep_translator`) exist **only as experiments** under `experiments/` — they
  are never part of the production path and require no project API keys.

## Requirements

- Python 3.11+
- Virtual environment at `.venv/` with dependencies installed
- Pretrained MarianMT models in `./models/`

## Setup

```bash
# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate    # Windows
source .venv/bin/activate  # macOS/Linux

# Install production dependencies
pip install -r requirements.txt

# (Optional) dev/test dependencies for experiments and integration tests
pip install -r requirements-dev.txt

# Download pretrained translation models (one-time)
python scripts/download_models.py
```

## Usage

### CLI

```bash
# Basic: OCR + translate a comic image
python cli.py panel.jpg -s ja

# Full options
python cli.py panel.jpg -s ko -t en -j --no-group

# Arguments:
#   image          Path to JPG/PNG comic image
#   -s, --source   Source language (auto, ko, ja, zh, zh-Hans, zh-Hant)
#   -t, --target   Target language (currently en only)
#   -j, --json     Output structured JSON instead of human-readable
#   --no-group     Disable text proximity grouping
```

Example output:

```
==================================================
OCR + Translation Results
==================================================
Source: ja, Target: en
OCR: 15160ms | Translation: 12221ms
Total: 27381ms | Regions: 3
==================================================

[1] こ そ
    -> That's it.
    conf: 0.9500 | bbox: [[44, 80], [98, 80], [98, 104], [44, 104]]
```

### FastAPI server

```bash
# Start on 127.0.0.1:8000 by default
python -m backend.main

# Endpoints:
#   GET  /health      Process liveness
#   GET  /ready       OCR and local translation readiness
#   POST /ocr         Image preprocessing + OCR only
#   POST /translate   Full pipeline: OCR + translation
```

`POST /translate` accepts multipart form data with fields `image` (file),
`source_language` (string), `target_language` (string, default "en").
The API accepts images up to 20 MiB and limits the full request to 21 MiB.
Clients can send `X-Request-ID`; responses echo it for correlation. See
[`docs/API.md`](docs/API.md) for error envelopes, readiness, and CORS behavior.

The module launcher reads `ACT_HOST` and `ACT_PORT` (defaults:
`127.0.0.1` and `8000`) and `ACT_MAX_CONCURRENT_INFERENCE` (default `1`).
Setting `ACT_HOST=0.0.0.0` exposes the backend on reachable network
interfaces; configure a firewall and understand that this API has no
authentication or TLS.

Translation responses are cached locally by default in `data/cache.sqlite3`
(repository-root-relative). Set `ACT_CACHE_ENABLED=false` to disable caching or
`ACT_CACHE_PATH` to select another file. The cache stores successful structured
results, including OCR and translated text, but never raw images. Fallback and
failed results are not cached. Cache inspection and clearing are available
through `python -m backend.cache stats` and `python -m backend.cache clear`.
See [`docs/API.md`](docs/API.md) for cache identity, persistence, and timing
details.

### Local performance benchmark

`/translate` responses expose request, validation/decode, preprocessing, OCR,
grouping, translation, serialization, cache, semaphore-wait, and model-load
timings. Cache hits report zero current-request inference work. The legacy
timing fields remain for API v1 clients; exact meanings and per-region batch
timing semantics are in [`docs/API.md`](docs/API.md).

Run the benchmark with models that are already installed locally:

```bash
python scripts/benchmark.py path/to/panel.png --source ja
python scripts/benchmark.py path/to/panels --source ja --json
```

It reports a first request in the process, a warm repeat with cache disabled,
and a cache hit, with per-image results and aggregate statistics. Directory
input is flat and deterministic. Only the first image can be the first request
in the process; the JSON aggregates separate that sample from first runs for
each image. A first request may include model loading, but is not a fresh
operating-system start. The utility requires the HTTPX
development dependency, uses a temporary cache, reports neutral image labels,
and refuses to download missing OCR or translation models. It never clears the
normal persistent cache. The real Japanese CPU measurements from this checkout
are recorded in [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

The response contract is documented in [`docs/API.md`](docs/API.md). It includes
the original image dimensions, per-region detected language and OCR
confidence, and bounding boxes in original input image pixels:

```json
{
  "api_version": "1",
  "source_language": "ja",
  "target_language": "en",
  "image": { "width": 1200, "height": 1800 },
  "ocr_time_ms": 15160.0,
  "translation_time_ms": 12221.0,
  "total_time_ms": 27381.0,
  "num_regions": 3,
  "regions": [
    {
      "original_text": "...",
      "translated_text": "...",
      "confidence": 0.95,
      "ocr_confidence": 0.95,
      "bbox": { "x1": 44, "y1": 80, "x2": 98, "y2": 104 },
      "bbox_points": [[44, 80], [98, 80], [98, 104], [44, 104]],
      "source_language": "ja",
      "translation_status": "ok",
      "translation_time_ms": 12324.5
    }
  ]
}
```

## Tests

```bash
# Phase 1: OCR pipeline
python tests/test_phase1.py

# Phase 2: Full OCR + translation pipeline
python tests/test_phase2.py

# API integration test (requires server running)
python tests/api_test.py
```

> `test_phase1.py` and `test_phase2.py` need local models to run the full
> pipeline and may take significant time / downloads. They should fail clearly
> rather than silently trigger huge downloads.

## Data

Sample comic screenshots are stored in `datas/` organized by language:

- `datas/japanes/` — Japanese comic panels (tracked; a few small samples)
- `datas/korean/` — Korean comic panels (empty, expectations only)
- `datas/chinese/` — Chinese comic panels (empty, expectations only)

## Roadmap

- `docs/ROADMAP.md` — detailed Phase 2.5 and Phase 3 implementation plan.
- `docs/architecture.md` — product architecture and vision.
- `docs/technical_document.md` — technical design document.

## License

MIT License


Phase 2.5 — COMPLETE

Backend v1 is ready for Phase 3 development.

Verified with real inference:
- Japanese explicit OCR + translation
- Japanese HTTP integration
- Japanese persistent cache
- Simplified Chinese explicit OCR + translation
- Simplified Chinese HTTP integration
- Simplified Chinese persistent cache
- Japanese/Korean/Chinese local translation models

Automated:
- API v1 contract
- language propagation
- mixed-language batching
- caching
- concurrency
- CORS
- errors
- instrumentation

Known verification gaps:
- Korean real-image OCR is not yet integration-tested because the
  local Korean PaddleOCR recognizer assets are unavailable.
- Full real-image auto-mode verification is pending because Korean and
  Traditional Chinese PaddleOCR recognizer assets are unavailable.
- These are tracked validation gaps, not blockers for beginning Phase 3.