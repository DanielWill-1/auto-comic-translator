from __future__ import annotations

import inspect
import logging
import os
from dataclasses import dataclass
from pathlib import Path
import sys
import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.config import OCR_CONFIDENCE_THRESHOLD

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
_PADDLEX_MODEL_FILES = ("inference.yml", "inference.pdiparams")
_PADDLEX_MODEL_PROGRAM_FILES = ("inference.json", "inference.pdmodel")
_PADDLEOCR3_MODEL_NAMES: dict[str, tuple[str, str]] = {
    "korean": ("PP-OCRv5_server_det", "korean_PP-OCRv5_mobile_rec"),
    "japan": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
    "ch": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
    "chinese_cht": ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
}


def _paddle_model_directories(paddleocr_module: Any, language: str) -> list[Path]:
    """Resolve PaddleOCR 2.x local models without initializing the reader."""
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


def _paddlex_model_directories(
    language: str, cache_root: Path | None = None
) -> tuple[tuple[str, Path], ...]:
    """Resolve PaddleOCR 3.x model names to PaddleX's local cache only."""
    try:
        model_names = _PADDLEOCR3_MODEL_NAMES[language]
    except KeyError as exc:
        raise RuntimeError(
            f"No local PaddleOCR 3 model mapping is configured for {language!r}."
        ) from exc

    if cache_root is None:
        cache_root = Path(
            os.environ.get("PADDLE_PDX_CACHE_HOME", Path.home() / ".paddlex")
        ).expanduser()
    model_root = cache_root / "official_models"
    return tuple((name, model_root / name) for name in model_names)


def _require_local_paddlex_model(model_name: str, model_directory: Path) -> None:
    missing_files = [
        name
        for name in _PADDLEX_MODEL_FILES
        if not (model_directory / name).is_file()
    ]
    if not any(
        (model_directory / name).is_file()
        for name in _PADDLEX_MODEL_PROGRAM_FILES
    ):
        missing_files.append("inference.json or inference.pdmodel")
    if missing_files:
        raise FileNotFoundError(
            f"Required local PaddleX OCR model {model_name!r} is missing or "
            f"incomplete at {model_directory}; missing: "
            f"{', '.join(missing_files)}. Model downloads are disabled."
        )


def _invoke_paddle_ocr(reader: Any, image: NDArray[np.uint8]) -> Any:
    """Use the installed reader's OCR API without masking inference errors."""
    ocr_method = reader.ocr
    if "cls" in inspect.signature(ocr_method).parameters:
        return ocr_method(image, cls=True)

    predict_method = getattr(reader, "predict", None)
    if callable(predict_method):
        return predict_method(image)
    return ocr_method(image)


def _is_paddlex_ocr_result(value: Any) -> bool:
    get_value = getattr(value, "get", None)
    return callable(get_value) and get_value("rec_texts") is not None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    return list(value)


def _ocr_result_rows(result: Any) -> list[tuple[Any, Any, Any]]:
    """Normalize PaddleOCR 2.x lines and PaddleX 3.x result objects."""
    if result is None:
        return []

    if _is_paddlex_ocr_result(result):
        paddlex_results = [result]
    elif isinstance(result, (list, tuple)):
        if not result:
            return []
        if _is_paddlex_ocr_result(result[0]):
            paddlex_results = result
        else:
            legacy_lines = result[0]
            if legacy_lines is None:
                return []
            return [
                (text, confidence, polygon)
                for polygon, (text, confidence) in legacy_lines
            ]
    else:
        return []

    rows: list[tuple[Any, Any, Any]] = []
    for paddlex_result in paddlex_results:
        texts = _as_list(paddlex_result.get("rec_texts"))
        confidences = _as_list(paddlex_result.get("rec_scores"))
        polygons = paddlex_result.get("dt_polys")
        if polygons is None or len(polygons) == 0:
            polygons = paddlex_result.get("rec_polys")
        rows.extend(
            (text, confidence, polygon)
            for text, confidence, polygon in zip(
                texts, confidences, _as_list(polygons)
            )
        )
    return rows


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
                import paddleocr
            except ImportError as e:
                raise RuntimeError(
                    "PaddleOCR is required to run OCR. "
                    "Install the production dependencies from requirements.txt."
                ) from e
            PaddleOCR = paddleocr.PaddleOCR
            paddle_lang = _PADDLE_LANG_MAP.get(lang_key, "ch")
            version = getattr(paddleocr, "__version__", "")
            try:
                major_version = int(version.split(".", maxsplit=1)[0])
            except (TypeError, ValueError):
                major_version = 2

            if major_version >= 3:
                model_specs = _paddlex_model_directories(paddle_lang)
                for model_name, model_directory in model_specs:
                    _require_local_paddlex_model(model_name, model_directory)

                detection_spec, recognition_spec = model_specs
                detection_name, detection_directory = detection_spec
                recognition_name, recognition_directory = recognition_spec
                with _PADDLE_READER_INIT_LOCK:
                    reader = PaddleOCR(
                        text_detection_model_name=detection_name,
                        text_detection_model_dir=str(detection_directory),
                        text_recognition_model_name=recognition_name,
                        text_recognition_model_dir=str(recognition_directory),
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        enable_mkldnn=False,
                        device="gpu:0" if self._use_gpu else "cpu",
                    )
            else:
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

                # PaddleOCR 2.x calls maybe_download during construction.
                # Replace it under a lock to stop request-time downloads.
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
            result = _invoke_paddle_ocr(reader, image)
            ocr_engine_time_ms += (time.perf_counter() - ocr_start) * 1000
            for text, conf, bbox_points in _ocr_result_rows(result):
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
