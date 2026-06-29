from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_LANGUAGES: dict[str, list[str]] = {
    "ko": ["ko"],
    "ja": ["ja"],
    "zh": ["ch_sim", "ch_tra"],
    "zh-Hans": ["ch_sim"],
    "zh-Hant": ["ch_tra"],
}

LANGUAGE_TO_MARIAN_CODE: dict[str, str] = {
    "ko": "ko",
    "ja": "ja",
    "zh": "zh",
    "zh-Hans": "zh",
    "zh-Hant": "zh",
}

MODEL_ROOT: Path = Path(__file__).resolve().parent.parent / "models"

LOCAL_MODELS: dict[str, str] = {
    "ko-en": str(MODEL_ROOT / "marian-ko-en"),
    "ja-en": str(MODEL_ROOT / "marian-ja-en"),
    "zh-en": str(MODEL_ROOT / "marian-zh-en"),
}

VALID_IMAGE_FORMATS: tuple[str, ...] = (
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp",
)

MAX_IMAGE_SIZE_BYTES: int = 20 * 1024 * 1024
MAX_IMAGE_DIMENSION: int = 8192
MIN_IMAGE_DIMENSION: int = 80

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
