"""Auto-mode OCR reader selection: skip locally unavailable readers safely.

These checks never load a real OCR or translation model and never download
anything. Fake ``paddleocr`` packages and fake readers are used throughout.
"""

from __future__ import annotations

import asyncio
import io
import sys
from types import ModuleType

import httpx
import numpy as np
import pytest
from PIL import Image

import backend.ocr as ocr_module
from backend.ocr import (
    OCREngine,
    OCRSetupError,
    _paddle_model_directories,
    _paddlex_model_directories,
    is_reader_available,
)


class RecordingReader:
    """Legacy-style reader that records every inference call."""

    def __init__(
        self,
        text: str = "こんにちは",
        confidence: float = 0.95,
        bbox: list[list[int]] | None = None,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.bbox = bbox or [[4, 8], [40, 8], [40, 60], [4, 60]]
        self.calls: list[np.ndarray] = []

    def ocr(self, input_image, cls=False):
        self.calls.append(input_image)
        polygon = self.bbox
        return [[(polygon, (self.text, self.confidence))]]


class BrokenReader:
    """A valid-looking reader whose inference raises an unrelated error."""

    def ocr(self, input_image, cls=False):
        raise TypeError("inference failed inside reader")


def image() -> np.ndarray:
    return np.zeros((64, 64, 3), dtype=np.uint8)


def install_fake_paddleocr3(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    install_model_files: bool,
):
    """Install a fake PaddleOCR 3.x package plus optional local model files."""
    reader_options: list[dict] = []

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            reader_options.append(kwargs)

        def ocr(self, input_image, **kwargs):
            return [
                {
                    "rec_texts": ["こんにちは"],
                    "rec_scores": np.asarray([0.95]),
                    "dt_polys": np.asarray(
                        [[[4, 8], [40, 8], [40, 60], [4, 60]]]
                    ),
                }
            ]

    paddle_package = ModuleType("paddleocr")
    paddle_package.__version__ = "3.7.0"
    paddle_package.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", paddle_package)
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path))

    model_specs = _paddlex_model_directories("japan", tmp_path)
    if install_model_files:
        for _, directory in model_specs:
            directory.mkdir(parents=True, exist_ok=True)
            for filename in (
                "inference.yml",
                "inference.json",
                "inference.pdiparams",
            ):
                (directory / filename).write_bytes(b"local model")
    return model_specs, reader_options


def install_fake_paddleocr2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    install_model_files: bool,
):
    """Install a fake PaddleOCR 2.x package plus optional local model files."""
    module_name = "fake_paddleocr2_module"
    paddle_module = ModuleType(module_name)
    paddle_module.BASE_DIR = str(tmp_path)
    paddle_module.DEFAULT_OCR_MODEL_VERSION = "test-version"
    paddle_module.parse_lang = lambda language: (language, "ml")
    paddle_module.get_model_config = lambda _kind, _version, model_type, language: {
        "url": f"https://example.invalid/{model_type}-{language}.tar"
    }
    downloads: list[tuple] = []

    def original_downloader(model_directory, url):
        downloads.append((model_directory, url))

    paddle_module.maybe_download = original_downloader
    reader_options: list[tuple] = []

    class FakePaddleOCR:
        def __init__(self, *, lang, use_gpu, show_log):
            reader_options.append((lang, use_gpu, show_log))

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


def test_auto_uses_available_readers_and_skips_missing_ones(monkeypatch):
    sample = image()
    reader = RecordingReader()
    engine = OCREngine(use_gpu=False)
    engine._readers["ja"] = reader
    monkeypatch.setattr(
        ocr_module, "is_reader_available", lambda lang_key: lang_key == "ja"
    )

    response = engine.recognize(sample, source_language="auto")

    assert response.source_language == "auto"
    assert [result.text for result in response.results] == ["こんにちは"]
    assert [result.language for result in response.results] == ["ja"]
    assert len(reader.calls) == 1
    assert reader.calls[0] is sample
    # Only the available reader was used; missing readers were never built.
    assert set(engine._readers) == {"ja"}


def test_auto_runs_a_shared_local_model_set_once(monkeypatch, tmp_path):
    """ja, zh, and zh-Hant share one PP-OCRv6 recognizer, so it runs once.

    Before this, auto mode built three readers over the same model files and paid
    three OCR passes for identical text.
    """
    _, reader_options = install_fake_paddleocr3(
        monkeypatch, tmp_path, install_model_files=True
    )
    engine = OCREngine(use_gpu=False)

    response = engine.recognize(image(), source_language="auto")

    assert [result.text for result in response.results] == ["こんにちは"]
    assert len(reader_options) == 1
    assert set(engine._readers) == {"ja"}


@pytest.mark.parametrize(
    ("text", "expected_language"),
    [
        ("こんにちは", "ja"),
        ("你好世界", "zh"),
        ("안녕하세요", "ko"),
    ],
)
def test_auto_labels_a_shared_reader_by_the_script_it_read(
    monkeypatch, tmp_path, text, expected_language
):
    """A shared recognizer cannot name its own language; the script can."""
    install_fake_paddleocr3(monkeypatch, tmp_path, install_model_files=True)
    engine = OCREngine(use_gpu=False)
    engine._readers["ja"] = RecordingReader(text)

    response = engine.recognize(image(), source_language="auto")

    assert [result.language for result in response.results] == [expected_language]


def test_auto_relabels_a_mismatched_reader_by_the_script_it_read(
    monkeypatch, tmp_path
):
    """A reader that misreads another script must not name the page.

    Measured on a real Japanese sample: the Korean reader produced a
    kana-containing line at a higher confidence than the Japanese reader, which
    made the whole page resolve to Korean and translate with the Korean model.
    """
    install_fake_paddleocr3(monkeypatch, tmp_path, install_model_files=True)
    monkeypatch.setattr(
        ocr_module,
        "is_reader_available",
        lambda lang_key: lang_key in {"ja", "ko"},
    )
    engine = OCREngine(use_gpu=False)
    engine._readers["ko"] = RecordingReader(
        "じゃーーん", confidence=0.81, bbox=[[4, 8], [40, 8], [40, 60], [4, 60]]
    )
    engine._readers["ja"] = RecordingReader(
        "お湯をわかします", confidence=0.73, bbox=[[60, 8], [96, 8], [96, 60], [60, 60]]
    )

    response = engine.recognize(image(), source_language="auto")

    assert [result.language for result in response.results] == ["ja", "ja"]


def test_auto_assigns_script_less_regions_the_page_language(monkeypatch, tmp_path):
    """A stray digit must not name the page after the reader that produced it.

    Measured on a real Japanese sample: the Korean reader returned short
    script-less fragments ('7', 'A', '#4') at higher confidence than the Japanese
    text, and together they outvoted it.
    """
    install_fake_paddleocr3(monkeypatch, tmp_path, install_model_files=True)
    monkeypatch.setattr(
        ocr_module,
        "is_reader_available",
        lambda lang_key: lang_key in {"ja", "ko"},
    )
    engine = OCREngine(use_gpu=False)
    engine._readers["ko"] = RecordingReader(
        "7", confidence=0.99, bbox=[[4, 8], [40, 8], [40, 60], [4, 60]]
    )
    engine._readers["ja"] = RecordingReader(
        "お湯をわかします", confidence=0.60, bbox=[[60, 8], [96, 8], [96, 60], [60, 60]]
    )

    response = engine.recognize(image(), source_language="auto")

    assert [result.language for result in response.results] == ["ja", "ja"]


def test_explicit_language_is_never_relabelled_by_script(monkeypatch, tmp_path):
    install_fake_paddleocr3(monkeypatch, tmp_path, install_model_files=True)
    engine = OCREngine(use_gpu=False)
    engine._readers["zh"] = RecordingReader("こんにちは")

    response = engine.recognize(image(), source_language="zh")

    assert [result.language for result in response.results] == ["zh"]


def test_auto_reports_a_controlled_setup_error_when_nothing_is_available(
    monkeypatch,
):
    engine = OCREngine(use_gpu=False)
    monkeypatch.setattr(ocr_module, "is_reader_available", lambda lang_key: False)

    with pytest.raises(OCRSetupError, match="No local OCR readers are available"):
        engine.recognize(image(), source_language="auto")

    assert engine._readers == {}


def test_auto_skips_a_reader_whose_models_disappeared(monkeypatch):
    engine = OCREngine(use_gpu=False)
    monkeypatch.setattr(
        ocr_module, "is_reader_available", lambda lang_key: lang_key == "ja"
    )

    def missing_reader(lang_key):
        raise FileNotFoundError(f"{lang_key} local model is missing")

    monkeypatch.setattr(engine, "_get_reader", missing_reader)

    with pytest.raises(OCRSetupError, match="No local OCR readers are available"):
        engine.recognize(image(), source_language="auto")


def test_explicit_language_reports_a_setup_error_not_a_generic_failure(monkeypatch):
    engine = OCREngine(use_gpu=False)

    def missing_reader(lang_key):
        raise FileNotFoundError(f"{lang_key} local model is missing")

    monkeypatch.setattr(engine, "_get_reader", missing_reader)

    # Explicit selection stays strict (no silent empty output) but reports the
    # missing local model set as a setup error, which the API maps to 503.
    with pytest.raises(OCRSetupError, match="source_language='ko'"):
        engine.recognize(image(), source_language="ko")


def test_explicit_language_with_uninstalled_models_never_initializes(
    monkeypatch, tmp_path
):
    _, reader_options = install_fake_paddleocr3(
        monkeypatch, tmp_path, install_model_files=False
    )
    engine = OCREngine(use_gpu=False)

    with pytest.raises(OCRSetupError, match="Model downloads are disabled"):
        engine.recognize(image(), source_language="ja")

    assert reader_options == []
    assert engine._readers == {}


def test_auto_does_not_swallow_unrelated_reader_errors(monkeypatch):
    engine = OCREngine(use_gpu=False)
    engine._readers["ja"] = BrokenReader()
    monkeypatch.setattr(
        ocr_module, "is_reader_available", lambda lang_key: lang_key == "ja"
    )

    with pytest.raises(TypeError, match="inference failed inside reader"):
        engine.recognize(image(), source_language="auto")


def test_reader_availability_is_filesystem_only(monkeypatch, tmp_path):
    _, reader_options = install_fake_paddleocr3(
        monkeypatch, tmp_path, install_model_files=True
    )

    assert is_reader_available("ja") is True
    # Japanese, Simplified and Traditional Chinese share the installed v6 models.
    assert is_reader_available("zh") is True
    assert is_reader_available("zh-Hant") is True
    # Korean needs PP-OCRv5_server_det, which is not installed here.
    assert is_reader_available("ko") is False
    # Deciding availability must not construct a reader or download anything.
    assert reader_options == []


def test_paddleocr2_availability_check_does_not_download(monkeypatch, tmp_path):
    module, original, downloads, reader_options = install_fake_paddleocr2(
        monkeypatch, tmp_path, install_model_files=True
    )

    assert is_reader_available("ja") is True
    assert is_reader_available("ko") is False
    assert downloads == []
    assert reader_options == []
    assert module.maybe_download is original


def test_auto_runs_only_the_installed_readers(monkeypatch, tmp_path):
    _, reader_options = install_fake_paddleocr3(
        monkeypatch, tmp_path, install_model_files=True
    )
    engine = OCREngine(use_gpu=False)

    response = engine.recognize(image(), source_language="auto")

    assert response.num_text_regions == 1
    assert response.source_language == "auto"
    # ja, zh and zh-Hant are served by one shared PP-OCRv6 model set, so auto
    # builds it once; Korean was skipped because its files are not installed.
    assert [options["text_detection_model_name"] for options in reader_options] == [
        "PP-OCRv6_medium_det"
    ]
    assert "ko" not in engine._readers
    assert set(engine._readers) == {"ja"}


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (120, 120), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def request_app(app_instance, method: str, path: str, **kwargs):
    async def send_request():
        transport = httpx.ASGITransport(app=app_instance)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(send_request())


@pytest.mark.parametrize("path", ["/ocr", "/translate"])
def test_zero_available_readers_returns_a_structured_error(monkeypatch, path):
    import backend.main as main_module

    def failing_pipeline():
        class FailingPipeline:
            def run(self, image, source_language="auto", **kwargs):
                raise OCRSetupError("no local readers")

            def run_with_grouping(self, image, source_language="auto", **kwargs):
                raise OCRSetupError("no local readers")

        return FailingPipeline()

    monkeypatch.setattr(main_module, "get_ocr_pipeline", failing_pipeline)
    monkeypatch.setattr(main_module, "get_full_pipeline", failing_pipeline)

    response = request_app(
        main_module.app,
        "POST",
        path,
        files={"image": ("page.png", png_bytes(), "image/png")},
        data={"source_language": "auto", "target_language": "en"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["api_version"] == "1"
    assert body["error"]["code"] == "OCR_READERS_UNAVAILABLE"
    assert "no local readers" not in body["error"]["message"]
    assert "Traceback" not in body["error"]["message"]
    assert body["error"]["request_id"]
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]


@pytest.mark.parametrize("path", ["/ocr", "/translate"])
def test_explicitly_unavailable_language_returns_503_not_500(monkeypatch, path):
    """An explicitly requested language with no local models is a setup error.

    This is the regression behind the reported Korean failure on an environment
    where the Korean model files are not installed: the request used to surface
    as a generic 500 with no actionable code.
    """
    import backend.main as main_module

    engine = OCREngine(use_gpu=False)

    def missing_reader(lang_key):
        raise FileNotFoundError(f"{lang_key} local model is missing")

    monkeypatch.setattr(engine, "_get_reader", missing_reader)

    def pipeline_factory():
        class Pipeline:
            def run(self, image, source_language="auto", **kwargs):
                return engine.recognize(image, source_language=source_language)

            def run_with_grouping(self, image, source_language="auto", **kwargs):
                return engine.recognize(image, source_language=source_language)

        return Pipeline()

    monkeypatch.setattr(main_module, "get_ocr_pipeline", pipeline_factory)
    monkeypatch.setattr(main_module, "get_full_pipeline", pipeline_factory)

    response = request_app(
        main_module.app,
        "POST",
        path,
        files={"image": ("page.png", png_bytes(), "image/png")},
        data={"source_language": "ko", "target_language": "en"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "OCR_READERS_UNAVAILABLE"
    assert "local model is missing" not in body["error"]["message"]


def test_ready_reports_the_available_ocr_languages(monkeypatch):
    import backend.main as main_module

    monkeypatch.setattr(main_module, "_ocr_pipeline", None)
    monkeypatch.setattr(
        main_module, "is_reader_available", lambda lang_key: lang_key == "ja"
    )

    response = request_app(main_module.app, "GET", "/ready")

    assert response.status_code in {200, 503}
    assert response.json()["ocr_languages"] == ["ja"]
