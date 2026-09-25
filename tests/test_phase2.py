"""End-to-end Phase 2 test: image -> OCR -> MarianMT translate."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import PipelineConfig
from backend.full_pipeline import FullPipeline, full_pipeline_result_to_dict
from backend.utils import bytes_to_ndarray, validate_image_bytes


def run_image(path: Path, source_lang: str) -> bool:
    print(f"\n{'=' * 50}")
    print(f"Testing: {path.name}")
    print(f"Source lang: {source_lang}")
    print(f"{'=' * 50}")

    data = path.read_bytes()
    validate_image_bytes(data)
    nd = bytes_to_ndarray(data)
    print(f"Image: {nd.shape[1]}x{nd.shape[0]}")

    config = PipelineConfig(use_gpu=False)
    pipeline = FullPipeline(config)

    result = pipeline.run(nd, source_language=source_lang, target_language="en")

    print(f"OCR:      {result.ocr_time_ms:.0f}ms")
    print(f"Translate: {result.translation_time_ms:.0f}ms")
    print(f"Total:     {result.total_time_ms:.0f}ms")
    print(f"Regions:   {result.num_regions}")

    output = full_pipeline_result_to_dict(result)
    print(json.dumps(output, ensure_ascii=False, indent=2))

    return len(result.regions) > 0


if __name__ == "__main__":
    ROOT = Path(__file__).resolve().parent.parent
    images = sorted(ROOT.glob("datas/japanes/*.png"), key=lambda p: p.stat().st_size, reverse=True)
    for img in images[:1]:
        ok = run_image(img, source_lang="ja")
        print(f"\n{'=' * 50}")
        print(f"Result: {'PASS' if ok else 'FAIL'}")
