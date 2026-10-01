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
| Phase 2.5.5 | Real-model integration and final backend hardening | Complete — known OCR asset gaps are documented |
| Phase 3.1 | Chromium extension skeleton and backend connection | Complete — see `docs/ROADMAP.md` |
| Phase 3.2 | Comic image discovery | Complete — manual Chromium verification passed |
| Phase 3.3 | Explicit image translation round trip | Complete — manual Chromium Alt+Click round trip verified; PaddleOCR 3.x compatibility fixed |
| Phase 3.4 | Lazy translation queue (`IntersectionObserver`, bounded to one request) | Implemented — automated tests pass; manual Chromium verification pending |
| Phase 3.5 | On-image overlay renderer for translated regions | Implemented — automated tests pass; manual Chromium verification pending |
| Phase 3.6 | Translation feed (reading-order panel) and expanded chapter fixture | Implemented — automated tests pass; manual Chromium verification pending |
| Phase 3.7 | Reliability and polish | Planned — see `docs/ROADMAP.md` |
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
extension/          Chromium Manifest V3 extension (Phases 3.1–3.6)
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

## Development

### Load the Chromium extension

1. Start the backend from the repository root with
   `.\.venv\Scripts\python.exe -m backend.main`.
2. Open `chrome://extensions` in Chrome or Chromium.
3. Turn on **Developer mode**.
4. Choose **Load unpacked** and select this repository's `extension/` folder.
5. Open the Auto Comic Translator popup from the browser toolbar.
6. Confirm the backend status shows **Backend connected**.

The popup saves local preferences and checks the backend.

**Phase 3.3 — explicit trigger.** Alt+Click an outlined comic candidate to send
that single image to `POST /translate` and show a temporary debug card with the
original and translated text. Manual Chromium verification of this round trip
passed: the extension sent `POST /translate`, the response was HTTP 200 with
`api_version: "1"` and non-empty regions, and the debug card showed the
original and translated text for a real Japanese sample.

**Phase 3.4 — lazy translation queue.** Discovered candidates are registered
with an `IntersectionObserver` (`rootMargin: 800px 0px`) and queued as they
approach the viewport, so translation starts shortly before you scroll to them.
Work is bounded to `MAX_CONCURRENT_TRANSLATIONS = 1` in
`extension/content.js`, processed first-in-first-out, and deduplicated per
image: an image that already succeeded, is queued, or is processing is never
translated twice. Alt+Click remains a development trigger that reuses the same
translation path.

**Phase 3.5 — on-image overlay.** A successful result is rendered over the
original comic image by `extension/lib/overlay-renderer.js`: one absolutely
positioned layer per image and one element per translated region, mapped from
the API's original-image `bbox` values onto the rectangle where the browser
actually draws the bitmap (including `object-fit: contain`/`cover`). The bitmap
is never modified — no canvas, no inpainting. `ResizeObserver` repositions the
overlays when the image changes size, scrolling moves image and overlay
together, malformed or out-of-range regions are skipped, `translation_status:
"fallback"` regions are not drawn (the debug card still reports them), and
translated text is always inserted as text, never as markup. The popup's
**Show translations on image** switch hides or restores overlays without
retranslating.

**Phase 3.6 — translation feed.** `extension/lib/translation-feed.js` renders a
collapsible panel (bottom-right **Feed** button) listing every translated image
in DOM reading order, one entry per image with its language pair, a region
summary, and each region's original and translated text. It is a view over the
same stored results the overlay uses — it never OCRs, translates, or fetches
anything — so entries appear whether or not the panel is open at translation
time. Clicking an entry header scrolls its comic image into view; the entry for
the image crossing the middle of the viewport is highlighted; `fallback` regions
are marked "Translation unavailable — showing original text" instead of being
presented as English; failures get a compact "Translation unavailable" entry
that a later manual retry replaces in place. Changing the source language or
backend URL invalidates overlays, feed entries, and stored results together, and
disabling the translator removes both.

### Test image discovery

From the repository root, run `python -m http.server 8080 --bind 127.0.0.1`
and open `http://127.0.0.1:8080/dev/test-site/`. The fixture uses local sample
images; orange outlines mark candidates and a dashed amber outline marks a
queued or in-flight image. Select **Japanese** in the popup and scroll toward
the first Japanese sample to watch it translate automatically, or Alt+Click it
to trigger the same request manually. Translated regions are drawn over the
image as soon as a validated result arrives. The content script is limited to
the exact `127.0.0.1` host. See [`dev/test-site/README.md`](dev/test-site/README.md)
for the full manual check.

The Phase 3.3 backend OCR compatibility fix supports PaddleOCR 2.x and 3.x.
A real Japanese image returned OCR regions, and a real `POST /translate`
request returned valid API v1 JSON. Phase 3.4's browser behaviour is verified by
the automated extension tests below; the manual Chromium scroll check is still
pending. See [`docs/HANDOFF.md`](docs/HANDOFF.md) for results and the current
checkpoint.

### Extension tests

The Phase 3.4 queue, observer, content-script wiring, the Phase 3.5 overlay
renderer, and the Phase 3.6 feed have dependency-free tests that run on Node's
built-in test runner. They stub the translation client, so no backend is
contacted and no models are loaded:

```bash
node --test "tests/extension/*.test.js"
```

Coverage includes queue lifecycle and deduplication, bounded concurrency,
failure isolation, viewport queueing, dynamic and lazy-loaded images, detached
images, Alt+Click interaction, coordinate mapping (including non-uniform scaling
and `object-fit`), bounds validation, overlay deduplication, resize
repositioning, cleanup, safe text insertion, feed shell/entry rendering, reading
order under out-of-order completion, feed navigation and active highlighting,
settings and source invalidation, and a static inventory check of the
`dev/test-site/` fixture.

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

`source_language=auto` runs the OCR readers whose local model files are
installed and skips the ones that are not, so a partial local installation still
translates instead of failing. Choosing a language explicitly stays strict and
reports a controlled setup error when its models are missing; `GET /ready` lists
the readers auto mode will use in `ocr_languages`. No request ever downloads a
model.

Two rules make auto mode both cheaper and more accurate:

- **One pass per distinct model set.** Upstream PaddleOCR ships a single
  `PP-OCRv6` recognizer for Japanese, Chinese, and Traditional Chinese, so
  `ja`, `zh`, and `zh-Hant` resolve to the same files. Auto runs that model set
  once instead of once per language. Measured on this machine with the cache
  disabled, a Chinese sample went from 49.6 s to 15.0 s wall time (OCR 33.4 s to
  12.6 s).
- **The language comes from the text, not the reader.** Readers are chosen by
  which models are installed, so the reader key is not a detection result. The
  script of each recognized line names the language (Hangul → `ko`, kana → `ja`,
  Han → `zh`), and a line with no identifiable script (a digit, a Latin fragment)
  takes the page's dominant language so a short misread cannot outvote real text.
  Before this, auto on a Chinese page reported `source_language: ja` and
  translated with the Japanese model. Han-only text cannot distinguish Simplified
  from Traditional Chinese and resolves to `zh`; select `zh-Hant` explicitly for
  Traditional text.

An explicit source language is never relabelled by these rules.

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
- Korean real-image OCR and full auto-language image mode were previously
  gated on missing local PaddleOCR assets. The Korean recognizer
  (`PP-OCRv5_server_det` + `korean_PP-OCRv5_mobile_rec`) was installed locally on
  2026-10-01; Korean explicit OCR, Korean auto detection, and Korean->English
  translation now pass the opt-in integration tests on this machine.
- Auto mode only needs the readers whose local model files are present, so a
  partial installation still works; see `docs/API.md`. Auto resolves the source
  language from the script of the recognized text, so Han-only pages resolve to
  `zh` (Simplified) and Traditional Chinese should be selected explicitly.
- `datas/korean/Screenshot 2026-09-26 015554.png` is a sound-effect panel with no
  OCR-readable text, so it is expected to return zero regions.
- The 13 opt-in integration tests all pass, but the file cannot run as a single
  pytest process on this machine: after several Paddle model sets have been
  exercised in one process, PaddleX's native inference runner faults with a
  Windows access violation. Each test passes when it runs in its own process.
  Run them per group, for example:

  ```bash
  python -m pytest tests/integration/test_real_pipeline.py -m integration \
    -k "explicit_language_pipeline and ko"
  ```

  This is a native limitation of the local Paddle build, not a backend defect:
  the served app builds its readers once and handled repeated auto requests
  (both model families) in one process during the measurements above.
- These are tracked validation details, not blockers for Phase 3.
