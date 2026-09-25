"""Shared test isolation for local persistent resources."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.cache import TranslationCache
from backend.config import MAX_CONCURRENT_INFERENCE


def pytest_collection_modifyitems(config, items):
    """Keep real-model integration tests opt-in with `pytest -m integration`."""
    if config.getoption("markexpr"):
        return
    skip_integration = pytest.mark.skip(
        reason="requires explicit `pytest -m integration` invocation"
    )
    for item in items:
        if item.get_closest_marker("integration") is not None:
            item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def isolate_translation_cache(monkeypatch, tmp_path):
    """Prevent API tests from opening the user's configured cache database."""
    import backend.main as main_module

    monkeypatch.setattr(
        main_module,
        "_translation_cache",
        TranslationCache(tmp_path / "disabled-test-cache.sqlite3", enabled=False),
    )
    # A semaphore can bind to the event loop of a concurrent test. Each test
    # gets its own instance because the API helpers create short-lived loops.
    monkeypatch.setattr(
        main_module,
        "_inference_semaphore",
        asyncio.Semaphore(MAX_CONCURRENT_INFERENCE),
    )
