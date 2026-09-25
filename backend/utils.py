from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, UnidentifiedImageError

from backend.config import (
    API_VERSION,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_SIZE_BYTES,
    MIN_IMAGE_DIMENSION,
    VALID_IMAGE_FORMATS,
)
from backend.ocr import OCRResponse


class ImageValidationError(ValueError):
    """A safe, machine-readable validation error for uploaded images."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _validate_image_header(data: bytes) -> None:
    if len(data) > MAX_IMAGE_SIZE_BYTES:
        raise ImageValidationError(
            "IMAGE_TOO_LARGE",
            f"Image size {len(data)} bytes exceeds maximum "
            f"{MAX_IMAGE_SIZE_BYTES} bytes"
        )

    ext = _detect_extension(data)
    if ext not in VALID_IMAGE_FORMATS:
        raise ImageValidationError(
            "UNSUPPORTED_IMAGE_FORMAT",
            f"Unsupported image format '{ext}'. Supported: "
            f"{VALID_IMAGE_FORMATS}"
        )


def _validate_dimensions(width: int, height: int) -> None:
    if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
        raise ImageValidationError(
            "INVALID_IMAGE",
            f"Image dimensions {width}x{height} below minimum "
            f"{MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION}"
        )
    if width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
        raise ImageValidationError(
            "INVALID_IMAGE",
            f"Image dimensions {width}x{height} exceed maximum "
            f"{MAX_IMAGE_DIMENSION}"
        )


def _image_decode_error() -> ImageValidationError:
    return ImageValidationError(
        "INVALID_IMAGE", "Malformed or unreadable image file"
    )


def validate_image_bytes(data: bytes) -> None:
    _validate_image_header(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            _validate_dimensions(*img.size)
            img.verify()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as e:
        raise _image_decode_error() from e


def decode_image_bytes(data: bytes) -> NDArray[np.uint8]:
    """Validate and decode an upload once, returning its original pixel grid."""
    _validate_image_header(data)
    try:
        with Image.open(io.BytesIO(data)) as img:
            _validate_dimensions(*img.size)
            img.load()
            return np.array(img.convert("RGB"), dtype=np.uint8)
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as e:
        raise _image_decode_error() from e


def bytes_to_ndarray(data: bytes) -> NDArray[np.uint8]:
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        return np.array(img, dtype=np.uint8)


def ndarray_to_bytes(image: NDArray[np.uint8], fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    pil = Image.fromarray(image)
    pil.save(buf, format=fmt)
    return buf.getvalue()


def _detect_extension(data: bytes) -> str:
    header = data[:12]
    if header[:4] == b"\x89PNG":
        return ".png"
    if header[:2] == b"\xff\xd8":
        return ".jpg"
    if header[:2] == b"BM":
        return ".bmp"
    if header[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    return ""


def ocr_response_to_dict(response: OCRResponse) -> dict[str, Any]:
    results = []
    for r in response.results:
        results.append({
            "text": r.text,
            "confidence": r.confidence,
            "bbox": r.bbox,
            "language": r.language,
        })
    return {
        "api_version": API_VERSION,
        "results": results,
        "source_language": response.source_language,
        "num_text_regions": response.num_text_regions,
        "average_confidence": response.average_confidence,
        "processing_time_ms": response.processing_time_ms,
    }
