"""PaddleOCR 2.x and 3.x invocation and result compatibility."""

from __future__ import annotations

import numpy as np
import pytest

from backend.ocr import OCREngine


def _engine_with_reader(reader: object) -> OCREngine:
    engine = OCREngine(use_gpu=False)
    engine._readers["ja"] = reader
    return engine


def test_legacy_reader_receives_cls_and_legacy_result_is_parsed():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    polygon = [[1, 2], [20, 2], [20, 12], [1, 12]]

    class LegacyReader:
        cls_values = []

        def ocr(self, input_image, cls=False):
            assert input_image is image
            self.cls_values.append(cls)
            return [[(polygon, ("legacy text", 0.91))]]

    reader = LegacyReader()
    response = _engine_with_reader(reader).recognize(image, "ja")

    assert reader.cls_values == [True]
    assert response.results[0].text == "legacy text"
    assert response.results[0].confidence == 0.91
    assert response.results[0].bbox == polygon
    assert response.results[0].language == "ja"


def test_reader_without_cls_or_predict_is_called_without_cls():
    image = np.zeros((32, 32, 3), dtype=np.uint8)

    class Reader:
        called = False

        def ocr(self, input_image):
            assert input_image is image
            self.called = True
            return [None]

    reader = Reader()
    _engine_with_reader(reader).recognize(image, "ja")

    assert reader.called


def test_paddlex_result_from_predict_is_parsed():
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    polygon = np.asarray([[[2, 3], [24, 3], [24, 15], [2, 15]]])

    class PaddleOCR3Reader:
        predict_calls = []

        def ocr(self, input_image, **kwargs):
            raise AssertionError("PaddleOCR 3 should use predict().")

        def predict(self, input_image):
            self.predict_calls.append(input_image)
            return [
                {
                    "rec_texts": ["こんにちは"],
                    "rec_scores": np.asarray([0.97]),
                    "dt_polys": polygon,
                }
            ]

    reader = PaddleOCR3Reader()
    response = _engine_with_reader(reader).recognize(image, "ja")

    assert reader.predict_calls == [image]
    assert response.results[0].text == "こんにちは"
    assert response.results[0].confidence == 0.97
    assert response.results[0].bbox == polygon[0].tolist()
    assert response.results[0].language == "ja"


def test_ocr_type_error_from_inside_reader_is_not_swallowed():
    image = np.zeros((32, 32, 3), dtype=np.uint8)

    class BrokenReader:
        def ocr(self, input_image, cls=False):
            raise TypeError("inference failed inside reader")

    with pytest.raises(TypeError, match="inference failed inside reader"):
        _engine_with_reader(BrokenReader()).recognize(image, "ja")
