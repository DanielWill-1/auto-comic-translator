# API — Auto Comic Translator

JSON API for the local / self-hosted OCR + translation backend. This is the
contract the future browser extension depends on.

- **Default address:** `http://127.0.0.1:8000`
- **API version:** `1` (top-level `api_version` field; routes remain unversioned)
- **Privacy:** all processing happens locally; images are not sent anywhere.
- **Request size:** maximum request body is 21 MiB; image files are limited to
  20 MiB and 8192 pixels per dimension.

---

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Process liveness |
| GET | `/ready` | OCR and translation readiness |
| POST | `/ocr` | OCR only (structured text regions) |
| POST | `/translate` | OCR + translation |

---

## `POST /translate`

Performs OCR, text grouping, and local translation, returning structured
regions with bounding boxes in **original input image pixel coordinates**.

### Request (multipart/form-data)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `image` | file | — (required) | JPG/PNG/BMP/TIFF/WEBP comic image (≤ 20 MB, 80–8192 px) |
| `source_language` | string | `auto` | `auto`, `ko`, `ja`, `zh`, `zh-Hans`, `zh-Hant` |
| `target_language` | string | `en` | target language code (currently `en`) |

When `source_language=auto`, OCR runs all language readers and **each region
carries the language of the reader that detected it**; translation uses that
per-region language. If grouping combines detections, the group uses the
confidence-weighted dominant language (ties are resolved deterministically).
The uploaded filename is never used to decide the language. With no detected
regions, the resolved top-level language is `unknown` and `regions` is empty.

### Response (JSON)

```jsonc
{
  "api_version": "1",
  "source_language": "ja",
  "target_language": "en",
  "image": {
    "width": 1200,
    "height": 1800
  },
  "ocr_time_ms": 15160.0,
  "translation_time_ms": 12221.0,
  "total_time_ms": 27381.0,
  "num_regions": 2,
  "regions": [
    {
      "original_text": "こんにちは",
      "translated_text": "Hello",
      "confidence": 0.97,
      "ocr_confidence": 0.97,
      "bbox": {
        "x1": 100,
        "y1": 200,
        "x2": 350,
        "y2": 280
      },
      "bbox_points": [[100, 200], [350, 200], [350, 280], [100, 280]],
      "translation_time_ms": 9123.4,
      "source_language": "ja",
      "translation_status": "ok"
    },
    {
      "original_text": "待って！",
      "translated_text": "Wait!",
      "confidence": 0.88,
      "ocr_confidence": 0.88,
      "bbox": {
        "x1": 420,
        "y1": 600,
        "x2": 700,
        "y2": 660
      },
      "bbox_points": [[420, 600], [700, 600], [700, 660], [420, 660]],
      "translation_time_ms": 1200.1,
      "source_language": "ja",
      "translation_status": "ok"
    }
  ]
}
```

### Field semantics

| Field | Semantics |
|-------|-----------|
| `api_version` | Always `"1"` in this contract. Stable; bump only on breaking changes. |
| `source_language` | **Resolved** source language. Explicit request → that code. `auto` → confidence-weighted dominant language across regions. `"unknown"` if nothing detected. Mixed pages are resolved here too, but per-region languages remain authoritative. |
| `image.width` / `image.height` | **Original input image** dimensions in pixels (not the preprocessed image). |
| `regions[].bbox` | Axis-aligned box `{x1, y1, x2, y2}` in **original input image pixels**. `x1,y1` = top-left, `x2,y2` = bottom-right. |
| `regions[].ocr_confidence` | The OCR confidence for the region. `confidence` is retained as an alias for existing clients. |
| `regions[].source_language` | The language that region was detected/translated in (may differ per region on mixed-language pages). `null` means OCR supplied no language. |
| `regions[].translation_status` | `"ok"` = successfully translated. `"fallback"` = local model unavailable or inference failed and the original text was echoed. |
| `regions[].bbox_points` | Original OCR polygon points retained for clients of the previous response shape. `bbox` is the browser-friendly axis-aligned box. |

### Auto-mode OCR readers

`source_language=auto` runs the configured OCR readers whose **local** model
files are complete and skips the ones that are not, because implicit model
downloads are disabled. A partial local installation therefore still works: with
only the shared `PP-OCRv6` detection/recognition models installed, `auto` uses
the Japanese and Chinese readers and skips Korean instead of failing the whole
request.

Auto mode applies two rules:

1. **One pass per distinct model set.** `ja`, `zh`, and `zh-Hant` resolve to the
   same `PP-OCRv6` files, so that model set runs once rather than once per
   language. A model set whose files cannot be resolved keeps its own key and is
   never merged with another language.
2. **The recognized text names the language, not the reader.** The reader key is
   an installation detail, not a detection result. Each line is labelled by its
   script (Hangul → `ko`, kana → `ja`, Han → `zh`); a line with no identifiable
   script (digits, Latin, symbols) takes the page's confidence-weighted dominant
   script language, so a short misread cannot outvote the page's real text. Han
   cannot distinguish Simplified from Traditional Chinese, so Han-only pages
   resolve to `zh`; request `zh-Hant` explicitly for Traditional Chinese.

An explicit `source_language` stays strict: if that language's OCR model files
are missing, the request reports a controlled setup error instead of silently
returning empty OCR output, and its regions are never relabelled. `GET /ready`
lists the readers auto mode will use in `ocr_languages`.

### Timing breakdown

`/translate` adds a `timing` object to API v1 responses. Values are
milliseconds measured with a monotonic clock and kept unrounded internally.

| Field | Meaning |
|-------|---------|
| `request_total_ms` | Time inside the `/translate` handler, from its start through response-dictionary construction, just before the performance log. FastAPI multipart parsing before the handler and JSON encoding/network transfer afterward are excluded. |
| `validation_ms` | Source/target validation, upload reading and size checks, and image decoding. |
| `preprocessing_ms` | Image enhancement before OCR. |
| `ocr_ms` | Time spent inside PaddleOCR `reader.ocr(...)` call(s), excluding reader initialization and result parsing. |
| `grouping_ms` | Post-OCR text grouping. |
| `translation_ms` | Translation provider work, including model loading on first use. |
| `serialization_ms` | Building the response dictionary, including region serialization and timing/cache metadata. FastAPI's later JSON encoding is excluded. |
| `cache_lookup_ms` | SQLite lookup and result decoding. It includes both the initial lookup and the second check under the inference semaphore when that check happens. |
| `cache_write_ms` | Cache-result validation/JSON encoding and the SQLite write for a reusable result. |
| `inference_wait_ms` | Time waiting to acquire the shared inference semaphore. |
| `ocr_model_load_ms` | Time initializing OCR reader(s) during this request; zero when readers were already loaded. |
| `translation_model_load_ms` | Time loading Marian tokenizer/model files during this request; zero when already loaded or no model load was attempted. |

The legacy `ocr_time_ms`, `translation_time_ms`, and `total_time_ms` remain.
`ocr_time_ms` is the existing OCR recognition-method duration, including
reader initialization and OCR result parsing/deduplication, but not
preprocessing. `translation_time_ms` is provider/batch elapsed time. The
pipeline's `total_time_ms` covers preprocessing through translation and does
not include request validation, semaphore wait, or API response construction.
Model loading is included in OCR or translation stage time, so stages can
overlap in meaning or leave gaps; they are not expected to sum to
`request_total_ms`.

For the default Marian provider, each `regions[].translation_time_ms` is the
provider elapsed time associated with its source-language batch, measured
through batch decoding. It is not an independently measured latency for that
region. Translation stays batched.

On a cache hit, current-request OCR, grouping, translation, model-load, and
legacy inference durations are zero; validation, cache lookup, response
construction, and request-total timings still describe this request. An
initial cache hit never acquires the inference semaphore and has
`inference_wait_ms: 0`. If a duplicate request waits for the semaphore and
then finds another request's result on the second lookup, it reports the
actual wait and both lookups while all inference timings remain zero.

Each successful `/translate` request emits one concise local
`translation_performance` log record. It includes request ID, requested and
resolved language, cache-hit state, region count, and timings; it excludes OCR
and translated text, image bytes, and page URLs.

### Bounding box to browser coordinates

Because `bbox` and `image.width/height` are in the **original image** pixel
space, mapping to a rendered `<img>` is:

```js
const scaleX = img.clientWidth  / image.width;
const scaleY = img.clientHeight / image.height;

left   = bbox.x1 * scaleX;
top    = bbox.y1 * scaleY;
width  = (bbox.x2 - bbox.x1) * scaleX;
height = (bbox.y2 - bbox.y1) * scaleY;
```

### Errors

All errors use the same JSON envelope. For example:

```json
{
  "api_version": "1",
  "error": {
    "code": "UNSUPPORTED_SOURCE_LANGUAGE",
    "message": "Unsupported source_language 'fr'.",
    "request_id": "reader-session-42"
  }
}
```

Validation errors may also include `error.details`, an array of safe field and
message pairs. Unexpected server errors use a generic message; exception
details and stack traces are not returned.

| HTTP status | Stable error codes and meaning |
|--------------|-------------------------------|
| `400` | `EMPTY_IMAGE`, `INVALID_IMAGE`, `UNSUPPORTED_IMAGE_FORMAT`, `UNSUPPORTED_SOURCE_LANGUAGE`, `UNSUPPORTED_TARGET_LANGUAGE`, `INVALID_CONTENT_LENGTH`. |
| `413` | `REQUEST_TOO_LARGE` or `IMAGE_TOO_LARGE`. |
| `422` | `VALIDATION_ERROR`, such as a missing multipart field. |
| `404` / `405` | `NOT_FOUND` / `METHOD_NOT_ALLOWED`. |
| `503` | `OCR_READERS_UNAVAILABLE`; no configured OCR reader has complete local model files. Returned when `auto` has no usable reader, and also when an explicitly requested language has no local models for it (the request is never answered with an empty result). Local model paths stay in the server log. |
| `5xx` | `INTERNAL_ERROR`; server details are logged locally and omitted from the response. |

When a translation model is missing or inference fails, the request still
returns OCR regions with `translation_status: "fallback"`; original text is
returned as `translated_text`. The request does not download a translation
model automatically. Install local models with `python scripts/download_models.py`.
If a region has no detected language in `auto` mode, its source language is
`null`, the overall source language is `unknown` when no other region is
identified, and that region is also returned with `translation_status:
"fallback"`.

### Local response cache

`/translate` uses a local SQLite cache by default. The default database is
`data/cache.sqlite3` under the repository root, independent of the process
working directory. Set `ACT_CACHE_ENABLED=false` to disable cache reads and
writes, or set `ACT_CACHE_PATH` to choose another database file. Relative custom
paths are resolved from the repository root; cache files inside `models/` are
rejected.

The cache key includes the SHA-256 hash of the uploaded image bytes, requested
source and target languages, a deterministic processing fingerprint, and the
cache schema version. The fingerprint covers preprocessing settings, OCR
implementation/version and confidence settings, grouping settings, translation
provider/model identifiers and configuration, and API/cache/pipeline versions.
Changing any of these produces a miss. Re-encoding an identical image can
produce a different key because the original upload bytes are hashed. Model
weights are not hashed: replacing weights at the same configured path may
require clearing the cache or changing the pipeline version.

When changing output-affecting pipeline code, bump `CACHE_PIPELINE_VERSION`;
bump `CACHE_SCHEMA_VERSION` when the cache format or identity schema changes.

The SQLite file stores image hashes and serialized API results, including OCR
and translated text, boxes, confidence, status, and timestamps/hit counts. It
does **not** store raw images, URLs, request headers, or browsing history. Failed
requests and results containing any `translation_status: "fallback"` are not
cached. A successful empty-region result is cacheable. SQLite or row corruption
is logged locally and treated as a cache miss so translation can continue.
The database is an ordinary local SQLite file, not encrypted by this feature;
the text remains readable on disk until cleared. There is no automatic eviction
yet; entries remain until manually cleared.

With caching enabled, successful `/translate` responses add:

```json
"cache": { "hit": true, "lookup_time_ms": 1.2 }
```

`hit` is `false` for a cache miss. On a miss, the existing OCR/translation/total
timings describe the current inference. On a hit, those top-level timings and
every region's `translation_time_ms` are zero; `cache.lookup_time_ms` measures
the current cache lookup work. When caching is disabled, the `cache` field is
omitted; the additive `timing` object is still returned.

The default inference semaphore allows one in-flight inference. A request that
misses its initial lookup checks the cache again after acquiring that slot, so
an identical request waiting behind it can reuse the newly written result. If
`ACT_MAX_CONCURRENT_INFERENCE` is raised above one, simultaneous identical
misses may still run inference concurrently.

Inspect or clear the local database from the repository root:

```bash
python -m backend.cache stats
python -m backend.cache clear
```

`stats` reports entry count, total hits, and database size. `clear` deletes the
cached results without deleting the database file.

### Local benchmark

Run the benchmark explicitly with one image or a flat directory of images:

```bash
python scripts/benchmark.py path/to/image.png --source ja
python scripts/benchmark.py path/to/images --source ja --json
```

The directory is processed in filename order and is not searched recursively.
The tool reports three scenarios: the first request in this process (which may
include model initialization), a warm repeat with cache reads/writes disabled,
and a cache hit. With directory input, only the first image can be the first
request in the process; later images' first runs may use already-loaded models.
The JSON labels those cases and separates `first_request_in_process` from
`first_run_per_image` aggregates. The first request is not a fresh
operating-system or library start; process-level cold behavior requires
starting a new process for each measurement. JSON includes per-image timing
and count/mean/median/min/max/p95 aggregates. It reports neutral image labels
instead of source filenames, and does not emit source paths or
machine-identifying metadata.

The benchmark requires already-installed local PaddleOCR and Marian files. It
sets Hugging Face offline mode and guards PaddleOCR's model downloader; missing
files stop the run with a setup message. It swaps in a disposable SQLite cache
under a temporary directory and restores the configured cache afterward. It
never clears `data/cache.sqlite3` or downloads models. Install the HTTPX
development dependency from `requirements-dev.txt` to use it.

---

## `POST /ocr`

Same request shape as `/translate`, but runs **OCR only** and returns:
`api_version`, `results[]` (each `text`, `confidence`, `bbox`, `language`),
`source_language`, `num_text_regions`, `average_confidence`, and
`processing_time_ms`.

---

## `GET /health` and `GET /ready`

`/health` is a cheap liveness check and returns `status`, `version`, and
`api_version`. It does not initialize OCR or translation models.

`/ready` checks whether every configured OCR reader is already initialized and
whether Transformers plus all local Marian model directories, weights, and
tokenizer files are present. It does not load models or run inference. It
returns `ocr_ready`, `translation_ready`, and the additive `ocr_languages` list
(the readers `source_language=auto` will use, derived from local files only);
the HTTP status is `200` when both flags are true and `503` otherwise. A missing
local model makes `ocr_ready` false, while auto-mode requests can still succeed
with the readers that are installed. Requests can still return OCR with
per-region `translation_status: "fallback"`.

## Request IDs and CORS

Clients may send `X-Request-ID` using 1–128 ASCII letters, digits, `.`, `_`,
`:`, or `-`. Invalid or missing IDs are replaced with a generated ID. Every
API response returns the ID in its `X-Request-ID` header; error bodies also
include it at `error.request_id`. CORS exposes this header to extension clients.

CORS allows only origins matching the pattern `^chrome-extension://[a-p]{32}$`.
Make API requests from the extension background context so a
comic site's webpage origin is not used. Random websites do not receive CORS
permission to read responses. CORS is still browser policy, not authentication;
it does not prevent a webpage from attempting a simple request or protect a
backend intentionally exposed on a network.

## Concurrency and cancellation

OCR and translation inference run in a worker thread, with a shared default
limit of one in-flight inference (`ACT_MAX_CONCURRENT_INFERENCE`). Set it to a
positive integer up to 64 to change the limit. This keeps expensive synchronous
ML work off the ASGI event loop and serializes access to shared model instances.
If a browser cancels a request, inference already running in a worker thread may
continue until it finishes; the server keeps its concurrency slot occupied
during that work. There is no server-side inference timeout.

## Self-hosting

The default bind is `127.0.0.1:8000`, for the extension and backend on the same
computer. The module launcher accepts `ACT_HOST` and `ACT_PORT`; invalid ports
are rejected. Advanced self-hosting can intentionally set `ACT_HOST=0.0.0.0`,
which exposes the service on reachable network interfaces. Use an appropriate
firewall and understand that the API has no authentication or TLS.

---

## Backward compatibility

API v1 permits additive response fields. Removing or renaming required fields
requires a future API version. The Phase 2.5.1 response adds
`api_version`, `image.{width,height}`,
`regions[].source_language`, `regions[].ocr_confidence`, and
`regions[].translation_status`. `regions[].confidence` is preserved as an
alias, and the polygon is available as `bbox_points`; HTTP
`regions[].bbox` is the documented `{x1,y1,x2,y2}` object. The CLI's `--json`
output retains its previous polygon in `bbox`. Timing fields (`ocr_time_ms`,
`translation_time_ms`, `total_time_ms`) and `regions[].original_text` /
`translated_text` are preserved.

## API v1 compatibility contract

For a successful `POST /translate`, clients may rely on these required fields:

- Top level: `api_version`, `source_language`, `target_language`, `image.width`,
  `image.height`, `num_regions`, `regions`, the legacy timing fields
  `ocr_time_ms`, `translation_time_ms`, and `total_time_ms`, plus the detailed
  `timing` object.
- Each region: `original_text`, `translated_text`, `confidence`,
  `ocr_confidence`, `bbox`, `bbox_points`, `source_language`,
  `translation_status`, and `translation_time_ms`.
- Each `timing` object includes `request_total_ms`, `validation_ms`,
  `preprocessing_ms`, `ocr_ms`, `grouping_ms`, `translation_ms`,
  `serialization_ms`, `cache_lookup_ms`, `cache_write_ms`,
  `inference_wait_ms`, `ocr_model_load_ms`, and
  `translation_model_load_ms`. Inference and model-load values are zero on a
  cache hit.

When caching is enabled, the response also includes `cache.hit` and
`cache.lookup_time_ms`. This object is omitted when caching is disabled.
`bbox` uses original-image pixel coordinates; `bbox_points` preserves the
polygon representation. `confidence` remains an alias for `ocr_confidence`.

Errors require `api_version` and `error.code`, `error.message`, and
`error.request_id`; `error.details` is optional. Health/readiness and `/ocr`
have endpoint-specific fields described above. API v1 may gain additive fields,
but removing a listed field or changing its meaning requires a future API
version. There is no `/v2` endpoint in Phase 2.5.
