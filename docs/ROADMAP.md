# Auto Comic Translator — ROADMAP

This roadmap tracks backend hardening and the later browser extension. The
project remains local-first and open source; paid translation APIs and hosted
inference are out of scope.

Status legend: `[x] done` · `[ ] planned` · `[~] in progress`

---

## Current state (Phases 1–2 — complete)

- Image preprocessing and PaddleOCR extraction.
- OCR deduplication and proximity-based text grouping.
- Local MarianMT translation.
- End-to-end orchestration, CLI, and FastAPI endpoints.

## Phase 2.5 — Backend hardening for extension clients

Overall phase status: **in progress**. Milestones 2.5.1 through 2.5.4 are
complete; milestone 2.5.5 is in progress while required Korean and
Traditional Chinese OCR assets are unavailable.

### Milestone 2.5.1 — Stable translation API and OCR language propagation [x]

- `/translate` returns `api_version`, resolved top-level source language,
  target language, original image dimensions, regions, and existing timings.
- Region output includes original and translated text, detected source
  language, OCR confidence, translation status, and a normalized `{x1,y1,x2,y2}`
  bounding box. Coordinates use original input image pixels. The prior polygon
  is retained as `bbox_points`; `confidence` remains as an alias for
  `ocr_confidence`.
- In `auto` mode, each OCR detection retains the language of its reader.
  Grouped detections use confidence-weighted dominant language, and the
  overall source language uses the same deterministic weighting. Empty OCR
  output resolves to `unknown` with an empty regions array.
- Mixed-language regions are batched by language and restored to their input
  order. Japanese, Korean, and Chinese variants select local Marian models;
  Chinese variants normalize to `zh-en` internally.
- Missing or failing local translation inference is identified by
  `translation_status: "fallback"`; the original text is returned. The API
  does not infer language from the upload filename or download MT models at
  request time.
- Focused no-inference tests and the contract are documented in
  `tests/test_phase25.py` and `docs/API.md`.

### Milestone 2.5.2 — Extension-friendly backend hardening [x]

- Standardize validation, HTTP, request parsing, and unexpected pipeline
  failures as `{"api_version","error":{"code","message","request_id"}}`;
  server details stay out of client responses.
- Keep `/health`, `/ocr`, and `/translate` unversioned, with `api_version: "1"`
  in success and error bodies. `/health` is cheap liveness; `/ready` reports
  cached OCR-reader and local translation-file readiness without model loads.
- Echo validated or generated request IDs in response headers and error bodies.
- Limit CORS to Chromium extension origins, expose the request ID header, and
  reject normal webpage origins from browser access.
- Default the module launcher to `127.0.0.1:8000`; allow validated `ACT_HOST`
  and `ACT_PORT` overrides and document the network exposure of `0.0.0.0`.
- Enforce the existing 20 MiB image limit while reading uploads and cap full
  request bodies at 21 MiB.
- Run shared synchronous inference in a worker thread, bounded by a configurable
  semaphore (default one); document cancellation behavior and log request IDs,
  endpoint, status, duration, and region counts without comic text.
- Add no-inference tests for errors, request limits and IDs, CORS, mocked
  translation compatibility, readiness, and concurrency in
  `tests/test_phase252.py`.

### Milestone 2.5.3 — Local persistent cache [x]

- Add a SQLite cache enabled by default but configurable, keyed by uploaded
  image hash, source/target languages, processing fingerprint, and cache schema
  version.
- Store successful serialized `/translate` results only. Raw image bytes are
  never written; fallback and failed results are not cached. Empty successful
  OCR results are cacheable.
- Keep timestamps and hit counts for future retention work. Automatic eviction
  is not implemented; users can inspect and clear the cache with
  `python -m backend.cache stats` and `python -m backend.cache clear`.
- Run cache tests with temporary databases and mocked inference only.

### Milestone 2.5.4 — Performance and timing instrumentation [x]

- Add a monotonic-clock `timing` breakdown to `/translate` for request-side
  validation/decode, preprocessing, OCR engine calls, grouping, translation,
  serialization, cache lookup/write, inference semaphore wait, and measurable
  OCR/translation model loading. Keep API v1 fields and cache-hit zero-inference
  behavior.
- Emit one privacy-conscious local translation performance log record per
  completed request. No OCR/translated text, image bytes, or page URLs are
  logged.
- Add `scripts/benchmark.py` for first request in process, warm repeat with
  cache disabled, and cache hit scenarios, including deterministic flat-folder
  input and aggregate statistics. It uses a temporary cache and refuses model
  downloads; JSON excludes source filenames and machine-identifying details.
- Document timing semantics, batching, cache behavior, queue wait, and the
  benchmark in `docs/API.md` and `README.md`.
- Add no-inference timing and benchmark safety/privacy tests in
  `tests/test_timing.py` and `tests/test_benchmark.py`.

### Milestone 2.5.5 — Real-model integration and final backend hardening [~]

- Add opt-in real-model translation, image pipeline, and loopback HTTP checks;
  the normal test suite skips integration tests and never loads large models.
- Guard PaddleOCR initialization and Marian model loading against implicit
  model downloads. Missing local OCR assets fail with a setup error.
- Verify a representative Japanese image, API v1 fields, source-image bounds,
  timing, cache miss/hit equivalence, CORS, request IDs, and safe HTTP errors.
- Record measured local benchmark timings in `docs/PERFORMANCE.md`.
- Three new Korean and three simplified Chinese samples are selected for
  opt-in tests. Simplified Chinese image OCR and translation pass on all three;
  Korean image inference is gated because its local PaddleOCR recognition
  files are missing. Auto-mode image checks also need the missing Korean and
  Traditional Chinese OCR assets. No model files are downloaded by tests.

## Phase 3 — Browser extension (separate from Phase 2.5)

The extension will call the local backend and map returned original-image
coordinates onto displayed images. Planned work includes:

1. Minimal Chromium Manifest V3 structure and popup settings.
2. Comic image discovery, including dynamically inserted images.
3. Viewport-aware requests with bounded concurrency.
4. Coordinate remapping on image resize and page layout changes.
5. Overlay and optional translation-feed display modes.
6. Session caching and failure handling for offline backends or missing text.

No browser-extension behavior is included in the completed Phase 2.5
milestones.

### Phase 3 backend readiness checklist

- [x] Local loopback server starts; verified by the live HTTP integration test.
- [x] `/health` responds without loading models.
- [x] `/ready` reports readiness truthfully; this environment returns `503`
  while OCR readers are unavailable.
- [x] Real Japanese image translation returns successful regions.
- [x] Real Korean and Chinese Marian translation models are available; their
  translation-only checks passed with `ok` status.
- [ ] Korean image pipeline: representative images are available, but the
  local PaddleOCR Korean recognizer's `inference.pdmodel` and
  `inference.pdiparams` files are missing.
- [x] Simplified Chinese (`zh-Hans`) image pipeline passes on three samples;
  real HTTP translation and a real-result cache miss/hit also pass.
- [ ] Real auto-language image mode: requires every configured OCR reader,
  including the missing Korean and Traditional Chinese assets.
- [x] Original-image bounding box contract verified on Japanese inference.
- [x] Real-result cache miss/hit preserves regions and reports zero hit
  inference timing.
- [x] Timing fields and cache-hit timing behavior verified.
- [x] Extension-origin CORS preflight allowed; ordinary web origin rejected.
- [x] Malformed, unsupported, empty, and oversized uploads fail safely.
- [x] OCR and Marian initialization refuse missing model assets rather than
  downloading them.
- [x] No paid or cloud inference dependency is required.
- [x] Full lightweight test suite: 75 passed, 15 opt-in integration cases
  skipped in the default run.

Phase 3 backend readiness remains **blocked by local Korean and Traditional
Chinese OCR assets**. Korean image, Korean HTTP/cache, and auto-mode image
checks could not run under the no-download rule. The extension milestone
should wait for those prerequisites.

## Privacy and out of scope

- Keep OCR and translation inference local; do not add telemetry, accounts,
  cloud inference, or paid translation providers.
- Broader API tests and browser-extension implementation remain separate
  milestones above.
- AI typesetting, speech-bubble inpainting, hosted translation, and cloud
  deployment remain out of scope.
