"""Loopback HTTP checks with a real image and local models; opt-in only."""

from __future__ import annotations

import asyncio
import io
import socket
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "datas" / "japanes" / "Screenshot 2026-06-29 122805.png"
EXTENSION_ORIGIN = "chrome-extension://" + ("a" * 32)
CHINESE_SAMPLE = (
    ROOT / "datas" / "chinese" / "Screenshot 2026-09-26 015428.png"
)


def _terminal_safe(value: str) -> str:
    return value.encode("ascii", errors="backslashreplace").decode("ascii")


@pytest.mark.integration
def test_live_http_japanese_miss_hit_cors_and_safe_errors(
    monkeypatch, tmp_path
):
    import httpx
    import uvicorn

    from backend.cache import TranslationCache
    from backend.main import app
    import backend.main as main_module

    if not SAMPLE.is_file():
        pytest.skip("The local Japanese sample panel is missing.")

    cache = TranslationCache(tmp_path / "phase255-live-cache.sqlite3")
    monkeypatch.setattr(main_module, "_translation_cache", cache)
    monkeypatch.setattr(
        main_module, "_inference_semaphore", asyncio.Semaphore(1)
    )

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    ))
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    server_thread.start()
    try:
        startup_deadline = time.monotonic() + 20
        while not server.started:
            if not server_thread.is_alive():
                pytest.fail("The local uvicorn server failed to start.")
            if time.monotonic() >= startup_deadline:
                pytest.fail("The local uvicorn server did not become ready.")
            time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        image_bytes = SAMPLE.read_bytes()
        with httpx.Client(base_url=base_url, timeout=180) as client:
            health = client.get("/health")
            ready = client.get("/ready")
            assert health.status_code == 200
            assert health.json()["api_version"] == "1"
            assert ready.status_code in {200, 503}
            assert isinstance(ready.json()["ocr_ready"], bool)
            assert isinstance(ready.json()["translation_ready"], bool)
            all_models_ready = (
                ready.json()["ocr_ready"]
                and ready.json()["translation_ready"]
            )
            assert ready.status_code == (200 if all_models_ready else 503)

            allowed_preflight = client.options(
                "/translate",
                headers={
                    "Origin": EXTENSION_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,x-request-id",
                },
            )
            denied_preflight = client.options(
                "/translate",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
            assert allowed_preflight.status_code == 200
            assert allowed_preflight.headers["access-control-allow-origin"] == (
                EXTENSION_ORIGIN
            )
            assert denied_preflight.status_code == 400
            assert "access-control-allow-origin" not in denied_preflight.headers

            def translate(request_id):
                return client.post(
                    "/translate",
                    files={"image": ("panel.png", image_bytes, "image/png")},
                    data={"source_language": "ja", "target_language": "en"},
                    headers={"X-Request-ID": request_id},
                )

            miss = translate("phase255-real-miss")
            hit = translate("phase255-real-hit")
            assert miss.status_code == hit.status_code == 200
            assert miss.headers["x-request-id"] == "phase255-real-miss"
            assert hit.headers["x-request-id"] == "phase255-real-hit"
            first, cached = miss.json(), hit.json()
            assert first["api_version"] == cached["api_version"] == "1"
            assert first["image"] == cached["image"] == {
                "width": 436, "height": 654
            }
            assert first["cache"]["hit"] is False
            assert cached["cache"]["hit"] is True
            assert first["num_regions"] > 0
            assert len(first["regions"]) == len(cached["regions"])
            stable_region_fields = (
                "original_text",
                "translated_text",
                "bbox",
                "bbox_points",
                "ocr_confidence",
                "source_language",
                "translation_status",
            )
            for original, replayed in zip(first["regions"], cached["regions"]):
                assert all(
                    original[field] == replayed[field]
                    for field in stable_region_fields
                )
                assert original["source_language"] == "ja"
                assert original["translation_status"] == "ok"
                assert original["translated_text"].strip()
                assert 0.0 <= original["ocr_confidence"] <= 1.0
                points = original["bbox_points"]
                assert points and all(
                    0 <= x < first["image"]["width"]
                    and 0 <= y < first["image"]["height"]
                    for x, y in points
                )
                print(
                    "Japanese sanity:",
                    _terminal_safe(repr(original["original_text"][:100])),
                    "->",
                    _terminal_safe(repr(original["translated_text"][:100])),
                    original["translation_status"],
                )

            timing = first["timing"]
            cached_timing = cached["timing"]
            assert timing["request_total_ms"] > 0
            assert timing["ocr_ms"] > 0
            assert timing["translation_ms"] > 0
            assert cached_timing["ocr_ms"] == 0.0
            assert cached_timing["translation_ms"] == 0.0
            assert cached_timing["inference_wait_ms"] == 0.0
            assert cached["ocr_time_ms"] == 0.0
            assert cached["translation_time_ms"] == 0.0
            assert cached["total_time_ms"] == 0.0

            malformed = client.post(
                "/translate",
                files={"image": ("bad.png", b"not an image", "image/png")},
                data={"source_language": "ja", "target_language": "en"},
            )
            unsupported_source = client.post(
                "/translate",
                files={"image": ("panel.png", image_bytes, "image/png")},
                data={"source_language": "fr", "target_language": "en"},
            )
            unsupported_target = client.post(
                "/translate",
                files={"image": ("panel.png", image_bytes, "image/png")},
                data={"source_language": "ja", "target_language": "fr"},
            )
            empty = client.post(
                "/translate",
                files={"image": ("empty.png", b"", "image/png")},
                data={"source_language": "ja", "target_language": "en"},
            )
            oversized = client.post(
                "/translate",
                files={
                    "image": (
                        "large.png",
                        b"0" * (20 * 1024 * 1024 + 1),
                        "image/png",
                    )
                },
                data={"source_language": "ja", "target_language": "en"},
            )
            expected_errors = (
                (malformed, 400, "UNSUPPORTED_IMAGE_FORMAT"),
                (unsupported_source, 400, "UNSUPPORTED_SOURCE_LANGUAGE"),
                (unsupported_target, 400, "UNSUPPORTED_TARGET_LANGUAGE"),
                (empty, 400, "EMPTY_IMAGE"),
                (oversized, 413, "IMAGE_TOO_LARGE"),
            )
            for response, status_code, error_code in expected_errors:
                assert response.status_code == status_code
                body = response.json()
                assert body["api_version"] == "1"
                assert body["error"]["code"] == error_code
                assert body["error"]["request_id"] == response.headers[
                    "x-request-id"
                ]
                assert "Traceback" not in response.text
                assert str(ROOT) not in response.text
    finally:
        server.should_exit = True
        server_thread.join(timeout=15)
        if server_thread.is_alive():
            server.force_exit = True
            server_thread.join(timeout=5)
        listener.close()
        assert not server_thread.is_alive()


@pytest.mark.integration
def test_live_http_chinese_cache_miss_hit(monkeypatch, tmp_path):
    if not CHINESE_SAMPLE.is_file():
        pytest.skip("The selected simplified Chinese sample is missing.")

    # Preserve Torch-before-Paddle import order on Windows.
    import backend.translate  # noqa: F401

    from backend.ocr import (
        _PADDLE_LANG_MAP,
        _PADDLE_MODEL_FILES,
        _paddle_model_directories,
    )
    from paddleocr import paddleocr as paddleocr_module

    paddle_language = _PADDLE_LANG_MAP["zh-Hans"]
    model_directories = _paddle_model_directories(
        paddleocr_module, paddle_language
    )
    if not all(
        all((directory / filename).is_file() for filename in _PADDLE_MODEL_FILES)
        for directory in model_directories
    ):
        pytest.skip("Local simplified Chinese PaddleOCR assets are missing.")

    import httpx
    import uvicorn

    from backend.cache import TranslationCache
    from backend.main import app
    import backend.main as main_module

    cache = TranslationCache(tmp_path / "phase255-chinese-cache.sqlite3")
    monkeypatch.setattr(main_module, "_translation_cache", cache)
    monkeypatch.setattr(
        main_module, "_inference_semaphore", asyncio.Semaphore(1)
    )

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
    ))
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    server_thread.start()
    try:
        startup_deadline = time.monotonic() + 20
        while not server.started:
            if not server_thread.is_alive():
                pytest.fail("The local uvicorn server failed to start.")
            if time.monotonic() >= startup_deadline:
                pytest.fail("The local uvicorn server did not become ready.")
            time.sleep(0.05)

        image_bytes = CHINESE_SAMPLE.read_bytes()
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=180
        ) as client:
            def translate(request_id):
                return client.post(
                    "/translate",
                    files={
                        "image": (
                            CHINESE_SAMPLE.name,
                            image_bytes,
                            "image/png",
                        )
                    },
                    data={
                        "source_language": "zh-Hans",
                        "target_language": "en",
                    },
                    headers={"X-Request-ID": request_id},
                )

            miss = translate("phase255-chinese-miss")
            hit = translate("phase255-chinese-hit")
            assert miss.status_code == hit.status_code == 200
            assert miss.headers["x-request-id"] == "phase255-chinese-miss"
            assert hit.headers["x-request-id"] == "phase255-chinese-hit"
            first, cached = miss.json(), hit.json()
            assert first["api_version"] == cached["api_version"] == "1"
            assert first["source_language"] == cached["source_language"] == (
                "zh-Hans"
            )
            assert first["image"] == cached["image"] == {
                "width": 773, "height": 356
            }
            assert first["cache"]["hit"] is False
            assert cached["cache"]["hit"] is True
            assert first["num_regions"] > 0
            assert len(first["regions"]) == len(cached["regions"])
            stable_fields = (
                "original_text",
                "translated_text",
                "bbox",
                "bbox_points",
                "ocr_confidence",
                "source_language",
                "translation_status",
            )
            for original, replayed in zip(first["regions"], cached["regions"]):
                assert all(
                    original[field] == replayed[field]
                    for field in stable_fields
                )
                assert original["source_language"] == "zh-Hans"
                assert original["translated_text"].strip()
                assert original["translation_status"] == "ok"
                assert 0.0 <= original["ocr_confidence"] <= 1.0
                box = original["bbox"]
                assert set(box) == {"x1", "y1", "x2", "y2"}
                assert 0 <= box["x1"] <= box["x2"] < first["image"]["width"]
                assert 0 <= box["y1"] <= box["y2"] < first["image"]["height"]
                assert original["bbox_points"]
                assert all(
                    0 <= x < first["image"]["width"]
                    and 0 <= y < first["image"]["height"]
                    for x, y in original["bbox_points"]
                )
            assert first["timing"]["ocr_ms"] > 0
            assert first["timing"]["translation_ms"] > 0
            assert cached["timing"]["ocr_ms"] == 0.0
            assert cached["timing"]["translation_ms"] == 0.0
            assert cached["timing"]["inference_wait_ms"] == 0.0
            example = first["regions"][0]
            print(
                "Chinese HTTP sanity:",
                _terminal_safe(repr(example["original_text"][:100])),
                "->",
                _terminal_safe(repr(example["translated_text"][:100])),
                example["translation_status"],
            )
    finally:
        server.should_exit = True
        server_thread.join(timeout=15)
        if server_thread.is_alive():
            server.force_exit = True
            server_thread.join(timeout=5)
        listener.close()
        assert not server_thread.is_alive()
