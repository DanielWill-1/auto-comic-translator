from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from backend.config import PipelineConfig
from backend.translate import TranslationEngine
from backend.pipeline import OCRPipeline


@dataclass
class TranslatedRegion:
    original_text: str
    translated_text: str
    confidence: float
    bbox: list[list[int]]
    translation_time_ms: float


@dataclass
class FullPipelineResult:
    source_language: str
    target_language: str
    ocr_time_ms: float
    translation_time_ms: float
    total_time_ms: float
    num_regions: int
    regions: list[TranslatedRegion]


class FullPipeline:
    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._ocr = OCRPipeline(self.config)
        self._translator = TranslationEngine()

    def run(
        self,
        image: NDArray[np.uint8],
        source_language: str = "auto",
        target_language: str = "en",
    ) -> FullPipelineResult:
        import time
        start = time.perf_counter()

        ocr_response = self._ocr.run_with_grouping(
            image, source_language=source_language
        )

        texts = [r.text for r in ocr_response.results]
        translations = self._translator.translate(
            texts, source_lang=source_language, target_lang=target_language,
        )

        regions: list[TranslatedRegion] = []
        for ocr_r, trans_r in zip(ocr_response.results, translations):
            regions.append(TranslatedRegion(
                original_text=ocr_r.text,
                translated_text=trans_r.translated_text,
                confidence=ocr_r.confidence,
                bbox=ocr_r.bbox,
                translation_time_ms=trans_r.processing_time_ms,
            ))

        total_ms = (time.perf_counter() - start) * 1000

        return FullPipelineResult(
            source_language=source_language,
            target_language=target_language,
            ocr_time_ms=ocr_response.processing_time_ms,
            translation_time_ms=round(total_ms - ocr_response.processing_time_ms, 2),
            total_time_ms=round(total_ms, 2),
            num_regions=len(regions),
            regions=regions,
        )


def full_pipeline_result_to_dict(result: FullPipelineResult) -> dict:
    regions = []
    for r in result.regions:
        regions.append({
            "original_text": r.original_text,
            "translated_text": r.translated_text,
            "confidence": r.confidence,
            "bbox": r.bbox,
            "translation_time_ms": r.translation_time_ms,
        })
    return {
        "source_language": result.source_language,
        "target_language": result.target_language,
        "ocr_time_ms": result.ocr_time_ms,
        "translation_time_ms": result.translation_time_ms,
        "total_time_ms": result.total_time_ms,
        "num_regions": result.num_regions,
        "regions": regions,
    }
