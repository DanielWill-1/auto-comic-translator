"""API timing tests using mocked pipelines and no model initialization."""

from __future__ import annotations

import asyncio
import io
import logging
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.cache import TranslationCache
from backend.full_pipeline import (
    FullPipelineResult,
    PipelineTimings,
    TranslatedRegion,
)
from backend.ocr import OCRResponse
from backend.main import app
from backend.pipeline import OCRPipeline
from backend.translate import TranslationEngine, TranslationResult

TIMING_FIELDS = (
    "request_total_ms",
    "validation_ms",
    "preprocessing_ms",
    "ocr_ms",
    "grouping_ms",
    "translation_ms",
    "serialization_ms",
    "cache_lookup_ms",
    "cache_write_ms",
    "inference_wait_ms",
    "ocr_model_load_ms",
    "translation_model_load_ms",
)


def png_bytes() -> bytes:
    image = Image.new("RGB", (120, 120), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def pipeline_result() -> FullPipelineResult:
    return FullPipelineResult(
        api_version="1",
        source_language="ja",
        target_language="en",
        image_width=120,
        image_height=120,
        ocr_time_ms=12.0,
        translation_time_ms=4.0,
        total_time_ms=20.0,
        num_regions=1,
        regions=[TranslatedRegion(
            original_text="PRIVATE OCR SENTENCE",
            translated_text="PRIVATE TRANSLATION SENTENCE",
            confidence=0.92,
            bbox=[[10, 20], [50, 20], [50, 40], [10, 40]],
            translation_time_ms=4.0,
            source_language="ja",
        )],
        timings=PipelineTimings(
            preprocessing_ms=1.0,
            ocr_ms=2.0,
            grouping_ms=0.5,
            translation_ms=4.0,
            ocr_model_load_ms=3.0,
            translation_model_load_ms=5.0,
        ),
    )


def post_translate(*, headers=None):
    async def send_request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(
                "/translate",
                files={"image": ("page.png", png_bytes(), "image/png")},
                data={"source_language": "ja", "target_language": "en"},
                headers=headers,
            )

    return asyncio.run(send_request())


def test_cache_miss_and_hit_expose_consistent_timing(monkeypatch, tmp_path, caplog):
    import backend.main as main_module

    cache = TranslationCache(tmp_path / "timing-cache.sqlite3", enabled=True)
    monkeypatch.setattr(main_module, "_translation_cache", cache)
    calls = 0

    class MockPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            return pipeline_result()

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: MockPipeline())
    caplog.set_level(logging.INFO, logger="auto-comic-translator")
    miss = post_translate(headers={"X-Request-ID": "timing-miss-1"})
    hit = post_translate(headers={"X-Request-ID": "timing-hit-2"})

    assert miss.status_code == hit.status_code == 200
    assert miss.headers["x-request-id"] == "timing-miss-1"
    assert hit.headers["x-request-id"] == "timing-hit-2"
    first, cached = miss.json(), hit.json()
    assert first["api_version"] == cached["api_version"] == "1"
    assert first["cache"]["hit"] is False
    assert cached["cache"]["hit"] is True
    assert first["ocr_time_ms"] == 12.0
    assert first["translation_time_ms"] == 4.0
    assert first["total_time_ms"] == 20.0
    assert calls == 1

    for body in (first, cached):
        timing = body["timing"]
        assert set(TIMING_FIELDS).issubset(timing)
        assert all(
            isinstance(timing[field], (int, float)) and timing[field] >= 0
            for field in TIMING_FIELDS
        )
    assert first["timing"]["preprocessing_ms"] == 1.0
    assert first["timing"]["ocr_ms"] == 2.0
    assert first["timing"]["grouping_ms"] == 0.5
    assert first["timing"]["translation_ms"] == 4.0
    assert first["timing"]["ocr_model_load_ms"] == 3.0
    assert first["timing"]["translation_model_load_ms"] == 5.0
    assert first["timing"]["cache_lookup_ms"] == pytest.approx(
        first["cache"]["lookup_time_ms"], abs=0.001
    )
    for field in (
        "preprocessing_ms",
        "ocr_ms",
        "grouping_ms",
        "translation_ms",
        "ocr_model_load_ms",
        "translation_model_load_ms",
    ):
        assert cached["timing"][field] == 0.0
    assert cached["ocr_time_ms"] == 0.0
    assert cached["translation_time_ms"] == 0.0
    assert cached["total_time_ms"] == 0.0
    assert cached["timing"]["inference_wait_ms"] == 0.0
    assert "translation_performance" in caplog.text
    assert "PRIVATE OCR SENTENCE" not in caplog.text
    assert "PRIVATE TRANSLATION SENTENCE" not in caplog.text


def test_queued_request_reports_semaphore_wait(monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(main_module, "_inference_semaphore", asyncio.Semaphore(1))
    calls = 0
    lock = threading.Lock()

    class SlowPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.06)
            return pipeline_result()

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: SlowPipeline())

    async def send_two_requests():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            requests = [
                client.post(
                    "/translate",
                    files={"image": ("page.png", png_bytes(), "image/png")},
                    data={"source_language": "ja", "target_language": "en"},
                )
                for _ in range(2)
            ]
            return await asyncio.gather(*requests)

    responses = asyncio.run(send_two_requests())
    assert all(response.status_code == 200 for response in responses)
    wait_times = [
        response.json()["timing"]["inference_wait_ms"] for response in responses
    ]
    assert all(value >= 0 for value in wait_times)
    assert max(wait_times) > min(wait_times)
    assert calls == 2


def test_waiting_duplicate_cache_hit_reports_wait_without_inference(
    monkeypatch, tmp_path
):
    import backend.main as main_module

    cache = TranslationCache(tmp_path / "queued-hit-cache.sqlite3", enabled=True)
    monkeypatch.setattr(main_module, "_translation_cache", cache)
    monkeypatch.setattr(main_module, "_inference_semaphore", asyncio.Semaphore(1))
    calls = 0

    class SlowPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            time.sleep(0.06)
            return pipeline_result()

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: SlowPipeline())

    async def send_duplicate_requests():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            requests = [
                client.post(
                    "/translate",
                    files={"image": ("page.png", png_bytes(), "image/png")},
                    data={"source_language": "ja", "target_language": "en"},
                )
                for _ in range(2)
            ]
            return await asyncio.gather(*requests)

    responses = asyncio.run(send_duplicate_requests())
    assert all(response.status_code == 200 for response in responses)
    bodies = [response.json() for response in responses]
    assert sorted(body["cache"]["hit"] for body in bodies) == [False, True]
    wait_times = [body["timing"]["inference_wait_ms"] for body in bodies]
    assert all(value >= 0 for value in wait_times)
    assert max(wait_times) > min(wait_times)
    cached = next(body for body in bodies if body["cache"]["hit"])
    assert cached["timing"]["ocr_ms"] == 0.0
    assert cached["timing"]["translation_ms"] == 0.0
    assert cached["timing"]["inference_wait_ms"] > 0.0
    assert calls == 1


def test_ocr_pipeline_reports_measured_stage_fields():
    class FakePreprocessor:
        def enhance(self, image):
            return image

    class FakeOCREngine:
        def recognize(self, image, source_language):
            return OCRResponse(
                results=[],
                source_language=source_language,
                num_text_regions=0,
                average_confidence=0.0,
                processing_time_ms=9.0,
                ocr_engine_time_ms=2.5,
                model_load_time_ms=1.5,
            )

    pipeline = OCRPipeline()
    pipeline._preprocessor = FakePreprocessor()
    pipeline._ocr = FakeOCREngine()
    _, timings = pipeline.run_with_grouping_timed(
        Image.new("RGB", (2, 2)), source_language="ja"
    )

    assert timings.preprocessing_ms >= 0
    assert timings.ocr_ms == 2.5
    assert timings.grouping_ms >= 0
    assert timings.ocr_model_load_ms == 1.5


def test_translation_engine_reports_provider_and_model_load_timings():
    class FakeProvider:
        def translate_with_timings(self, texts, source_lang, target_lang):
            return ([
                TranslationResult(
                    original_text=texts[0],
                    translated_text="translated",
                    source_language=source_lang,
                    target_language=target_lang,
                    confidence=0.9,
                    processing_time_ms=1.0,
                )
            ], 3.5)

    results, translation_ms, model_load_ms = TranslationEngine(
        provider=FakeProvider()
    ).translate_mixed_with_timings([("source", "ja")], "en")

    assert len(results) == 1
    assert translation_ms >= 0
    assert model_load_ms == 3.5
