#!/usr/bin/env python
"""Phase 2 CLI: image -> OCR -> translate -> display."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import PipelineConfig, SUPPORTED_LANGUAGES
from backend.full_pipeline import FullPipeline, full_pipeline_result_to_dict
from backend.utils import bytes_to_ndarray, validate_image_bytes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Auto Comic Translator — OCR + translate a comic image.",
    )
    parser.add_argument("image", help="Path to JPG or PNG comic image.")
    parser.add_argument(
        "-s", "--source", default="auto",
        choices=["auto", "ko", "ja", "zh", "zh-Hans", "zh-Hant"],
        help="Source language (default: auto).",
    )
    parser.add_argument(
        "-t", "--target", default="en",
        help="Target language code (default: en).",
    )
    parser.add_argument(
        "-j", "--json", action="store_true",
        help="Output structured JSON instead of human-readable format.",
    )
    parser.add_argument(
        "--no-group", action="store_true",
        help="Disable text grouping.",
    )
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Error: file not found: {image_path}", file=sys.stderr)
        return 1

    data = image_path.read_bytes()
    try:
        validate_image_bytes(data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    nd = bytes_to_ndarray(data)

    config = PipelineConfig(use_gpu=False)
    pipeline = FullPipeline(config)

    print(f"Processing: {image_path.name} ({nd.shape[1]}x{nd.shape[0]})", file=sys.stderr)

    source_lang = args.source if args.source != "auto" else _detect_lang_hint(image_path)
    print(f"Source: {source_lang}, Target: {args.target}", file=sys.stderr)

    result = pipeline.run(nd, source_language=source_lang, target_language=args.target)

    if args.json:
        print(json.dumps(full_pipeline_result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        _print_human(result)

    return 0


def _detect_lang_hint(path: Path) -> str:
    name = path.name.lower()
    if any(tok in name for tok in ["ko", "kor", "korean"]):
        return "ko"
    if any(tok in name for tok in ["jp", "ja", "jpn", "japanese"]):
        return "ja"
    if any(tok in name for tok in ["zh", "cn", "ch", "chinese", "mandarin"]):
        return "zh"
    return "auto"


def _print_human(result) -> None:
    print(f"\n{'=' * 50}")
    print("OCR + Translation Results")
    print(f"{'=' * 50}")
    print(f"Source: {result.source_language}, Target: {result.target_language}")
    print(f"OCR: {result.ocr_time_ms:.0f}ms | Translation: {result.translation_time_ms:.0f}ms")
    print(f"Total: {result.total_time_ms:.0f}ms | Regions: {result.num_regions}")
    print(f"{'=' * 50}")

    for i, r in enumerate(result.regions, 1):
        print(f"\n[{i}] {r.original_text}")
        print(f"    -> {r.translated_text}")
        print(f"    conf: {r.confidence:.4f} | bbox: {r.bbox}")


if __name__ == "__main__":
    sys.exit(main())
