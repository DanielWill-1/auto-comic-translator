# Local inference performance

These are measured timings from real Japanese and simplified Chinese comic
images using the local API pipeline. The first request and cache used temporary
SQLite databases; the normal application cache was not touched.

| Language | Mode | Resolution | First request | Warm repeat | Cache hit | Preprocess | OCR stage | Translation |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Japanese (`ja`) | Explicit | 436 × 654 | 12,751.77 ms | 1,584.73 ms | 49.34 ms | 24.08 ms | 587.40 ms | 10,847.15 ms |
| Chinese, simplified (`zh-Hans`) | Explicit | 773 × 356 | 6,877.85 ms | 793.87 ms | 26.37 ms | 13.84 ms | 319.79 ms | 5,812.01 ms |
| Korean (`ko`) | Explicit | 486 × 297 | Not run | Not run | Not run | Not run | Not run | Not run |

The Japanese image produced two regions; both translations had `ok` status.
The first request loaded the Japanese PaddleOCR reader in 1,221.56 ms and the
Marian translation model in 2,372.15 ms. The Chinese image also produced two
regions with `ok` status; its first request loaded the simplified Chinese
PaddleOCR reader in 684.11 ms and its Marian model in 1,337.84 ms. Warm repeats
reported zero model-load time. Cache hits bypassed OCR and translation, returned
matching region text/language/status/bounding boxes, and reported zero
inference timings.

Execution was CPU-only (`use_gpu=False`) with Python 3.11.0, PyTorch
2.5.1+cu121, and PaddlePaddle 3.0.0. The local model identifiers were
`PaddleOCR` Japanese recognition/detection/classification assets and
`Helsinki-NLP/opus-mt-ja-en` and `Helsinki-NLP/opus-mt-zh-en` (MarianMT). The
table is one observed run per scenario on one image, not a statistical
performance claim. The first request means the first request in that process;
model load is reported separately and it is not an operating-system cold-start
measurement.

## Auto mode (measured 2026-10-01)

Auto mode, cache disabled, CPU only, one observed run per sample:

| Sample | Resolved language | Regions | Wall | OCR | Translation |
|---|---|---:|---:|---:|---:|
| Japanese 436 × 654 | `ja` | 2 | 27.7 s | 16.9 s | 10.7 s |
| Chinese, simplified 829 × 472 | `zh` | 4 | 15.0 s | 12.6 s | 2.5 s |
| Korean 451 × 335 | `ko` | 3 | 7.9 s | 5.4 s | 2.5 s |

Before auto mode ran one pass per distinct local model set, the same Chinese
sample took 49.6 s wall with 33.4 s in OCR: the shared `PP-OCRv6` recognizer was
run once for each of `ja`, `zh`, and `zh-Hant`. Auto remains slower than an
explicit language because it still runs every installed model family (here the
`PP-OCRv6` set and the Korean `PP-OCRv5` set).

## Phase 4.5 baseline

Phase 4.5 (advanced performance) continues to report cold request, warm request,
cache hit, auto mode, and explicit language separately. The two tables in this
document are the baseline that any candidate optimization — translation
batching across regions, persistent warm models, preprocessing reuse, parallel
preprocessing, and evaluated (not adopted) quantization, ONNX, or GPU execution
— must beat. No optimization is adopted without a measurement.

Korean and Chinese translation model files are present, and the Korean
translation and image checks now pass: the Korean recognizer
(`PP-OCRv5_server_det` + `korean_PP-OCRv5_mobile_rec`) was installed locally on
2026-10-01, so the Korean row in the first table can be filled in when that
scenario is next measured. Auto mode no longer requires every configured reader
to be present — it runs the readers whose local model files exist and skips the
rest — so auto timings are available and are reported in the section above.
No values are inferred for runs that were not performed.
