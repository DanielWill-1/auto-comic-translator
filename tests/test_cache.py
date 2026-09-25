"""Persistent translation-cache checks without OCR or translation models."""

from __future__ import annotations

import asyncio
import io
import sqlite3
import sys
import threading
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.cache import (
    TranslationCache,
    build_cache_identity,
    processing_config_fingerprint,
)
from backend.config import PipelineConfig, PreprocessingConfig
from backend.full_pipeline import FullPipelineResult, TranslatedRegion
from backend.main import app


def png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (120, 120), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def api_result(
    *, source_language: str = "ja", status: str = "ok", with_region: bool = True
) -> FullPipelineResult:
    regions = []
    if with_region:
        regions.append(TranslatedRegion(
            original_text="漫画のテキスト",
            translated_text=(
                "Manga text" if status == "ok" else "漫画のテキスト"
            ),
            confidence=0.93,
            bbox=[[10, 20], [50, 20], [50, 40], [10, 40]],
            translation_time_ms=3.5,
            source_language=source_language,
            translation_status=status,
        ))
    return FullPipelineResult(
        api_version="1",
        source_language=source_language if with_region else "unknown",
        target_language="en",
        image_width=120,
        image_height=120,
        ocr_time_ms=10.0,
        translation_time_ms=3.5 if with_region else 0.0,
        total_time_ms=13.5 if with_region else 10.0,
        num_regions=len(regions),
        regions=regions,
    )


def post_translate(image: bytes, *, source: str = "ja"):
    async def send_request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(
                "/translate",
                files={"image": ("page.png", image, "image/png")},
                data={"source_language": source, "target_language": "en"},
            )

    return asyncio.run(send_request())


def install_cache(monkeypatch, tmp_path) -> TranslationCache:
    import backend.main as main_module

    cache = TranslationCache(tmp_path / "translation-cache.sqlite3")
    monkeypatch.setattr(main_module, "_translation_cache", cache)
    return cache


def test_first_request_misses_then_identical_request_hits_with_full_contract(
    monkeypatch, tmp_path
):
    import backend.main as main_module

    cache = install_cache(monkeypatch, tmp_path)
    calls = 0

    class MockPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            return api_result(source_language=source_language)

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: MockPipeline())
    image = png_bytes()
    miss = post_translate(image)
    hit = post_translate(image)

    assert miss.status_code == hit.status_code == 200
    first, second = miss.json(), hit.json()
    assert first["cache"]["hit"] is False
    assert second["cache"]["hit"] is True
    assert second["cache"]["lookup_time_ms"] >= 0
    assert calls == 1
    assert first["regions"][0]["bbox"] == second["regions"][0]["bbox"] == {
        "x1": 10, "y1": 20, "x2": 50, "y2": 40
    }
    region = second["regions"][0]
    assert region["bbox_points"] == [[10, 20], [50, 20], [50, 40], [10, 40]]
    assert region["source_language"] == "ja"
    assert region["ocr_confidence"] == region["confidence"] == 0.93
    assert region["translation_status"] == "ok"
    assert second["ocr_time_ms"] == 0.0
    assert second["translation_time_ms"] == 0.0
    assert second["total_time_ms"] == 0.0
    assert region["translation_time_ms"] == 0.0

    stats = cache.stats()
    assert stats["entry_count"] == 1
    assert stats["total_hits"] == 1
    with sqlite3.connect(cache.path) as connection:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(translation_cache)"
            )
        }
        stored_json = connection.execute(
            "SELECT result_json FROM translation_cache"
        ).fetchone()[0]
    assert "image_bytes" not in columns
    assert "result_json" in columns
    assert image not in cache.path.read_bytes()
    assert "漫画のテキスト" in stored_json


def test_cache_identity_changes_for_image_languages_fingerprint_and_schema():
    def identity(image, source="ja", target="en", fingerprint="fp", schema=1):
        return build_cache_identity(
            image, source, target, fingerprint, schema_version=schema
        )

    baseline = identity(b"image")
    assert identity(b"different image").cache_key != baseline.cache_key
    assert identity(b"image", source="ko").cache_key != baseline.cache_key
    assert identity(b"image", target="fr").cache_key != baseline.cache_key
    assert identity(b"image", fingerprint="changed").cache_key != baseline.cache_key
    assert identity(b"image", schema=2).cache_key != baseline.cache_key


def test_processing_fingerprint_tracks_processing_configuration():
    baseline = processing_config_fingerprint(PipelineConfig(use_gpu=False))
    changed_preprocessing = processing_config_fingerprint(
        PipelineConfig(
            preprocessing=PreprocessingConfig(clahe_clip_limit=3.0),
            use_gpu=False,
        )
    )
    changed_grouping = processing_config_fingerprint(
        PipelineConfig(text_group_proximity_px=20, use_gpu=False)
    )
    changed_schema = processing_config_fingerprint(
        PipelineConfig(use_gpu=False), schema_version=2
    )
    assert changed_preprocessing != baseline
    assert changed_grouping != baseline
    assert changed_schema != baseline


def test_cache_survives_a_new_instance_and_clear_and_stats_work(tmp_path):
    first_cache = TranslationCache(tmp_path / "cache.sqlite3")
    identity = build_cache_identity(b"image", "ja", "en", "fingerprint")
    from backend.full_pipeline import full_pipeline_result_to_dict

    stored = full_pipeline_result_to_dict(api_result())
    assert first_cache.put(identity, stored)

    second_cache = TranslationCache(tmp_path / "cache.sqlite3")
    assert second_cache.get(identity)["regions"][0]["translated_text"] == "Manga text"
    assert second_cache.stats()["entry_count"] == 1
    assert second_cache.stats()["total_hits"] == 1
    assert second_cache.clear() == 1
    assert second_cache.stats()["entry_count"] == 0


def test_cache_management_cli_uses_configured_path(monkeypatch, tmp_path, capsys):
    import backend.config as config_module
    import backend.cache as cache_module
    from backend.full_pipeline import full_pipeline_result_to_dict

    cache_path = tmp_path / "cli-cache.sqlite3"
    monkeypatch.setattr(config_module, "CACHE_PATH", cache_path)
    cache = TranslationCache(cache_path)
    identity = build_cache_identity(b"image", "ja", "en", "fp")
    assert cache.put(identity, full_pipeline_result_to_dict(api_result()))

    monkeypatch.setattr(sys, "argv", ["backend.cache", "stats"])
    assert cache_module._run_cli() == 0
    assert '"entry_count": 1' in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["backend.cache", "clear"])
    assert cache_module._run_cli() == 0
    assert "Cleared 1" in capsys.readouterr().out
    assert not cache.stats()["entry_count"]


def test_disabled_cache_never_looks_up_or_writes(monkeypatch, tmp_path):
    import backend.main as main_module

    disabled = TranslationCache(tmp_path / "disabled.sqlite3", enabled=False)
    monkeypatch.setattr(main_module, "_translation_cache", disabled)
    calls = 0

    class MockPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            return api_result()

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: MockPipeline())
    first, second = post_translate(png_bytes()), post_translate(png_bytes())

    assert first.status_code == second.status_code == 200
    assert "cache" not in first.json()
    assert "cache" not in second.json()
    assert calls == 2
    assert not disabled.path.exists()


def test_fallback_results_are_not_cached(monkeypatch, tmp_path):
    import backend.main as main_module

    cache = install_cache(monkeypatch, tmp_path)
    calls = 0

    class FallbackPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            return api_result(source_language=source_language, status="fallback")

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: FallbackPipeline())
    first, second = post_translate(png_bytes()), post_translate(png_bytes())

    assert first.json()["regions"][0]["translation_status"] == "fallback"
    assert first.json()["cache"]["hit"] is False
    assert second.json()["cache"]["hit"] is False
    assert calls == 2
    assert cache.stats()["entry_count"] == 0


def test_successful_empty_region_result_is_cached(monkeypatch, tmp_path):
    import backend.main as main_module

    install_cache(monkeypatch, tmp_path)
    calls = 0

    class EmptyPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            return api_result(with_region=False)

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: EmptyPipeline())
    first, second = post_translate(png_bytes()), post_translate(png_bytes())

    assert first.json()["regions"] == []
    assert first.json()["cache"]["hit"] is False
    assert second.json()["cache"]["hit"] is True
    assert calls == 1


def test_corrupt_json_is_a_cache_miss_and_inference_recovers(monkeypatch, tmp_path):
    import backend.main as main_module

    cache = install_cache(monkeypatch, tmp_path)
    calls = 0

    class MockPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            return api_result(source_language=source_language)

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: MockPipeline())
    image = png_bytes()
    post_translate(image)
    with sqlite3.connect(cache.path) as connection:
        connection.execute(
            "UPDATE translation_cache SET result_json = ?", ("{invalid",)
        )
    recovered = post_translate(image)

    assert recovered.status_code == 200
    assert recovered.json()["cache"]["hit"] is False
    assert recovered.json()["regions"][0]["translated_text"] == "Manga text"
    assert calls == 2


def test_changed_source_fingerprint_and_schema_miss(monkeypatch, tmp_path):
    import backend.main as main_module

    install_cache(monkeypatch, tmp_path)
    calls = 0

    class MockPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            return api_result(source_language=source_language)

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: MockPipeline())
    image = png_bytes()
    post_translate(image, source="ja")
    changed_image = post_translate(png_bytes(color="black"))
    changed_source = post_translate(image, source="ko")

    monkeypatch.setattr(
        main_module, "processing_config_fingerprint",
        lambda config, schema_version: "test-fingerprint-v2",
    )
    changed_fingerprint = post_translate(image, source="ko")
    monkeypatch.setattr(main_module, "CACHE_SCHEMA_VERSION", 2)
    changed_schema = post_translate(image, source="ko")

    assert changed_image.json()["cache"]["hit"] is False
    assert changed_source.json()["cache"]["hit"] is False
    assert changed_fingerprint.json()["cache"]["hit"] is False
    assert changed_schema.json()["cache"]["hit"] is False
    assert calls == 5


def test_pipeline_errors_are_not_cached(monkeypatch, tmp_path):
    import backend.main as main_module

    cache = install_cache(monkeypatch, tmp_path)
    calls = 0

    class BrokenPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            calls += 1
            raise RuntimeError("mock inference failure")

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: BrokenPipeline())
    image = png_bytes()
    first, second = post_translate(image), post_translate(image)

    assert first.status_code == second.status_code == 500
    assert calls == 2
    assert cache.stats()["entry_count"] == 0


def test_hostile_language_value_is_stored_as_parameterized_data(tmp_path):
    cache = TranslationCache(tmp_path / "cache.sqlite3")
    hostile_source = "ja'); DROP TABLE translation_cache; --"
    identity = build_cache_identity(b"image", hostile_source, "en", "fp")
    from backend.full_pipeline import full_pipeline_result_to_dict

    stored = full_pipeline_result_to_dict(api_result())
    assert cache.put(identity, stored)
    assert cache.get(identity) == stored
    assert cache.stats()["entry_count"] == 1


def test_concurrent_duplicate_requests_only_run_pipeline_once(monkeypatch, tmp_path):
    import backend.main as main_module

    install_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(main_module, "_inference_semaphore", asyncio.Semaphore(1))
    calls = 0
    calls_lock = threading.Lock()

    class SlowPipeline:
        def run(self, image, source_language, target_language):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.08)
            return api_result(source_language=source_language)

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: SlowPipeline())

    async def send_concurrent_requests():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await asyncio.gather(*[
                client.post(
                    "/translate",
                    files={"image": ("page.png", png_bytes(), "image/png")},
                    data={"source_language": "ja", "target_language": "en"},
                )
                for _ in range(2)
            ])

    responses = asyncio.run(send_concurrent_requests())
    bodies = [response.json() for response in responses]

    assert all(response.status_code == 200 for response in responses)
    assert calls == 1
    assert sorted(body["cache"]["hit"] for body in bodies) == [False, True]
