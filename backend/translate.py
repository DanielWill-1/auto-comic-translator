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


class TranslationProvider(Protocol):
    def translate(self, texts: list[str], source_lang: str, target_lang: str) -> list[TranslationResult]: ...


class MarianMTProvider:
    def __init__(self, config: TranslationConfig | None = None) -> None:
        self.config = config or TranslationConfig()
        self._models: dict[str, Any] = {}
        self._tokenizers: dict[str, Any] = {}

    def _model_key(self, source_lang: str, target_lang: str) -> str:
        src_code = LANGUAGE_TO_MARIAN_CODE.get(source_lang, source_lang)
        return f"{src_code}-{target_lang}"

    def _load_model(self, model_key: str) -> None:
        from transformers import MarianMTModel, MarianTokenizer

        local_path = LOCAL_MODELS.get(model_key)
        if local_path and Path(local_path).exists():
            self._tokenizers[model_key] = MarianTokenizer.from_pretrained(local_path)
            self._models[model_key] = MarianMTModel.from_pretrained(local_path)
        else:
            model_name = f"Helsinki-NLP/opus-mt-{model_key}"
            self._tokenizers[model_key] = MarianTokenizer.from_pretrained(model_name)
            self._models[model_key] = MarianMTModel.from_pretrained(model_name)

    def translate(
        self,
        texts: list[str],
        source_lang: str,
        target_lang: str,
    ) -> list[TranslationResult]:
        start = time.perf_counter()

        try:
            from transformers import MarianMTModel, MarianTokenizer
        except ImportError:
            return self._fallback_translate(texts, source_lang, target_lang, start)

        model_key = self._model_key(source_lang, target_lang)

        if model_key not in self._tokenizers:
            try:
                self._load_model(model_key)
            except Exception:
                return self._fallback_translate(texts, source_lang, target_lang, start)

        tokenizer = self._tokenizers[model_key]
        model = self._models[model_key]

        results: list[TranslationResult] = []
        for i in range(0, len(texts), self.config.batch_size):
            batch = texts[i : i + self.config.batch_size]
            inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=True)
            translated = model.generate(**inputs)
            decoded = tokenizer.batch_decode(translated, skip_special_tokens=True)
            for orig, trans in zip(batch, decoded):
                elapsed = (time.perf_counter() - start) * 1000
                results.append(TranslationResult(
                    original_text=orig,
                    translated_text=trans,
                    source_language=source_lang,
                    target_language=target_lang,
                    confidence=0.85,
                    processing_time_ms=round(elapsed, 2),
                ))
        return results

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
