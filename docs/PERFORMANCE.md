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

Korean and Chinese translation model files are present, and the Korean Marian
translation-only check passed. Korean image measurements are unavailable
because its local PaddleOCR recognition files are missing. Auto-mode timings
are also unavailable because auto mode needs all configured OCR readers,
including the missing Korean and Traditional Chinese assets. No values are
inferred for those runs.
