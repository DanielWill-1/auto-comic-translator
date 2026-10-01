# Project handoff

Checkpoint: 2026-10-01

## Current state

- Phases 1, 2, and 2.5 are complete. Phase 3.1 (extension shell and backend
  connection), Phase 3.2 (comic image discovery), and Phase 3.3 (explicit
  Alt+Click translation round trip) are complete and manually verified. See
  [`ROADMAP.md`](ROADMAP.md) for the phase plan.
- **Phase 3.4 (lazy translation queue), 3.5 (overlay renderer), and 3.6
  (translation feed) are complete.** Each has automated coverage, and the project
  owner ran the browser checks in `dev/test-site/README.md` with no issues
  (recorded 2026-10-01).
- Phase 3.7 (reliability and polish) is planned and not started.
- Phase 4 (advanced reading quality) and Phase 5 (productization and general
  release) are **planned only** — see [`ROADMAP.md`](ROADMAP.md). Do not begin
  either until the Phase 3 → Phase 4 gate in that document is met.

## Future phases

Phase 4 — advanced reading quality: smart typesetting, speech-bubble/text-area
detection, panel and reading-order reconstruction, chapter/session state,
advanced performance work, context-aware local translation, and native-looking
rendering.

Phase 5 — productization and general release: packaging, backend lifecycle
management, model manager, first-run setup, production extension UX, browser
distribution, updates, security audit, compatibility testing, and release
documentation.

Both are planning entries in [`ROADMAP.md`](ROADMAP.md), which holds the
milestone detail, completion definitions, and transition rules. No Phase 4 or
Phase 5 code, module, dependency, or test exists yet.

## Auto-mode OCR fix (the reported failure)

Root cause: `source_language=auto` resolved to every language in
`OCREngine.SUPPORTED_LANGS` and initialized each reader eagerly. The Korean
reader's local `PP-OCRv5_server_det` model is absent on this machine, so
`_require_local_paddlex_model` raised `FileNotFoundError` before Japanese OCR
could run, and the request failed with a generic 500.

Fix, in `backend/ocr.py` and `backend/main.py`:

- `is_reader_available(language)` decides availability from local files only
  (no reader construction, no download) and `OCREngine.available_auto_languages()`
  exposes the result.
- Auto mode uses the installed readers and skips the rest, logging which were
  skipped; the confidence-weighted dominant-language logic is unchanged.
- An explicit `source_language` stays strict, and unrelated inference errors are
  still never swallowed.
- Zero usable readers raises `OCRSetupError`, which maps to a controlled
  `503 OCR_READERS_UNAVAILABLE` response with a safe message.
- `GET /ready` gained the additive `ocr_languages` field.

Evidence from this machine (real local Paddle runtime, no downloads):

- `/ready` → `{"ocr_ready": false, "translation_ready": true,
  "ocr_languages": ["ja", "zh", "zh-Hant"]}` at the time of the fix (Korean was
  not installed yet; see below).
- Real `POST /translate` with `source_language=auto` on
  `datas/japanes/Screenshot 2026-06-29 122805.png` → HTTP 200, `api_version` 1,
  resolved `source_language` `ja`, 2 regions, both `translation_status: "ok"`.
- Direct pipeline run confirmed `ko: False`, `ja: True`, `zh: True`,
  `zh-Hant: True` for local reader availability.

Note: `ja`, `zh`, and `zh-Hant` currently resolve to the same shared
`PP-OCRv6_medium_det`/`PP-OCRv6_medium_rec` files, so auto mode constructs three
equivalent readers. That is pre-existing model-name mapping (and matches
upstream PaddleOCR's own table), not introduced here; it costs extra OCR passes.
Measured on this machine: warm auto request ~14 s on a small sample, ~38 s on the
first request in a process; a 108 s reading was observed under heavy CPU
contention while models were being installed, so auto can be slow but stays
inside the extension's 60 s timeout in normal conditions.

### Korean OCR installed (2026-10-01)

The user authorised a one-time out-of-band install. Both model directories were
downloaded directly by PaddleOCR (not through the project, whose code still
refuses to download anything) into
`C:\Users\danie\.paddlex\official_models\`:

- `PP-OCRv5_server_det`
- `korean_PP-OCRv5_mobile_rec`

Verified after the install:

- `is_reader_available` → `{ko: True, ja: True, zh: True, zh-Hant: True}`.
- `/ready` (no restart needed) → `"ocr_languages": ["ko","ja","zh","zh-Hant"]`.
- Explicit Korean: `POST /translate` with `source_language=ko` on
  `datas/korean/Screenshot 2026-09-26 015537.png` → HTTP 200, 3 regions, all
  `ok`, e.g. `그날도` → "And that day.", `평화로운 오후였다` → "It was a peaceful
  afternoon."
- Auto: the same image with `source_language=auto` → HTTP 200, resolved `ko`,
  same 3 translated regions. Korean is therefore detected by auto as well.
- Opt-in integration tests: `pytest tests/integration/test_real_pipeline.py -m
  integration -k ko -q` → **5 passed** (Korean translation model, three Korean
  explicit-language image pipelines, Korean auto-language propagation).

Finding: `datas/korean/Screenshot 2026-09-26 015554.png` is a text-free
sound-effect panel. Its only detection recognises as an empty string with
confidence 0.0 (the Japanese reader reads it as "A" at 0.086), so the pipeline
correctly returns zero regions. That sample is now recorded in the integration
test as `TEXT_FREE_SAMPLES` with an empty-result expectation.

Caveat: now that the Korean reader runs in auto mode, it also runs on
non-Korean pages and can contribute a low-confidence, Korean-labelled region
(observed on a Japanese sample, translated through the Korean model). Use an
explicit source language when the page language is known. The global OCR
confidence threshold was deliberately not changed.

## Phase 3.4 and 3.5 implementation

Phase 3.4 (`extension/lib/lazy-observer.js`, `extension/lib/translation-queue.js`,
`extension/content.js`): `IntersectionObserver` registration with
`rootMargin: 800px 0px`, a FIFO queue with per-image state, deduplication,
`MAX_CONCURRENT_TRANSLATIONS = 1`, skip-on-detach, no automatic retries, one
shared `translateCandidate(image)` path for the lazy queue and Alt+Click, and
per-image storage of the validated API v1 result.

Phase 3.5 (`extension/lib/overlay-renderer.js`): one absolutely positioned
overlay layer per translated image, one element per region, mapped from the
API's original-image `bbox` onto the drawn bitmap rectangle (element content box
plus `object-fit` `fill`/`contain`/`cover`/`none`/`scale-down` handling).
`cover`/`none` cropping is clipped to the visible box and fully cropped regions
are skipped. Malformed, negative, zero-size, reversed, or out-of-range
coordinates are skipped. `ResizeObserver` repositions overlays without
retranslating, the layer scrolls with the image, `fallback` regions are not
drawn (the collapsed debug card still reports them), and text is inserted with
`textContent` only. Source changes, image removal, and disabling the translator
all remove the overlay and its observation. Completed results survive a
disable/enable cycle (`translationQueue.reset({ keepResults: true })`), so
re-enabling restores overlays without new requests. The popup gained a **Show
translations on image** switch (default on).

## Phase 3.6 implementation

`extension/lib/translation-feed.js` adds the secondary reading mode. It is a view
over the per-image results the Phase 3.4 queue already stores, so no result is
computed twice:

- Collapsible panel (`Feed` button, bottom-right; `×` to close), fixed and
  page-overlaying, so the comic reader's layout is never changed or reflowed.
- One entry per translated image in DOM reading order (`document.images` index),
  independent of completion order; region order follows the backend response.
  `Map`-keyed deduplication means repeated completions, Alt+Click, re-entry, or a
  retry reuse the same entry.
- Entry content: image index, language pair, region summary, and each region's
  original and translated text. Request IDs, timings, bboxes, and model names are
  excluded. All strings go through `textContent`.
- Active entry highlighting follows the image crossing the middle of the
  viewport (`rootMargin: -45% 0px -45% 0px`). Clicking an entry header scrolls
  its image into view and never retranslates. Feed auto-scroll was deliberately
  not implemented, so there is no scroll feedback loop.
- `fallback` regions are labelled "Translation unavailable — showing original
  text"; failed images get a compact "Translation unavailable" entry with no
  backend error text.
- Lifecycle: source changes and removals drop the entry, disabling the translator
  destroys the panel, re-enabling restores overlays and entries from the stored
  results without new requests.

Prerequisite repair made for Phase 3.6: `invalidateTranslations()` now runs when
the source language or backend URL changes, dropping stored results, overlays,
and feed entries together. Previously a language switch left stale overlays and
results on the page, which would have made the feed diverge from the overlay.

The fixture (`dev/test-site/`) is now a chapter-like page: Japanese (4),
Chinese (3), and Korean (2) candidate sections, a duplicate-source pair, a
responsive case, a narrow-display case, an explicit lazy-source replacement
button, an intentionally broken image, a 32×24 tiny raster, the existing SVG
negatives, the hidden image, and below-threshold real comic crops as documented
negatives. `tests/extension/fixture-inventory.test.js` statically verifies that
every referenced file exists (except the intentional broken source) and that the
required cases are present.

## Environment split worth knowing

`requirements.txt` pins `paddleocr==2.9.1`, and the project venv has that version
(its local models live in `~/.paddleocr/whl`, which currently has `det` for
`ch`/`en`/`ml` and `rec` for `ch`/`en`/`japan`). A second interpreter on this
machine — the global Python 3.11 — has PaddleOCR 3.7 with the local PaddleX
models in `~/.paddlex/official_models` (`PP-OCRv6_medium_det/rec`,
`PP-OCRv5_server_det`, `korean_PP-OCRv5_mobile_rec`).

Consequences, measured on this machine:

- Under the venv (2.9.1): `/ready` reports `ocr_languages: ["ja","zh"]`, and a
  request for `ko` (or `zh-Hant`) returns **503 `OCR_READERS_UNAVAILABLE`**
  because the 2.x Korean/Traditional-Chinese recognizer files are not installed.
  `auto` and explicit `ja` still return 200.
- Under the global Python (3.7): all four languages are reported and Korean
  round-trips end to end.

So the Korean install described above serves the 3.x environment. Making Korean
work under the pinned 2.9.1 environment needs the matching 2.x recognizer assets
installed out-of-band; the app never downloads models at request time in either
case.

Measured on 2026-10-01: a backend started fresh with the 3.7 interpreter on a free
port reports `status: ready`, `ocr_ready: true`, and
`ocr_languages: ["ko","ja","zh","zh-Hant"]`, and Korean round-trips through
`/translate`. A backend that has been running on this machine since before the
Korean models were installed keeps serving the 2.9.1 model set
(`ocr_languages: ["ja","zh"]`, Korean → 503). Restart such a backend with the
interpreter that has the models.

### Native PaddleX fault when many models run in one process

The opt-in integration file cannot run as a single pytest process here: after
several Paddle model sets have been built in one process, PaddleX's static runner
faults with a Windows access violation (`exit=139`). Every test passes when it
runs in its own process. The test helper now builds one pipeline per process,
mirroring the app, which fixed the Korean group; the auto group still needs
per-group invocation. Recommended commands:

```bash
python -m pytest tests/integration/test_real_pipeline.py -m integration \
  -k "test_real_local_translation_model"
python -m pytest tests/integration/test_real_pipeline.py -m integration \
  -k "explicit_language_pipeline and ko"
python -m pytest tests/integration/test_real_pipeline.py -m integration \
  -k "test_real_auto_language_propagation"
```

The served app is not affected: it builds its readers once and handled repeated
auto requests covering both model families in one process.

## Automated checks

- Extension tests: `node --test "tests/extension/*.test.js"` → **86 passed, 0
  failed** (queue, observer, content-script integration, overlay renderer,
  translation feed, fixture inventory).
- `pytest` → **102 passed, 15 skipped, 3 warnings** (skips are the opt-in
  real-model integration tests). Includes 17 auto-mode OCR tests in
  `tests/test_phase3_ocr_auto.py`: reader selection, skip semantics, the
  503-not-500 contract for an explicitly requested language, one pass per shared
  model set, and script-based language labelling.
- Opt-in integration tests (`-m integration`, run per group): **13 passed**. The
  file cannot run as one process on this machine — see the native PaddleX fault
  in the environment section below.
- `python -m compileall backend scripts` → passed.
- `git diff --check` → clean (only CRLF conversion warnings).
- No model downloads occurred.

## Real verification performed

- Real local OCR + translation through `POST /translate` with `auto` (above).
- The real response payload was fed through the overlay renderer geometry: a
  436 × 654 image displayed at 300 × 450 produced one layer and two regions at
  `27.5/30.3/244.3×90.8` and `17.9/168.6/245.0×73.6` px, both inside the image.

## Manual Chromium verification NOT performed

The browser harness on this machine could not attach: it requires interactive
"Allow remote debugging" approval in Chrome and the extension cannot be loaded
into a browser the harness starts. Two connection attempts were refused, so no
browser result is claimed. The servers were prepared for the check: a backend
running the fixed code is listening on `127.0.0.1:8000` (a stale backend from
the earlier session, which served the old code, was stopped), and the fixture is
served on `127.0.0.1:8080`.

## Environment and known limits

- Local PaddleX models present: `PP-OCRv6_medium_det`, `PP-OCRv6_medium_rec`,
  `PP-OCRv5_server_det`, `korean_PP-OCRv5_mobile_rec`, plus document/textline
  orientation models. Traditional Chinese is served by the shared `PP-OCRv6`
  recognizer (matching upstream PaddleOCR); there is no dedicated
  Traditional-Chinese recognizer installed.
- `/ready` still reports `ocr_ready: false` until every reader has been
  initialized in the `/ocr` pipeline process, which is the documented meaning of
  that flag; `ocr_languages` and auto-mode requests work regardless.
- Overlay typesetting is MVP: text may overflow its original OCR box for
  readability, and there is no bubble detection, inpainting, font matching, or
  curved text. These are planned Phase 4 milestones (4.1 typesetting, 4.2 bubble
  detection, 4.7 source-text cleanup), not Phase 3 gaps. Translation quality is
  not evaluated by this phase.
- The debug card is still present (collapsed) and is development UI.

## Next action

Phase 3 is functionally complete (3.1–3.6 verified). The next work item is
**Phase 3.7 — reliability and polish** (failure handling, settings, accessibility,
browser compatibility), which also satisfies most of the Phase 3 → Phase 4 gate.

After 3.7, Phase 4 begins at milestone 4.1 (smart typesetting). Phase 4 and
Phase 5 are documented as planned only in [`ROADMAP.md`](ROADMAP.md) — do not
start them before the gate conditions there are met.
