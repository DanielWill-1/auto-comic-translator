from __future__ import annotations

import cv2
import numpy as np
from numpy.typing import NDArray

from backend.config import PreprocessingConfig


class ImagePreprocessor:
    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self.config = config or PreprocessingConfig()

    def enhance(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Light enhancement for PaddleOCR — keeps RGB color."""
        image = self._denoise(image)
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        gray = self._enhance_contrast(gray)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    def process(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        """Full preprocessing with adaptive threshold — best for binary OCR."""
        if image.ndim == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        image = self._denoise(image)
        image = self._enhance_contrast(image)
        image = self._adaptive_threshold(image)
        return image

    def _denoise(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        return cv2.bilateralFilter(
            image,
            self.config.bilateral_d,
            self.config.bilateral_sigma_color,
            self.config.bilateral_sigma_space,
        )

    def _enhance_contrast(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        clahe = cv2.createCLAHE(
            clipLimit=self.config.clahe_clip_limit,
            tileGridSize=self.config.clahe_tile_grid_size,
        )
        return clahe.apply(image)

    def _adaptive_threshold(self, image: NDArray[np.uint8]) -> NDArray[np.uint8]:
        return cv2.adaptiveThreshold(
            image,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            self.config.adaptive_threshold_block_size,
            self.config.adaptive_threshold_c,
        )
