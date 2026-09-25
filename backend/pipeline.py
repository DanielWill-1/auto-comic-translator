from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backend.config import PipelineConfig
from backend.ocr import OCREngine, OCRResponse, OCRResult
from backend.preprocessing import ImagePreprocessor


@dataclass(frozen=True)
class OCRStageTimings:
    preprocessing_ms: float = 0.0
    ocr_ms: float = 0.0
    grouping_ms: float = 0.0
    ocr_model_load_ms: float = 0.0


class OCRPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._preprocessor = ImagePreprocessor(self.config.preprocessing)
        self._ocr = OCREngine(
            confidence_threshold=self.config.confidence_threshold,
            use_gpu=self.config.use_gpu,
        )

    def run(
        self,
        image: NDArray[np.uint8],
        source_language: str = "auto",
    ) -> OCRResponse:
        preprocessed = self._preprocessor.enhance(image)
        response = self._ocr.recognize(preprocessed, source_language=source_language)
        return response

    def run_with_grouping(
        self,
        image: NDArray[np.uint8],
        source_language: str = "auto",
    ) -> OCRResponse:
        response, _ = self.run_with_grouping_timed(
            image, source_language=source_language
        )
        return response

    def run_with_grouping_timed(
        self,
        image: NDArray[np.uint8],
        source_language: str = "auto",
    ) -> tuple[OCRResponse, OCRStageTimings]:
        preprocessing_start = time.perf_counter()
        preprocessed = self._preprocessor.enhance(image)
        preprocessing_ms = (time.perf_counter() - preprocessing_start) * 1000

        response = self._ocr.recognize(
            preprocessed, source_language=source_language
        )
        grouping_start = time.perf_counter()
        response.results = self._group_text_regions(response.results)
        grouping_ms = (time.perf_counter() - grouping_start) * 1000
        return response, OCRStageTimings(
            preprocessing_ms=preprocessing_ms,
            ocr_ms=response.ocr_engine_time_ms,
            grouping_ms=grouping_ms,
            ocr_model_load_ms=response.model_load_time_ms,
        )

    def _group_text_regions(self, results: list[OCRResult]) -> list[OCRResult]:
        if len(results) < 2:
            return results

        proximity = self.config.text_group_proximity_px
        sorted_results = sorted(results, key=self._bbox_center_y)
        groups: list[list[OCRResult]] = []
        current_group = [sorted_results[0]]

        for next_result in sorted_results[1:]:
            last_in_group = current_group[-1]
            if self._distance(last_in_group, next_result) <= proximity:
                current_group.append(next_result)
            else:
                groups.append(current_group)
                current_group = [next_result]
        groups.append(current_group)

        merged: list[OCRResult] = []
        for group in groups:
            if len(group) == 1:
                merged.append(group[0])
            else:
                merged.append(self._merge_group(group))
        return merged

    @staticmethod
    def _bbox_center_y(result: OCRResult) -> float:
        ys = [pt[1] for pt in result.bbox]
        return (min(ys) + max(ys)) / 2.0

    def _distance(self, a: OCRResult, b: OCRResult) -> float:
        ay = self._bbox_center_y(a)
        by = self._bbox_center_y(b)
        return abs(ay - by)

    def _merge_group(self, group: list[OCRResult]) -> OCRResult:
        sorted_by_x = sorted(group, key=lambda r: min(pt[0] for pt in r.bbox))
        merged_text = " ".join(r.text for r in sorted_by_x)
        merged_conf = sum(r.confidence for r in group) / len(group)
        all_pts = [pt for r in group for pt in r.bbox]
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        merged_bbox = [
            [min(xs), min(ys)],
            [max(xs), min(ys)],
            [max(xs), max(ys)],
            [min(xs), max(ys)],
        ]
        return OCRResult(
            text=merged_text,
            confidence=round(merged_conf, 4),
            bbox=merged_bbox,
            # Deterministic policy for a merged multi-line region: the
            # confidence-weighted dominant language. Grouping keys off vertical
            # proximity, so a merged region is expected to be one language;
            # this picks the most confident detection if it is ever mixed.
            language=self._dominant_language(group),
        )

    @staticmethod
    def _dominant_language(results: list[OCRResult]) -> str | None:
        """Return the confidence-weighted dominant language of a region group.

        Detections contributed by the same OCR reader already share a
        ``language`` value, so weighting by confidence is a simple, stable way
        to break ties without introducing another heuristic.
        """
        scores: dict[str, float] = {}
        for r in results:
            lang = r.language
            if lang is None or lang == "auto":
                continue
            scores[lang] = scores.get(lang, 0.0) + r.confidence
        if not scores:
            return results[0].language if results else None
        return max(scores, key=lambda k: (scores[k], k))
