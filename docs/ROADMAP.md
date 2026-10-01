# Auto Comic Translator — ROADMAP

This roadmap tracks backend hardening and browser extension development. The
project remains local-first and open source; paid translation APIs and hosted
inference are out of scope.

Status legend: `[x] done` · `[ ] planned` · `[~] in progress`

---

## Current state (Phases 1–2.5 — complete)

- Image preprocessing and PaddleOCR extraction.
- OCR deduplication and proximity-based text grouping.
- Local MarianMT translation.
- End-to-end orchestration, CLI, and FastAPI endpoints.

## Phase 2.5 — Backend hardening for extension clients

Overall phase status: **complete**. Known Korean and full auto-mode OCR asset
gaps remain documented; they do not block Phase 3 development.

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

### Milestone 2.5.5 — Real-model integration and final backend hardening [x]

- Add opt-in real-model translation, image pipeline, and loopback HTTP checks;
  the normal test suite skips integration tests and never loads large models.
- Guard PaddleOCR initialization and Marian model loading against implicit
  model downloads. Missing local OCR assets fail with a setup error.
- Verify a representative Japanese image, API v1 fields, source-image bounds,
  timing, cache miss/hit equivalence, CORS, request IDs, and safe HTTP errors.
- Record measured local benchmark timings in `docs/PERFORMANCE.md`.
- Three new Korean and three simplified Chinese samples are selected for opt-in
  tests. Simplified Chinese image OCR and translation pass on all three. Korean
  image inference was gated because its local PaddleOCR recognition files were
  missing; those assets were installed on 2026-10-01 and the Korean tests now run
  and pass (see the validation record below). No model files are downloaded by
  tests.

### Phase 2.5 validation record

- [x] Local loopback server starts; verified by the live HTTP integration test.
- [x] `/health` responds without loading models.
- [x] `/ready` reports readiness truthfully; this environment returns `503`
  while OCR readers are unavailable.
- [x] Real Japanese image translation returns successful regions.
- [x] Real Korean and Chinese Marian translation models are available; their
  translation-only checks passed with `ok` status.
- [x] Korean image pipeline: the local `PP-OCRv5_server_det` and
  `korean_PP-OCRv5_mobile_rec` model directories were installed on 2026-10-01.
  Two Korean samples return OCR regions and Korean->English translations; the
  third is a text-free sound-effect panel and correctly returns zero regions.
- [x] Simplified Chinese (`zh-Hans`) image pipeline passes on three samples;
  real HTTP translation and a real-result cache miss/hit also pass.
- [x] Real auto-language image mode: auto uses every reader whose local model
  files are present and skips the rest. With all four readers installed, the
  opt-in auto-language propagation checks pass for `ja`, `ko`, and `zh-Hans`.
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

Korean image OCR is now verified locally (2026-10-01). Traditional-Chinese
recognition still uses the shared `PP-OCRv6` recognizer, matching upstream
PaddleOCR, so `zh-Hant` coverage is verified through that shared model rather
than a dedicated Traditional-Chinese recognizer.

## Phase 3 — Chromium extension

The extension will connect to the local backend, discover comic images, and
eventually show translated text. Work is split into these milestones:

1. **3.1 Extension skeleton and backend connection** [x] — Manifest V3 popup,
   local settings, and a version-checked `/health` request.
2. **3.2 Comic image discovery** [x] — identify candidate comic images on a
   page without sending them to the backend yet; manual Chromium verification
   passed.
3. **3.3 First image-to-backend integration** [x] — explicitly send one
   selected image to the existing API v1 and handle its translated regions.
   Manual Chromium verification passed (see the record below).
4. **3.4 Lazy translation queue** [~] — queue images near the viewport with
   `IntersectionObserver` and bounded work. Implemented with automated
   coverage; manual Chromium verification pending.
5. **3.5 Overlay renderer** [~] — place translated regions over their source
   image using the original-image coordinate contract. Implemented with
   automated coverage; manual Chromium verification pending.
6. **3.6 Translation feed** [~] — provide a scrollable original-and-translation
   view in reading order. Implemented with automated coverage; manual Chromium
   verification pending.
7. **3.7 Reliability and polish** [ ] — improve failure handling, settings,
   accessibility, and browser compatibility.

Milestones 3.1 and 3.2 are implemented and manually verified. Phase 3.3 adds
an Alt+Click development trigger, a bounded `/translate` request, and a
temporary result card. Its small service worker submits the fixed loopback
request with the extension origin accepted by the existing backend CORS
policy. The backend API v1 remains frozen for Phase 3 unless integration work
exposes a genuine compatibility defect.

### Phase 3.3 validation record

- [x] Extension loaded/reloaded unpacked in Chromium.
- [x] Backend running on `127.0.0.1:8000`; local development fixture opened.
- [x] Japanese selected as the explicit source language.
- [x] Existing Alt+Click trigger used on the Japanese comic image.
- [x] Extension sent `POST /translate`; response status was HTTP 200.
- [x] API response was version 1 with non-empty OCR/translation regions.
- [x] Temporary debug UI showed original and translated text.
- [x] Backend OCR compatibility fix works with the installed PaddleOCR 3.7.0 /
  PaddleX 3.7.2 runtime.
- [ ] Korean auto-language coverage: still gated on the missing local Korean
  and Traditional Chinese PaddleOCR assets. Not part of Phase 3.3.

### Milestone 3.4 — Lazy translation queue [~]

Phase 3.4 replaces manual-only triggering with progressive translation while
scrolling. It deliberately reuses the Phase 3.3 request path and development
presentation; overlays remain Phase 3.5.

- `extension/lib/lazy-observer.js` registers discovered candidates with an
  `IntersectionObserver` using `rootMargin: 800px 0px`, and exposes
  `observe`/`unobserve`/`disconnect`. Unobserving and re-observing an image is
  how a lazy-loaded source swap forces a fresh intersection callback.
- `extension/lib/translation-queue.js` is a dependency-free FIFO queue with
  per-image state (`idle` → `queued` → `processing` → `success`/`error`),
  `WeakMap`-based state and results, and a bounded worker pool. Concurrency is
  `MAX_CONCURRENT_TRANSLATIONS = 1` in `extension/content.js`; the queue also
  defaults to one and supports a higher bound.
- Deduplication is by queue state, so repeated observer callbacks, scrolling
  away and back, DOM mutations, and repeated pump passes cannot duplicate a
  request. A successful image is terminal for the page session; an errored
  image is terminal for automatic queueing (no retry storm) but can be retried
  by an explicit Alt+Click.
- Detached and ineligible images are skipped at both enqueue and dequeue time
  without holding a worker slot. `forget()` invalidates in-flight work when an
  image's source changes, and `reset()` (used when the translator is disabled)
  cannot leave counters negative or above the bound.
- The successful API v1 result is stored per image (`{status, result}`) for
  Phase 3.5 to consume; no coordinates are transformed and no overlays are
  rendered yet.
- Automatic results reuse the Phase 3.3 debug card in a collapsed `<details>`
  form; Alt+Click keeps the full card. Queue events (`observed`, `queued`,
  `processing`, `completed`, `failed`, `skipped`, `reused`) are logged with
  state, manual flag, reason, and request IDs only — never image bytes, OCR
  text, or translated dialogue.
- Failures (image fetch, timeout, backend offline, HTTP/API errors, malformed
  responses) release the worker slot and never block following images. There
  are no automatic retries.
- Coverage lives in `tests/extension/` and runs on Node's built-in test runner
  with a stubbed translation client: queue lifecycle, deduplication, bounded
  concurrency, failure isolation, observer registration, viewport queueing,
  dynamic/lazy-loaded images, detached images, and Alt+Click interaction.

### Auto-mode OCR reader availability (backend fix during 3.4 verification)

Auto mode previously resolved to every configured language and initialized each
reader eagerly, so a missing Korean `PP-OCRv5_server_det` local model aborted an
otherwise valid Japanese request with a `FileNotFoundError` and a generic 500.

- `backend/ocr.py` gained `is_reader_available(language)` (filesystem only, no
  reader construction, no download) and `OCREngine.available_auto_languages()`.
- `source_language=auto` now uses the readers whose local model files are
  complete and skips the rest, logging which readers were skipped. The existing
  confidence-weighted dominant-language logic is unchanged.
- An explicit `source_language` keeps its strict setup error, and a
  `FileNotFoundError` raised while initializing an auto-mode reader is skipped
  rather than failing the request. Unrelated inference errors (`TypeError`,
  `RuntimeError`, `ValueError`) are still never swallowed.
- Zero available readers raises `OCRSetupError`, which `backend/main.py` maps to
  a controlled `503 OCR_READERS_UNAVAILABLE` response instead of a generic 500;
  local model paths stay in the server log.
- `GET /ready` adds `ocr_languages` (the readers auto mode will use), computed
  without initializing anything.
- Regression coverage is in `tests/test_phase3_ocr_auto.py` (12 tests).
- Real local verification: with only `ja`/`zh`/`zh-Hant` installed, a real
  `POST /translate` with `source_language=auto` returned HTTP 200, API v1,
  resolved source `ja`, and two translated regions instead of the previous 500.
  The Korean reader (`PP-OCRv5_server_det` + `korean_PP-OCRv5_mobile_rec`) was
  installed locally on 2026-10-01, so `/ready` now reports all four languages and
  the opt-in Korean explicit/auto integration checks pass.
- Caveat now that Korean runs in auto: the Korean recognizer also runs on
  non-Korean pages and can contribute a low-confidence region carrying a
  Korean-labelled translation (observed on a Japanese sample). Use an explicit
  source language when the page language is known; the global confidence
  threshold was deliberately left unchanged here.

### Milestone 3.5 — On-image overlay renderer [~]

Phase 3.5 renders translated regions over the original comic image. It is
browser rendering only: no OCR/translation is repeated, and the bitmap is never
modified (no canvas, no inpainting).

- `extension/lib/overlay-renderer.js` owns creation, coordinate mapping,
  resize handling, and cleanup. Networking and queue logic stay in
  `content.js` / `translation-queue.js`.
- Anchoring: one `position: absolute` layer inserted as a sibling immediately
  after the image, so it shares the image's containing block and scrolls with
  the page without per-scroll measurement. Page layout is never modified (no
  wrapper elements).
- Coordinate mapping scales the API's original-image `bbox` against the
  rectangle where the browser draws the bitmap: the element's content box plus
  `object-fit` handling for `fill`, `contain`, `cover`, `none`, and
  `scale-down`. `cover`/`none` cropping is clipped to the visible element box,
  and a region that is entirely cropped is skipped rather than misplaced.
- Bounds: non-finite, negative, zero-size, reversed, or out-of-range coordinates
  and malformed regions are skipped, never rendered outside the image.
- `ResizeObserver` repositions existing overlays when the image changes size;
  there is no `requestAnimationFrame` measurement loop and no retranslation.
- Fallback decision: regions with `translation_status: "fallback"` (untranslated
  original text) are **not** drawn over the image; the collapsed debug card still
  reports them so the failure stays visible.
- Lifecycle: overlays are created only after a validated success, one layer per
  image (repeated observer events and Alt+Click reuse it), a source change
  removes the stale overlay before rediscovery, removing the image removes its
  overlay, resize observation, and debug card, and disabling the translator
  removes overlays immediately. Completed results are kept across a
  disable/enable cycle (`translationQueue.reset({ keepResults: true })`), so
  re-enabling restores overlays without retranslating.
- Text safety: translated text is inserted with `textContent` only.
- The popup gained a **Show translations on image** switch (default on) that
  hides or restores overlays without retranslating. The Phase 3.3 debug card is
  kept but always collapsed so it is not the final reading experience.
- Coverage: 16 renderer tests plus content-script integration tests in
  `tests/extension/`.

### Milestone 3.6 — Translation feed and chapter fixture [~]

Phase 3.6 adds a secondary reading mode over the same per-image results the
overlay uses, plus a fixture big enough to exercise it.

- `extension/lib/translation-feed.js` owns the panel: shell creation,
  entry insert/update, reading order, active highlighting, and cleanup. It never
  performs OCR, translation, or fetching, and it never changes page layout (a
  `position: fixed` panel with its own styles, not a wrapper around the reader).
- Reading order is DOM order (live `document.images` index), so images that
  finish out of order still read in page order; an image inserted between two
  existing ones takes the middle position. Region order stays the backend order.
- One entry per image, deduplicated through a `Map` keyed by the image element;
  repeated completions, Alt+Click, re-entry, or a retry update the same entry.
  Entries are created whether or not the panel is open, and opening later shows
  everything already translated.
- Entry content is user-facing only: index, language pair, region summary, and
  each region's original and translated text. Request IDs, timings, bounding
  boxes, and model names are deliberately excluded.
- Clicking an entry header calls `image.scrollIntoView({behavior: "smooth",
  block: "center"})` and never retranslates. There is no feed auto-scroll, so
  there is no scroll feedback loop.
- `fallback` regions are marked "Translation unavailable — showing original
  text" rather than presented as English; failed images get a compact
  "Translation unavailable" entry with no backend error text, which a later
  manual success replaces in place.
- Prerequisite repair: source-language and backend-URL changes now invalidate
  overlays, feed entries, and stored per-image results together
  (`invalidateTranslations`), so the two views cannot diverge and images become
  eligible again under the new identity.
- `dev/test-site/` was expanded into a chapter-like fixture: nine candidate comic
  images across Japanese/Chinese/Korean sections, a duplicate-source case, a
  responsive case, a narrow-display case, an explicit lazy-source replacement,
  an intentionally broken image, a tiny raster, the existing SVG negatives, the
  hidden image, and below-threshold real crops as documented negatives.
- Coverage: 18 feed tests, 10 content-script feed integration tests, and a static
  fixture inventory test (86 extension tests total).
- Contract repair found while checking the pinned environment: an explicitly
  requested language whose local model files are missing used to surface as a
  generic `500`. It now raises `OCRSetupError` and returns
  `503 OCR_READERS_UNAVAILABLE`, so a missing model set is distinguishable from a
  server fault. The detail stays in the server log.

### Auto-mode optimization and final verification pass

Two measured problems in auto mode were fixed after Phase 3.6:

- **Redundant OCR passes.** `ja`, `zh`, and `zh-Hant` all resolve to the same
  `PP-OCRv6` model files, so auto ran that model set three times for identical
  text. `_reader_model_signature()` groups languages by the local model set they
  would load and auto now runs each distinct set once. Measured with the cache
  disabled on a Chinese sample: wall time 49.6 s → 15.0 s, OCR 33.4 s → 12.6 s.
- **Wrong language identity.** Because the shared recognizer was labelled with
  its reader key, auto reported `source_language: ja` for a Chinese page and
  translated it with the Japanese model. Regions are now labelled from the script
  of the recognized text (Hangul → `ko`, kana → `ja`, Han → `zh`), and
  script-less lines take the page's dominant language so short misreads cannot
  outvote real text. A Japanese sample that previously resolved to `ko` (the
  Korean reader's junk fragment outvoted the Japanese text) now resolves to `ja`.
  Explicit source languages are never relabelled.

Verification of this pass: `pytest` 102 passed / 15 skipped, extension tests 86
passed, `compileall` clean, `git diff --check` clean, and all 13 opt-in
real-model integration tests pass (run per group, see
[`../README.md`](../README.md) known gaps for the native PaddleX fault that
prevents a single-process run on this machine).

Phase status: **3.3 COMPLETE — MANUAL VERIFICATION PASSED** ·
**3.4 IMPLEMENTED — MANUAL VERIFICATION PENDING** ·
**3.5 IMPLEMENTED — MANUAL VERIFICATION PENDING** ·
**3.6 IMPLEMENTED — MANUAL VERIFICATION PENDING**.

## Privacy and out of scope

- Keep OCR and translation inference local; do not add telemetry, accounts,
  cloud inference, or paid translation providers.
- Broader API tests and browser-extension implementation remain separate
  milestones above.
- AI typesetting, speech-bubble inpainting, hosted translation, and cloud
  deployment remain out of scope.
