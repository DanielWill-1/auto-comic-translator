from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Stable version of the /translate (and /ocr) JSON contract exposed to
# browser-extension clients. Bump only on non-backward-compatible changes.
API_VERSION: str = "1"

SUPPORTED_LANGUAGES: dict[str, list[str]] = {
    "ko": ["ko"],
    "ja": ["ja"],
    "zh": ["ch_sim", "ch_tra"],
    "zh-Hans": ["ch_sim"],
    "zh-Hant": ["ch_tra"],
}
SUPPORTED_TARGET_LANGUAGES: tuple[str, ...] = ("en",)

LANGUAGE_TO_MARIAN_CODE: dict[str, str] = {
    "ko": "ko",
    "ja": "ja",
    "zh": "zh",
    "zh-Hans": "zh",
    "zh-Hant": "zh",
}

REPOSITORY_ROOT: Path = Path(__file__).resolve().parent.parent
MODEL_ROOT: Path = REPOSITORY_ROOT / "models"

LOCAL_MODELS: dict[str, str] = {
    "ko-en": str(MODEL_ROOT / "marian-ko-en"),
    "ja-en": str(MODEL_ROOT / "marian-ja-en"),
    "zh-en": str(MODEL_ROOT / "marian-zh-en"),
}

VALID_IMAGE_FORMATS: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp",
)

MAX_IMAGE_SIZE_BYTES: int = 20 * 1024 * 1024
# Allow multipart framing and the small language form fields around the image.
MAX_REQUEST_BODY_BYTES: int = MAX_IMAGE_SIZE_BYTES + 1024 * 1024
MAX_IMAGE_DIMENSION: int = 8192
MIN_IMAGE_DIMENSION: int = 80


def _positive_env_int(name: str, default: int, maximum: int) -> int:
    raw_value = os.getenv(name)
    try:
        value = default if raw_value is None else int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


HOST: str = os.getenv("ACT_HOST", "127.0.0.1")
if not HOST or HOST != HOST.strip() or any(char.isspace() for char in HOST):
    raise ValueError("ACT_HOST must be a non-empty hostname or IP address")
if HOST == "*":
    raise ValueError("ACT_HOST must be an explicit hostname or IP address")

PORT: int = _positive_env_int("ACT_PORT", 8000, 65535)
# PaddleOCR/PyTorch are shared module-level instances; serialize inference by
# default while keeping the ASGI event loop responsive.
MAX_CONCURRENT_INFERENCE: int = _positive_env_int(
    "ACT_MAX_CONCURRENT_INFERENCE", 1, 64
)


def _parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _resolve_cache_path(raw_path: str | None) -> Path:
    if raw_path is None:
        candidate = REPOSITORY_ROOT / "data" / "cache.sqlite3"
    else:
        if not raw_path.strip():
            raise ValueError("ACT_CACHE_PATH must not be empty")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = REPOSITORY_ROOT / candidate

    resolved = candidate.resolve()
    try:
        resolved.relative_to(MODEL_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("ACT_CACHE_PATH must not be inside the models directory")
    if resolved.exists() and resolved.is_dir():
        raise ValueError("ACT_CACHE_PATH must point to a cache file, not a directory")
    return resolved


CACHE_ENABLED: bool = _parse_bool_env("ACT_CACHE_ENABLED", True)
CACHE_PATH: Path = _resolve_cache_path(os.getenv("ACT_CACHE_PATH"))
CACHE_SCHEMA_VERSION: int = 1
# Bump when output-affecting pipeline implementation changes without a config
# or dependency version change.
CACHE_PIPELINE_VERSION: int = 1

OCR_CONFIDENCE_THRESHOLD: float = 0.15
OCR_MIN_TEXT_LENGTH: int = 1


@dataclass
class PreprocessingConfig:
    clahe_clip_limit: float = 2.0
    clahe_tile_grid_size: tuple[int, int] = (8, 8)
    bilateral_d: int = 9
    bilateral_sigma_color: float = 75.0
    bilateral_sigma_space: float = 75.0
    adaptive_threshold_block_size: int = 11
    adaptive_threshold_c: int = 2
    scale_factor: float = 1.0
    target_min_dimension: int = 1200


@dataclass
class TranslationConfig:
    target_language: str = "en"
    device: str = "cpu"
    batch_size: int = 8
    max_length: int = 512
    use_local_models: bool = True


@dataclass
class PipelineConfig:
    preprocessing: PreprocessingConfig = field(default_factory=PreprocessingConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    confidence_threshold: float = OCR_CONFIDENCE_THRESHOLD
    text_group_proximity_px: int = 16
    use_gpu: bool = False
