"""Benchmark utility safety and output tests without real model inference."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import benchmark


def test_source_language_selects_only_required_local_models():
    assert benchmark._required_model_keys("ja") == ("ja-en",)
    assert benchmark._required_model_keys("zh-Hant") == ("zh-en",)
    assert set(benchmark._required_model_keys("auto")) == {
        "ko-en", "ja-en", "zh-en"
    }


def test_paddle_guard_refuses_missing_models_without_downloading(
    monkeypatch, tmp_path
):
    module_name = "fake_paddleocr_for_benchmark_test"
    download_calls = []
    original = lambda *args: download_calls.append(args)
    module = SimpleNamespace(maybe_download=original)
    monkeypatch.setitem(sys.modules, module_name, module)
    fake_class = type("FakePaddleOCR", (), {})
    fake_class.__module__ = module_name

    with benchmark._paddle_no_download_guard(fake_class):
        with pytest.raises(benchmark.BenchmarkSetupError, match="will not download"):
            module.maybe_download(tmp_path, "model-url")
    assert download_calls == []
    assert module.maybe_download is original


def test_paddle_guard_restores_downloader_after_local_model_check(
    monkeypatch, tmp_path
):
    module_name = "fake_paddleocr_with_local_models"
    original_calls = []
    original = lambda *args: original_calls.append(args)
    module = SimpleNamespace(maybe_download=original)
    monkeypatch.setitem(sys.modules, module_name, module)
    fake_class = type("FakePaddleOCR", (), {})
    fake_class.__module__ = module_name
    model_dir = tmp_path / "local-model"
    model_dir.mkdir()
    for name in ("inference.pdmodel", "inference.pdiparams"):
        (model_dir / name).write_bytes(b"local")

    with benchmark._paddle_no_download_guard(fake_class):
        module.maybe_download(model_dir, "model-url")
    assert original_calls == []
    assert module.maybe_download is original


def test_temporary_benchmark_cache_never_clears_normal_cache():
    class NormalCache:
        enabled = True
        clear_calls = 0

        def clear(self):
            self.clear_calls += 1

    normal_cache = NormalCache()
    fake_main = SimpleNamespace(_translation_cache=normal_cache)
    with benchmark._temporary_benchmark_cache(fake_main) as temporary_cache:
        assert temporary_cache is fake_main._translation_cache
        assert temporary_cache is not normal_cache
        assert temporary_cache.path.name == "benchmark-cache.sqlite3"
        temporary_cache.clear()
    assert normal_cache.clear_calls == 0
    assert fake_main._translation_cache is normal_cache


def test_benchmark_json_uses_safe_image_labels_and_aggregates(
    monkeypatch, tmp_path
):
    private_filename = "danielle-private-comic-page.png"
    image_path = tmp_path / private_filename
    image_path.write_bytes(b"mock image")

    class FakeCache:
        enabled = True

        def clear(self):
            return 0

        def stats(self):
            return {"entry_count": 1}

    scenario_bodies = (
        {
            "cache": {"hit": False},
            "image": {"width": 120, "height": 90},
            "num_regions": 1,
            "regions": [{"translation_status": "ok"}],
            "ocr_time_ms": 5.0,
            "translation_time_ms": 3.0,
            "total_time_ms": 10.0,
            "timing": {field: 1.0 for field in benchmark.TIMING_FIELDS},
        },
        {
            "cache": {"hit": False},
            "image": {"width": 120, "height": 90},
            "num_regions": 1,
            "regions": [{"translation_status": "ok"}],
            "ocr_time_ms": 5.0,
            "translation_time_ms": 3.0,
            "total_time_ms": 10.0,
            "timing": {field: 2.0 for field in benchmark.TIMING_FIELDS},
        },
        {
            "cache": {"hit": True},
            "image": {"width": 120, "height": 90},
            "num_regions": 1,
            "regions": [{"translation_status": "ok"}],
            "ocr_time_ms": 0.0,
            "translation_time_ms": 0.0,
            "total_time_ms": 0.0,
            "timing": {field: 0.0 for field in benchmark.TIMING_FIELDS},
        },
    )
    bodies = iter(scenario_bodies * 2)

    async def fake_post_image(_client, _path, _source):
        return next(bodies)

    monkeypatch.setattr(benchmark, "_post_image", fake_post_image)
    image_reports = asyncio.run(
        benchmark._collect_measurements(
            app=object(),
            cache=FakeCache(),
            image_paths=[image_path, tmp_path / "private-second-page.png"],
            source_language="ja",
        )
    )
    report = benchmark._build_report(image_reports, "ja")
    serialized = json.dumps(report)

    assert report["images"][0]["image"] == "image_001"
    assert report["images"][1]["image"] == "image_002"
    assert report["aggregate"]["first_request_in_process"]["count"] == 1
    assert report["aggregate"]["first_run_per_image"]["count"] == 2
    assert report["aggregate"]["cache_hit"]["count"] == 2
    assert (
        report["images"][1]["scenarios"]["first_request"]["label"]
        == "first_run_for_image_process_already_used"
    )
    assert private_filename not in serialized
    assert "private-second-page.png" not in serialized
    assert str(tmp_path) not in serialized
    assert str(Path.home()) not in serialized
