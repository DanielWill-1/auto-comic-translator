from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from backend.config import LANGUAGE_TO_MARIAN_CODE, LOCAL_MODELS, TranslationConfig

try:
    import torch  # noqa: F401 — must import before paddle to avoid DLL conflict
    import transformers  # noqa: F401
except ImportError:
    pass


@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    confidence: float
    processing_time_ms: float
    status: str = "ok"  # "ok" = real translation; "fallback" = model unavailable


class TranslationProvider(Protocol):
    def translate(
        self, texts: list[str], source_lang: str, target_lang: str
    ) -> list[TranslationResult]: ...


class MarianMTProvider:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self.config = config or TranslationConfig()
        self._models: dict[str, Any] = {}
        self._tokenizers: dict[str, Any] = {}

    def _model_key(self, source_lang: str, target_lang: str) -> str:
        src_code = LANGUAGE_TO_MARIAN_CODE.get(source_lang, source_lang)
        return f"{src_code}-{target_lang}"

    def _load_model(self, model_key: str) -> None:
        local_path = LOCAL_MODELS.get(model_key)
        if not local_path or not Path(local_path).is_dir():
            raise FileNotFoundError(
                f"Local translation model '{model_key}' is unavailable. "
                "Download it with scripts/download_models.py."
            )

        from transformers import MarianMTModel, MarianTokenizer

        self._tokenizers[model_key] = MarianTokenizer.from_pretrained(
            local_path, local_files_only=True
        )
        self._models[model_key] = MarianMTModel.from_pretrained(
            local_path, local_files_only=True
        )

    def translate(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[TranslationResult]:
        translated, _ = self.translate_with_timings(
            texts, source_lang, target_lang
        )
        return translated

    def translate_with_timings(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> tuple[list[TranslationResult], float]:
        start = time.perf_counter()
        model_load_time_ms = 0.0

        try:
            from transformers import MarianMTModel, MarianTokenizer
        except ImportError:
            return (
                self._fallback_translate(texts, source_lang, target_lang, start),
                model_load_time_ms,
            )

        model_key = self._model_key(source_lang, target_lang)

        if model_key not in self._tokenizers:
            load_start = time.perf_counter()
            try:
                self._load_model(model_key)
            except Exception:
                model_load_time_ms = (time.perf_counter() - load_start) * 1000
                return (
                    self._fallback_translate(
                        texts, source_lang, target_lang, start
                    ),
                    model_load_time_ms,
                )
            model_load_time_ms = (time.perf_counter() - load_start) * 1000

        tokenizer = self._tokenizers[model_key]
        model = self._models[model_key]

        results: list[TranslationResult] = []
        try:
            for i in range(0, len(texts), self.config.batch_size):
                batch = texts[i : i + self.config.batch_size]
                inputs = tokenizer(
                    batch, return_tensors="pt", padding=True, truncation=True
                )
                translated = model.generate(**inputs)
                decoded = tokenizer.batch_decode(
                    translated, skip_special_tokens=True
                )
                if len(decoded) != len(batch):
                    raise RuntimeError("Translation model returned an invalid batch")
                for orig, trans in zip(batch, decoded):
                    elapsed = (time.perf_counter() - start) * 1000
                    results.append(TranslationResult(
                        original_text=orig,
                        translated_text=trans,
                        source_language=source_lang,
                        target_language=target_lang,
                        confidence=0.85,
                        processing_time_ms=round(elapsed, 2),
                        status="ok",
                    ))
        except Exception:
            return (
                self._fallback_translate(texts, source_lang, target_lang, start),
                model_load_time_ms,
            )
        return results, model_load_time_ms

    def _fallback_translate(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
        start: float,
    ) -> list[TranslationResult]:
        elapsed = (time.perf_counter() - start) * 1000
        return [
            TranslationResult(
                original_text=t,
                translated_text=t,
                source_language=source_lang,
                target_language=target_lang,
                confidence=0.0,
                processing_time_ms=round(elapsed, 2),
                status="fallback",
            )
            for t in texts
        ]


class TranslationEngine:
    def __init__(self, provider: TranslationProvider | None = None) -> None:
        self._provider = provider or MarianMTProvider()

    def translate(
        self,
        texts: list[str],
        source_lang: str = "ko",
        target_lang: str = "en",
    ) -> list[TranslationResult]:
        return self._provider.translate(texts, source_lang, target_lang)

    def translate_single(
        self,
        text: str,
        source_lang: str = "ko",
        target_lang: str = "en",
    ) -> TranslationResult:
        results = self.translate([text], source_lang, target_lang)
        return results[0]

    def translate_mixed(
        self,
        items: list[tuple[str, str | None]],
        target_lang: str = "en",
    ) -> list[TranslationResult]:
        translated, _, _ = self.translate_mixed_with_timings(items, target_lang)
        return translated

    def translate_mixed_with_timings(
        self,
        items: list[tuple[str, str | None]],
        target_lang: str = "en",
    ) -> tuple[list[TranslationResult], float, float]:
        """Translate regions that may have different source languages.

        ``items`` is a list of ``(text, source_lang)`` pairs in original
        region order. Texts are grouped by their resolved source language so
        each language is translated as a single efficient batch (never one
        model instance per region), then results are returned in the original
        order. Regions with no usable language are echoed with an explicit
        fallback status rather than sent to a nonexistent ``auto-en`` model.
        """
        translation_start = time.perf_counter()
        model_load_time_ms = 0.0
        if not items:
            return [], (time.perf_counter() - translation_start) * 1000, 0.0

        groups: dict[str, list[tuple[int, str]]] = {}
        for idx, (text, lang) in enumerate(items):
            key = (lang or "auto").strip() or "auto"
            groups.setdefault(key, []).append((idx, text))

        # Translate each language group as a batch.
        by_index: dict[int, TranslationResult] = {}
        for lang, group in groups.items():
            ordered = sorted(group, key=lambda pair: pair[0])
            texts = [t for _, t in ordered]
            if lang == "auto":
                # Auto is an OCR request mode, not a Marian model code. If a
                # region has no detected language, preserve its text and make
                # the unavailable translation explicit instead of attempting
                # to load a nonexistent auto-en model.
                for idx, text in ordered:
                    by_index[idx] = TranslationResult(
                        original_text=text,
                        translated_text=text,
                        source_language="unknown",
                        target_language=target_lang,
                        confidence=0.0,
                        processing_time_ms=0.0,
                        status="fallback",
                    )
                continue
            timed_translate = getattr(
                self._provider, "translate_with_timings", None
            )
            if callable(timed_translate):
                translated, load_ms = timed_translate(texts, lang, target_lang)
                model_load_time_ms += load_ms
            else:
                translated = self._provider.translate(texts, lang, target_lang)
            for (idx, _), result in zip(ordered, translated):
                by_index[idx] = result

        return (
            [by_index[i] for i in range(len(items))],
            (time.perf_counter() - translation_start) * 1000,
            model_load_time_ms,
        )
