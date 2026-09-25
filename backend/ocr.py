from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import sys
import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.config import OCR_CONFIDENCE_THRESHOLD

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

import logging
logging.getLogger("ppocr").setLevel(logging.WARNING)


@dataclass
class OCRResult:
    text: str
    confidence: float
    bbox: list[list[int]]
    language: str | None


@dataclass
class OCRResponse:
    results: list[OCRResult]
    source_language: str
    num_text_regions: int
    average_confidence: float
    processing_time_ms: float
    ocr_engine_time_ms: float = 0.0
    model_load_time_ms: float = 0.0


_PADDLE_LANG_MAP: dict[str, str] = {
    "ko": "korean",
    "ja": "japan",
    "zh": "ch",
    "zh-Hans": "ch",
    "zh-Hant": "chinese_cht",
    "auto": "ch",
}
_PADDLE_READER_INIT_LOCK = threading.Lock()
_PADDLE_MODEL_FILES = ("inference.pdmodel", "inference.pdiparams")


def _paddle_model_directories(paddleocr_module: Any, language: str) -> list[Path]:
    """Resolve PaddleOCR 2.x's local model directories without initializing it."""
    try:
        model_language, detection_language = paddleocr_module.parse_lang(language)
        model_version = paddleocr_module.DEFAULT_OCR_MODEL_VERSION
        base_directory = Path(paddleocr_module.BASE_DIR).expanduser() / "whl"
        model_specs = (
            ("det", detection_language, detection_language),
            ("rec", model_language, model_language),
            ("cls", "ch", ""),
        )
        directories = []
        for model_type, config_language, subdirectory in model_specs:
            model_config = paddleocr_module.get_model_config(
                "OCR", model_version, model_type, config_language
            )
            model_name = model_config["url"].rsplit("/", 1)[-1]
            if not model_name.endswith(".tar"):
                raise ValueError("PaddleOCR returned an unexpected model archive")
            model_directory = base_directory / model_type
            if subdirectory:
                model_directory /= subdirectory
            directories.append(model_directory / model_name[:-4])
        return directories
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "Cannot verify local PaddleOCR models; refusing to initialize "
            "a reader that may download models."
        ) from exc


def _require_local_paddle_model(model_directory: str | Path) -> None:
    model_path = Path(model_directory)
    if not all((model_path / filename).is_file() for filename in _PADDLE_MODEL_FILES):
        raise FileNotFoundError(
            "A required local PaddleOCR model is missing. Install the OCR "
            "models before running inference; requests do not download models."
        )


class OCREngine:
    SUPPORTED_LANGS: list[str] = ["ko", "ja", "zh", "zh-Hant"]

    def __init__(
        self,
        languages: list[str] | None = None,
        confidence_threshold: float = OCR_CONFIDENCE_THRESHOLD,
        use_gpu: bool = True,
    ) -> None:
        self.languages = languages or []
        self.confidence_threshold = confidence_threshold
        self._readers: dict[str, Any] = {}
        self._use_gpu = use_gpu

    def _get_reader(self, lang_key: str) -> Any:
        if lang_key not in self._readers:
            try:
                from paddleocr import PaddleOCR
            except ImportError as e:
                raise RuntimeError(
                    "PaddleOCR is required to run OCR. "
                    "Install the production dependencies from requirements.txt."
                ) from e
            paddle_lang = _PADDLE_LANG_MAP.get(lang_key, "ch")
            paddleocr_module = sys.modules.get(PaddleOCR.__module__)
            if paddleocr_module is None or not callable(
                getattr(paddleocr_module, "maybe_download", None)
            ):
                raise RuntimeError(
                    "Cannot verify that PaddleOCR model downloads are disabled."
                )
            model_directories = _paddle_model_directories(
                paddleocr_module, paddle_lang
            )
            for model_directory in model_directories:
                _require_local_paddle_model(model_directory)

            # PaddleOCR 2.x calls maybe_download during construction. Replace
            # that function under a lock so a file removed after preflight
            # cannot trigger a request-time download.
            with _PADDLE_READER_INIT_LOCK:
                original_downloader = paddleocr_module.maybe_download

                def require_local_model(model_directory, _url):
                    _require_local_paddle_model(model_directory)

                paddleocr_module.maybe_download = require_local_model
                try:
                    reader = PaddleOCR(
                        lang=paddle_lang,
                        use_gpu=self._use_gpu,
                        show_log=False,
                    )
                finally:
                    paddleocr_module.maybe_download = original_downloader
            self._readers[lang_key] = reader
        return self._readers[lang_key]

    @property
    def readers(self) -> dict[str, Any]:
        if not self._readers:
            for lang in self.SUPPORTED_LANGS:
                _ = self._get_reader(lang)
        return self._readers

    def recognize(
        self,
        image: NDArray[np.uint8],
        source_language: str | None = None,
    ) -> OCRResponse:
        import time

        start = time.perf_counter()

        lang_keys = self._resolve_langs(source_language)
        raw_results: list[OCRResult] = []
        ocr_engine_time_ms = 0.0
        model_load_time_ms = 0.0

        for lang_key in lang_keys:
            reader_was_loaded = lang_key in self._readers
            load_start = time.perf_counter()
            reader = self._get_reader(lang_key)
            if not reader_was_loaded:
                model_load_time_ms += (time.perf_counter() - load_start) * 1000
            ocr_start = time.perf_counter()
            result = reader.ocr(image, cls=True)
            ocr_engine_time_ms += (time.perf_counter() - ocr_start) * 1000
            if result is None or result[0] is None:
                continue
            for line in result[0]:
                bbox_points, (text, conf) = line
                if conf < self.confidence_threshold:
                    continue
                text = text.strip()
                if len(text) < 1:
                    continue
                points = [[int(pt[0]), int(pt[1])] for pt in bbox_points]
                # In auto mode, preserve which reader produced this result.
                # The caller's request value is not a detection result.
                detected_language = (
                    lang_key
                    if source_language in (None, "auto")
                    else source_language
                )
                raw_results.append(OCRResult(
                    text=text,
                    confidence=round(float(conf), 4),
                    bbox=points,
                    language=detected_language,
                ))

        results = self._deduplicate(raw_results)
        elapsed_ms = (time.perf_counter() - start) * 1000

        avg_conf = (
            round(sum(r.confidence for r in results) / len(results), 4)
            if results
            else 0.0
        )

        return OCRResponse(
            results=results,
            source_language=source_language or "auto",
            num_text_regions=len(results),
            average_confidence=avg_conf,
            processing_time_ms=round(elapsed_ms, 2),
            ocr_engine_time_ms=ocr_engine_time_ms,
            model_load_time_ms=model_load_time_ms,
        )

    def _resolve_langs(self, source_language: str | None) -> list[str]:
        if source_language is None or source_language == "auto":
            return self.SUPPORTED_LANGS
        return [source_language]

    @staticmethod
    def _deduplicate(results: list[OCRResult]) -> list[OCRResult]:
        if len(results) < 2:
            return results

        sorted_results = sorted(results, key=lambda r: -r.confidence)
        kept: list[OCRResult] = []

        for r in sorted_results:
            duplicate = False
            for k in kept:
                if OCREngine._iou(r.bbox, k.bbox) > 0.5:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(r)

        return kept

    @staticmethod
    def _iou(bbox_a: list[list[int]], bbox_b: list[list[int]]) -> float:
        x1 = max(min(p[0] for p in bbox_a), min(p[0] for p in bbox_b))
        y1 = max(min(p[1] for p in bbox_a), min(p[1] for p in bbox_b))
        x2 = min(max(p[0] for p in bbox_a), max(p[0] for p in bbox_b))
        y2 = min(max(p[1] for p in bbox_a), max(p[1] for p in bbox_b))
        if x2 <= x1 or y2 <= y1:
            return 0.0
        inter = (x2 - x1) * (y2 - y1)
        area_a = (max(p[0] for p in bbox_a) - min(p[0] for p in bbox_a)) * (
            max(p[1] for p in bbox_a) - min(p[1] for p in bbox_a)
        )
        area_b = (max(p[0] for p in bbox_b) - min(p[0] for p in bbox_b)) * (
            max(p[1] for p in bbox_b) - min(p[1] for p in bbox_b)
        )
        return inter / (area_a + area_b - inter)
