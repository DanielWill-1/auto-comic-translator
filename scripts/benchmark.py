"""Run local first-request, warm-inference, and cache-hit measurements."""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import math
import os
import platform
import statistics
import sys
import tempfile
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"
}
SUPPORTED_SOURCES = ("auto", "ko", "ja", "zh", "zh-Hans", "zh-Hant")
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
AGGREGATE_FIELDS = (
    "preprocessing_ms",
    "ocr_ms",
    "grouping_ms",
    "translation_ms",
    "request_total_ms",
)
MODEL_IDENTIFIERS = {
    "ko-en": "Helsinki-NLP/opus-mt-ko-en",
    "ja-en": "Helsinki-NLP/opus-mt-ja-en",
    "zh-en": "Helsinki-NLP/opus-mt-zh-en",
}
SOURCE_MODEL_KEYS = {
    "ko": ("ko-en",),
    "ja": ("ja-en",),
    "zh": ("zh-en",),
    "zh-Hans": ("zh-en",),
    "zh-Hant": ("zh-en",),
}


class BenchmarkSetupError(RuntimeError):
    """A safe, user-facing reason the local benchmark cannot start."""


@contextmanager
def _force_transformers_offline():
    names = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    previous = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ[name] = "1"
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def _paddle_no_download_guard(paddle_ocr_class: type):
    """Make PaddleOCR reader setup fail when local inference files are absent."""
    import importlib

    module = sys.modules.get(paddle_ocr_class.__module__)
    if module is None:
        module = importlib.import_module(paddle_ocr_class.__module__)
    if not hasattr(module, "maybe_download"):
        raise BenchmarkSetupError(
            "This PaddleOCR build cannot be guarded against model downloads."
        )
    original_downloader = module.maybe_download

    def require_local_model(model_dir: str | Path, _url: str) -> None:
        model_path = Path(model_dir)
        required_files = ("inference.pdmodel", "inference.pdiparams")
        if not all((model_path / name).is_file() for name in required_files):
            raise BenchmarkSetupError(
                "A PaddleOCR model is missing from the local model cache. "
                "Install the OCR models manually before benchmarking; "
                "the benchmark will not download them."
            )

    module.maybe_download = require_local_model
    try:
        yield
    finally:
        module.maybe_download = original_downloader


def _package_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def _environment_metadata() -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "platform_family": platform.system(),
        "device": "cpu",
        "torch_version": _package_version("torch"),
        "paddle_version": _package_version("paddlepaddle"),
        "model_identifiers": MODEL_IDENTIFIERS,
    }


def _required_model_keys(source_language: str) -> tuple[str, ...]:
    if source_language == "auto":
        return tuple(MODEL_IDENTIFIERS)
    return SOURCE_MODEL_KEYS[source_language]


def _discover_images(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise BenchmarkSetupError("The selected file is not a supported image.")
        return [input_path]
    if not input_path.is_dir():
        raise BenchmarkSetupError("The selected image path does not exist.")
    images = sorted(
        (
            child for child in input_path.iterdir()
            if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS
        ),
        key=lambda child: (child.name.casefold(), child.name),
    )
    if not images:
        raise BenchmarkSetupError(
            "The selected directory contains no supported image files."
        )
    return images


def _safe_scenario(body: dict[str, Any]) -> dict[str, Any]:
    timing = body.get("timing", {})
    selected_timing = {
        field: timing.get(field, 0.0) for field in TIMING_FIELDS
    }
    statuses: dict[str, int] = {}
    for region in body.get("regions", []):
        status = region.get("translation_status", "unknown")
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "cache_hit": body.get("cache", {}).get("hit"),
        "num_regions": body.get("num_regions", 0),
        "translation_status_counts": statuses,
        "legacy_timing_ms": {
            "ocr_time_ms": body.get("ocr_time_ms", 0.0),
            "translation_time_ms": body.get("translation_time_ms", 0.0),
            "total_time_ms": body.get("total_time_ms", 0.0),
        },
        "timing": selected_timing,
    }


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    index = max(math.ceil(0.95 * len(ordered)) - 1, 0)
    return ordered[index]


def _aggregate_scenarios(
    images: list[dict[str, Any]],
    scenario_name: str,
    *,
    process_first_only: bool = False,
) -> dict[str, Any]:
    samples = [
        image["scenarios"][scenario_name]["timing"]
        for image in images
        if image["scenarios"].get(scenario_name, {}).get("available") is not False
        and (not process_first_only or image.get("process_first_request"))
    ]
    aggregate: dict[str, Any] = {"count": len(samples)}
    for field in AGGREGATE_FIELDS:
        values = [sample[field] for sample in samples]
        if not values:
            aggregate[field] = None
            continue
        aggregate[field] = {
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "p95": _percentile_95(values),
        }
    return aggregate


async def _post_image(client, image_path: Path, source_language: str):
    response = await client.post(
        "/translate",
        files={
            "image": (
                f"benchmark-image{image_path.suffix.lower()}",
                image_path.read_bytes(),
                mimetypes.guess_type(image_path.name)[0] or "image/png",
            )
        },
        data={"source_language": source_language, "target_language": "en"},
    )
    if response.status_code != 200:
        body = response.json()
        error = body.get("error", {})
        code = error.get("code", "BACKEND_ERROR")
        raise BenchmarkSetupError(
            f"The local backend rejected a benchmark request ({code}). "
            "Confirm it is ready and its local models are installed; "
            "the benchmark does not download models."
        )
    return response.json()


async def _collect_measurements(
    app: Any,
    cache: Any,
    image_paths: list[Path],
    source_language: str,
) -> list[dict[str, Any]]:
    try:
        import httpx
    except ImportError as exc:
        raise BenchmarkSetupError(
            "Install development tools with `pip install -r requirements-dev.txt` "
            "to use the benchmark."
        ) from exc

    transport = httpx.ASGITransport(app=app)
    reports: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        transport=transport, base_url="http://benchmark.local"
    ) as client:
        for index, image_path in enumerate(image_paths):
            # This clear is limited to the disposable benchmark database.
            cache.clear()
            first_body = await _post_image(client, image_path, source_language)
            first = _safe_scenario(first_body)
            first["available"] = True
            first["label"] = (
                "first_request_in_process"
                if index == 0
                else "first_run_for_image_process_already_used"
            )

            cache.enabled = False
            try:
                warm_body = await _post_image(client, image_path, source_language)
            finally:
                cache.enabled = True
            warm = _safe_scenario(warm_body)
            warm["available"] = True
            warm["label"] = "warm_repeat_cache_disabled"

            if cache.stats()["entry_count"]:
                hit_body = await _post_image(client, image_path, source_language)
                hit = _safe_scenario(hit_body)
                hit["available"] = hit_body.get("cache", {}).get("hit") is True
                hit["label"] = "cache_hit"
                if not hit["available"]:
                    hit["reason"] = "The first result was not cacheable."
            else:
                hit = {
                    "available": False,
                    "reason": "The first result was not cacheable.",
                }

            image_metadata = first_body.get("image", {})
            reports.append({
                # Do not include a source filename that could contain personal
                # information when users share JSON benchmark output.
                "image": f"image_{index + 1:03d}",
                "resolution": {
                    "width": image_metadata.get("width"),
                    "height": image_metadata.get("height"),
                },
                "process_first_request": index == 0,
                "num_regions": first_body.get("num_regions", 0),
                "scenarios": {
                    "first_request": first,
                    "warm_repeat": warm,
                    "cache_hit": hit,
                },
            })
    return reports


@contextmanager
def _temporary_benchmark_cache(main_module: Any):
    from backend.cache import TranslationCache

    original_cache = main_module._translation_cache
    try:
        with tempfile.TemporaryDirectory(prefix="act-benchmark-") as temp_dir:
            benchmark_cache = TranslationCache(
                Path(temp_dir) / "benchmark-cache.sqlite3", enabled=True
            )
            main_module._translation_cache = benchmark_cache
            yield benchmark_cache
    finally:
        main_module._translation_cache = original_cache


def _build_report(
    image_reports: list[dict[str, Any]], source_language: str
) -> dict[str, Any]:
    return {
        "environment": _environment_metadata(),
        "source_language": source_language,
        "target_language": "en",
        "images": image_reports,
        "aggregate": {
            "first_request_in_process": _aggregate_scenarios(
                image_reports, "first_request", process_first_only=True
            ),
            "first_run_per_image": _aggregate_scenarios(
                image_reports, "first_request"
            ),
            "warm_repeat": _aggregate_scenarios(image_reports, "warm_repeat"),
            "cache_hit": _aggregate_scenarios(image_reports, "cache_hit"),
        },
    }


def run_benchmark(
    image_paths: list[Path], source_language: str
) -> dict[str, Any]:
    with _force_transformers_offline():
        try:
            import importlib.util

            if importlib.util.find_spec("paddleocr") is None:
                raise BenchmarkSetupError(
                    "PaddleOCR is not installed; install local backend dependencies "
                    "before benchmarking."
                )
            # Import the backend first: backend.translate imports Torch before
            # Paddle, which avoids a DLL conflict on Windows.
            import backend.main as main_module

            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise BenchmarkSetupError(
                "A local inference dependency is not available in this Python "
                "environment."
            ) from exc

        with _paddle_no_download_guard(PaddleOCR):
            required_models = _required_model_keys(source_language)
            translation_ready = (
                importlib.util.find_spec("transformers") is not None
                and all(
                    main_module._local_marian_model_ready(
                        Path(main_module.LOCAL_MODELS[model_key])
                    )
                    for model_key in required_models
                )
            )
            if not translation_ready:
                raise BenchmarkSetupError(
                    "Local Marian model files for the selected source language "
                    "are incomplete. Install them "
                    "manually before benchmarking; the benchmark will not "
                    "download them."
                )

            original_full_pipeline = main_module._full_pipeline
            original_ocr_pipeline = main_module._ocr_pipeline
            try:
                with _temporary_benchmark_cache(main_module) as benchmark_cache:
                    reports = asyncio.run(_collect_measurements(
                        main_module.app,
                        benchmark_cache,
                        image_paths,
                        source_language,
                    ))
            finally:
                main_module._full_pipeline = original_full_pipeline
                main_module._ocr_pipeline = original_ocr_pipeline

    return _build_report(reports, source_language)


def _format_scenario(scenario: dict[str, Any]) -> list[str]:
    if not scenario.get("available"):
        return [f"  unavailable: {scenario.get('reason', 'no measurement')}"]
    timing = scenario["timing"]
    labels = (
        ("Validation", "validation_ms"),
        ("Preprocessing", "preprocessing_ms"),
        ("OCR", "ocr_ms"),
        ("Grouping", "grouping_ms"),
        ("Translation", "translation_ms"),
        ("Serialization", "serialization_ms"),
        ("Cache lookup", "cache_lookup_ms"),
        ("Cache write", "cache_write_ms"),
        ("Inference wait", "inference_wait_ms"),
        ("Total", "request_total_ms"),
    )
    return [f"  {label + ':':<20}{timing[field]:9.2f} ms" for label, field in labels]


def _print_human_report(report: dict[str, Any]) -> None:
    print("Auto Comic Translator Benchmark")
    print(
        "Environment: Python {python_version}, {platform_family}, {device}".format(
            **report["environment"]
        )
    )
    print(
        f"Source: {report['source_language']}, "
        f"Target: {report['target_language']}"
    )
    for image in report["images"]:
        width = image["resolution"]["width"]
        height = image["resolution"]["height"]
        print(f"\nImage: {image['image']} ({width}x{height})")
        for key, label in (
            ("first_request", "First request"),
            ("warm_repeat", "Warm repeat"),
            ("cache_hit", "Cache hit"),
        ):
            if key == "first_request" and not image["process_first_request"]:
                label = "First run for image (models may be warm)"
            elif key == "first_request":
                label = "First request in process"
            print(f"{label}")
            print("\n".join(_format_scenario(image["scenarios"][key])))

    print("\nAggregate statistics (milliseconds)")
    print(json.dumps(report["aggregate"], indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure first-run, warm-repeat, and cache-hit timings using "
            "already-installed local models."
        )
    )
    parser.add_argument("input", type=Path, help="Image file or flat image directory")
    parser.add_argument(
        "--source",
        choices=SUPPORTED_SOURCES,
        default="auto",
        help="Source language (default: auto)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Write machine-readable JSON"
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        image_paths = _discover_images(args.input)
        report = run_benchmark(image_paths, args.source)
    except BenchmarkSetupError as exc:
        parser.exit(2, f"Benchmark unavailable: {exc}\n")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
