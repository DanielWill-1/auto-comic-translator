from __future__ import annotations

import inspect
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
import sys
import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.config import OCR_CONFIDENCE_THRESHOLD

logging.getLogger("ppocr").setLevel(logging.WARNING)
logger = logging.getLogger("auto-comic-translator.ocr")


class OCRSetupError(RuntimeError):
    """No configured OCR reader can run with only locally installed models."""


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


def _paddleocr_major_version(paddleocr_module: Any) -> int:
    version = getattr(paddleocr_module, "__version__", "")
    try:
        return int(version.split(".", maxsplit=1)[0])
    except (TypeError, ValueError):
        return 2


# Script ranges used to label auto-mode regions when the recognizer that
# produced them is shared by several configured languages.
_HANGUL_PATTERN = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")
_KANA_PATTERN = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff]")
_HAN_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _script_language(text: str) -> str | None:
    """Best-effort language of a recognized line from the script it uses.

    PaddleOCR ships one PP-OCRv6 recognizer for Japanese, Chinese, and
    Traditional Chinese, so the reader key cannot identify the language of a
    region produced by it. The script of the recognized text can: Hangul is
    Korean, kana is Japanese, and Han-only text is Chinese. Han-only text cannot
    distinguish Simplified from Traditional Chinese, so it resolves to ``zh``.
    """
    if _HANGUL_PATTERN.search(text):
        return "ko"
    if _KANA_PATTERN.search(text):
        return "ja"
    if _HAN_PATTERN.search(text):
        return "zh"
    return None


def _reader_model_signature(lang_key: str) -> tuple[str, ...]:
    """Identity of the local model set a language would run.

    Two languages with the same signature share every model file, so running
    both does identical work twice. Resolution is filesystem-only, matching
    :func:`is_reader_available`: nothing is initialized and nothing is
    downloaded. A language whose layout cannot be resolved keeps its own key as
    the signature, so it is never merged with another language by accident.
    """
    try:
        import paddleocr
    except ImportError:
        return (lang_key,)

    paddle_lang = _PADDLE_LANG_MAP.get(lang_key, "ch")
    try:
        if _paddleocr_major_version(paddleocr) >= 3:
            return _PADDLEOCR3_MODEL_NAMES.get(paddle_lang, (paddle_lang,))
        paddleocr_module = sys.modules.get(paddleocr.PaddleOCR.__module__)
        if paddleocr_module is None:
            return (lang_key,)
        return tuple(
            str(directory)
            for directory in _paddle_model_directories(paddleocr_module, paddle_lang)
        )
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        return (lang_key,)


def is_reader_available(lang_key: str) -> bool:
    """Report whether a language's local OCR model files are complete.

    Availability is decided from the filesystem only: no reader is constructed
    and no model download can be triggered. Errors that mean "the local layout
    cannot be verified" are reported as unavailable so auto mode can skip the
    reader instead of risking an implicit download. Inference errors are not
    affected because no inference happens here.
    """
    try:
        import paddleocr
    except ImportError:
        return False

    paddle_lang = _PADDLE_LANG_MAP.get(lang_key, "ch")
    try:
        if _paddleocr_major_version(paddleocr) >= 3:
            for model_name, model_directory in _paddlex_model_directories(
                paddle_lang
            ):
                _require_local_paddlex_model(model_name, model_directory)
            return True

        paddleocr_module = sys.modules.get(paddleocr.PaddleOCR.__module__)
        if paddleocr_module is None:
            return False
        for model_directory in _paddle_model_directories(
            paddleocr_module, paddle_lang
        ):
            _require_local_paddle_model(model_directory)
        return True
    except FileNotFoundError:
        return False
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        logger.info("OCR reader %s cannot be verified locally: %s", lang_key, exc)
        return False


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
            major_version = _paddleocr_major_version(paddleocr)

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

    def available_auto_languages(self) -> list[str]:
        """Auto-mode languages whose local OCR model files are installed.

        Availability is checked from the filesystem only, so this never
        initializes a reader and never downloads a model.
        """
        return [
            lang_key
            for lang_key in self.SUPPORTED_LANGS
            if is_reader_available(lang_key)
        ]

    def recognize(
        self,
        image: NDArray[np.uint8],
        source_language: str | None = None,
    ) -> OCRResponse:
        import time

        start = time.perf_counter()

        auto_mode = source_language is None or source_language == "auto"
        lang_keys = self._resolve_langs(source_language)
        raw_results: list[OCRResult] = []
        # Auto-mode language evidence, collected before any label is assigned:
        # the script of each recognized line, and the confidence it carries.
        pending: list[tuple[str, float, list[list[int]], str | None, str]] = []
        script_scores: dict[str, float] = {}
        ocr_engine_time_ms = 0.0
        model_load_time_ms = 0.0
        readers_run = 0

        for lang_key in lang_keys:
            reader_was_loaded = lang_key in self._readers
            load_start = time.perf_counter()
            try:
                reader = self._get_reader(lang_key)
            except FileNotFoundError as exc:
                if not auto_mode:
                    # An explicitly requested language keeps a clear setup error
                    # instead of silently returning empty OCR output, and it is
                    # reported as a controlled 503 rather than a generic 500.
                    raise OCRSetupError(
                        f"No local OCR model files are available for "
                        f"source_language={lang_key!r}: {exc}. Requests do not "
                        f"download models."
                    ) from exc
                logger.info(
                    "auto OCR: reader %s has no local models; skipping", lang_key
                )
                continue
            readers_run += 1
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
                script_language = _script_language(text) if auto_mode else None
                if script_language is not None:
                    script_scores[script_language] = (
                        script_scores.get(script_language, 0.0) + float(conf)
                    )
                pending.append((text, float(conf), points, script_language, lang_key))

        if auto_mode and readers_run == 0:
            raise OCRSetupError(
                "No local OCR readers are available for auto mode. Install the "
                "local PaddleOCR model assets; requests never download models."
            )

        # In auto mode the reader key is not a detection result: readers are
        # chosen by which local models are installed, and one PP-OCRv6 recognizer
        # serves ja/zh/zh-Hant. The script of the recognized text names the
        # language. A line with no identifiable script (digits, Latin, symbols —
        # typically a sound effect or a stray mark) takes the page's dominant
        # script language, so a short misread cannot outvote the real text and
        # flip the page's language. An explicit selection is never changed.
        page_language = (
            max(script_scores, key=lambda key: (script_scores[key], key))
            if script_scores
            else None
        )
        for text, conf, points, script_language, lang_key in pending:
            if auto_mode:
                detected_language = script_language or page_language or lang_key
            else:
                detected_language = source_language
            raw_results.append(OCRResult(
                text=text,
                confidence=round(conf, 4),
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
            return self._auto_lang_keys()
        return [source_language]

    def _auto_lang_keys(self) -> list[str]:
        """Auto mode uses every locally installed reader and skips the rest.

        A reader whose local model files are missing is skipped instead of
        failing the request, because implicit downloads are disabled. An
        explicit language selection is not affected by this method.

        Each distinct local model set runs once: ja, zh, and zh-Hant share one
        PP-OCRv6 recognizer, so running all three produces identical text three
        times over. Regions from such a reader are labelled from the script of
        the recognized text instead of from the reader key.
        """
        available = self.available_auto_languages()
        skipped = [
            lang_key
            for lang_key in self.SUPPORTED_LANGS
            if lang_key not in available
        ]
        if skipped:
            logger.info(
                "auto OCR: skipping readers without local models: %s",
                ", ".join(skipped),
            )
        if not available:
            raise OCRSetupError(
                "No local OCR readers are available for auto mode. Install the "
                "local PaddleOCR model assets; requests never download models."
            )

        unique: list[str] = []
        signatures: set[tuple[str, ...]] = set()
        for lang_key in available:
            signature = _reader_model_signature(lang_key)
            if signature in signatures:
                logger.info(
                    "auto OCR: %s shares a local model set with an earlier "
                    "reader; running those models once",
                    lang_key,
                )
                continue
            signatures.add(signature)
            unique.append(lang_key)
        return unique

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
