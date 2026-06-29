from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from backend.config import PipelineConfig
from backend.ocr import OCREngine, OCRResponse, OCRResult
from backend.preprocessing import ImagePreprocessor


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
        response = self.run(image, source_language=source_language)
        response.results = self._group_text_regions(response.results)
        return response

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
            language=group[0].language,
        )
