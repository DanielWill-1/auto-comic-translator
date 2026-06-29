"""Phase 1 integration test — image -> preprocessing -> OCR -> structured output."""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import PipelineConfig, PreprocessingConfig
from backend.pipeline import OCRPipeline
from backend.utils import bytes_to_ndarray, ocr_response_to_dict, validate_image_bytes


def create_test_image(texts: list[str]) -> bytes:
    import io
    img = Image.new("RGB", (800, 200 + 70 * len(texts)), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 48)
    except OSError:
        f = ImageFont.load_default()
    for i, t in enumerate(texts):
        d.text((50, 40 + i * 70), t, fill="black", font=f)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main():
    print("Phase 1 Integration Test")
    print("=" * 50)

    print("\n[1/4] Creating test image...")
    data = create_test_image(["Hello World", "Test OCR Pipeline"])
    validate_image_bytes(data)
    nd = bytes_to_ndarray(data)
    print(f"      Image: {nd.shape[1]}x{nd.shape[0]}, {len(data)} bytes")

    print("\n[2/4] Initializing OCR pipeline...")
    config = PipelineConfig(
        preprocessing=PreprocessingConfig(),
        use_gpu=False,
    )
    pipeline = OCRPipeline(config)
    print("      Pipeline ready")

    print("\n[3/4] Running OCR...")
    sys.stdout.flush()
    result = pipeline.run(nd, source_language="en")
    print(f"      Time: {result.processing_time_ms:.1f} ms")
    print(f"      Text regions found: {result.num_text_regions}")
    print(f"      Average confidence: {result.average_confidence:.4f}")

    for r in result.results:
        print(f"        [{r.confidence:.4f}] \"{r.text}\"")

    print("\n[4/4] Serializing structured output...")
    output = ocr_response_to_dict(result)
    print("      JSON keys:", list(output.keys()))
    if output["results"]:
        print("      First result:", json.dumps(output["results"][0], indent=8))

    print("\n[OK] Phase 1 pipeline verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
