"""Phase 2.5.1 tests — stable /translate contract and auto-language propagation.

These tests deliberately avoid loading OCR or translation models. The
expensive pieces (PaddleOCR, MarianMT) are stubbed by substituting
``FullPipeline._ocr`` and ``FullPipeline._translator`` with lightweight fakes.
Run with:  pytest tests/test_phase25.py
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

import numpy as np
import pytest
import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.full_pipeline import (
    FullPipeline,
    full_pipeline_result_to_dict,
    _normalize_bbox,
)
from backend.ocr import OCRResponse, OCRResult, OCREngine
from backend.pipeline import OCRPipeline
from backend.translate import MarianMTProvider, TranslationEngine, TranslationResult


# --------------------------------------------------------------------------- #
# Fakes — no model inference
# --------------------------------------------------------------------------- #

class FakeOCR:
    """Returns hand-built OCR regions irrespective of the image content."""

    def __init__(self, results: list[OCRResult]):
        self._results = results

    def run_with_grouping(self, image, source_language="auto"):
        return OCRResponse(
            results=list(self._results),
            source_language=source_language or "auto",
            num_text_regions=len(self._results),
            average_confidence=(
                sum(r.confidence for r in self._results) / len(self._results)
                if self._results else 0.0
            ),
            processing_time_ms=1.0,
        )


class FakeTranslator:
    """Records the resolved source language for each fake translation."""

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    def translate_mixed(self, items, target_lang="en"):
        for _, lang in items:
            self.calls.append((lang,))  # record resolved lang per item
        results = []
        for text, lang in items:
            results.append(TranslationResult(
                original_text=text,
                translated_text=f"[TR:{lang}] {text}",
                source_language=lang or "auto",
                target_language=target_lang,
                confidence=0.9,
                processing_time_ms=1.0,
                status="ok",
            ))
        return results


def make_pipeline(ocr_results: list[OCRResult]) -> FullPipeline:
    p = FullPipeline()
    p._ocr = FakeOCR(ocr_results)
    p._translator = FakeTranslator()
    return p


def make_image_png(width=1200, height=1800) -> bytes:
    """A real, valid PNG buffer (white canvas) — needed for /translate tests."""
    img = Image.new("RGB", (width, height), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_image(width=1200, height=1800) -> np.ndarray:
    arr = np.full((height, width, 3), 255, dtype=np.uint8)
    return arr


def post_app(app, path, **kwargs):
    """Send one ASGI request without TestClient's httpx version coupling."""
    async def send():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(path, **kwargs)

    return asyncio.run(send())


def result(*, text, lang, conf=0.95, bbox=None):
    return OCRResult(
        text=text,
        confidence=conf,
        bbox=bbox or [[100, 200], [350, 200], [350, 280], [100, 280]],
        language=lang,
    )


# --------------------------------------------------------------------------- #
# 1. / translate response contains image dimensions
# --------------------------------------------------------------------------- #

def response(p: FullPipeline, src="auto"):
    return p.run(make_image(), source_language=src, target_language="en")


def test_image_dimensions_in_response():
    p = make_pipeline([result(text="x", lang="ja")])
    out = response(p)
    assert out.image_width == 1200
    assert out.image_height == 1800


def test_image_dimensions_in_dict():
    p = make_pipeline([result(text="x", lang="ja")])
    d = full_pipeline_result_to_dict(response(p))
    assert d["image"] == {"width": 1200, "height": 1800}


# --------------------------------------------------------------------------- #
# 2. Region serialization contains required fields
# --------------------------------------------------------------------------- #

def test_region_serialization_fields():
    p = make_pipeline([result(text="こんにちは", lang="ja", conf=0.97)])
    d = full_pipeline_result_to_dict(response(p))
    region = d["regions"][0]
    assert region["original_text"] == "こんにちは"
    assert region["translated_text"].startswith("[TR:ja]")
    assert set(region).issuperset({
        "original_text", "translated_text", "confidence", "bbox",
        "translation_time_ms", "source_language", "translation_status",
    })
    assert region["confidence"] == 0.97
    assert region["ocr_confidence"] == 0.97
    assert region["source_language"] == "ja"
    assert region["translation_status"] == "ok"
    assert region["bbox_points"] == [
        [100, 200], [350, 200], [350, 280], [100, 280]
    ]


# --------------------------------------------------------------------------- #
# 3. bbox serialization follows x1/y1/x2/y2 semantics
# --------------------------------------------------------------------------- #

def test_bbox_x1y1x2y2_semantics():
    p = make_pipeline([result(text="x", lang="ja")])
    d = full_pipeline_result_to_dict(response(p))
    bbox = d["regions"][0]["bbox"]
    assert bbox == {"x1": 100, "y1": 200, "x2": 350, "y2": 280}
    assert bbox["x1"] <= bbox["x2"]
    assert bbox["y1"] <= bbox["y2"]


def test_cli_legacy_bbox_shape_is_preserved():
    p = make_pipeline([result(text="x", lang="ja")])
    d = full_pipeline_result_to_dict(response(p), legacy_bbox=True)
    assert d["regions"][0]["bbox"] == [
        [100, 200], [350, 200], [350, 280], [100, 280]
    ]
    assert "bbox_points" not in d["regions"][0]


def test_normalize_bbox_rejects_empty():
    with pytest.raises(ValueError):
        _normalize_bbox([])


# --------------------------------------------------------------------------- #
# 4-6. Explicit language model selection
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("src,expected", [
    ("ja", "ja"),
    ("ko", "ko"),
    ("zh-Hans", "zh-Hans"),
    ("zh-Hant", "zh-Hant"),
])
def test_explicit_source_language_propagated(src, expected):
    p = make_pipeline([result(text="x", lang="ja", conf=0.5)])
    out = response(p, src=src)
    d = full_pipeline_result_to_dict(out)
    assert out.source_language == expected
    # Explicit lang overrides the fake OCR-detected lang.
    assert all(r["source_language"] == expected for r in d["regions"])
    # The translator saw the explicit language for the region.
    assert p._translator.calls == [(expected,)]


def test_zh_hans_hant_map_to_chinese_model():
    provider = MarianMTProvider()
    assert provider._model_key("zh", "en") == "zh-en"
    assert provider._model_key("zh-Hans", "en") == "zh-en"
    assert provider._model_key("zh-Hant", "en") == "zh-en"
    assert provider._model_key("ja", "en") == "ja-en"
    assert provider._model_key("ko", "en") == "ko-en"


def test_ocr_auto_preserves_the_reader_language():
    class Reader:
        def __init__(self, text, x):
            self.text = text
            self.x = x

        def ocr(self, image, cls=True):
            points = [
                [self.x, 10], [self.x + 10, 10],
                [self.x + 10, 20], [self.x, 20],
            ]
            return [[(points, (self.text, 0.95))]]

    engine = OCREngine()
    x_positions = {"ko": 0, "ja": 100, "zh": 200, "zh-Hant": 300}
    engine._get_reader = lambda lang: Reader(lang, x_positions[lang])
    detected = engine.recognize(np.zeros((100, 500, 3), dtype=np.uint8), "auto")
    assert {region.language for region in detected.results} == set(
        engine.SUPPORTED_LANGS
    )


def test_explicit_ocr_language_uses_only_requested_reader():
    called = []

    class Reader:
        def ocr(self, image, cls=True):
            return [[([[10, 10], [20, 10], [20, 20], [10, 20]], ("hello", 0.95))]]

    engine = OCREngine()

    def get_reader(lang):
        called.append(lang)
        return Reader()

    engine._get_reader = get_reader
    result = engine.recognize(np.zeros((100, 100, 3), dtype=np.uint8), "ja")
    assert called == ["ja"]
    assert result.results[0].language == "ja"


def test_grouped_region_uses_confidence_weighted_dominant_language():
    pipeline = OCRPipeline()
    merged = pipeline._merge_group([
        result(text="a", lang="ja", conf=0.8,
               bbox=[[10, 10], [20, 10], [20, 20], [10, 20]]),
        result(text="b", lang="ko", conf=0.9,
               bbox=[[22, 10], [32, 10], [32, 20], [22, 20]]),
        result(text="c", lang="ja", conf=0.95,
               bbox=[[34, 10], [44, 10], [44, 20], [34, 20]]),
    ])
    assert merged.language == "ja"


# --------------------------------------------------------------------------- #
# 7-8. Auto-language: OCR region language drives translation
# --------------------------------------------------------------------------- #

def test_auto_ja_region_uses_japanese():
    p = make_pipeline([result(text="こんにちは", lang="ja")])
    out = response(p, src="auto")
    d = full_pipeline_result_to_dict(out)
    assert out.source_language == "ja"
    assert d["regions"][0]["source_language"] == "ja"
    assert d["regions"][0]["translated_text"].startswith("[TR:ja]")


def test_auto_ko_region_uses_korean():
    p = make_pipeline([result(text="안녕하세요", lang="ko")])
    out = response(p, src="auto")
    d = full_pipeline_result_to_dict(out)
    assert out.source_language == "ko"
    assert d["regions"][0]["source_language"] == "ko"
    assert d["regions"][0]["translated_text"].startswith("[TR:ko]")


# --------------------------------------------------------------------------- #
# 9. Mixed auto-language: grouped by language, batched, original order restored
# --------------------------------------------------------------------------- #

def test_mixed_language_grouping_and_order():
    regions = [
        result(text="jaタイトル", lang="ja", conf=0.9),
        result(text="ko원문", lang="ko", conf=0.8),
        result(text="ja二番目", lang="ja", conf=0.85),
    ]
    p = make_pipeline(regions)
    out = response(p, src="auto")
    d = full_pipeline_result_to_dict(out)

    langs = [r["source_language"] for r in d["regions"]]
    assert langs == ["ja", "ko", "ja"]  # original order preserved

    # Overall dominant is "ja" (0.9 + 0.85 = 1.75 vs ko 0.8).
    assert out.source_language == "ja"

    # Each region translated with its detected language.
    texts = [r["translated_text"] for r in d["regions"]]
    assert texts[0].startswith("[TR:ja]")
    assert texts[1].startswith("[TR:ko]")
    assert texts[2].startswith("[TR:ja]")


def test_full_pipeline_preserves_mixed_language_labels():
    regions = [
        result(text="a", lang="ja"),
        result(text="b", lang="ko"),
    ]
    p = make_pipeline(regions)
    response(p, src="auto")
    # The mixed provider batching behavior is tested separately below.
    langs = {c[0] for c in p._translator.calls}
    assert langs == {"ja", "ko"}


def test_translation_engine_batches_by_language_and_restores_order():
    class RecordingProvider:
        def __init__(self):
            self.calls = []

        def translate(self, texts, source_lang, target_lang):
            self.calls.append((list(texts), source_lang, target_lang))
            return [
                TranslationResult(
                    original_text=text,
                    translated_text=f"{source_lang}:{text}",
                    source_language=source_lang,
                    target_language=target_lang,
                    confidence=0.9,
                    processing_time_ms=1.0,
                )
                for text in texts
            ]

    provider = RecordingProvider()
    engine = TranslationEngine(provider)
    translated = engine.translate_mixed(
        [("first", "ja"), ("second", "ko"), ("third", "ja")]
    )

    assert provider.calls == [
        (["first", "third"], "ja", "en"),
        (["second"], "ko", "en"),
    ]
    assert [result.translated_text for result in translated] == [
        "ja:first", "ko:second", "ja:third"
    ]


def test_unknown_region_language_reports_fallback_without_model_lookup():
    engine = TranslationEngine()
    result = engine.translate_mixed([("unlabeled", None)])[0]
    assert result.translated_text == "unlabeled"
    assert result.source_language == "unknown"
    assert result.status == "fallback"


def test_model_unavailable_reports_fallback_without_claiming_success():
    provider = MarianMTProvider()

    def missing_local_model(model_key):
        raise FileNotFoundError(model_key)

    provider._load_model = missing_local_model
    result = provider.translate(["original"], "ja", "en")[0]
    assert result.translated_text == "original"
    assert result.status == "fallback"
    assert result.confidence == 0.0


# --------------------------------------------------------------------------- #
# 10. No OCR regions -> valid empty response
# --------------------------------------------------------------------------- #

def test_no_regions_returns_empty():
    p = make_pipeline([])
    out = response(p, src="auto")
    d = full_pipeline_result_to_dict(out)
    assert d["regions"] == []
    assert d["num_regions"] == 0
    assert out.source_language == "unknown"
    assert d["image"]["width"] == 1200


# --------------------------------------------------------------------------- #
# 11. HTTP API does not use uploaded filename as authoritative language
# --------------------------------------------------------------------------- #

def test_http_api_ignores_filename_as_language():
    # The /translate endpoint only accepts a source_language request field,
    # and the pipeline resolves language from OCR regions, never the filename.
    from fastapi import HTTPException
    from backend.main import VALID_SOURCE_LANGUAGES, _validate_source_language

    # A random string / filename is NOT a valid source language.
    filename_like = r"c:\path\some_japan.png"
    assert filename_like not in VALID_SOURCE_LANGUAGES
    with pytest.raises(HTTPException):
        _validate_source_language(filename_like)

    # auto is valid and must be treated as auto (OCR decides), not as a lang.
    assert "auto" in VALID_SOURCE_LANGUAGES
    _validate_source_language("auto")


# --------------------------------------------------------------------------- #
# FastAPI-level smoke test (stubs pipeline singletons)
# --------------------------------------------------------------------------- #

def test_fastapi_translate_returns_new_shape():
    """Drive FastAPI with a stubbed pipeline to assert the HTTP response."""
    import backend.main as main_mod

    # Stub the two lazy singletons so no OCR/MT models load.
    main_mod._full_pipeline = make_pipeline([result(text="こんにちは", lang="ja")])

    img_bytes = make_image_png()  # valid PNG; OCR is stubbed

    resp = post_app(
        main_mod.app,
        "/translate",
        # Deliberately conflicts with the stub's Japanese OCR language.
        files={"image": ("korean.png", img_bytes, "image/png")},
        data={"source_language": "auto", "target_language": "en"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_version"] == "1"
    assert body["source_language"] == "ja"
    assert body["image"] == {"width": 1200, "height": 1800}
    assert body["regions"][0]["source_language"] == "ja"
    assert "bbox" in body["regions"][0]
    assert body["regions"][0]["ocr_confidence"] == 0.95


def test_fastapi_translate_rejects_unsupported_language():
    import backend.main as main_mod

    img_bytes = make_image_png()
    resp = post_app(
        main_mod.app,
        "/translate",
        files={"image": ("whatever.png", img_bytes, "image/png")},
        data={"source_language": "not-a-lang"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_SOURCE_LANGUAGE"
    assert "source_language" in resp.json()["error"]["message"]


def test_fastapi_translate_rejects_unsupported_target_language():
    import backend.main as main_mod

    resp = post_app(
        main_mod.app,
        "/translate",
        files={"image": ("valid.png", make_image_png(), "image/png")},
        data={"source_language": "ja", "target_language": "fr"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_TARGET_LANGUAGE"
    assert "target_language" in resp.json()["error"]["message"]


def test_fastapi_translate_rejects_malformed_image_cleanly():
    import backend.main as main_mod

    resp = post_app(
        main_mod.app,
        "/translate",
        files={
            "image": (
                "broken.png",
                b"\x89PNG\r\n\x1a\nnot-an-image",
                "image/png",
            )
        },
        data={"source_language": "auto", "target_language": "en"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_IMAGE"
    assert "Malformed" in resp.json()["error"]["message"]


def test_fastapi_translate_rejects_empty_upload():
    import backend.main as main_mod

    resp = post_app(
        main_mod.app,
        "/translate",
        files={"image": ("empty.png", b"", "image/png")},
        data={"source_language": "auto", "target_language": "en"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "EMPTY_IMAGE"
    assert "Empty image" in resp.json()["error"]["message"]


def test_fastapi_translate_returns_empty_regions_without_ocr_results():
    import backend.main as main_mod

    main_mod._full_pipeline = make_pipeline([])
    resp = post_app(
        main_mod.app,
        "/translate",
        files={"image": ("empty-results.png", make_image_png(), "image/png")},
        data={"source_language": "auto", "target_language": "en"},
    )
    assert resp.status_code == 200
    assert resp.json()["regions"] == []
    assert resp.json()["source_language"] == "unknown"
