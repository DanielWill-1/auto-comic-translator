"""Opt-in real-model checks over available local comic samples."""

from __future__ import annotations

from collections import Counter
import functools
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIRECTORIES = {
    "ja": "japanes",
    "ko": "korean",
    "zh-Hans": "chinese",
}
SAMPLE_FILENAMES = {
    "ja": ("Screenshot 2026-06-29 122805.png",),
    "ko": (
        "Screenshot 2026-09-26 015537.png",
        "Screenshot 2026-09-26 015601.png",
        "Screenshot 2026-09-26 015554.png",
    ),
    "zh-Hans": (
        "Screenshot 2026-09-26 015428.png",
        "Screenshot 2026-09-26 015435.png",
        "Screenshot 2026-09-26 015443.png",
    ),
}
LANGUAGE_MODEL_KEYS = {"ja": "ja-en", "ko": "ko-en", "zh-Hans": "zh-en"}
TRANSLATION_SANITY_INPUTS = (
    ("ja", "今日はいい天気ですね。"),
    ("ko", "안녕하세요. 만나서 반갑습니다."),
    ("zh", "你好！今天过得怎么样？"),
)

# Verified 2026-10-01 with the locally installed Korean reader: this sample is
# a sound-effect panel with no OCR-readable text. Its single detection
# recognises as an empty string with confidence 0.0 (the Japanese reader reads
# it as "A" at 0.086), so a valid empty result is the correct expectation.
TEXT_FREE_SAMPLES = frozenset({"Screenshot 2026-09-26 015554.png"})


def _terminal_safe(value: str) -> str:
    return value.encode("ascii", errors="backslashreplace").decode("ascii")


def _sample_for(source_language: str) -> Path:
    directory = ROOT / "datas" / SAMPLE_DIRECTORIES[source_language]
    for filename in SAMPLE_FILENAMES[source_language]:
        image_path = directory / filename
        if image_path.is_file():
            return image_path
    if not directory.is_dir():
        pytest.skip(f"No local {source_language} representative sample image exists.")
    pytest.skip(f"No selected {source_language} sample image exists.")


def _local_reader_models(language_keys: list[str]) -> list[str]:
    # Preserve Torch-before-Paddle import order on Windows.
    import backend.translate  # noqa: F401

    from backend.ocr import (
        _PADDLE_LANG_MAP,
        _PADDLE_MODEL_FILES,
        _paddle_model_directories,
    )
    import paddleocr

    try:
        major_version = int(paddleocr.__version__.split(".", maxsplit=1)[0])
    except (AttributeError, TypeError, ValueError):
        major_version = 2

    missing = []
    for language_key in language_keys:
        paddle_language = _PADDLE_LANG_MAP[language_key]
        if major_version >= 3:
            from backend.ocr import (
                _paddlex_model_directories,
                _require_local_paddlex_model,
            )

            model_specs = _paddlex_model_directories(paddle_language)
            try:
                for model_name, model_directory in model_specs:
                    _require_local_paddlex_model(model_name, model_directory)
            except FileNotFoundError:
                missing.append(language_key)
        else:
            from paddleocr import paddleocr as paddleocr_module

            model_directories = _paddle_model_directories(
                paddleocr_module, paddle_language
            )
            if not all(
                all(
                    (directory / filename).is_file()
                    for filename in _PADDLE_MODEL_FILES
                )
                for directory in model_directories
            ):
                missing.append(language_key)
    return missing


@functools.lru_cache(maxsize=None)
def _shared_full_pipeline():
    """One pipeline per process, mirroring how the app runs.

    Building a pipeline per test constructs a fresh set of PaddleOCR readers
    every time. On this machine that eventually faults inside Paddle's native
    runner (Windows access violation) once several model instances have been
    loaded into one process, which made the whole integration file unrunnable.
    The app builds its pipeline once and caches it; the tests do the same.
    """
    from backend.config import PipelineConfig
    from backend.full_pipeline import FullPipeline

    return FullPipeline(PipelineConfig(use_gpu=False))


def _run_real_pipeline(image_path: Path, source_language: str):
    from backend.config import LOCAL_MODELS
    from backend.main import _local_marian_model_ready
    from backend.utils import decode_image_bytes

    model_languages = (
        LANGUAGE_MODEL_KEYS.values()
        if source_language == "auto"
        else (LANGUAGE_MODEL_KEYS[source_language],)
    )
    for model_key in model_languages:
        if not _local_marian_model_ready(Path(LOCAL_MODELS[model_key])):
            pytest.skip(f"Local Marian model {model_key} is incomplete.")
    image = decode_image_bytes(image_path.read_bytes())
    return _shared_full_pipeline().run(
        image, source_language=source_language, target_language="en"
    )


@pytest.mark.integration
@pytest.mark.parametrize(("source_language", "source_text"), TRANSLATION_SANITY_INPUTS)
def test_real_local_translation_model(source_language, source_text):
    from backend.config import LOCAL_MODELS
    from backend.main import _local_marian_model_ready
    from backend.translate import MarianMTProvider

    model_key = LANGUAGE_MODEL_KEYS[
        "zh-Hans" if source_language == "zh" else source_language
    ]
    if not _local_marian_model_ready(Path(LOCAL_MODELS[model_key])):
        pytest.skip(f"Local Marian model {model_key} is incomplete.")

    result = MarianMTProvider().translate(
        [source_text], source_language, "en"
    )[0]
    print(
        _terminal_safe(
            f"Translation sanity {source_language}: "
            f"{source_text} -> {result.translated_text} ({result.status})"
        )
    )
    assert result.status == "ok"
    assert result.translated_text.strip()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source_language", "reader_key", "filename"),
    (
        ("ja", "ja", SAMPLE_FILENAMES["ja"][0]),
        *(('ko', 'ko', filename) for filename in SAMPLE_FILENAMES["ko"]),
        *(
            ("zh-Hans", "zh", filename)
            for filename in SAMPLE_FILENAMES["zh-Hans"]
        ),
    ),
)
def test_real_explicit_language_pipeline(source_language, reader_key, filename):
    image_path = ROOT / "datas" / SAMPLE_DIRECTORIES[source_language] / filename
    if not image_path.is_file():
        pytest.skip(f"Selected sample {filename} is missing.")
    missing = _local_reader_models([reader_key])
    if missing:
        pytest.skip(
            f"Local PaddleOCR reader files are missing for {source_language}."
        )

    result = _run_real_pipeline(image_path, source_language)
    from backend.full_pipeline import full_pipeline_result_to_dict

    payload = full_pipeline_result_to_dict(result)
    assert payload["api_version"] == "1"
    assert payload["source_language"] == source_language
    assert payload["image"] == {
        "width": result.image_width,
        "height": result.image_height,
    }
    if image_path.name in TEXT_FREE_SAMPLES:
        # No OCR-readable text: the request must still return a valid, empty
        # API v1 result instead of failing or inventing regions.
        assert result.num_regions == 0
        return
    assert result.num_regions > 0, f"No text regions detected in {image_path.name}."
    assert result.source_language == source_language
    assert all(region.source_language == source_language for region in result.regions)
    assert all(region.original_text.strip() for region in result.regions)
    assert all(region.translated_text.strip() for region in result.regions)
    assert all(
        region.translation_status in {"ok", "fallback"}
        for region in result.regions
    )
    for region, serialized in zip(result.regions, payload["regions"]):
        assert 0.0 <= region.confidence <= 1.0
        assert all(
            0 <= x < result.image_width and 0 <= y < result.image_height
            for x, y in region.bbox
        )
        assert serialized["original_text"] == region.original_text
        assert serialized["translated_text"] == region.translated_text
        assert serialized["source_language"] == source_language
        assert serialized["translation_status"] == region.translation_status
        assert 0.0 <= serialized["ocr_confidence"] <= 1.0
        assert set(serialized["bbox"]) == {"x1", "y1", "x2", "y2"}
        assert serialized["bbox_points"]
        assert all(
            0 <= x < result.image_width and 0 <= y < result.image_height
            for x, y in serialized["bbox_points"]
        )
    example = payload["regions"][0]
    print(
        "Real pipeline sanity:",
        source_language,
        _terminal_safe(repr(example["original_text"][:100])),
        "->",
        _terminal_safe(repr(example["translated_text"][:100])),
        example["translation_status"],
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("source_language", "expected_language"),
    (("ja", "ja"), ("ko", "ko"), ("zh-Hans", "zh")),
)
def test_real_auto_language_propagation(source_language, expected_language):
    image_path = _sample_for(source_language)
    # Auto mode runs every reader whose local models are present and skips the
    # rest, so only the reader this assertion depends on has to be installed.
    reader_language = {"ja": "ja", "ko": "ko", "zh-Hans": "zh"}[source_language]
    missing = _local_reader_models([reader_language])
    if missing:
        pytest.skip(
            f"Auto mode needs the local {reader_language} PaddleOCR reader; "
            "missing " + ", ".join(missing) + "."
        )

    result = _run_real_pipeline(image_path, "auto")
    region_languages = [region.source_language for region in result.regions]
    assert all(
        language in {"ko", "ja", "zh", "zh-Hant"}
        for language in region_languages
    )
    assert expected_language in Counter(region_languages)
