# Auto Comic Translator — Phase 3.7 Reliability, Performance, and Browser Polish

We are now implementing:

# Phase 3.7 — Reliability and Polish

Do NOT begin Phase 4.

Do NOT redesign the project.

Preserve the working Phase 1–3.6 architecture.

This phase should primarily:

1. fix remaining real-browser correctness bugs;
2. significantly improve perceived and actual translation speed where safely possible;
3. harden overlay/image ownership;
4. improve queue prioritization;
5. improve settings/error handling;
6. finish browser usability/accessibility polish;
7. verify the complete extension end-to-end in real Chromium.

---

# CURRENT PROJECT STATE

Existing architecture now includes:

```text
Phase 3.1
Extension shell + backend connection

Phase 3.2
Comic image discovery

Phase 3.3
Manual Alt+Click translation

Phase 3.4
IntersectionObserver + lazy translation queue

Phase 3.5
Responsive image overlays

Phase 3.6
Translation feed
```

The current pipeline is approximately:

```text
image discovered
    ↓
observed
    ↓
near viewport
    ↓
translation queue
    ↓
content script
    ↓
service worker
    ↓
POST /translate
    ↓
FastAPI
    ↓
OCR
    ↓
translation
    ↓
result stored
   ↙       ↘
overlay    feed
```

Do not duplicate any of these systems.

---

# CURRENT TEST STATUS

Recent automated verification:

```text
node --test "tests/extension/*.test.js"
86 passed, 0 failed

pytest -q
95 passed, 15 skipped

compileall backend scripts tests
OK

node --check
all extension/test JS parsed

git diff --check
clean
```

Do not regress this.

---

# IMPORTANT ENVIRONMENT SPLIT

There are currently TWO Python/Paddle environments.

## Project venv

```text
PaddleOCR 2.9.1
models under ~/.paddleocr/whl
available OCR roughly: ja + zh
Korean recognizer unavailable
```

Behavior:

```text
explicit ja → 200
auto → 200
explicit ko → controlled 503 OCR_READERS_UNAVAILABLE
```

## Global Python 3.11

```text
PaddleOCR 3.7
PaddleX 3.7.x
models under ~/.paddlex/official_models
```

More OCR languages are available there, including the Korean configuration previously tested.

Do NOT merge these environments or silently download models.

Do NOT change dependency versions merely to make tests pass.

Maintain compatibility with the project's existing 2.x/3.x OCR support.

---

# PRIMARY REAL-BROWSER BUG

There is still a serious overlay ownership/layout defect.

Observed behavior:

```text
Image 1 translated
        ↓
some translated boxes appear spatially near Image 2
or later in the document
```

In the real fixture, overlays associated with one manga page can visibly appear beside another page instead of remaining entirely attached to their source image.

THIS MUST BE FIXED FIRST.

Do not attempt to solve this with:

```css
left: -500px;
transform: translateX(...);
```

or other magic offsets.

The invariant must be:

```text
one image
    ↓
one translation identity
    ↓
one overlay owner
    ↓
only that image's regions
```

---

# PART A — REPOSITORY AUDIT

Before changing code, inspect the actual current implementation.

At minimum:

```text
extension/content.js
extension/content.css
extension/manifest.json

extension/lib/image-detector.js
extension/lib/lazy-observer.js
extension/lib/translation-queue.js
extension/lib/translation-api.js
extension/lib/overlay-renderer.js
extension/lib/translation-feed.js

extension/background.js
extension/popup/*

backend/main.py
backend/ocr.py
backend/pipeline.py
backend/full_pipeline.py
backend/cache.py
backend/translate.py
backend/config.py

tests/extension/
tests/

docs/API.md
docs/PERFORMANCE.md
docs/ROADMAP.md
docs/HANDOFF.md
dev/test-site/
```

Report the real current architecture before modifying it.

Do not work from assumptions from older handoffs.

---

# PART B — FIX CROSS-IMAGE OVERLAY OWNERSHIP

This is the highest-priority correctness issue.

Investigate whether any of these are currently possible:

```text
overlay node reused for another image
result stored under wrong image key
DOM-order index used as identity
image reference changed after async completion
overlay container shared by images
stale async request writes after src change
source change does not invalidate renderer
settings invalidation leaves renderer ownership stale
ResizeObserver callback uses stale image/result
translation completion captures mutable loop variable
feed ordering accidentally reused as overlay identity
```

Find the ACTUAL cause.

---

# B1. Identity must never be based only on index

Do NOT identify images using only:

```text
Image 1
Image 2
Image 3
```

or:

```javascript
document.images[index]
```

Indexes can change when dynamic images are inserted/removed.

DOM order is useful for DISPLAY ORDER.

It must not be used as the canonical translation owner.

Use the actual image DOM element plus translation identity.

---

# B2. Define canonical per-image translation identity

Each active result should be associated with something conceptually equivalent to:

```text
DOM image element
+
resolved image source identity
+
source language
+
target language
+
backend URL
```

For example:

```javascript
{
    element,
    sourceKey,
    sourceLanguage,
    targetLanguage,
    backendUrl
}
```

You do not have to implement that exact structure.

Use the simplest architecture compatible with current code.

---

# B3. Protect against stale async completion

Critical race:

```text
Image A queued
    ↓
request running
    ↓
image src changes / settings change / state reset
    ↓
old request completes
    ↓
OLD result must NOT render
```

Every async translation completion must verify that it still belongs to the current image identity.

Use the existing epoch/generation mechanism if Phase 3.4 already has one.

If not sufficient, strengthen it.

Conceptually:

```javascript
const generationAtStart = state.generation;

await translate();

if (state.generation !== generationAtStart) {
    discardResult();
}
```

Do not render stale results.

---

# B4. Overlay owner

There must be exactly:

```text
0 or 1 overlay root
```

per translated image element.

Use something like:

```javascript
WeakMap<HTMLImageElement, OverlayState>
```

if appropriate.

The state may contain:

```text
overlayElement
resizeObserver
translationIdentity
result
```

A renderer call for Image A must never retrieve Image B's overlay root.

---

# B5. Overlay containment

Each translation region must exist inside the overlay associated with its own image.

Example:

```html
Image A
└── Overlay A
    ├── Region A1
    └── Region A2

Image B
└── Overlay B
    ├── Region B1
    └── Region B2
```

Never:

```html
Shared Overlay
├── A1
├── A2
├── B1
└── B2
```

unless the renderer has rock-solid per-image viewport coordinate isolation.

Prefer image-local containment.

---

# B6. Debug cards must not affect ownership

The existing:

```text
ACT Translation Debug
```

cards are inserted below images.

They must not:

```text
become the anchor for overlays
change which image an overlay belongs to
change the overlay origin
shift overlay state to the next sibling
```

Explicitly test:

```text
Image A
Debug Card A
Image B
```

Overlay A must remain on Image A.

---

# B7. Dynamic DOM regression

Test:

```text
Image A
Image B
Image C
```

translate A and B.

Then insert:

```text
Image X
```

before B.

Expected:

```text
Overlay A remains on A
Overlay B remains on B
```

Only feed numbering/order may change.

Overlay ownership must not.

---

# B8. Removal regression

Translate:

```text
A
B
C
```

Remove B.

Expected:

```text
A overlay remains correct
C overlay remains correct
B overlay cleaned
```

No overlay migration.

---

# B9. Duplicate source regression

The fixture deliberately contains two `<img>` elements with the same source.

Example:

```text
Image A -> manga.png
Image B -> manga.png
```

Backend result content may be reusable.

But:

```text
overlay A belongs to A
overlay B belongs to B
```

They must be separate DOM renderers even if the API result object is shared.

---

# PART C — FIX GEOMETRY ROBUSTNESS

Even after ownership is fixed, preserve these invariants.

For every image:

```text
overlay origin = visual image content origin
overlay width = visual image content width
overlay height = visual image content height
```

Translated bbox positions must remain image-local.

---

# C1. Never use document order for coordinates

Region coordinate mapping must depend only on:

```text
API source dimensions
displayed image/content dimensions
that image's own visual rect
```

Never:

```text
previous image height
number of previous images
feed index
debug card height
page scroll offset
```

---

# C2. Resize stability

ResizeObserver callbacks must update only their associated image.

Explicitly test:

```text
resize Image A
```

does NOT mutate:

```text
Overlay B
Overlay C
```

---

# C3. Source-change stability

When image source changes:

```text
remove old overlay
invalidate result
retranslate new source
create new overlay
```

Old region DOM must never survive on the new source.

---

# PART D — PERFORMANCE PROFILING FIRST

The extension currently feels slow.

Do NOT immediately start changing model architecture or concurrency.

Measure where the time is actually spent.

The backend already returns detailed timing information.

Use it.

Collect representative timings for:

```text
first request after process start
warm uncached request
backend cache hit
Auto language
explicit Japanese
```

For each, capture existing timing fields corresponding to:

```text
request decode
preprocessing
OCR model loading
OCR inference
grouping
translation model loading
translation inference
cache lookup/write
semaphore wait
serialization
total
```

Also measure browser-side stages:

```text
image fetch
blob creation
message dispatch
service-worker handling
network round trip
response validation
overlay rendering
feed update
```

Do NOT log actual comic text.

---

# D1. Produce a before-optimization profile

Create a compact report similar to:

```text
Explicit Japanese, first request
total: ...
model load: ...
OCR: ...
translation: ...
queue wait: ...

Explicit Japanese, warm
total: ...

cache hit
total: ...
```

Do not optimize blindly.

---

# PART E — SPEED: ELIMINATE REDUNDANT REQUESTS

Review all paths that can issue translation.

There must be no duplicates caused by:

```text
IntersectionObserver re-entry
MutationObserver re-discovery
Alt+Click while lazy request active
feed interaction
overlay resize
settings refresh
debug-card rerender
source observer callback
responsive layout
duplicate queue pump
```

For one image identity:

```text
one active request maximum
```

---

# E1. In-flight request coalescing

If two consumers request the SAME translation identity while it is processing:

```text
lazy queue
+
manual Alt+Click
```

they should await/reuse the same in-flight promise/result rather than issue two backend requests.

Do not only reject one request if that prevents its UI from receiving the eventual result.

Prefer:

```text
same identity
→ one backend request
→ multiple consumers notified
```

where practical.

---

# PART F — SESSION RESULT REUSE

Backend SQLite cache already handles persistent result caching, but the extension can avoid unnecessary browser work too.

Within the current page/session, consider a small translation-result cache keyed by:

```text
resolved image source
source language
target language
backend URL
```

This is especially useful for the duplicate-source fixture.

If:

```text
Image A
Image B
```

have the same exact resolved image source and translation identity:

Image B may reuse Image A's successful API result.

It still needs:

```text
its own overlay
its own feed entry
```

but does not necessarily need:

```text
another fetch
another upload
another backend request
```

---

# F1. Be conservative

Only reuse results when identity is clearly equivalent.

Do NOT reuse by:

```text
filename alone
DOM index
alt text
dimensions alone
```

A resolved URL/session identity is acceptable as an optimization.

If correctness is uncertain, fall back to backend processing.

---

# PART G — QUEUE PRIORITY FOR PERCEIVED SPEED

Current queue is FIFO with concurrency 1.

This is safe, but with a chapter-like fixture it can feel slow because an image farther away can block the one the user is actually looking at.

Improve pending queue prioritization.

Do NOT break bounded concurrency.

---

# G1. Priority model

Pending, NOT-YET-STARTED images may be prioritized approximately:

```text
1. currently visible image
2. image just below viewport / likely next reading image
3. image slightly above viewport
4. farther prefetch candidates
```

Do not cancel an OCR request already executing just because another image becomes visible.

Only reprioritize pending work.

---

# G2. Reading direction

For normal vertical comic reading:

prefer images below the viewport over equally distant images above it.

Keep this simple.

No complex prediction model.

---

# G3. Current visible image must not wait behind many prefetched images

Example:

```text
Queue:
A 800px above
B 500px below
C visible now
```

Before processing begins or when choosing next:

```text
C
B
A
```

is preferable.

---

# G4. Preserve concurrency

Do NOT simply change:

```text
MAX_CONCURRENT_TRANSLATIONS = 1
```

to a huge number.

The backend already protects synchronous inference with a semaphore.

Sending many requests merely causes:

```text
browser network congestion
extra blobs in memory
backend semaphore waits
worse responsiveness
```

Keep concurrency 1 unless profiling and explicit safety testing prove 2 gives a real benefit.

---

# PART H — TEST CONCURRENCY = 2 EXPERIMENTALLY, NOT BY DEFAULT

Because the backend currently serializes expensive inference, browser concurrency >1 may provide little benefit.

Perform an isolated benchmark:

```text
extension concurrency 1
vs
extension concurrency 2
```

Measure:

```text
time-to-current-image
chapter throughput
backend queue wait
memory
error rate
```

Only increase the default if there is a clear measured improvement and backend inference remains safe.

Otherwise keep:

```text
MAX_CONCURRENT_TRANSLATIONS = 1
```

Document the benchmark.

---

# PART I — REDUCE EXPENSIVE IMAGE FETCH WORK

Inspect:

```javascript
fetch(image.currentSrc || image.src)
```

path.

Ensure image data is not fetched more than once unnecessarily for the same active translation identity.

If the image is already being translated:

reuse the in-flight work.

If a successful same-source result exists in session cache:

reuse it.

Do NOT fetch blobs repeatedly for:

```text
overlay rerender
feed rendering
resize
scroll
```

---

# PART J — BACKEND MODEL REUSE

Verify that OCR and Marian model instances remain cached/reused between requests.

They must NOT be recreated every image.

Confirm from actual code.

Add instrumentation/test coverage if necessary.

Expected:

```text
first request
model load expensive

later request
model load ≈ 0
```

If the same model is being reconstructed repeatedly, fix that.

---

# PART K — FIRST-REQUEST LATENCY

The first real translation may naturally be slower due to model loading.

Improve perceived behavior without violating local-first design.

Possible safe improvements:

```text
show "Loading local OCR model…"
show "Translating…"
```

instead of appearing frozen.

If there is already a lightweight local initialization mechanism that can safely warm the selected model AFTER explicit user enabling, evaluate it.

But:

Do NOT make `/health` load models.

Do NOT make `/ready` unexpectedly load models.

Do NOT download models.

Do NOT introduce expensive startup work unless measured benefit justifies it.

Prefer keeping lazy loading and clearly communicating first-load state.

---

# PART L — CACHE FAST PATH

Verify backend cache lookup happens before expensive model loading/inference wherever possible.

A cache hit should not initialize OCR/translation models just to return an already-cached result.

Existing historical behavior already targeted zero inference on cache hit.

Ensure recent code has not regressed this.

Benchmark:

```text
same image + same settings
```

second request should be dramatically faster.

---

# PART M — AUTO MODE PERFORMANCE

Auto mode can inherently be slower because more than one locally available OCR reader may run.

Measure:

```text
explicit Japanese
vs
Auto on Japanese
```

Do not hide this.

If Auto is significantly slower because multiple OCR readers execute:

document that.

Only optimize if you can preserve detection correctness.

Do NOT create a weak heuristic that guesses a language solely to make benchmarks look faster.

---

# PART N — EXTENSION UI PROGRESS STATES

Improve visible state feedback.

Each candidate image should have clear lightweight state:

```text
queued
translating
translated
failed
```

Do not flood the page with debug cards.

Possible subtle indicator:

```text
small border / badge
```

during development.

Normal users should not need the large ACT debug card.

---

# N1. Debug card policy

Recommended:

```text
automatic translation
→ no large debug card

Alt+Click/manual debug
→ detailed debug card
```

Keep developer diagnostics available.

This will also reduce DOM noise and page length.

---

# PART O — TRANSLATION FEED POLISH

The Phase 3.6 feed works.

Improve only reliability/usability.

Do not redesign it.

Check:

```text
entry never belongs to wrong image
DOM order updates correctly
dynamic images insert correctly
removed images disappear
settings invalidation updates entries
same-source duplicate has two separate feed entries
```

Feed index is presentation only.

Never use feed index as canonical overlay identity.

---

# PART P — ERROR HANDLING

All extension errors should have useful structured output.

Never:

```text
[object Object]
```

Normalize:

```text
message
code
status
requestId
```

Do not expose comic text or unnecessary filesystem details.

---

# P1. User-facing messages

Examples:

Backend offline:

```text
Local translator is unavailable.
Start the Auto Comic Translator backend.
```

Missing local OCR:

```text
OCR model for Korean is not installed locally.
```

Timeout:

```text
Translation timed out.
```

Keep technical details in development logs.

---

# PART Q — BACKEND OFFLINE RECOVERY

If backend is stopped:

```text
current image fails
```

The queue must not spam repeated requests.

When the backend becomes available later:

manual retry must work.

A future image should also be able to process normally.

Do not permanently poison the entire session.

---

# PART R — SETTINGS POLISH

Review popup settings.

At minimum ensure clean support for:

```text
enabled
source language
backend URL
```

If existing implementation already supports target language, preserve it.

Potential Phase 3.7 additions only if they remain small:

```text
Show overlays
Show translation feed
```

Do not build a large settings page.

---

# R1. Settings identity changes

These must invalidate translation identity where appropriate:

```text
source language
target language
backend URL
```

Visual-only settings such as:

```text
feed visible
overlay visible
```

must NOT cause backend retranslation.

---

# PART S — OVERLAY VISIBILITY TOGGLE

If straightforward, expose:

```text
Show translations on images
```

Default:

```text
on
```

Turning it off:

```text
hide/remove rendered overlays
```

but preserve successful results.

Turning it back on:

```text
rerender from stored result
```

with:

```text
ZERO new /translate request
```

---

# PART T — FEED VISIBILITY

Similarly:

```text
Show translation feed
```

may control whether the feed button/panel is available.

Changing feed visibility must not invalidate translation results.

---

# PART U — MEMORY / CLEANUP

Long comic chapters can contain many images.

Audit:

```text
WeakMap usage
WeakSet usage
ResizeObservers
IntersectionObservers
MutationObserver
AbortControllers
event listeners
feed references
overlay DOM
debug-card references
```

Removed images must not be kept alive unnecessarily.

---

# U1. Overlay cleanup

When an image leaves the DOM permanently:

```text
disconnect its ResizeObserver
remove its overlay
remove feed entry
release strong references
```

---

# PART V — MUTATIONOBSERVER PERFORMANCE

A broad:

```text
documentElement
subtree: true
```

MutationObserver can become expensive on busy sites.

Profile it.

Do NOT rescan:

```javascript
document.images
```

on every unrelated DOM mutation.

Prefer processing:

```text
newly-added nodes
changed img src/srcset
```

incrementally.

If current code already does this efficiently, leave it alone.

---

# V1. Debounce only where needed

Do not add random 500ms delays.

If mutations arrive in bursts, a microtask or short batched rescan can be acceptable.

Measure before/after.

---

# PART W — INTERSECTIONOBSERVER PERFORMANCE

Ensure each image is observed only once per relevant identity.

Do not repeatedly:

```text
observe
unobserve
observe
```

without a source/settings reason.

Check the expanded 13-candidate fixture.

---

# PART X — TEST SITE PERFORMANCE PANEL

Enhance the development fixture with a SMALL diagnostics section if useful.

Possible counters:

```text
Candidates
Queued
Processing
Translated
Failed
Backend requests
Cache hits
```

This must be development-only.

It can make real Chromium verification easier.

Do NOT couple production extension behavior to this fixture.

---

# PART Y — PERFORMANCE DEBUG LOGGING

Add optional concise development logs such as:

```text
[ACT perf]
image=3
fetch=12ms
backend=1580ms
render=4ms
cache=false
```

Do not include:

```text
OCR text
translated text
image bytes
full image URL if privacy-sensitive
```

Use index/internal debug ID only.

---

# PART Z — AUTOMATED REGRESSION TESTS

Add extensive tests for the real bugs.

---

## Z1. Cross-image ownership

Create:

```text
Image A
Image B
```

Return different known results.

Assert:

```text
A text only exists inside Overlay A
B text only exists inside Overlay B
```

---

## Z2. Async reverse completion

Requests:

```text
A begins
B begins/queued
```

Resolve responses in an unusual order where architecture permits.

Verify no ownership swap.

---

## Z3. DOM insertion

Translate A/B.

Insert X before B.

A/B overlay ownership unchanged.

---

## Z4. DOM removal

Translate A/B/C.

Remove B.

A and C unchanged.

---

## Z5. Same source twice

A/B share URL.

If session reuse occurs:

```text
backend request count may be 1
```

but:

```text
overlay count = 2
feed entries = 2
```

---

## Z6. Stale source completion

Start translation.

Change src before response resolves.

Resolve old request.

Assert:

```text
old result discarded
old overlay absent
```

---

## Z7. Settings race

Start Auto translation.

Change to Japanese before completion.

Old Auto completion must not render over Japanese state.

---

## Z8. Resize isolation

Resize A.

Only A overlay recalculates.

---

## Z9. Debug-card isolation

Add/remove debug card A.

Overlay B unchanged.

---

## Z10. Session cache

Translate same identity twice on distinct elements.

Verify result reuse if implemented.

---

## Z11. In-flight coalescing

Lazy translation + Alt+Click simultaneously.

Exactly one backend request.

Both paths receive final state.

---

## Z12. Queue prioritization

Candidates:

```text
far above
near below
visible
```

Verify next job is:

```text
visible
```

then near below.

---

## Z13. Pending reprioritization

Queue several images.

Scroll so another pending candidate becomes visible.

Ensure it moves ahead of farther pending candidates.

---

## Z14. Cache hit

Mock cached backend response.

Ensure no unnecessary extra extension processing/request.

---

## Z15. Toggle overlays

Disable overlay display.

No request.

Enable again.

Stored result rerenders.

No request.

---

## Z16. Disable extension

All visual extension UI removed/hidden.

Queue stopped safely.

---

# AA — PERFORMANCE BENCHMARK SCRIPT / REPORT

Reuse:

```text
scripts/benchmark.py
```

where appropriate.

Do not create a second redundant backend benchmark if one exists.

Run representative Japanese cases.

Record:

```text
cold
warm uncached
cache hit
```

Also create extension-side timing observations using the real fixture.

Document before/after numbers in:

```text
docs/PERFORMANCE.md
```

Do not claim improvement without measured numbers.

---

# AB — PERFORMANCE TARGET

Do NOT promise arbitrary sub-second OCR.

Instead optimize measurable overhead.

Goals:

```text
cache hit feels effectively immediate
warm request has minimal extension overhead
visible image is prioritized
no redundant requests
no unnecessary blob fetches
model reused
overlay/feed rendering negligible relative to OCR
```

For first-request model loading:

clearly indicate progress rather than appearing frozen.

---

# AC — REAL CHROMIUM VERIFICATION

This is mandatory for Phase 3.7 completion.

Previous phases still have:

```text
manual Chromium verification pending
```

Use this phase to finally close that gap.

Start backend and fixture normally.

Reload unpacked extension.

Use current real expanded test site.

---

# AC1. Explicit Japanese

Select Japanese.

Scroll through all Japanese pages.

Verify:

```text
correct image gets correct overlay
no overlay jumps to next image
feed entry matches same image
visible image gets priority
no duplicate backend request
```

---

# AC2. Adjacent-image regression

This specifically targets the screenshot bug.

Use two Japanese images stacked sequentially:

```text
Image A
Image B
```

Translate both.

Explicitly confirm:

```text
every A overlay element lies within A
every B overlay element lies within B
```

Scroll between them repeatedly.

Resize browser.

No crossover.

---

# AC3. 13-candidate chapter test

Scroll naturally from top to bottom.

Verify queue does not translate the whole chapter unnecessarily ahead of you.

Visible/next image should take priority.

---

# AC4. Feed mapping

Click each feed entry.

Confirm it goes to the image containing that entry's overlay.

This is an excellent ownership sanity check.

---

# AC5. Same-source duplicate

Confirm:

```text
two image DOM elements
two overlay sets
two feed entries
```

and inspect request count.

If session reuse implemented:

prefer one backend translation.

---

# AC6. Responsive fixture

Toggle responsive width.

Overlays stay attached.

No backend request.

---

# AC7. Narrow fixture

Ensure translated boxes remain readable and attached to the narrow image.

---

# AC8. Dynamic insertion

Add several images.

No existing overlay moves to another image.

New images translate normally.

---

# AC9. Remove dynamic image

Remove one translated image.

Its overlay/feed entry disappear.

Other images remain untouched.

---

# AC10. Lazy source replacement

Change placeholder to real image.

No stale placeholder result.

Correct new overlay appears.

---

# AC11. Auto mode

Verify Japanese sample with:

```text
Auto
```

Confirm 200 and correct overlay ownership.

---

# AC12. Missing Korean in venv

Using the venv intentionally:

```text
explicit Korean
```

should produce:

```text
503 OCR_READERS_UNAVAILABLE
```

with clean extension UX.

No overlay.

No repeated request storm.

---

# AC13. Backend offline

Stop backend.

Bring one new image near viewport.

One clean failure.

No loop.

Restart backend.

Manual retry / subsequent image works.

---

# AC14. Speed measurements

Record actual user-visible times for:

```text
cold Japanese
warm Japanese
cache hit
same-source reuse if implemented
```

Include browser-side and backend timing.

---

# AD — ACCESSIBILITY BASICS

Phase 3.7 should finish basic accessibility polish.

Check:

```text
feed open/close buttons
popup controls
overlay toggle
feed toggle
debug controls
```

Ensure:

```text
real button elements
keyboard focus
aria labels where needed
visible focus behavior
```

Do not attempt full WCAG certification.

---

# AE — CSS ISOLATION

Audit extension CSS for overly broad selectors.

Do not style page elements globally using selectors such as:

```css
img {}
button {}
section {}
```

All extension styles should be scoped to:

```text
act-
```

classes/data attributes.

The extension must not break arbitrary host pages.

---

# AF — Z-INDEX

Use a small intentional z-index hierarchy.

Example:

```text
image overlay
feed panel
development debug UI
```

Do not use arbitrary:

```css
z-index: 2147483647;
```

everywhere.

Avoid covering site navigation unnecessarily.

---

# AG — FINAL DEBUG CARD CLEANUP

Large debug cards are no longer appropriate for every automatic request.

Change normal mode to:

```text
no debug card
```

or extremely compact status.

Keep detailed debug output for:

```text
Alt+Click
development mode
```

This should make the fixture substantially cleaner and reduce DOM overhead.

---

# AH — DOCUMENTATION

Update:

```text
README.md
docs/ROADMAP.md
docs/HANDOFF.md
docs/PERFORMANCE.md
dev/test-site/README.md
```

Include:

```text
overlay ownership architecture
queue prioritization behavior
session dedup/reuse behavior
performance measurements
environment split
real Chromium verification record
known missing OCR assets
settings/toggles
```

---

# AI — PHASE STATUS

Do NOT mark earlier manual verification complete merely because automated tests pass.

After real Chromium verification, record truthful status.

Target:

```text
3.1 [x]
3.2 [x]
3.3 [x]
3.4 [x]
3.5 [x]
3.6 [x]
3.7 [x]
```

Only if the browser tests actually pass.

If not:

```text
3.7 IMPLEMENTED — MANUAL VERIFICATION PENDING
```

or:

```text
3.7 IN PROGRESS — overlay ownership bug remains
```

---

# AJ — REQUIRED COMMANDS

Run at minimum:

```powershell
node --test "tests/extension/*.test.js"
python -m pytest -q
python -m compileall backend scripts tests
git diff --check
```

Also:

```text
node --check
```

for all modified JS files.

Run the existing benchmark safely without model downloads.

---

# AK — DO NOT DO THESE

Do NOT:

```text
enable cloud APIs
enable implicit model downloads
replace PaddleOCR
replace MarianMT
rewrite extension architecture
rewrite backend
remove cache
increase concurrency blindly
hard-code positional offsets
use DOM index as result identity
start Phase 4
implement image inpainting
build perfect manga typesetting
```

---

# AL — EXPECTED FINAL REPORT

Provide a detailed report.

## 1. Root cause of cross-image overlays

Explain exactly why Image A's translation could appear around Image B.

Include the specific old state/DOM relationship responsible.

---

## 2. Ownership fix

Explain:

```text
image identity
result identity
overlay ownership
async-generation protection
cleanup
```

---

## 3. Performance profile BEFORE

Give actual timing numbers for:

```text
cold
warm
cache hit
Auto
```

and identify the dominant stage.

---

## 4. Performance changes

For every speed optimization explain:

```text
what changed
why
measured benefit
correctness tradeoff
```

Do not list speculative improvements as wins.

---

## 5. Performance AFTER

Provide the same measurements.

Show before vs after.

---

## 6. Queue changes

Explain priority behavior.

State whether concurrency remained 1 or changed.

If changed, provide benchmark justification.

---

## 7. Request deduplication

Report behavior for:

```text
observer repeat
Alt+Click collision
same source duplicates
settings change
src change
```

---

## 8. Files changed

Every file and purpose.

---

## 9. Tests added

Especially include cross-image ownership regression tests.

---

## 10. Exact test results

Report:

```text
extension tests:
pytest:
compileall:
node --check:
git diff --check:
```

---

## 11. Real Chromium verification

Explicit result for:

```text
adjacent images
full 13-image fixture
responsive image
narrow image
duplicate source
dynamic insertion
removal
lazy source replacement
Auto
explicit Japanese
missing Korean
backend offline
feed navigation
resize
```

---

## 12. Performance numbers

Give:

```text
cold:
warm:
cache:
same-source reuse:
```

with units.

---

## 13. Remaining limitations

Examples:

```text
first model load still expensive
Auto slower than explicit language
Korean unavailable in pinned 2.x venv
translation quality
perfect typesetting
```

---

## 14. Final status

End with:

```text
Phase 3.3:
Phase 3.4:
Phase 3.5:
Phase 3.6:
Phase 3.7:

Ready for Phase 4: YES / NO
```

Do NOT say YES if the adjacent-image overlay bug remains.

---

# MOST IMPORTANT CORRECTNESS INVARIANT

This must ALWAYS remain true:

```text
Image A
 ├─ Result A
 ├─ Overlay A
 └─ Feed Entry A

Image B
 ├─ Result B
 ├─ Overlay B
 └─ Feed Entry B
```

Never:

```text
Result A → Overlay B
Result B → Image A
```

DOM ordering may change.

Feed numbering may change.

Async completion order may change.

The ownership relationship must NOT.

---

# MOST IMPORTANT PERFORMANCE INVARIANT

Optimize:

```text
duplicate work
queue priority
cache reuse
image fetching
DOM overhead
model reuse
```

before considering additional inference concurrency.

The objective is:

```text
user scrolls to image
        ↓
that image gets priority
        ↓
one request maximum
        ↓
existing local models reused
        ↓
result reused wherever safe
        ↓
overlay appears immediately after response
```

Profile first.

Measure after.

Do not sacrifice correctness for benchmark numbers.

---

# END OF PHASE 3

Phase 3.7 is the LAST Phase 3 milestone.

Do not begin Phase 4 during this task.

Once 3.7 is genuinely stable and manually verified, produce a clean handoff describing what Phase 4 should address next.