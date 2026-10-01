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
4. **3.4 Lazy translation queue** [x] — queue images near the viewport with
   `IntersectionObserver` and bounded work. Manual Chromium verification passed.
5. **3.5 Overlay renderer** [x] — place translated regions over their source
   image using the original-image coordinate contract. Manual Chromium
   verification passed.
6. **3.6 Translation feed** [x] — provide a scrollable original-and-translation
   view in reading order. Manual Chromium verification passed.
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
**3.4 COMPLETE — MANUAL VERIFICATION PASSED** ·
**3.5 COMPLETE — MANUAL VERIFICATION PASSED** ·
**3.6 COMPLETE — MANUAL VERIFICATION PASSED** (all recorded 2026-10-01).
Phase 3.7 (reliability and polish) is planned and not started.

### Phase 3.4–3.6 manual verification record

The project owner ran the Phase 3.4, 3.5, and 3.6 checks in
[`../dev/test-site/README.md`](../dev/test-site/README.md) in Chromium with the
unpacked extension loaded and reported no issues (2026-10-01): progressive
translation as images approach the viewport, overlays drawn over the source
regions and following the image on resize, the feed panel listing translated
images in page order, feed navigation and highlighting, and no retranslation on
repeat scroll or Alt+Click. Automated coverage for the same behaviour: 86
extension tests, 102 backend tests, and 13 opt-in real-model integration tests.

## Project trajectory

```text
Phase 1   — Core OCR + translation prototype          [x]
Phase 2   — Comic processing pipeline                 [x]
Phase 2.5 — Backend hardening                         [x]
Phase 3   — Chromium extension MVP                    [~]
            3.1 Extension shell + backend connection   [x]
            3.2 Comic image discovery                  [x]
            3.3 First image → backend integration      [x]
            3.4 Lazy translation queue                 [x]
            3.5 Overlay renderer                       [x]
            3.6 Translation feed                       [x]
            3.7 Reliability / performance / polish     [ ] planned
Phase 4   — Advanced reading quality                  [ ] planned
Phase 5   — Productization and general release         [ ] planned
```

```text
PHASE 3   "It works as a browser extension."
              ↓
PHASE 4   "It reads and looks like a genuinely good comic translation experience."
              ↓
PHASE 5   "Anyone can install it and use it without being a developer."
```

Milestone detail for Phase 4 and Phase 5 follows. Everything in those two phases
is **planned only** — no Phase 4 or Phase 5 work has started, and this document
does not commit to any implementation that has not been chosen and benchmarked.

## Phase 4 — Advanced Reading Quality [ ]

The purpose of Phase 4 is not to add more features. It is to improve how well
translated comics are understood, how naturally translations are placed, how
smoothly chapters are processed, and how close the result feels to a proper
translated manga/manhwa reader.

It builds on the stable Phase 3 path —

```text
discover image → lazy queue → OCR → translate → result → overlay → feed
```

— and improves the **quality** of that experience rather than its shape.

### Milestone 4.1 — Smart Typesetting [ ]

- **Solves:** the translated line is drawn into the OCR box with one fixed style,
  so longer English overflows or clips and sits unevenly inside the bubble.
- **Planned:** treat the OCR region as an available text area and fit the text
  into it — adaptive font sizing with minimum/maximum bounds, line wrapping,
  centering and vertical alignment, padding, expansion when English is longer
  than the source text, keeping text inside the image, avoiding overlap between
  neighbouring regions, narrow-bubble and long-translation handling, better
  contrast and readability, and configurable overlay styling.
- **Out of scope:** image inpainting, replacing source artwork, manual per-page
  layout tools. 4.1 stays DOM/browser rendering and must not require inpainting.
- **Next:** 4.2, which provides a better available area to typeset into.

### Milestone 4.2 — Speech Bubble / Text Area Detection [ ]

- **Solves:** OCR bounding boxes hug the glyphs, so the renderer has far less
  room than the bubble actually offers — and English usually needs more space
  than Japanese, Korean, or Chinese source text.
- **Planned:** from an OCR region, identify the surrounding speech bubble or text
  area and typeset inside it. Techniques to investigate first, simplest first:
  thresholding, contour detection, connected components, white-region detection,
  shape analysis, classical OpenCV/Pillow processing. A machine-learning detector
  is evaluated only if classical methods prove insufficient.
- **Out of scope:** mandating a heavyweight ML detector at this stage, and
  inpainting.
- **Next:** 4.3.

### Milestone 4.3 — Panel Detection and Reading-Order Reconstruction [ ]

- **Solves:** regions are ordered by geometry alone, which does not match how a
  page is actually read, so overlays and the feed can present text out of story
  order.
- **Planned:** a processing hierarchy of page → panels → bubbles/text areas →
  OCR regions → reading order; panel detection, bubble and text-region grouping,
  reading-order heuristics, layout graphs, language-aware ordering (Japanese
  manga right-to-left and top-to-bottom, webtoon/manhwa vertical progression),
  and using the reconstructed order in both the overlay and the translation feed.
- **Out of scope:** defining a final algorithm. This milestone is exploratory
  until it has been measured against real pages.
- **Next:** 4.4.

### Milestone 4.4 — Chapter / Session Architecture [ ]

- **Solves:** work is per image, so a chapter has no shared state: progress is
  lost on reload, images can be processed again, and cache reuse is incidental.
- **Planned:** a chapter/session model holding ordered images, processed and
  unprocessed state, translation results, source/target languages, image hashes
  and cache identities, progress, failures, session lifecycle, and
  revisit/reload behaviour — with chapter navigation, progress persistence, and
  better cache reuse as the visible benefits.
- **Out of scope:** accounts, cloud sync, server-side chapter storage. This
  builds on the existing backend SQLite cache and extension session state rather
  than replacing them.
- **Next:** 4.5.

### Milestone 4.5 — Advanced Performance Optimization [ ]

- **Solves:** CPU-only inference makes a realistic chapter slow, and work is
  repeated unnecessarily (preprocessing, one translation call per region, cold
  model loads).
- **Planned evaluation areas:** OCR preprocessing optimization, translation
  batching across OCR regions, persistent warm models, CPU/GPU execution options,
  model quantization, ONNX or other runtime options, parallel preprocessing, a
  cheaper auto-language mode, image-preprocessing reuse, and chapter-level
  scheduling.
- **Out of scope:** committing to ONNX, quantization, GPU inference, or another
  runtime. These are candidates; any optimization must be benchmarked before
  adoption. Performance documentation keeps reporting cold request, warm
  request, cache hit, auto mode, and explicit language separately.
- **Next:** 4.6.

### Milestone 4.6 — Context-Aware Local Translation [ ]

- **Solves:** each region is translated in isolation, so pronouns, sentences split
  across bubbles, names, honorifics, and repeated terms drift between bubbles.
- **Planned experiments:** translating with limited nearby context (previous
  bubble → current bubble → next bubble, or the previous N regions), consistent
  character terminology, and better handling of punctuation and sentence
  continuation across bubbles.
- **Out of scope:** cloud or paid translation APIs, and rewriting the rest of the
  pipeline. Local-first is a hard constraint, and no specific model change is
  promised at this stage.
- **Next:** 4.7.

### Milestone 4.7 — Native-Looking Comic Rendering / Text Cleanup [ ]

- **Solves:** English is drawn on top of the source text, so both remain visible
  and the page reads as an annotation rather than a translated comic.
- **Planned:** detect text/bubble → remove or mask the source text → reconstruct
  the background → render the translation. Start with simple cases (a plain white
  speech bubble cleared and re-drawn cleanly) and only later investigate complex
  backgrounds. Candidate techniques: solid-colour cleanup, local background
  estimation, classical inpainting, and optionally ML-based inpainting.
- **Out of scope:** generative/AI inpainting as a requirement.
- **Next:** Phase 4 completion review.

### Phase 4 order

```text
4.1 Smart Typesetting
        ↓
4.2 Bubble / Text Area Detection
        ↓
4.3 Panel + Reading Order
        ↓
4.4 Chapter / Session Architecture
        ↓
4.5 Advanced Performance
        ↓
4.6 Context-Aware Translation
        ↓
4.7 Native-Looking Rendering
```

This is the intended dependency order, not a claim that the milestones are
independent: 4.4 and 4.5 may partially overlap earlier milestones when real
performance findings require it.

### What "Phase 4 complete" means [ ]

Phase 4 is complete when the extension reliably provides an advanced reading
experience in which:

```text
comic images are detected
        ↓
translations occur progressively
        ↓
text regions are grouped and order-aware
        ↓
translations use useful surrounding layout
        ↓
English is typeset intelligently
        ↓
chapter state is preserved and reused
        ↓
performance is acceptable on realistic chapters
        ↓
local translation can use limited dialogue context
        ↓
source text can be cleanly replaced or visually suppressed in supported cases
```

This does **not** mean the product is ready for arbitrary users. That is Phase 5.

### What Phase 4 is not

Phase 4 is not cloud hosting, comic distribution, content hosting, an account
system, a social platform, DRM bypass, an automated scraping service, or a
commercial translation-API dependency. The project remains a user-side comic
translation tool.

### Local-first principle

```text
local OCR · local translation · local cache · local image processing
```

No paid or cloud provider becomes mandatory in Phase 4 or Phase 5. Optional
external providers may remain a possible future extension only when a user
explicitly configures them, and they are not part of the Phase 4 core plan.

## Phase 5 — Productization and General Release [ ]

Phase 5 means the product is functionally done and a normal user can install and
use it. It is not primarily about new research features: it takes the mature
Phase 4 system and makes it safe, installable, understandable, maintainable, and
releasable.

By the end of Phase 5, a non-developer should not need to clone the repository,
install Python, run `uvicorn`, run a local file server, edit source files, know
where Paddle models live, use DevTools, or understand OCR model internals.

### Milestone 5.1 — Production Packaging [ ]

- **Goal:** package the local backend and its runtime so users do not configure a
  Python environment by hand.
- **Planned:** Windows installer, self-contained Python runtime or packaged
  executable, backend executable, dependency packaging, a versioned application
  directory, and uninstall support.
- **Out of scope:** choosing the final packaging technology.
- **Next:** 5.2.

### Milestone 5.2 — Backend Lifecycle Management [ ]

- **Goal:** the user never runs `python.exe -m uvicorn backend.main:app`.
- **Planned:** start, stop, restart, crash detection, and health checking for the
  local backend, with a likely shape of desktop/background companion app →
  local backend → browser extension.
- **Out of scope:** fixing the final architecture; this is a Phase 5
  implementation decision.
- **Next:** 5.3.

### Milestone 5.3 — Model Setup / Model Manager [ ]

- **Goal:** a safe, explicit way to obtain the local OCR and translation models.
- **Planned:** a model inventory that reports per-language state (Japanese
  installed, Chinese installed, Korean missing, Traditional Chinese missing),
  disk-space estimates, download progress, checksum/integrity verification,
  repair/reinstall, and removal of unused models, driven by an explicit user
  action.
- **Out of scope:** silent downloads during a translation request — that stays
  forbidden, as it is today.
- **Next:** 5.4.

### Milestone 5.4 — First-Run Setup [ ]

- **Goal:** a guided first-run experience with no developer terminal.
- **Planned:** welcome → choose languages → install local models → verify backend
  → install/connect the browser extension → test translation → ready.
- **Out of scope:** automated account or cloud onboarding.
- **Next:** 5.5.

### Milestone 5.5 — Production Extension UX [ ]

- **Goal:** the Phase 3 extension UI is development/MVP quality; Phase 5 makes it
  a product UI.
- **Planned:** finalize popup, settings, error states, accessibility, status,
  onboarding, feed, overlays, language controls, and model-readiness information;
  hide development/debug UI from normal users while keeping optional developer
  diagnostics behind a deliberate debug mode.
- **Out of scope:** new translation features.
- **Next:** 5.6.

### Milestone 5.6 — Browser Distribution [ ]

- **Goal:** normal installation and distribution.
- **Planned:** Chrome Web Store and Chromium-compatible targets with a manual
  signed/unpacked fallback for development; review manifest permissions, CSP,
  packaging, icons and assets, privacy disclosure, versioning, and the extension
  update strategy.
- **Out of scope:** claiming store availability before it exists.
- **Next:** 5.7.

### Milestone 5.7 — Installer / Application Updates [ ]

- **Goal:** defined update behaviour across components.
- **Planned:** version and compatibility rules for the backend version, extension
  version, model version, and cache schema version, so an update cannot silently
  corrupt a cache or mismatch the API contract.
- **Out of scope:** automatic silent major-version upgrades.
- **Next:** 5.8.

### Milestone 5.8 — Security / Privacy Release Audit [ ]

- **Goal:** a formal audit before general release.
- **Planned:** loopback backend exposure, CORS, request limits, extension
  permissions, model downloads, cache contents, logs, optional provider keys if
  any ever exist, dependency vulnerabilities, filesystem permissions, and update
  integrity.
- **Out of scope:** any change that would make the product cloud-dependent by
  default; it remains local-first.
- **Next:** 5.9.

### Milestone 5.9 — Compatibility Testing [ ]

- **Goal:** tested behaviour on realistic sites and environments.
- **Planned matrix:** Windows 10 and Windows 11; Chrome, Edge, and other
  Chromium browsers where feasible; Japanese manga, Chinese manhua, Korean
  manhwa, webtoon long-strip layouts, traditional page layouts, dynamic readers,
  and lazy-loaded sites.
- **Out of scope:** claiming support for anything untested.
- **Next:** 5.10.

### Milestone 5.10 — Release Documentation [ ]

- **Goal:** everything a user or future maintainer needs before Phase 5
  completion.
- **Planned:** installation guide, first-run guide, troubleshooting, model
  storage information, privacy explanation, supported languages, known
  limitations, performance expectations, uninstall instructions, and developer
  documentation.
- **Out of scope:** marketing material.
- **Next:** Phase 5 completion review.

### What "Phase 5 complete" means [ ]

A normal user can use Auto Comic Translator without development knowledge:

```text
download/install application
        ↓
guided model setup
        ↓
install extension
        ↓
backend starts automatically
        ↓
open comic page
        ↓
extension detects comic
        ↓
translation works
        ↓
overlay/feed works
        ↓
cache works
        ↓
clear errors when something is unavailable
        ↓
application can be updated/uninstalled normally
```

No terminal is required for ordinary operation, no Python commands are run by
hand, no model directories are located manually, and no repository checkout is
required.

## Phase transition rules

### Phase 3 → Phase 4

Phase 4 implementation does not begin until:

```text
3.7 reliability work finished
overlay ownership stable
lazy queue stable
feed stable
real Chromium verification complete
major Phase 3 regression tests passing
```

### Phase 4 → Phase 5

Product packaging does not begin until the advanced reader itself is stable.
Phase 4 completion establishes the feature and reading-quality foundation; Phase
5 then packages and releases it.

## Privacy and out of scope

- Keep OCR and translation inference local; do not add telemetry, accounts,
  cloud inference, or paid translation providers.
- Broader API tests and browser-extension implementation remain separate
  milestones above.
- Smart typesetting, speech-bubble/text-area detection, panel and reading-order
  reconstruction, and source-text cleanup are **planned** Phase 4 milestones
  (4.1–4.3, 4.7), not out-of-scope work.
- Hosted/cloud translation, cloud deployment, content hosting, and any account
  system remain out of scope.
