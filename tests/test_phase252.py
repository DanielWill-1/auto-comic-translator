"""Phase 2.5.2 API hardening checks; no OCR or translation models are loaded."""

from __future__ import annotations

import asyncio
import io
import json
import re
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

from backend.config import MAX_IMAGE_SIZE_BYTES, MAX_REQUEST_BODY_BYTES
from backend.full_pipeline import FullPipelineResult, TranslatedRegion
from backend.main import RequestContextMiddleware, _local_marian_model_ready, app
from backend.ocr import OCRResponse


def request_app(app_instance, method: str, path: str, **kwargs):
    async def send_request():
        transport = httpx.ASGITransport(app=app_instance)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send_request())


def png_bytes() -> bytes:
    image = Image.new("RGB", (120, 120), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def translate_request(image_bytes: bytes, **kwargs):
    data = kwargs.pop(
        "data", {"source_language": "ja", "target_language": "en"}
    )
    return request_app(
        app,
        "POST",
        "/translate",
        files={"image": ("page.png", image_bytes, "image/png")},
        data=data,
        **kwargs,
    )


def test_health_is_cheap_and_returns_api_version(monkeypatch):
    import backend.main as main_module

    def unexpected_initialization():
        raise AssertionError("health must not initialize a pipeline")

    monkeypatch.setattr(main_module, "get_ocr_pipeline", unexpected_initialization)
    monkeypatch.setattr(main_module, "get_full_pipeline", unexpected_initialization)
    response = request_app(app, "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.2.0",
        "api_version": "1",
    }


def test_ready_reports_cached_pipeline_and_local_model_state():
    response = request_app(app, "GET", "/ready")

    assert response.status_code in {200, 503}
    body = response.json()
    assert body["api_version"] == "1"
    assert body["status"] in {"ready", "not_ready"}
    assert isinstance(body["ocr_ready"], bool)
    assert isinstance(body["translation_ready"], bool)


def test_translation_readiness_requires_model_assets(tmp_path):
    assert not _local_marian_model_ready(tmp_path)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "model.safetensors").write_bytes(b"weights")
    (tmp_path / "source.spm").write_bytes(b"source")
    (tmp_path / "target.spm").write_bytes(b"target")
    assert _local_marian_model_ready(tmp_path)


@pytest.mark.parametrize("request_id", ["bad id", b"bad-\xff"])
def test_invalid_request_id_is_replaced_with_safe_generated_id(request_id):
    response = request_app(
        app,
        "GET",
        "/missing-route",
        headers={"X-Request-ID": request_id},
    )

    response_id = response.headers["x-request-id"]
    assert re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", response_id)
    assert response_id != request_id
    assert response.json()["api_version"] == "1"
    assert response.json()["error"]["request_id"] == response_id
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_valid_request_id_is_preserved_in_headers_and_errors():
    response = translate_request(
        png_bytes(),
        headers={"X-Request-ID": "reader-session-42"},
        data={"source_language": "unsupported", "target_language": "en"},
    )

    assert response.status_code == 400
    assert response.headers["x-request-id"] == "reader-session-42"
    assert response.json()["api_version"] == "1"
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_SOURCE_LANGUAGE"
    assert error["request_id"] == "reader-session-42"


def test_missing_multipart_field_uses_standard_validation_envelope():
    response = request_app(app, "POST", "/translate")

    assert response.status_code == 422
    body = response.json()
    assert body["api_version"] == "1"
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"][0]["field"] == "image"
    assert response.headers["x-request-id"] == body["error"]["request_id"]
    assert "Traceback" not in response.text


def test_malformed_image_has_stable_error_without_traceback():
    response = translate_request(b"\x89PNG\r\n\x1a\nnot-an-image")

    assert response.status_code == 400
    assert response.json()["api_version"] == "1"
    assert response.json()["error"]["code"] == "INVALID_IMAGE"
    assert "Traceback" not in response.text


def test_empty_upload_has_stable_error():
    response = translate_request(b"")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_IMAGE"


def test_unsupported_image_format_has_stable_error():
    response = translate_request(b"not an image")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_IMAGE_FORMAT"


def test_oversized_image_has_stable_error():
    response = translate_request(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_SIZE_BYTES)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "IMAGE_TOO_LARGE"


def test_unsupported_target_language_has_stable_error():
    response = request_app(
        app,
        "POST",
        "/translate",
        files={"image": ("page.png", png_bytes(), "image/png")},
        data={"source_language": "ja", "target_language": "fr"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED_TARGET_LANGUAGE"


def test_unexpected_pipeline_error_is_generic_and_correlated(monkeypatch):
    import backend.main as main_module

    class BrokenPipeline:
        def run(self, *args, **kwargs):
            raise RuntimeError("internal secret detail")

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: BrokenPipeline())
    response = translate_request(
        png_bytes(), headers={"X-Request-ID": "pipeline-check"}
    )

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["message"] == "An internal server error occurred."
    assert "internal secret detail" not in response.text
    assert "Traceback" not in response.text
    assert error["request_id"] == response.headers["x-request-id"]


def test_internal_http_exception_detail_is_not_returned(monkeypatch):
    import backend.main as main_module
    from starlette.exceptions import HTTPException as StarletteHTTPException

    class BrokenPipeline:
        def run(self, *args, **kwargs):
            raise StarletteHTTPException(500, detail="private model path")

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: BrokenPipeline())
    response = translate_request(png_bytes())

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["message"] == "An internal server error occurred."
    assert "private model path" not in response.text


def test_request_body_limit_returns_413_with_request_id():
    async def unused_app(scope, receive, send):
        raise AssertionError("oversized request must be rejected before routing")

    middleware = RequestContextMiddleware(unused_app, max_request_bytes=16)
    sent = []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/translate",
        "headers": [
            (b"content-length", b"17"),
            (b"x-request-id", b"oversized-body"),
        ],
        "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))

    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    body = next(
        message["body"]
        for message in sent
        if message["type"] == "http.response.body"
    )
    assert start["status"] == 413
    assert dict(start["headers"])[b"x-request-id"] == b"oversized-body"
    payload = json.loads(body)
    assert payload["api_version"] == "1"
    assert payload["error"]["code"] == "REQUEST_TOO_LARGE"
    assert MAX_REQUEST_BODY_BYTES > 20 * 1024 * 1024


def test_streamed_body_without_content_length_is_also_limited():
    async def drain_body(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body", False):
                break

    middleware = RequestContextMiddleware(drain_body, max_request_bytes=5)
    sent = []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/translate",
        "headers": [(b"x-request-id", b"stream-limit")],
        "state": {},
    }
    chunks = iter([
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"456", "more_body": False},
    ])

    async def receive():
        return next(chunks)

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))

    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    body = next(
        message["body"]
        for message in sent
        if message["type"] == "http.response.body"
    )
    assert start["status"] == 413
    assert json.loads(body)["error"]["request_id"] == "stream-limit"


def test_extension_preflight_is_allowed_and_random_web_origins_are_not():
    extension_origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    preflight = request_app(
        app,
        "OPTIONS",
        "/translate",
        headers={
            "Origin": extension_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )
    extension_response = request_app(
        app,
        "GET",
        "/health",
        headers={"Origin": extension_origin},
    )
    unrelated_preflight = request_app(
        app,
        "OPTIONS",
        "/translate",
        headers={
            "Origin": "https://reader.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-request-id",
        },
    )
    unrelated = request_app(
        app,
        "GET",
        "/health",
        headers={"Origin": "https://reader.example"},
    )

    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == extension_origin
    assert extension_response.status_code == 200
    assert extension_response.headers["access-control-allow-origin"] == extension_origin
    assert "x-request-id" in extension_response.headers[
        "access-control-expose-headers"
    ].lower()
    assert unrelated_preflight.status_code == 400
    assert "access-control-allow-origin" not in unrelated_preflight.headers
    assert unrelated.status_code == 200
    assert "access-control-allow-origin" not in unrelated.headers


def test_successful_mocked_translation_keeps_phase_25_1_contract(monkeypatch):
    import backend.main as main_module

    class MockPipeline:
        def run(self, image, source_language, target_language):
            return FullPipelineResult(
                api_version="1",
                source_language="ja",
                target_language="en",
                image_width=120,
                image_height=120,
                ocr_time_ms=10.0,
                translation_time_ms=3.0,
                total_time_ms=13.0,
                num_regions=1,
                regions=[TranslatedRegion(
                    original_text="こんにちは",
                    translated_text="Hello",
                    confidence=0.95,
                    bbox=[[10, 20], [50, 20], [50, 40], [10, 40]],
                    translation_time_ms=3.0,
                    source_language="ja",
                )],
            )

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: MockPipeline())
    response = translate_request(png_bytes())

    assert response.status_code == 200
    body = response.json()
    assert body["api_version"] == "1"
    assert body["source_language"] == "ja"
    assert body["image"] == {"width": 120, "height": 120}
    assert body["regions"][0]["original_text"] == "こんにちは"
    assert body["regions"][0]["translated_text"] == "Hello"
    assert body["regions"][0]["bbox"] == {"x1": 10, "y1": 20, "x2": 50, "y2": 40}
    assert body["regions"][0]["translation_status"] == "ok"


def test_mocked_ocr_success_includes_api_version(monkeypatch):
    import backend.main as main_module

    class MockOCRPipeline:
        def run_with_grouping(self, image, source_language):
            return OCRResponse(
                results=[],
                source_language=source_language,
                num_text_regions=0,
                average_confidence=0.0,
                processing_time_ms=1.0,
            )

    monkeypatch.setattr(main_module, "get_ocr_pipeline", lambda: MockOCRPipeline())
    response = request_app(
        app,
        "POST",
        "/ocr",
        files={"image": ("page.png", png_bytes(), "image/png")},
        data={"source_language": "ja"},
    )

    assert response.status_code == 200
    assert response.json()["api_version"] == "1"
    assert response.json()["results"] == []


def test_concurrent_translation_requests_respect_inference_bound(monkeypatch):
    import backend.main as main_module

    active = 0
    maximum_active = 0
    counts_lock = threading.Lock()

    class SlowPipeline:
        def run(self, image, source_language, target_language):
            nonlocal active, maximum_active
            with counts_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.04)
            with counts_lock:
                active -= 1
            return FullPipelineResult(
                api_version="1",
                source_language="ja",
                target_language="en",
                image_width=120,
                image_height=120,
                ocr_time_ms=1.0,
                translation_time_ms=1.0,
                total_time_ms=2.0,
                num_regions=0,
                regions=[],
            )

    monkeypatch.setattr(main_module, "get_full_pipeline", lambda: SlowPipeline())

    async def send_concurrent_requests():
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

    responses = asyncio.run(send_concurrent_requests())

    assert all(response.status_code == 200 for response in responses)
    assert maximum_active == 1


def test_routes_remain_unversioned_for_api_v1_contract():
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/ready" in paths
    assert "/ocr" in paths
    assert "/translate" in paths
    assert "/api/v1/translate" not in paths
