from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from backend.config import API_VERSION, PipelineConfig
from backend.translate import TranslationEngine
from backend.pipeline import OCRPipeline


@dataclass
class TranslatedRegion:
    original_text: str
    translated_text: str
    confidence: float
    bbox: list[list[int]]
    translation_time_ms: float
    source_language: str | None = None
    translation_status: str = "ok"  # "ok" | "fallback"


@dataclass
class PipelineTimings:
    preprocessing_ms: float = 0.0
    ocr_ms: float = 0.0
    grouping_ms: float = 0.0
    translation_ms: float = 0.0
    ocr_model_load_ms: float = 0.0
    translation_model_load_ms: float = 0.0


@dataclass
class FullPipelineResult:
    api_version: str
    source_language: str
    target_language: str
    image_width: int
    image_height: int
    ocr_time_ms: float
    translation_time_ms: float
    total_time_ms: float
    num_regions: int
    regions: list[TranslatedRegion]
    timings: PipelineTimings = field(default_factory=PipelineTimings)


def _normalize_bbox(bbox: list[list[int]]) -> dict[str, int]:
    """Normalize an OCR quad (four points) to a {x1, y1, x2, y2} box.

    The OCR engine returns an arbitrary 4-point polygon. For browsers we emit
    the axis-aligned bounding box in ORIGINAL INPUT IMAGE pixel coordinates:

        x1, y1 = top-left
        x2, y2 = bottom-right

    A browser can then map to the rendered image with:
        scaleX = displayedWidth / image_width
        scaleY = displayedHeight / image_height
    """
    if not bbox or any(len(pt) < 2 for pt in bbox):
        raise ValueError("A bounding box must contain at least one x/y point")

    xs = [pt[0] for pt in bbox]
    ys = [pt[1] for pt in bbox]
    return {
        "x1": int(min(xs)),
        "y1": int(min(ys)),
        "x2": int(max(xs)),
        "y2": int(max(ys)),
    }


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

        # NOTE (coordinate contract): preprocessing denoises and enhances the
        # image without resizing it, so OCR boxes and these dimensions use the
        # ORIGINAL INPUT IMAGE pixel grid.
        height, width = image.shape[:2]

        if hasattr(self._ocr, "run_with_grouping_timed"):
            ocr_response, ocr_timings = self._ocr.run_with_grouping_timed(
                image, source_language=source_language
            )
        else:
            ocr_start = time.perf_counter()
            ocr_response = self._ocr.run_with_grouping(
                image, source_language=source_language
            )
            from backend.pipeline import OCRStageTimings

            ocr_timings = OCRStageTimings(
                ocr_ms=(time.perf_counter() - ocr_start) * 1000,
                ocr_model_load_ms=getattr(
                    ocr_response, "model_load_time_ms", 0.0
                ),
            )

        # Resolve a per-region source language. For explicit source languages
        # every region uses that language; for "auto" each region keeps the
        # language the OCR reader that detected it reported.
        resolved_regions_source = self._resolve_region_languages(
            ocr_response.results, source_language
        )

        items = [
            (r.text, lang)
            for r, lang in zip(ocr_response.results, resolved_regions_source)
        ]
        translate_timed = getattr(
            self._translator, "translate_mixed_with_timings", None
        )
        if callable(translate_timed):
            translations, translation_ms, translation_model_load_ms = (
                translate_timed(items, target_language)
            )
        else:
            translation_start = time.perf_counter()
            translations = self._translator.translate_mixed(items, target_language)
            translation_ms = (time.perf_counter() - translation_start) * 1000
            translation_model_load_ms = 0.0

        regions: list[TranslatedRegion] = []
        for ocr_r, lang, trans_r in zip(
            ocr_response.results, resolved_regions_source, translations
        ):
            regions.append(TranslatedRegion(
                original_text=ocr_r.text,
                translated_text=trans_r.translated_text,
                confidence=ocr_r.confidence,
                bbox=ocr_r.bbox,
                translation_time_ms=trans_r.processing_time_ms,
                source_language=lang,
                translation_status=trans_r.status,
            ))

        total_ms = (time.perf_counter() - start) * 1000

        return FullPipelineResult(
            api_version=API_VERSION,
            source_language=self._resolve_overall_source(
                ocr_response.results, source_language
            ),
            target_language=target_language,
            image_width=width,
            image_height=height,
            ocr_time_ms=ocr_response.processing_time_ms,
            translation_time_ms=round(translation_ms, 2),
            total_time_ms=round(total_ms, 2),
            num_regions=len(regions),
            regions=regions,
            timings=PipelineTimings(
                preprocessing_ms=ocr_timings.preprocessing_ms,
                ocr_ms=ocr_timings.ocr_ms,
                grouping_ms=ocr_timings.grouping_ms,
                translation_ms=translation_ms,
                ocr_model_load_ms=ocr_timings.ocr_model_load_ms,
                translation_model_load_ms=translation_model_load_ms,
            ),
        )

    @staticmethod
    def _resolve_region_languages(
        results: list, source_language: str
    ) -> list[str | None]:
        """Per-region source language.

        - Explicit source language: every region uses it.
        - auto: use the language the OCR reader reported for each region.
          Regions without a detection remain unknown and are marked as
          untranslated fallback results.
        """
        if source_language and source_language != "auto":
            return [source_language] * len(results)
        return [
            r.language if r.language not in (None, "auto") else None
            for r in results
        ]

    @staticmethod
    def _resolve_overall_source(results: list, source_language: str) -> str:
        """Overall (top-level) resolved source language.

        - Explicit: return it as-is.
        - auto: confidence-weighted dominant language across all regions.
        - No regions / no detections: return "unknown" rather than inventing a
          language. Individual regions remain authoritative when mixed.
        """
        if source_language and source_language != "auto":
            return source_language
        if not results:
            return "unknown"
        scores: dict[str, float] = {}
        for r in results:
            lang = r.language
            if lang and lang != "auto":
                scores[lang] = scores.get(lang, 0.0) + r.confidence
        if not scores:
            return "unknown"
        return max(scores, key=lambda k: (scores[k], k))


def full_pipeline_result_to_dict(
    result: FullPipelineResult,
    *,
    legacy_bbox: bool = False,
) -> dict[str, Any]:
    regions = []
    for r in result.regions:
        region = {
            "original_text": r.original_text,
            "translated_text": r.translated_text,
            "confidence": r.confidence,
            "ocr_confidence": r.confidence,
            "translation_time_ms": r.translation_time_ms,
            "source_language": r.source_language,
            "translation_status": r.translation_status,
        }
        if legacy_bbox:
            # Keep the CLI's pre-Phase-2.5 JSON representation unchanged.
            region["bbox"] = r.bbox
        else:
            region["bbox"] = _normalize_bbox(r.bbox)
            # The HTTP contract adds a browser-friendly box while retaining
            # the original OCR polygon under a clear compatibility name.
            region["bbox_points"] = r.bbox
        regions.append(region)
    return {
        "api_version": result.api_version,
        "source_language": result.source_language,
        "target_language": result.target_language,
        "image": {
            "width": result.image_width,
            "height": result.image_height,
        },
        "ocr_time_ms": result.ocr_time_ms,
        "translation_time_ms": result.translation_time_ms,
        "total_time_ms": result.total_time_ms,
        "num_regions": result.num_regions,
        "regions": regions,
    }
