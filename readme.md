# Auto Comic Translator

Automatic OCR and translation pipeline for webcomic, manga, and manhwa pages. Extracts Korean, Japanese, and Chinese text from comic images, translates it to English using local MarianMT models, and outputs structured results with bounding boxes.

The long-term goal is a browser extension that performs translation seamlessly while readers scroll through raw chapters on official sources. The current implementation covers the complete processing pipeline: image preprocessing, OCR extraction, translation, and structured output delivery.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Image preprocessing, OCR, structured text extraction | Complete |
| Phase 2 | Local MarianMT translation, CLI tooling, API endpoints | Complete |
| Phase 3 | Browser extension with DOM scanning and overlay rendering | Planned |
| Phase 4 | Advanced typesetting, chapter-wide caching, faster inference | Planned |

## Architecture

```
Image Input (JPG/PNG)
       |
       v
Image Preprocessing (grayscale, denoise, CLAHE, adaptive threshold)
       |
       v
OCREngine (EasyOCR — 4 language groups: ko-en, ja-en, zh_sim-en, zh_tra-en)
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

### Backend modules

| Module | Purpose |
|--------|---------|
| `backend/config.py` | Language mappings, model paths, preprocessing/translation/pipeline configs |
| `backend/preprocessing.py` | `ImagePreprocessor` — grayscale, bilateral denoise, CLAHE, adaptive threshold |
| `backend/ocr.py` | `OCREngine` — wraps EasyOCR with IoU-based deduplication across 4 language group readers |
| `backend/pipeline.py` | `OCRPipeline` — preprocessing to OCR with vertical-proximity text grouping |
| `backend/translate.py` | `TranslationEngine` + `MarianMTProvider` — loads local models from `./models/` |
| `backend/full_pipeline.py` | `FullPipeline` — OCR to translation end-to-end, structured `FullPipelineResult` |
| `backend/utils.py` | Image validation, bytes/ndarray conversion, result serialization |
| `backend/main.py` | FastAPI app (v0.2.0) — `/health`, `/ocr`, `/translate`, `/ocr-batch` endpoints |

### Pretrained models

Translation models are stored locally in `./models/` and excluded from version control:

| Directory | Language Pair | Model |
|-----------|--------------|-------|
| `models/marian-ko-en/` | Korean to English | Helsinki-NLP/opus-mt-ko-en |
| `models/marian-ja-en/` | Japanese to English | Helsinki-NLP/opus-mt-ja-en |
| `models/marian-zh-en/` | Chinese to English | Helsinki-NLP/opus-mt-zh-en |

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

# Install dependencies
pip install -r requirements.txt

# Download pretrained translation models (one-time)
python testmt.py
```

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
#   -t, --target   Target language (default: en)
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

[2] ねば
    -> It has to be.
    conf: 0.2021 | bbox: [[44, 98], [102, 98], [102, 128], [44, 128]]
```

### FastAPI server

```bash
# Start server
uvicorn backend.main:app --reload

# Endpoints:
#   GET  /health           Server health check
#   POST /ocr              Image preprocessing + OCR only
#   POST /translate        Full pipeline: OCR + translation
#   POST /ocr-batch        Batch OCR processing
```

`POST /translate` accepts multipart form data with fields `image` (file), `source_language` (string), `target_language` (string, default "en").

Response format:

```json
{
  "source_language": "ja",
  "target_language": "en",
  "ocr_time_ms": 15160.0,
  "translation_time_ms": 12221.0,
  "total_time_ms": 27381.0,
  "num_regions": 3,
  "regions": [
    {
      "original_text": "...",
      "translated_text": "...",
      "confidence": 0.95,
      "bbox": [[44, 80], [98, 80], [98, 104], [44, 104]],
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

## Data

Sample comic screenshots are stored in `datas/` organized by language:

- `datas/japanes/` — Japanese comic panels
- `datas/korean/` — Korean comic panels
- `datas/chinese/` — Chinese comic panels

These are used for testing and development. They are excluded from version control.

## Next Steps (Phase 3)

- DOM scanner for the Chrome extension to detect comic images on web pages
- Automatic source language detection
- Browser overlay rendering using OCR bounding boxes
- Extension-to-backend communication via local HTTP
- Progressive translation while scrolling
- Backend-side result caching with SQLite

## License

MIT License
