"""Small, local SQLite cache for successful translation API results."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterator

from backend.config import (
    API_VERSION,
    CACHE_PIPELINE_VERSION,
    CACHE_SCHEMA_VERSION,
    LOCAL_MODELS,
    PipelineConfig,
    SUPPORTED_LANGUAGES,
    TranslationConfig,
)

logger = logging.getLogger("auto-comic-translator.cache")

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS translation_cache (
    cache_key TEXT PRIMARY KEY,
    image_hash TEXT NOT NULL,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_accessed_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0
)
"""

_REQUIRED_RESULT_FIELDS = {
    "api_version",
    "source_language",
    "target_language",
    "image",
    "ocr_time_ms",
    "translation_time_ms",
    "total_time_ms",
    "num_regions",
    "regions",
}
_REQUIRED_REGION_FIELDS = {
    "original_text",
    "translated_text",
    "confidence",
    "ocr_confidence",
    "translation_time_ms",
    "source_language",
    "translation_status",
    "bbox",
    "bbox_points",
}


@dataclass(frozen=True)
class CacheIdentity:
    cache_key: str
    image_hash: str
    source_language: str
    target_language: str
    config_fingerprint: str
    schema_version: int


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _installed_version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "not-installed"


def _finite_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def processing_config_fingerprint(
    pipeline_config: PipelineConfig | None = None,
    *,
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> str:
    """Hash only settings and model identities that can affect a result."""
    config = pipeline_config or PipelineConfig(use_gpu=False)
    model_ids = {
        "ko-en": "Helsinki-NLP/opus-mt-ko-en",
        "ja-en": "Helsinki-NLP/opus-mt-ja-en",
        "zh-en": "Helsinki-NLP/opus-mt-zh-en",
    }
    models = {
        model_key: {
            "identifier": model_ids[model_key],
            "configured_path": str(Path(path).resolve()),
        }
        for model_key, path in sorted(LOCAL_MODELS.items())
    }
    fingerprint_data = {
        "api_version": API_VERSION,
        "pipeline_implementation_version": CACHE_PIPELINE_VERSION,
        "cache_schema_version": schema_version,
        "ocr": {
            "implementation": "PaddleOCR",
            "versions": {
                "paddleocr": _installed_version("paddleocr"),
                "paddlepaddle": _installed_version("paddlepaddle"),
            },
            "supported_languages": SUPPORTED_LANGUAGES,
            "confidence_threshold": config.confidence_threshold,
            "use_gpu": config.use_gpu,
        },
        "preprocessing": {
            "implementation": "ImagePreprocessor-v1",
            "versions": {
                "opencv-python": _installed_version("opencv-python"),
                "Pillow": _installed_version("Pillow"),
                "numpy": _installed_version("numpy"),
            },
            "config": asdict(config.preprocessing),
        },
        "grouping": {
            "implementation": "vertical-proximity-v1",
            "proximity_px": config.text_group_proximity_px,
        },
        "translation": {
            "provider": "MarianMTProvider",
            "implementation_version": 1,
            "library_versions": {
                "transformers": _installed_version("transformers"),
                "torch": _installed_version("torch"),
            },
            "config": asdict(TranslationConfig()),
            "generation_kwargs": {},
            "models": models,
        },
    }
    encoded = _canonical_json(fingerprint_data).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_cache_identity(
    image_bytes: bytes,
    source_language: str,
    target_language: str,
    config_fingerprint: str,
    *,
    schema_version: int = CACHE_SCHEMA_VERSION,
) -> CacheIdentity:
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    identity_data = {
        "image_hash": image_hash,
        "source_language": source_language,
        "target_language": target_language,
        "config_fingerprint": config_fingerprint,
        "schema_version": schema_version,
    }
    cache_key = hashlib.sha256(
        _canonical_json(identity_data).encode("utf-8")
    ).hexdigest()
    return CacheIdentity(
        cache_key=cache_key,
        image_hash=image_hash,
        source_language=source_language,
        target_language=target_language,
        config_fingerprint=config_fingerprint,
        schema_version=schema_version,
    )


def is_cacheable_result(result: object) -> bool:
    """Accept complete successful API results, including valid empty results."""
    if not isinstance(result, dict) or not _REQUIRED_RESULT_FIELDS.issubset(result):
        return False
    if result.get("api_version") != API_VERSION:
        return False
    if not isinstance(result.get("source_language"), str):
        return False
    if not isinstance(result.get("target_language"), str):
        return False
    image = result.get("image")
    if not isinstance(image, dict) or not all(
        type(image.get(key)) is int and image[key] > 0
        for key in ("width", "height")
    ):
        return False
    regions = result.get("regions")
    if (
        not isinstance(regions, list)
        or type(result.get("num_regions")) is not int
        or result["num_regions"] != len(regions)
    ):
        return False
    if not all(
        _finite_number(result.get(field)) and result[field] >= 0
        for field in ("ocr_time_ms", "translation_time_ms", "total_time_ms")
    ):
        return False

    for region in regions:
        if not isinstance(region, dict) or not _REQUIRED_REGION_FIELDS.issubset(region):
            return False
        if region.get("translation_status") != "ok":
            return False
        if not isinstance(region.get("original_text"), str):
            return False
        if not isinstance(region.get("translated_text"), str):
            return False
        if region.get("source_language") is not None and not isinstance(
            region["source_language"], str
        ):
            return False
        if not all(
            _finite_number(region.get(field)) and 0 <= region[field] <= 1
            for field in ("confidence", "ocr_confidence")
        ):
            return False
        if not _finite_number(region.get("translation_time_ms")):
            return False
        if region["translation_time_ms"] < 0:
            return False
        bbox = region.get("bbox")
        if not isinstance(bbox, dict) or not all(
            type(bbox.get(key)) is int for key in ("x1", "y1", "x2", "y2")
        ):
            return False
        if bbox["x1"] > bbox["x2"] or bbox["y1"] > bbox["y2"]:
            return False
        bbox_points = region.get("bbox_points")
        if not isinstance(bbox_points, list) or not bbox_points:
            return False
        if not all(
            isinstance(point, list)
            and len(point) == 2
            and all(type(coordinate) is int for coordinate in point)
            for point in bbox_points
        ):
            return False
    return True


class TranslationCache:
    """SQLite cache using a fresh short-lived connection for each operation."""

    def __init__(self, path: Path | str, *, enabled: bool = True) -> None:
        self.path = Path(path).expanduser().resolve()
        self.enabled = enabled

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute(_TABLE_SQL)
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def get(self, identity: CacheIdentity) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """SELECT image_hash, source_language, target_language,
                              config_fingerprint, schema_version, result_json
                       FROM translation_cache WHERE cache_key = ?""",
                    (identity.cache_key,),
                ).fetchone()
                if row is None:
                    return None
                row_matches = (
                    row["image_hash"] == identity.image_hash
                    and row["source_language"] == identity.source_language
                    and row["target_language"] == identity.target_language
                    and row["config_fingerprint"] == identity.config_fingerprint
                    and row["schema_version"] == identity.schema_version
                )
                try:
                    result = json.loads(row["result_json"])
                except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
                    result = None
                if not row_matches or not is_cacheable_result(result):
                    logger.warning(
                        "Ignoring corrupt or incompatible translation cache row"
                    )
                    connection.execute(
                        "DELETE FROM translation_cache WHERE cache_key = ?",
                        (identity.cache_key,),
                    )
                    return None
                connection.execute(
                    """UPDATE translation_cache
                       SET last_accessed_at = ?, hit_count = hit_count + 1
                       WHERE cache_key = ?""",
                    (self._now(), identity.cache_key),
                )
                return result
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            logger.warning("Translation cache read failed; treating as miss: %s", exc)
            return None

    def put(self, identity: CacheIdentity, result: dict[str, Any]) -> bool:
        if not self.enabled or not is_cacheable_result(result):
            return False
        try:
            result_json = _canonical_json(result)
            now = self._now()
            with self._connection() as connection:
                connection.execute(
                    """INSERT INTO translation_cache (
                           cache_key, image_hash, source_language, target_language,
                           config_fingerprint, schema_version, result_json,
                           created_at, last_accessed_at, hit_count
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                       ON CONFLICT(cache_key) DO UPDATE SET
                           image_hash = excluded.image_hash,
                           source_language = excluded.source_language,
                           target_language = excluded.target_language,
                           config_fingerprint = excluded.config_fingerprint,
                           schema_version = excluded.schema_version,
                           result_json = excluded.result_json,
                           created_at = excluded.created_at,
                           last_accessed_at = excluded.last_accessed_at,
                           hit_count = 0""",
                    (
                        identity.cache_key,
                        identity.image_hash,
                        identity.source_language,
                        identity.target_language,
                        identity.config_fingerprint,
                        identity.schema_version,
                        result_json,
                        now,
                        now,
                    ),
                )
            return True
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            logger.warning(
                "Translation cache write failed; continuing without cache: %s",
                exc,
            )
            return False

    def clear(self) -> int:
        if not self.enabled:
            return 0
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM translation_cache")
            return max(cursor.rowcount, 0)

    def stats(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "entry_count": 0,
                "total_hits": 0,
                "database_bytes": 0,
            }
        try:
            with self._connection() as connection:
                row = connection.execute(
                    """SELECT COUNT(*) AS entry_count,
                              COALESCE(SUM(hit_count), 0) AS total_hits
                       FROM translation_cache"""
                ).fetchone()
            try:
                database_bytes = self.path.stat().st_size
            except OSError:
                database_bytes = 0
            return {
                "enabled": True,
                "entry_count": row["entry_count"],
                "total_hits": row["total_hits"],
                "database_bytes": database_bytes,
            }
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            logger.warning("Translation cache stats failed: %s", exc)
            return {
                "enabled": True,
                "entry_count": 0,
                "total_hits": 0,
                "database_bytes": 0,
                "error": "cache unavailable",
            }


def _run_cli() -> int:
    import argparse

    from backend.config import CACHE_PATH

    parser = argparse.ArgumentParser(
        description="Inspect or clear the local translation cache."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("stats", help="show cache entry and hit counts")
    commands.add_parser("clear", help="remove all cached translation results")
    args = parser.parse_args()
    cache = TranslationCache(CACHE_PATH, enabled=True)

    if args.command == "stats":
        print(json.dumps(cache.stats(), indent=2))
        return 0

    deleted = cache.clear()
    print(f"Cleared {deleted} cached translation result(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run_cli())
