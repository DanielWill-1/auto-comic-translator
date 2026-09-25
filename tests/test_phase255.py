"""Local PaddleOCR model loading must never download during a request."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from backend.ocr import OCREngine, _paddle_model_directories


def install_fake_paddleocr(monkeypatch, tmp_path, *, install_model_files):
    module_name = "fake_paddleocr_reader_module"
    paddle_module = ModuleType(module_name)
    paddle_module.BASE_DIR = str(tmp_path)
    paddle_module.DEFAULT_OCR_MODEL_VERSION = "test-version"
    paddle_module.parse_lang = lambda language: (language, "ml")
    paddle_module.get_model_config = lambda _kind, _version, model_type, language: {
        "url": f"https://example.invalid/{model_type}-{language}.tar"
    }
    downloads = []

    def original_downloader(model_directory, url):
        downloads.append((model_directory, url))

    paddle_module.maybe_download = original_downloader
    reader_options = []

    class FakePaddleOCR:
        def __init__(self, *, lang, use_gpu, show_log):
            reader_options.append((lang, use_gpu, show_log))
            for model_directory in _paddle_model_directories(
                paddle_module, lang
            ):
                paddle_module.maybe_download(
                    model_directory, "https://example.invalid/model.tar"
                )

    FakePaddleOCR.__module__ = module_name
    paddle_package = ModuleType("paddleocr")
    paddle_package.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, module_name, paddle_module)
    monkeypatch.setitem(sys.modules, "paddleocr", paddle_package)

    directories = _paddle_model_directories(paddle_module, "japan")
    if install_model_files:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            for filename in ("inference.pdmodel", "inference.pdiparams"):
                (directory / filename).write_bytes(b"local model")
    return paddle_module, original_downloader, downloads, reader_options


def test_missing_paddle_model_fails_before_downloader_is_called(
    monkeypatch, tmp_path
):
    module, original, downloads, reader_options = install_fake_paddleocr(
        monkeypatch, tmp_path, install_model_files=False
    )

    with pytest.raises(FileNotFoundError, match="do not download models"):
        OCREngine(use_gpu=False)._get_reader("ja")

    assert downloads == []
    assert reader_options == []
    assert module.maybe_download is original


def test_local_paddle_models_load_with_configured_device_and_quiet_logs(
    monkeypatch, tmp_path
):
    module, original, downloads, reader_options = install_fake_paddleocr(
        monkeypatch, tmp_path, install_model_files=True
    )
    engine = OCREngine(use_gpu=False)

    reader = engine._get_reader("ja")
    assert reader is engine._get_reader("ja")
    assert reader_options == [("japan", False, False)]
    assert downloads == []
    assert module.maybe_download is original
