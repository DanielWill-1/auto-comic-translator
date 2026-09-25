We are finishing the remaining verification work for Phase 2.5.5 of
AUTO-COMIC-TRANSLATOR.

DO NOT add new features.

Japanese real-model verification has already passed.

Current verified state:

- Japanese 436x654 comic image passed real OCR + translation.
- Japanese real HTTP /translate passed.
- Japanese real cache miss -> hit passed.
- Japanese returned two translated regions with translation_status="ok".
- Japanese measured:
    first request: 12,751.77 ms
    warm repeat:    1,584.73 ms
    cache hit:         49.34 ms
- Japanese, Korean, and Chinese local Marian translation models have
  independently loaded and produced nonempty translations.
- Korean and Chinese IMAGE OCR/integration verification remained missing.
- Default suite previously passed:
    75 passed, 10 skipped
- Integration suite previously:
    5 passed, 5 skipped
- No model downloads are permitted.
- No paid/cloud services are permitted.

I have now added representative Korean and Chinese comic images under
the project's datas/ directory.

The ONLY objective of this task is to finish Korean and Chinese
real-image verification and determine whether Phase 2.5.5 can be marked
complete.

============================================================
DO NOT DEVELOP NEW FEATURES
============================================================

Do not:

- redesign OCR
- replace PaddleOCR
- replace MarianMT
- change translation models
- optimize performance
- implement the extension
- change API v1
- add cloud APIs
- download models
- download OCR assets
- add telemetry
- change cache architecture

Fix code ONLY if real testing exposes a genuine correctness or
integration bug.

============================================================
1. DISCOVER THE NEW SAMPLES
============================================================

Inspect:

datas/korean/
datas/chinese/

and the existing:

datas/japanes/

Do not assume exact filenames.

List which representative files will be tested.

Prefer 2-5 images per newly available language if enough exist.

Do not test hundreds of files.

Choose representative samples based on:

- readable resolution
- actual comic text
- variation where available

Do not modify the source images.

============================================================
2. VERIFY LOCAL ASSETS FIRST
============================================================

Before inference, verify all required LOCAL assets exist.

For Korean:

- PaddleOCR Korean OCR assets
- local Korean -> English translation model

For Chinese:

- required PaddleOCR Chinese OCR assets
- local Chinese -> English translation model

NO DOWNLOADS.

The application has already been hardened to refuse missing model
downloads.

If an OCR asset is missing, report exactly which LOCAL prerequisite is
missing and stop that language's test rather than downloading it.

============================================================
3. KOREAN — EXPLICIT REAL PIPELINE
============================================================

Run real image inference with:

source_language=ko
target_language=en

For each selected Korean sample verify:

image
  -> preprocessing
  -> REAL PaddleOCR
  -> grouping
  -> REAL local Marian translation
  -> serialized API result

Check:

- no crash
- regions detected when visible text exists
- original_text is nonempty for detected regions
- translated_text is nonempty
- translation_status is truthful
- expected source language is preserved
- bbox is valid
- bbox is inside original image dimensions
- bbox_points are valid
- OCR confidence is valid
- Unicode survives correctly

Show a SHORT human-readable sample of detected text and translation.

Do not require exact translation wording.

============================================================
4. KOREAN — AUTO MODE
============================================================

Run the same representative Korean image with:

source_language=auto

Inspect:

- top-level resolved language
- region-level languages
- number of regions
- translation model routing
- translation statuses
- OCR timing
- translation timing
- total timing

Compare against explicit ko.

The purpose is to catch catastrophic language-routing problems.

Do not demand every individual region be perfectly classified.

============================================================
5. CHINESE — EXPLICIT REAL PIPELINE
============================================================

Determine whether the supplied samples are:

- simplified Chinese
- traditional Chinese
- mixed/unknown

Use the appropriate existing source-language option.

Run real image inference.

Verify the same contract as Korean:

- real OCR
- real local translation
- valid regions
- valid bbox
- valid bbox_points
- valid confidence
- correct model routing
- nonempty translation
- truthful translation_status
- Unicode correctness

Remember:

zh / zh-Hans / zh-Hant may normalize internally to the local zh-en
translation model.

Preserve the detected/requested language information in the API as
currently designed.

============================================================
6. CHINESE — AUTO MODE
============================================================

Run a representative Chinese image with:

source_language=auto

Inspect:

- resolved source language
- region languages
- number of regions
- translation routing
- translation status
- OCR timing
- translation timing
- total timing

Compare explicit vs auto.

Again:

DO NOT optimize auto mode during this task.

Measure and report it.

============================================================
7. HUMAN SANITY CHECK
============================================================

For each language show a few SHORT examples:

Korean:

Original:
...

Translation:
...

Chinese:

Original:
...

Translation:
...

We are looking for catastrophic failures, NOT perfect literary
translation.

Flag things like:

- OCR garbage
- untranslated output
- obvious wrong-model routing
- duplicate regions
- missing text
- encoding corruption

Distinguish:

OCR problem

from:

translation problem

where possible.

============================================================
8. REAL HTTP TEST
============================================================

After direct pipeline verification succeeds, start the real local
FastAPI server.

Use at least:

one Korean image
one Chinese image

Send actual multipart HTTP requests to:

POST /translate

Verify:

HTTP 200
api_version == "1"
correct image dimensions
regions serialize correctly
bbox contract survives HTTP
request ID exists
timing exists
translation_status exists
no traceback/path leakage

Do not rely only on Python function calls.

============================================================
9. REAL CACHE TEST
============================================================

For one Korean and one Chinese sample:

FIRST REQUEST
    cache miss
    real inference occurs

SECOND IDENTICAL REQUEST
    cache hit
    inference is bypassed

Verify:

cache.hit == true
ocr timing == 0
translation timing == 0
bbox preserved
bbox_points preserved
text preserved
language preserved
translation_status preserved

Use a temporary cache.

Do NOT modify or clear the user's normal cache.

============================================================
10. PERFORMANCE
============================================================

Use the existing instrumentation.

Record real measurements for Korean and Chinese.

At minimum report:

resolution
explicit/auto
preprocessing_ms
ocr_ms
translation_ms
request_total_ms

Where practical also record:

first request
warm request
cache hit

DO NOT optimize anything based on these results yet.

Update docs/PERFORMANCE.md with REAL numbers only.

Clearly identify:

CPU/GPU mode
explicit vs auto

Do not include personal absolute filesystem paths.

============================================================
11. INTEGRATION TESTS
============================================================

Use or extend the existing opt-in integration tests.

Do NOT make normal pytest unexpectedly load real models.

Integration tests should remain explicitly opt-in.

Run the Korean and Chinese integration cases.

Then run the entire lightweight suite again.

Expected commands should remain conceptually:

pytest

and separately:

pytest -m integration

or the project's established equivalent.

============================================================
12. FAILURE POLICY
============================================================

If Korean or Chinese fails, diagnose the layer.

Classify failure as one of:

ENVIRONMENT
OCR MODEL/ASSET
PREPROCESSING
OCR
GROUPING
LANGUAGE ROUTING
TRANSLATION
SERIALIZATION
CACHE
HTTP

Do not start rewriting unrelated components.

If it is a straightforward implementation bug, fix it and rerun the
affected tests.

If it is fundamentally model-quality related, document it instead of
redesigning the system.

============================================================
13. PHASE 2.5 COMPLETION CRITERIA
============================================================

Phase 2.5.5 can be marked complete when we have demonstrated:

Japanese:
[x] real image OCR
[x] real local translation
[x] HTTP
[x] cache

Korean:
[ ] real image OCR
[ ] real local translation
[ ] explicit mode
[ ] auto mode
[ ] HTTP
[ ] cache

Chinese:
[ ] real image OCR
[ ] real local translation
[ ] explicit mode
[ ] auto mode
[ ] HTTP
[ ] cache

Global:
[x/verify] API v1
[x/verify] bbox contract
[x/verify] local-only operation
[x/verify] no request-time model downloads
[x/verify] lightweight test suite
[x/verify] extension CORS policy

Only mark boxes complete when actually verified.

============================================================
14. FINAL VALIDATION
============================================================

After real testing run:

pytest

appropriate opt-in integration tests

python -m compileall backend scripts

python cli.py --help

python scripts/benchmark.py --help

Verify:

from backend.main import app

Run:

git diff --check

Confirm:

- no models downloaded
- no paid APIs introduced
- no telemetry introduced
- API v1 unchanged
- normal cache untouched
- no accidental file deletion

============================================================
15. DOCUMENTATION
============================================================

Update only where warranted:

docs/PERFORMANCE.md
docs/ROADMAP.md
docs/API.md if an actual discrepancy was discovered

Do not rewrite documentation unnecessarily.

If all completion criteria pass:

mark Phase 2.5.5 complete.

Then mark:

PHASE 2.5 COMPLETE

Do NOT begin Phase 3.

============================================================
FINAL REPORT
============================================================

Return:

### Korean
Samples tested
Explicit result
Auto result
Short OCR -> translation examples
Performance
HTTP result
Cache result

### Chinese
Samples tested
Explicit result
Auto result
Short OCR -> translation examples
Performance
HTTP result
Cache result

### Japanese
Confirm previous verified status remains valid.

### Bugs found
Only actual integration bugs.

### Automated tests
Exact pass/skip/fail counts.

### Model downloads
Explicitly confirm whether ANYTHING was downloaded.

### Phase 2.5 verdict

If every required check passed, say exactly:

"Backend Phase 2.5 is complete and ready for Phase 3."

Otherwise list ONLY the remaining blockers.

DO NOT START PHASE 3.