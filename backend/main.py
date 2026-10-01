from __future__ import annotations

import asyncio
import importlib.util
import logging
import re
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, TypeVar

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import (
    API_VERSION,
    CACHE_ENABLED,
    CACHE_PATH,
    CACHE_SCHEMA_VERSION,
    HOST,
    LOCAL_MODELS,
    MAX_IMAGE_SIZE_BYTES,
    MAX_CONCURRENT_INFERENCE,
    MAX_REQUEST_BODY_BYTES,
    PORT,
    SUPPORTED_LANGUAGES,
    SUPPORTED_TARGET_LANGUAGES,
    PipelineConfig,
)
from backend.cache import (
    CacheIdentity,
    TranslationCache,
    build_cache_identity,
    processing_config_fingerprint,
)
from backend.full_pipeline import (
    FullPipeline,
    FullPipelineResult,
    full_pipeline_result_to_dict,
)
from backend.ocr import OCREngine, OCRResponse, OCRSetupError, is_reader_available
from backend.pipeline import OCRPipeline
from backend.utils import (
    ImageValidationError,
    decode_image_bytes,
    ocr_response_to_dict,
)

VALID_SOURCE_LANGUAGES = set(SUPPORTED_LANGUAGES.keys()) | {"auto"}
REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
CORS_EXTENSION_ORIGIN_PATTERN = r"^chrome-extension://[a-p]{32}$"
logger = logging.getLogger("auto-comic-translator")
_inference_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INFERENCE)
_InferenceResult = TypeVar("_InferenceResult")
_translation_cache = TranslationCache(CACHE_PATH, enabled=CACHE_ENABLED)


@dataclass(frozen=True)
class _TranslationOutcome:
    result: dict
    cache_hit: bool
    lookup_time_ms: float
    pipeline_timings: dict[str, float] = field(default_factory=dict)
    serialization_time_ms: float = 0.0
    cache_write_time_ms: float = 0.0


def _request_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _validate_source_language(source_language: str) -> None:
    """Reject unsupported source-language codes with a clean HTTP 400.

    ``auto`` and every key of ``SUPPORTED_LANGUAGES`` (ko, ja, zh, zh-Hans,
    zh-Hant) are valid. Anything else — including an uploaded filename — is
    never used as an authoritative source language here.
    """
    if source_language not in VALID_SOURCE_LANGUAGES:
        raise _request_error(
            400,
            "UNSUPPORTED_SOURCE_LANGUAGE",
            f"Unsupported source_language '{source_language}'. "
            f"Supported: {sorted(VALID_SOURCE_LANGUAGES)}",
        )


def _validate_target_language(target_language: str) -> None:
    if target_language not in SUPPORTED_TARGET_LANGUAGES:
        raise _request_error(
            400,
            "UNSUPPORTED_TARGET_LANGUAGE",
            f"Unsupported target_language '{target_language}'. "
            f"Supported: {list(SUPPORTED_TARGET_LANGUAGES)}",
        )


def _error_response(
    request_id: str,
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    error: dict[str, object] = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }
    if details:
        error["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"api_version": API_VERSION, "error": error},
        headers={REQUEST_ID_HEADER: request_id},
    )


class RequestContextMiddleware:
    """Bound request bodies and echo a safe request ID on every response."""

    def __init__(self, app, max_request_bytes: int) -> None:
        self.app = app
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = time.perf_counter()
        response_status: int | None = None
        incoming_headers = dict(scope.get("headers", []))
        try:
            candidate = incoming_headers.get(b"x-request-id", b"").decode("ascii")
        except UnicodeDecodeError:
            candidate = ""
        request_id = (
            candidate
            if _REQUEST_ID_PATTERN.fullmatch(candidate)
            else uuid.uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id
        response_started = False

        async def send_with_request_id(message) -> None:
            nonlocal response_started, response_status
            if message["type"] == "http.response.start":
                response_started = True
                response_status = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            raw_content_length = incoming_headers.get(b"content-length")
            if raw_content_length is not None:
                try:
                    content_length = int(raw_content_length)
                except ValueError:
                    response = _error_response(
                        request_id,
                        400,
                        "INVALID_CONTENT_LENGTH",
                        "Invalid Content-Length header.",
                    )
                    await response(scope, receive, send_with_request_id)
                    return
                if content_length < 0:
                    response = _error_response(
                        request_id,
                        400,
                        "INVALID_CONTENT_LENGTH",
                        "Invalid Content-Length header.",
                    )
                    await response(scope, receive, send_with_request_id)
                    return
                if content_length > self.max_request_bytes:
                    response = _error_response(
                        request_id,
                        413,
                        "REQUEST_TOO_LARGE",
                        f"Request body exceeds {self.max_request_bytes} bytes.",
                    )
                    await response(scope, receive, send_with_request_id)
                    return

            received_bytes = 0

            async def receive_with_limit():
                nonlocal received_bytes
                message = await receive()
                if message["type"] == "http.request":
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > self.max_request_bytes:
                        raise _RequestBodyTooLarge
                return message

            try:
                await self.app(scope, receive_with_limit, send_with_request_id)
            except _RequestBodyTooLarge:
                if response_started:
                    raise
                response = _error_response(
                    request_id,
                    413,
                    "REQUEST_TOO_LARGE",
                    f"Request body exceeds {self.max_request_bytes} bytes.",
                )
                await response(scope, receive, send_with_request_id)
            except Exception:
                if response_started:
                    raise
                logger.exception("Unhandled request error request_id=%s", request_id)
                response = _error_response(
                    request_id,
                    500,
                    "INTERNAL_ERROR",
                    "An internal server error occurred.",
                )
                await response(scope, receive, send_with_request_id)
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                request_id,
                scope.get("method", ""),
                scope.get("path", ""),
                response_status if response_status is not None else "cancelled",
                elapsed_ms,
            )


class _RequestBodyTooLarge(Exception):
    pass


_ocr_pipeline: OCRPipeline | None = None
_full_pipeline: FullPipeline | None = None


def get_ocr_pipeline() -> OCRPipeline:
    global _ocr_pipeline
    if _ocr_pipeline is None:
        _ocr_pipeline = OCRPipeline(PipelineConfig(use_gpu=False))
    return _ocr_pipeline


def get_full_pipeline() -> FullPipeline:
    global _full_pipeline
    if _full_pipeline is None:
        _full_pipeline = FullPipeline(PipelineConfig(use_gpu=False))
    return _full_pipeline


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("Warming up OCR pipeline...")
    try:
        p = get_ocr_pipeline()
        warmup = np.zeros((100, 100, 3), dtype=np.uint8)
        p._preprocessor.enhance(warmup)
        _ = p._ocr.readers
        logger.info("PaddleOCR pipeline ready")
    except Exception as e:
        logger.warning("Pipeline warmup incomplete: %s", e)
    yield


app = FastAPI(
    title="Auto Comic Translator — Phase 2",
    version="0.2.0",
    description="OCR + Translation pipeline for comic images",
    lifespan=lifespan,
)

app.add_middleware(RequestContextMiddleware, max_request_bytes=MAX_REQUEST_BODY_BYTES)
# The extension should call the API from its background context. Allow only
# Chromium extension origins; normal comic-site origins do not get API access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=CORS_EXTENSION_ORIGIN_PATTERN,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", REQUEST_ID_HEADER],
    expose_headers=[REQUEST_ID_HEADER],
)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail
    if exc.status_code >= 500:
        code = "INTERNAL_ERROR"
        message = "An internal server error occurred."
    elif isinstance(detail, dict) and "code" in detail and "message" in detail:
        code = str(detail["code"])
        message = str(detail["message"])
    else:
        code = {
            400: "BAD_REQUEST",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }.get(exc.status_code, "HTTP_ERROR")
        message = str(detail)
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    response = _error_response(
        request_id,
        exc.status_code,
        code,
        message,
    )
    for name, value in (exc.headers or {}).items():
        response.headers[name] = value
    return response


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = []
    for error in exc.errors():
        location = [
            str(part)
            for part in error.get("loc", ())
            if part not in {"body", "query", "path"}
        ]
        details.append({
            "field": ".".join(location),
            "message": str(error.get("msg", "Invalid value.")),
        })
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    return _error_response(
        request_id,
        422,
        "VALIDATION_ERROR",
        "Request validation failed.",
        details=details,
    )


@app.exception_handler(OCRSetupError)
async def ocr_setup_error_handler(
    request: Request, exc: OCRSetupError
) -> JSONResponse:
    """Report an unusable local OCR setup as a controlled, safe API error.

    Local model paths and other filesystem details stay in the server log; the
    client receives the standard error envelope instead of a generic 500.
    """
    request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
    logger.warning("OCR setup error request_id=%s: %s", request_id, exc)
    return _error_response(
        request_id,
        503,
        "OCR_READERS_UNAVAILABLE",
        "No local OCR readers are available for the requested language. "
        "Install the local OCR model assets before translating; requests do "
        "not download models.",
    )


async def _read_image_upload(image: UploadFile) -> tuple[bytes, np.ndarray]:
    if not image.content_type or not image.content_type.startswith("image/"):
        raise _request_error(400, "INVALID_IMAGE", "File must be an image.")

    data = await image.read(MAX_IMAGE_SIZE_BYTES + 1)
    if not data:
        raise _request_error(400, "EMPTY_IMAGE", "Empty image file.")
    if len(data) > MAX_IMAGE_SIZE_BYTES:
        raise _request_error(
            413,
            "IMAGE_TOO_LARGE",
            f"Image exceeds the {MAX_IMAGE_SIZE_BYTES} byte limit.",
        )

    try:
        return data, decode_image_bytes(data)
    except ImageValidationError as exc:
        status_code = 413 if exc.code == "IMAGE_TOO_LARGE" else 400
        raise _request_error(status_code, exc.code, str(exc)) from exc


def _ocr_ready() -> bool:
    if _ocr_pipeline is None:
        return False
    engine = getattr(_ocr_pipeline, "_ocr", None)
    readers = getattr(engine, "_readers", {})
    return set(OCREngine.SUPPORTED_LANGS).issubset(readers)


def _available_ocr_languages() -> list[str]:
    """Languages with complete local OCR model files; initializes nothing."""
    if _ocr_pipeline is not None:
        engine = getattr(_ocr_pipeline, "_ocr", None)
        if engine is not None:
            return engine.available_auto_languages()
    return [
        lang_key
        for lang_key in OCREngine.SUPPORTED_LANGS
        if is_reader_available(lang_key)
    ]


def _translation_ready() -> bool:
    if importlib.util.find_spec("transformers") is None:
        return False
    return all(
        _local_marian_model_ready(Path(path))
        for path in LOCAL_MODELS.values()
    )


def _local_marian_model_ready(model_dir: Path) -> bool:
    if not model_dir.is_dir() or not (model_dir / "config.json").is_file():
        return False
    has_weights = any(model_dir.glob("model*.safetensors")) or any(
        model_dir.glob("pytorch_model*.bin")
    )
    has_tokenizer = (
        (model_dir / "source.spm").is_file()
        and (model_dir / "target.spm").is_file()
    ) or (model_dir / "tokenizer.json").is_file()
    return has_weights and has_tokenizer


@app.get("/health")
async def health() -> dict[str, str]:
    """Cheap liveness check; does not initialize OCR or translation models."""
    return {
        "status": "ok",
        "version": "0.2.0",
        "api_version": API_VERSION,
    }


@app.get("/ready")
async def ready() -> JSONResponse:
    """Report cached OCR and local translation asset readiness without loading."""
    ocr_ready = _ocr_ready()
    translation_ready = _translation_ready()
    is_ready = ocr_ready and translation_ready
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "not_ready",
            "version": "0.2.0",
            "api_version": API_VERSION,
            "ocr_ready": ocr_ready,
            "translation_ready": translation_ready,
            # Additive diagnostic: the readers `source_language=auto` will use.
            "ocr_languages": _available_ocr_languages(),
        },
    )


async def _run_limited_inference(
    function: Callable[..., _InferenceResult],
    *args: object,
    **kwargs: object,
) -> tuple[_InferenceResult, float]:
    """Run shared ML pipeline work off-loop and hold the bound through cancel."""
    wait_started = time.perf_counter()
    await _inference_semaphore.acquire()
    inference_wait_ms = (time.perf_counter() - wait_started) * 1000
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    release_after_worker = False

    def release_cancelled_worker(task: asyncio.Task[_InferenceResult]) -> None:
        try:
            task.result()
        except Exception:
            logger.exception("Inference failed after the client request was cancelled")
        finally:
            _inference_semaphore.release()

    try:
        return await asyncio.shield(worker), inference_wait_ms
    except asyncio.CancelledError:
        # Cancelling the HTTP request cannot stop Paddle/PyTorch work in a
        # worker thread. Keep its slot occupied until the thread actually ends.
        release_after_worker = True
        worker.add_done_callback(release_cancelled_worker)
        raise
    finally:
        if not release_after_worker:
            _inference_semaphore.release()


def _run_ocr_request(
    image: np.ndarray, source_language: str, group_text: bool
) -> OCRResponse:
    pipeline = get_ocr_pipeline()
    if group_text:
        return pipeline.run_with_grouping(image, source_language=source_language)
    return pipeline.run(image, source_language=source_language)


def _run_translation_request(
    image: np.ndarray, source_language: str, target_language: str
) -> FullPipelineResult:
    pipeline = get_full_pipeline()
    return pipeline.run(
        image, source_language=source_language, target_language=target_language
    )


def _timed_cache_lookup(
    identity: CacheIdentity,
) -> tuple[dict | None, float]:
    started_at = time.perf_counter()
    result = _translation_cache.get(identity)
    return result, (time.perf_counter() - started_at) * 1000


def _zero_inference_timings(result: dict) -> dict:
    result["ocr_time_ms"] = 0.0
    result["translation_time_ms"] = 0.0
    result["total_time_ms"] = 0.0
    for region in result["regions"]:
        region["translation_time_ms"] = 0.0
    return result


def _run_translation_with_cache(
    image: np.ndarray,
    source_language: str,
    target_language: str,
    identity: CacheIdentity,
    first_lookup_time_ms: float,
) -> _TranslationOutcome:
    """Double-check while holding the inference slot, then infer and persist."""
    cached, second_lookup_time_ms = _timed_cache_lookup(identity)
    if cached is not None:
        return _TranslationOutcome(
            result=cached,
            cache_hit=True,
            lookup_time_ms=first_lookup_time_ms + second_lookup_time_ms,
        )

    pipeline_result = _run_translation_request(
        image, source_language, target_language
    )
    serialization_start = time.perf_counter()
    result = full_pipeline_result_to_dict(pipeline_result)
    serialization_time_ms = (time.perf_counter() - serialization_start) * 1000
    cache_write_start = time.perf_counter()
    _translation_cache.put(identity, result)
    cache_write_time_ms = (time.perf_counter() - cache_write_start) * 1000
    pipeline_timings = pipeline_result.timings
    return _TranslationOutcome(
        result=result,
        cache_hit=False,
        lookup_time_ms=first_lookup_time_ms + second_lookup_time_ms,
        pipeline_timings={
            "preprocessing_ms": pipeline_timings.preprocessing_ms,
            "ocr_ms": pipeline_timings.ocr_ms,
            "grouping_ms": pipeline_timings.grouping_ms,
            "translation_ms": pipeline_timings.translation_ms,
            "ocr_model_load_ms": pipeline_timings.ocr_model_load_ms,
            "translation_model_load_ms": (
                pipeline_timings.translation_model_load_ms
            ),
        },
        serialization_time_ms=serialization_time_ms,
        cache_write_time_ms=cache_write_time_ms,
    )


@app.post("/ocr", response_model=dict)
async def ocr_endpoint(
    request: Request,
    image: Annotated[UploadFile, File(...)],
    source_language: Annotated[str, Form()] = "auto",
    group_text: Annotated[bool, Form()] = True,
) -> dict:
    _validate_source_language(source_language)
    _, nd = await _read_image_upload(image)
    response, _ = await _run_limited_inference(
        _run_ocr_request, nd, source_language, group_text
    )
    logger.info(
        "request_id=%s endpoint=ocr regions=%d",
        request.state.request_id,
        response.num_text_regions,
    )
    return ocr_response_to_dict(response)


@app.post("/translate", response_model=dict)
async def translate_endpoint(
    request: Request,
    image: Annotated[UploadFile, File(...)],
    source_language: Annotated[str, Form()] = "auto",
    target_language: Annotated[str, Form()] = "en",
) -> dict:
    request_started = time.perf_counter()
    validation_started = time.perf_counter()
    _validate_source_language(source_language)
    _validate_target_language(target_language)
    image_bytes, nd = await _read_image_upload(image)
    validation_time_ms = (time.perf_counter() - validation_started) * 1000
    inference_wait_ms = 0.0
    serialization_time_ms = 0.0
    cache_write_time_ms = 0.0
    cache_lookup_time_ms = 0.0
    cache_hit = False
    pipeline_timings: dict[str, float] = {
        "preprocessing_ms": 0.0,
        "ocr_ms": 0.0,
        "grouping_ms": 0.0,
        "translation_ms": 0.0,
        "ocr_model_load_ms": 0.0,
        "translation_model_load_ms": 0.0,
    }
    if _translation_cache.enabled:
        schema_version = CACHE_SCHEMA_VERSION
        fingerprint = processing_config_fingerprint(
            PipelineConfig(use_gpu=False), schema_version=schema_version
        )
        identity = build_cache_identity(
            image_bytes,
            source_language,
            target_language,
            fingerprint,
            schema_version=schema_version,
        )
        cached, lookup_time_ms = await asyncio.to_thread(
            _timed_cache_lookup, identity
        )
        if cached is not None:
            outcome = _TranslationOutcome(
                result=cached,
                cache_hit=True,
                lookup_time_ms=lookup_time_ms,
            )
        else:
            outcome, inference_wait_ms = await _run_limited_inference(
                _run_translation_with_cache,
                nd,
                source_language,
                target_language,
                identity,
                lookup_time_ms,
            )
        result = outcome.result
        cache_hit = outcome.cache_hit
        cache_lookup_time_ms = outcome.lookup_time_ms
        serialization_time_ms = outcome.serialization_time_ms
        cache_write_time_ms = outcome.cache_write_time_ms
        pipeline_timings = outcome.pipeline_timings
        if outcome.cache_hit:
            result = _zero_inference_timings(result)
        region_count = result["num_regions"]
    else:
        pipeline_result, inference_wait_ms = await _run_limited_inference(
            _run_translation_request, nd, source_language, target_language
        )
        serialization_started = time.perf_counter()
        result = full_pipeline_result_to_dict(pipeline_result)
        serialization_time_ms = (
            time.perf_counter() - serialization_started
        ) * 1000
        region_count = pipeline_result.num_regions
        stage_timings = pipeline_result.timings
        pipeline_timings = {
            "preprocessing_ms": stage_timings.preprocessing_ms,
            "ocr_ms": stage_timings.ocr_ms,
            "grouping_ms": stage_timings.grouping_ms,
            "translation_ms": stage_timings.translation_ms,
            "ocr_model_load_ms": stage_timings.ocr_model_load_ms,
            "translation_model_load_ms": (
                stage_timings.translation_model_load_ms
            ),
        }

    final_serialization_started = time.perf_counter()
    if _translation_cache.enabled:
        result["cache"] = {
            "hit": outcome.cache_hit,
            "lookup_time_ms": round(cache_lookup_time_ms, 3),
        }
    result["timing"] = {
        "request_total_ms": 0.0,
        "validation_ms": validation_time_ms,
        **pipeline_timings,
        "serialization_ms": serialization_time_ms,
        "cache_lookup_ms": cache_lookup_time_ms,
        "cache_write_ms": cache_write_time_ms,
        "inference_wait_ms": inference_wait_ms,
    }
    if cache_hit:
        # Cache lookup responses did no current-request inference or model load.
        for field_name in (
            "preprocessing_ms",
            "ocr_ms",
            "grouping_ms",
            "translation_ms",
            "ocr_model_load_ms",
            "translation_model_load_ms",
        ):
            result["timing"][field_name] = 0.0
    result["timing"]["serialization_ms"] += (
        time.perf_counter() - final_serialization_started
    ) * 1000
    result["timing"]["request_total_ms"] = (
        time.perf_counter() - request_started
    ) * 1000
    logger.info(
        "translation_performance request_id=%s cache_hit=%s "
        "source_language=%s resolved_source_language=%s num_regions=%d "
        "request_total_ms=%.3f inference_wait_ms=%.3f "
        "preprocessing_ms=%.3f ocr_ms=%.3f grouping_ms=%.3f "
        "translation_ms=%.3f",
        request.state.request_id,
        cache_hit,
        source_language,
        result["source_language"],
        region_count,
        result["timing"]["request_total_ms"],
        inference_wait_ms,
        result["timing"]["preprocessing_ms"],
        result["timing"]["ocr_ms"],
        result["timing"]["grouping_ms"],
        result["timing"]["translation_ms"],
    )
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host=HOST, port=PORT, reload=True)
