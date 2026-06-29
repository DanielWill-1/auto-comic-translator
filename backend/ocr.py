from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from paddleocr import PaddleOCR

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


_PADDLE_LANG_MAP: dict[str, str] = {
    "ko": "korean",
    "ja": "japan",
    "zh": "ch",
    "zh-Hans": "ch",
    "zh-Hant": "chinese_cht",
    "auto": "ch",
}


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
        self._readers: dict[str, PaddleOCR] = {}
        self._use_gpu = use_gpu

    def _get_reader(self, lang_key: str) -> PaddleOCR:
        if lang_key not in self._readers:
            paddle_lang = _PADDLE_LANG_MAP.get(lang_key, "ch")
            self._readers[lang_key] = PaddleOCR(lang=paddle_lang)
        return self._readers[lang_key]

    @property
    def readers(self) -> dict[str, PaddleOCR]:
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

        for lang_key in lang_keys:
            reader = self._get_reader(lang_key)
            result = reader.ocr(image, cls=True)
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
                raw_results.append(OCRResult(
                    text=text,
                    confidence=round(float(conf), 4),
                    bbox=points,
                    language=source_language or lang_key,
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
