from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from .translation_literals import (
    missing_protected_literals,
    protect_literals,
    restore_literals,
    translate_preserving_literals,
)

FAST_MODELS = {
    ("en", "ru"): "Helsinki-NLP/opus-mt-en-ru",
    ("uk", "ru"): "Helsinki-NLP/opus-mt-uk-ru",
}

FAST_CORE_FILES = ("model.bin", "config.json")
FAST_TOKENIZER_FILES = ("source.spm", "target.spm")
FAST_BEAM_SIZE = 6
FAST_REPETITION_PENALTY = 1.0
FAST_NO_REPEAT_NGRAM_SIZE = 0
FAST_SOURCE_EOS_TOKEN = "</s>"
FAST_RETRY_BEAM_SIZE = 8
FAST_RETRY_REPETITION_PENALTY = 1.12
FAST_RETRY_NO_REPEAT_NGRAM_SIZE = 3
FAST_TRANSLATION_PIPELINE_VERSION = 6


@dataclass(frozen=True)
class FastTranslationStats:
    engine: str
    model: str
    compute_type: str
    inter_threads: int
    intra_threads: int
    pages_total: int
    pages_translated: int
    elapsed_seconds: float
    chars_translated: int
    pages_per_minute: float
    chars_per_second: float
    page_batch: int
    quality_retries: int
    quality_fallbacks: int
    quality_warnings: int
    literal_segment_fallbacks: int


def fast_translation_available() -> bool:
    return all(
        importlib.util.find_spec(name) is not None
        for name in ("ctranslate2", "sentencepiece", "transformers")
    )


def fast_model_dir(settings, source_lang: str, target_lang: str = "ru") -> Path:
    return (
        settings.workspace_dir
        / "models"
        / "translation"
        / f"{source_lang}-{target_lang}-opus-int8"
    )


def _usable_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _fast_model_core_ready(path: Path) -> bool:
    return all(_usable_file(path / name) for name in FAST_CORE_FILES)


def fast_model_ready(settings, source_lang: str, target_lang: str = "ru") -> bool:
    path = fast_model_dir(settings, source_lang, target_lang)
    return _fast_model_core_ready(path) and all(
        _usable_file(path / name) for name in FAST_TOKENIZER_FILES
    )


def _download_model_asset(model_id: str, filename: str) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=model_id, filename=filename))


def _ensure_tokenizer_assets(
    model_id: str,
    output_dir: Path,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    missing = [name for name in FAST_TOKENIZER_FILES if not _usable_file(output_dir / name)]
    total = len(missing)

    for index, filename in enumerate(missing, 1):
        if progress:
            progress(index - 1, total, f"Restoring tokenizer asset {filename}…")
        cached = _download_model_asset(model_id, filename)
        if not _usable_file(cached):
            raise RuntimeError(f"Downloaded tokenizer asset is missing or empty: {filename}")
        destination = output_dir / filename
        temp = destination.with_suffix(destination.suffix + ".tmp")
        try:
            shutil.copyfile(cached, temp)
            temp.replace(destination)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass

    still_missing = [
        name for name in FAST_TOKENIZER_FILES
        if not _usable_file(output_dir / name)
    ]
    if still_missing:
        raise RuntimeError(
            "Fast tokenizer assets are incomplete: " + ", ".join(still_missing)
        )


def fast_ready_pairs(settings) -> set[tuple[str, str]]:
    return {
        pair for pair in FAST_MODELS
        if fast_model_ready(settings, *pair)
    }


def prepare_fast_model(
    settings,
    source_lang: str,
    target_lang: str = "ru",
    *,
    progress: Callable[[int, int, str], None] | None = None,
    run_benchmark: bool = True,
) -> dict:
    pair = (source_lang, target_lang)
    model_id = FAST_MODELS.get(pair)
    if model_id is None:
        raise RuntimeError(f"Fast translation model is not configured for {source_lang}→{target_lang}")
    if not fast_translation_available():
        raise RuntimeError(
            "Fast Translation dependencies are missing. Run the updater or install: "
            "pip install -e '.[fasttranslate]'"
        )

    output_dir = fast_model_dir(settings, source_lang, target_lang)
    if fast_model_ready(settings, source_lang, target_lang):
        info = {
            "ready": True,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "model": model_id,
            "path": str(output_dir),
        }
        benchmark = load_fast_benchmark(settings, source_lang, target_lang)
        if benchmark:
            info["benchmark"] = benchmark
        return info

    output_dir.parent.mkdir(parents=True, exist_ok=True)

    # A previous setup may already contain the expensive converted weights but
    # miss tokenizer assets. Repair that directory in-place instead of
    # converting the model again.
    if _fast_model_core_ready(output_dir):
        try:
            if progress:
                progress(0, 0, f"Repairing {source_lang}→{target_lang} tokenizer files…")
            _ensure_tokenizer_assets(model_id, output_dir, progress=progress)
        except Exception as exc:
            raise RuntimeError(f"Fast model tokenizer repair failed: {exc}") from exc
    else:
        temp_dir = output_dir.with_name(output_dir.name + ".tmp")
        shutil.rmtree(temp_dir, ignore_errors=True)
        if progress:
            progress(0, 0, f"Downloading and converting {source_lang}→{target_lang} Fast model…")

        try:
            import ctranslate2

            converter = ctranslate2.converters.TransformersConverter(
                model_id,
                copy_files=list(FAST_TOKENIZER_FILES),
            )
            converter.convert(
                str(temp_dir),
                quantization="int8",
                force=True,
            )
            # Do not rely solely on converter copy_files: explicitly ensure the
            # tokenizer assets exist before promoting the temporary model.
            _ensure_tokenizer_assets(model_id, temp_dir, progress=progress)
            if output_dir.exists():
                shutil.rmtree(output_dir)
            temp_dir.replace(output_dir)
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"Fast model setup failed: {exc}") from exc

    if not fast_model_ready(settings, source_lang, target_lang):
        raise RuntimeError(
            f"Fast model {source_lang}→{target_lang} is incomplete after setup"
        )

    result = {
        "ready": True,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": model_id,
        "path": str(output_dir),
    }
    if run_benchmark:
        if progress:
            progress(0, 0, "Benchmarking Fast Translation…")
        result["benchmark"] = benchmark_fast_translation(
            settings,
            source_lang,
            target_lang,
        )
    if progress:
        progress(1, 1, f"Fast Translation {source_lang}→{target_lang} ready")
    return result


def choose_threading(settings) -> tuple[int, int]:
    logical = max(1, int(os.cpu_count() or 1))
    profile = str(settings.performance.get("profile") or "economy").casefold()
    cfg = settings.translation

    configured_workers = int(cfg.get("fast_inter_threads", 0) or 0)
    configured_threads = int(cfg.get("fast_intra_threads", 0) or 0)
    if configured_workers > 0 and configured_threads > 0:
        return max(1, configured_workers), max(1, configured_threads)

    if profile == "balanced" and logical >= 6:
        inter_threads = 2
        intra_threads = max(1, logical // 2)
    else:
        inter_threads = 1
        intra_threads = max(1, logical // 2)
    while inter_threads * intra_threads > logical:
        intra_threads = max(1, intra_threads - 1)
    return inter_threads, intra_threads


def _load_sentencepiece_processor(spm_module, path: Path):
    """Load a SentencePiece model from bytes to avoid native Windows Unicode-path issues."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Cannot read tokenizer model: {path}: {exc}") from exc
    if not payload:
        raise RuntimeError(f"Tokenizer model is empty: {path}")

    processor = spm_module.SentencePieceProcessor()
    try:
        loaded = processor.LoadFromSerializedProto(payload)
    except Exception as exc:
        raise RuntimeError(f"Cannot load tokenizer model from memory: {path.name}: {exc}") from exc
    if loaded is False:
        raise RuntimeError(f"Cannot load tokenizer model from memory: {path.name}")
    return processor


def _source_token_windows(tokens: Sequence[str], max_input_tokens: int) -> list[list[str]]:
    # Models converted with TransformersConverter expect the same special tokens
    # returned by the Hugging Face tokenizer. MarianTokenizer appends </s> to
    # every source sequence; raw SentencePiece does not, so we add it here.
    content_limit = max(1, int(max_input_tokens) - 1)
    return [
        list(tokens[start:start + content_limit]) + [FAST_SOURCE_EOS_TOKEN]
        for start in range(0, len(tokens), content_limit)
    ]


def _semantic_units(text: str) -> list[str]:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    # PDF text extraction often flattens columns and form fields into very long
    # lines separated by large whitespace gaps. Treat those gaps as boundaries
    # before normalizing ordinary spaces.
    value = re.sub(r"[ \t]{4,}", "\n", value)
    value = re.sub(r"\s+(?=\d{1,3}[.)]\s+)", "\n", value)

    units: list[str] = []
    for block in re.split(r"\n+", value):
        block = re.sub(r"[ \t]+", " ", block).strip()
        if not block:
            continue
        parts = re.split(r"(?<=[.!?…;:])\s+(?=\S)", block)
        units.extend(part.strip() for part in parts if part.strip())
    return units


TECHNICAL_FILL_RE = re.compile(r"(?:_{2,}|[.·]{5,})")
URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
OUTPUT_URL_RE = re.compile(r"https?:/{1,2}[^\s<>()]+", re.IGNORECASE)


def _clean_translation_unit(text: str) -> str:
    value = TECHNICAL_FILL_RE.sub(" ", str(text or ""))
    value = re.sub(r"«\s*»", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def _is_structured_unit(raw_text: str, tokens: Sequence[str]) -> bool:
    value = str(raw_text or "")
    return (
        bool(TECHNICAL_FILL_RE.search(value))
        or "№" in value
        or bool(URL_RE.search(value))
        or bool(re.match(r"^\s*\d{1,3}[.)]\s+", value))
        or len(tokens) <= 36
    )


def _restore_source_urls(source: str, translated: str) -> str:
    source_urls = URL_RE.findall(str(source or ""))
    if not source_urls:
        return translated

    matches = list(OUTPUT_URL_RE.finditer(translated))
    if not matches:
        suffix = " ".join(source_urls)
        return f"{translated.rstrip()} {suffix}".strip()

    pieces: list[str] = []
    last = 0
    for index, match in enumerate(matches):
        pieces.append(translated[last:match.start()])
        replacement = source_urls[min(index, len(source_urls) - 1)]
        pieces.append(replacement)
        last = match.end()
    pieces.append(translated[last:])
    result = "".join(pieces)

    if len(matches) < len(source_urls):
        result = f"{result.rstrip()} {' '.join(source_urls[len(matches):])}".strip()
    return result


def _semantic_token_windows(
    text: str,
    source_sp,
    max_input_tokens: int,
    segment_tokens: int,
) -> list[list[str]]:
    content_limit = max(1, int(max_input_tokens) - 1)
    soft_limit = min(content_limit, max(32, int(segment_tokens)))
    windows: list[list[str]] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            windows.append(current + [FAST_SOURCE_EOS_TOKEN])
            current = []

    for raw_unit in _semantic_units(text):
        unit = _clean_translation_unit(raw_unit)
        if not unit:
            continue
        tokens = list(source_sp.encode(unit, out_type=str))
        if not tokens:
            continue
        structured = _is_structured_unit(raw_unit, tokens)
        if len(tokens) > content_limit:
            flush()
            windows.extend(_source_token_windows(tokens, max_input_tokens))
            continue
        if structured:
            flush()
            windows.append(tokens + [FAST_SOURCE_EOS_TOKEN])
            continue
        if current and len(current) + len(tokens) > soft_limit:
            flush()
        current.extend(tokens)
    flush()
    return windows


def _degeneracy_score(source: str, translated: str) -> int:
    source = str(source or "")
    translated = str(translated or "")
    if not translated.strip():
        return 10 if source.strip() else 0

    score = 0
    if len(translated) > max(240, int(len(source) * 2.4)):
        score += 2
    if re.search(r"(.)\1{5,}", translated, flags=re.IGNORECASE):
        score += 3

    words = re.findall(r"[^\W_]+", translated.casefold(), flags=re.UNICODE)
    run = 1
    max_run = 1
    for previous, current in zip(words, words[1:]):
        if current == previous:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 1
    if max_run >= 4:
        score += 4

    token_fragments = re.findall(r"(?<!\w)[^\s_]{1,16}_(?=\s|$)", translated)
    if len(token_fragments) >= 4:
        score += 4
    elif len(token_fragments) >= 2:
        score += 2
    return score


def _translation_quality_score(
    source: str,
    translated: str,
    *,
    target_lang: str = "ru",
) -> int:
    source = _clean_translation_unit(source)
    translated = str(translated or "").strip()
    score = _degeneracy_score(source, translated)
    if not source or not translated:
        return score

    source_visible = len(re.sub(r"\s+", "", source))
    translated_visible = len(re.sub(r"\s+", "", translated))
    if source_visible >= 30:
        ratio = translated_visible / max(1, source_visible)
        if ratio < 0.45 or ratio > 1.95:
            score += 2

    missing_literals = missing_protected_literals(source, translated)
    if missing_literals:
        score += 10 + min(10, len(missing_literals) * 2)

    source_numbers = set(re.findall(r"(?<!\w)\d+(?:[.,:/-]\d+)*(?!\w)", source))
    missing_numbers = [token for token in source_numbers if token not in translated]
    score += min(3, len(missing_numbers))

    source_codes = set(
        re.findall(r"\b(?:[A-Z]{2,}(?:-[A-Z0-9]+)*|[A-Z]\d+)\b", source)
    )
    missing_codes = [token for token in source_codes if token not in translated]
    score += min(2, len(missing_codes))

    mixed_script_words = re.findall(
        r"\b(?=[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]*[A-Za-z])"
        r"(?=[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]*[А-Яа-яЁёІіЇїЄєҐґ])"
        r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ]{4,}\b",
        translated,
    )
    if mixed_script_words:
        score += min(3, len(mixed_script_words))

    if target_lang == "ru":
        alpha = [char for char in translated if char.isalpha()]
        if len(alpha) >= 8:
            cyrillic = sum(
                ("А" <= char <= "я") or char in "ЁёІіЇїЄєҐґ"
                for char in alpha
            )
            if cyrillic / len(alpha) < 0.65:
                score += 4

        ukrainian_residue = re.findall(r"[ІіЇїЄєҐґ]", translated)
        if ukrainian_residue:
            score += 2 + min(2, len(ukrainian_residue))

    return score


def _decode_options(tokenized: Sequence[Sequence[str]], *, retry: bool = False) -> dict:
    longest_source = max((len(tokens) for tokens in tokenized), default=0)
    max_decoding_length = max(48, min(384, int(longest_source * 1.8) + 24))
    return {
        "beam_size": FAST_RETRY_BEAM_SIZE if retry else FAST_BEAM_SIZE,
        "repetition_penalty": (
            FAST_RETRY_REPETITION_PENALTY if retry else FAST_REPETITION_PENALTY
        ),
        "no_repeat_ngram_size": (
            FAST_RETRY_NO_REPEAT_NGRAM_SIZE if retry else FAST_NO_REPEAT_NGRAM_SIZE
        ),
        "max_decoding_length": max_decoding_length,
    }


class FastTranslator:
    def __init__(self, settings, source_lang: str, target_lang: str = "ru"):
        if not fast_model_ready(settings, source_lang, target_lang):
            raise RuntimeError(f"Fast model {source_lang}→{target_lang} is not prepared")
        import ctranslate2
        import sentencepiece as spm

        self.settings = settings
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model_id = FAST_MODELS[(source_lang, target_lang)]
        self.model_dir = fast_model_dir(settings, source_lang, target_lang)
        self.inter_threads, self.intra_threads = choose_threading(settings)
        self.compute_type = str(settings.translation.get("fast_compute_type") or "int8")
        configured_batch = int(settings.translation.get("fast_batch_tokens", 0) or 0)
        benchmark = load_fast_benchmark(settings, source_lang, target_lang)
        recommended_batch = int((benchmark or {}).get("recommended_batch_tokens") or 0)
        if configured_batch > 0:
            self.batch_tokens = max(256, configured_batch)
        elif recommended_batch > 0:
            self.batch_tokens = max(256, recommended_batch)
        else:
            profile = str(settings.performance.get("profile") or "economy").casefold()
            self.batch_tokens = 4096 if profile == "balanced" else 2048
        self.max_input_tokens = max(64, min(512, int(settings.translation.get("fast_max_input_tokens", 220))))
        self.segment_tokens = max(
            48,
            min(
                self.max_input_tokens - 1,
                int(settings.translation.get("fast_segment_tokens", 120) or 120),
            ),
        )
        self.translator = ctranslate2.Translator(
            str(self.model_dir),
            device="cpu",
            compute_type=self.compute_type,
            inter_threads=self.inter_threads,
            intra_threads=self.intra_threads,
        )
        self.source_sp = _load_sentencepiece_processor(
            spm,
            self.model_dir / "source.spm",
        )
        self.target_sp = _load_sentencepiece_processor(
            spm,
            self.model_dir / "target.spm",
        )
        self.quality_retries = 0
        self.quality_fallbacks = 0
        self.quality_warnings = 0
        self.literal_segment_fallbacks = 0
        self.quality_retry_score = max(
            1,
            int(settings.translation.get("quality_retry_score", 2) or 2),
        )
        self.quality_fallback_score = max(
            self.quality_retry_score,
            int(settings.translation.get("quality_fallback_score", 4) or 4),
        )

    def _translate_windows(self, tokenized: list[list[str]], *, retry: bool = False) -> list[str]:
        if not tokenized:
            return []
        results = self.translator.translate_batch(
            tokenized,
            max_batch_size=self.batch_tokens,
            batch_type="tokens",
            return_scores=False,
            max_input_length=self.max_input_tokens,
            **_decode_options(tokenized, retry=retry),
        )
        decoded: list[str] = []
        for result in results:
            pieces = result.hypotheses[0] if result.hypotheses else []
            decoded.append(self.target_sp.decode(pieces).strip())
        return decoded

    def _translate_raw_text(
        self,
        text: str,
        *,
        retry: bool = False,
        segment_tokens: int | None = None,
    ) -> str:
        windows = _semantic_token_windows(
            str(text),
            self.source_sp,
            self.max_input_tokens,
            segment_tokens if segment_tokens is not None else self.segment_tokens,
        )
        return " ".join(
            part for part in self._translate_windows(windows, retry=retry) if part
        ).strip()

    def translate_texts(
        self,
        texts: Sequence[str],
        *,
        fallback_translator: Callable[[str], str] | None = None,
    ) -> list[str]:
        tokenized: list[list[str]] = []
        ownership: list[int] = []
        protections = []

        for text_index, text_value in enumerate(texts):
            protection = protect_literals(str(text_value))
            protections.append(protection)
            windows = _semantic_token_windows(
                protection.masked_text,
                self.source_sp,
                self.max_input_tokens,
                self.segment_tokens,
            )
            for window in windows:
                tokenized.append(window)
                ownership.append(text_index)

        if not tokenized:
            return ["" for _ in texts]

        decoded = self._translate_windows(tokenized)
        grouped: list[list[str]] = [[] for _ in texts]
        for owner, translated_text in zip(ownership, decoded):
            if translated_text:
                grouped[owner].append(translated_text)

        translated: list[str] = []
        for source_value, protection, group in zip(texts, protections, grouped):
            source = str(source_value)
            raw_output = " ".join(part for part in group if part).strip()
            restored, intact = restore_literals(protection, raw_output)
            if not intact:
                restored, _ = translate_preserving_literals(
                    source,
                    lambda value: self._translate_raw_text(value),
                )
                self.literal_segment_fallbacks = (
                    getattr(self, "literal_segment_fallbacks", 0) + 1
                )
            translated.append(_restore_source_urls(source, restored))

        for index, (source_value, output) in enumerate(zip(texts, translated)):
            source = str(source_value)
            best_output = output
            best_score = _translation_quality_score(
                source,
                best_output,
                target_lang=self.target_lang,
            )

            if best_score >= self.quality_retry_score:
                self.quality_retries += 1
                retry_output, retry_intact = translate_preserving_literals(
                    source,
                    lambda value: self._translate_raw_text(
                        value,
                        retry=True,
                        segment_tokens=max(48, self.segment_tokens // 2),
                    ),
                )
                if not retry_intact:
                    self.literal_segment_fallbacks += 1
                retry_output = _restore_source_urls(source, retry_output)
                retry_score = _translation_quality_score(
                    source,
                    retry_output,
                    target_lang=self.target_lang,
                )
                if retry_output and retry_score < best_score:
                    best_output = retry_output
                    best_score = retry_score

            if (
                best_score >= self.quality_fallback_score
                and fallback_translator is not None
            ):
                try:
                    fallback_output = str(fallback_translator(source) or "").strip()
                except Exception:
                    fallback_output = ""
                fallback_output = _restore_source_urls(source, fallback_output)
                fallback_score = _translation_quality_score(
                    source,
                    fallback_output,
                    target_lang=self.target_lang,
                )
                if fallback_output and fallback_score < best_score:
                    best_output = fallback_output
                    best_score = fallback_score
                    self.quality_fallbacks += 1
                    record_selected = getattr(fallback_translator, "record_selected", None)
                    if callable(record_selected):
                        record_selected()

            if best_score >= self.quality_fallback_score:
                self.quality_warnings += 1
            translated[index] = best_output

        return translated


def translate_sections_fast(
    settings,
    sha256: str,
    sections: list[tuple[int | None, str]],
    source_lang: str,
    target_lang: str = "ru",
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
    fallback_translator: Callable[[str], str] | None = None,
) -> tuple[list[tuple[int | None, str]], FastTranslationStats]:
    engine = FastTranslator(settings, source_lang, target_lang)
    checkpoint = _load_checkpoint(settings, sha256, source_lang, target_lang, engine.model_id)
    translated_by_index = {
        int(item["index"]): (item.get("page"), str(item.get("text") or ""))
        for item in checkpoint.get("sections", [])
        if isinstance(item, dict) and "index" in item
    }

    total = len(sections)
    page_batch = max(
        1,
        min(32, int(settings.translation.get("fast_page_batch", 4) or 4)),
    )
    text_batch = max(
        1,
        min(256, int(settings.translation.get("fast_text_batch", 32) or 32)),
    )
    if progress:
        progress(len(translated_by_index), total, "Preparing Fast Translation…")

    started = time.perf_counter()
    session_chars = 0
    session_pages = 0
    pending_indices = [
        index for index in range(total)
        if index not in translated_by_index
    ]

    for window_indices in _batches(pending_indices, page_batch):
        _wait_for_interactive(
            should_pause,
            progress,
            len(translated_by_index),
            total,
        )

        page_parts: dict[int, list[str]] = {
            index: [] for index in window_indices
        }
        texts_to_translate: list[str] = []
        owners: list[int] = []

        # Flatten paragraphs from multiple pages so CTranslate2 receives a
        # useful batch even when each individual page contains little text.
        for index in window_indices:
            _page, text = sections[index]
            for paragraph in _paragraphs(text):
                texts_to_translate.append(paragraph)
                owners.append(index)

        for start_index in range(0, len(texts_to_translate), text_batch):
            _wait_for_interactive(
                should_pause,
                progress,
                len(translated_by_index),
                total,
            )
            batch_texts = texts_to_translate[start_index:start_index + text_batch]
            batch_owners = owners[start_index:start_index + text_batch]
            if fallback_translator is None:
                translated_batch = engine.translate_texts(batch_texts)
            else:
                translated_batch = engine.translate_texts(
                    batch_texts,
                    fallback_translator=fallback_translator,
                )
            if len(translated_batch) != len(batch_texts):
                raise RuntimeError(
                    "Fast Translation returned an unexpected number of results"
                )
            for owner, translated_text in zip(batch_owners, translated_batch):
                if translated_text.strip():
                    page_parts[owner].append(translated_text.strip())

        # Commit the completed page window together. This preserves page
        # provenance while avoiding an increasingly expensive full-checkpoint
        # rewrite after every single page.
        for index in window_indices:
            page, text = sections[index]
            translated_text = "\n\n".join(page_parts[index]).strip()
            translated_by_index[index] = (page, translated_text)
            session_chars += len(text)
            session_pages += 1

        _save_checkpoint(
            settings,
            sha256,
            source_lang,
            target_lang,
            engine.model_id,
            translated_by_index,
        )

        elapsed = max(0.001, time.perf_counter() - started)
        rate = session_pages * 60.0 / elapsed
        chars_per_second = session_chars / elapsed
        remaining = total - len(translated_by_index)
        eta = remaining / rate if rate > 0 else 0

        pages = [sections[index][0] for index in window_indices]
        visible_pages = [page for page in pages if page is not None]
        if not visible_pages:
            page_label = "document"
        elif len(visible_pages) == 1:
            page_label = f"page {visible_pages[0]}"
        else:
            page_label = f"pages {visible_pages[0]}–{visible_pages[-1]}"

        if progress:
            progress(
                len(translated_by_index),
                total,
                f"Fast Translation · {page_label} · {rate:.1f} pages/min"
                f" · {chars_per_second:.0f} chars/s"
                + (
                    f" · quality retry {getattr(engine, 'quality_retries', 0)}"
                    if getattr(engine, "quality_retries", 0)
                    else ""
                )
                + (
                    f" · fallback {getattr(engine, 'quality_fallbacks', 0)}"
                    if getattr(engine, "quality_fallbacks", 0)
                    else ""
                )
                + (f" · ETA {eta:.1f} min" if remaining else ""),
            )

    elapsed = max(0.001, time.perf_counter() - started)
    pages_per_minute = session_pages * 60.0 / elapsed if session_pages else 0.0
    chars_per_second = session_chars / elapsed if session_chars else 0.0
    translated = [
        translated_by_index[index]
        for index in range(total)
        if index in translated_by_index
    ]
    stats = FastTranslationStats(
        engine="ctranslate2-int8",
        model=engine.model_id,
        compute_type=engine.compute_type,
        inter_threads=engine.inter_threads,
        intra_threads=engine.intra_threads,
        pages_total=total,
        pages_translated=session_pages,
        elapsed_seconds=elapsed,
        chars_translated=session_chars,
        pages_per_minute=pages_per_minute,
        chars_per_second=chars_per_second,
        page_batch=page_batch,
        quality_retries=getattr(engine, "quality_retries", 0),
        quality_fallbacks=getattr(engine, "quality_fallbacks", 0),
        quality_warnings=getattr(engine, "quality_warnings", 0),
        literal_segment_fallbacks=getattr(engine, "literal_segment_fallbacks", 0),
    )
    return translated, stats

def clear_fast_checkpoint(settings, sha256: str, target_lang: str = "ru") -> None:
    path = _checkpoint_path(settings, sha256, target_lang)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def benchmark_fast_translation(settings, source_lang: str, target_lang: str = "ru") -> dict:
    engine = FastTranslator(settings, source_lang, target_lang)
    if source_lang == "uk":
        sample = (
            "Безпілотні системи використовуються для розвідки, спостереження та підтримки логістики. "
            "Підрозділи адаптують тактику відповідно до умов місцевості та радіоелектронної обстановки."
        )
    else:
        sample = (
            "Unmanned systems are used for reconnaissance, observation, and logistics support. "
            "Units adapt tactics to terrain conditions and the electronic warfare environment."
        )
    texts = [sample for _ in range(32)]
    engine.translate_texts(texts[:4])

    candidates = [1024, 2048, 4096]
    measurements: list[dict] = []
    best_batch = engine.batch_tokens
    best_chars_per_second = 0.0
    chars = sum(len(value) for value in texts)

    for batch_tokens in candidates:
        engine.batch_tokens = batch_tokens
        started = time.perf_counter()
        engine.translate_texts(texts)
        elapsed = max(0.001, time.perf_counter() - started)
        chars_per_second = chars / elapsed
        measurements.append({
            "batch_tokens": batch_tokens,
            "chars_per_second": round(chars_per_second, 1),
            "elapsed_seconds": round(elapsed, 3),
        })
        if chars_per_second > best_chars_per_second:
            best_chars_per_second = chars_per_second
            best_batch = batch_tokens

    assumed_chars_per_page = max(800, int(settings.translation.get("benchmark_chars_per_page", 1800)))
    pages_per_minute = best_chars_per_second * 60.0 / assumed_chars_per_page
    result = {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": engine.model_id,
        "compute_type": engine.compute_type,
        "inter_threads": engine.inter_threads,
        "intra_threads": engine.intra_threads,
        "recommended_batch_tokens": best_batch,
        "measurements": measurements,
        "chars_per_second": round(best_chars_per_second, 1),
        "estimated_pages_per_minute": round(pages_per_minute, 1),
        "estimated_100_pages_minutes": round(100.0 / pages_per_minute, 1) if pages_per_minute > 0 else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _benchmark_path(settings, source_lang, target_lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(path, result)
    return result

def load_fast_benchmark(settings, source_lang: str, target_lang: str = "ru") -> dict | None:
    path = _benchmark_path(settings, source_lang, target_lang)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _looks_like_layout_field(line: str) -> bool:
    value = str(line or "").strip()
    words = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    letters = [char for char in value if char.isalpha()]
    uppercase_ratio = (
        sum(char.isupper() for char in letters) / len(letters)
        if letters
        else 0.0
    )
    short_label = (
        len(value) <= 70
        and len(words) <= 3
        and not re.search(r"[.!?…,:;—-]\s*$", value)
    )
    heading = len(value) <= 160 and len(letters) >= 4 and uppercase_ratio >= 0.75
    return (
        bool(TECHNICAL_FILL_RE.search(value))
        or "№" in value
        or bool(URL_RE.search(value))
        or bool(re.match(r"^\d{1,3}[.)]\s+", value))
        or (":" in value[:80] and len(value) <= 180)
        or short_label
        or heading
    )


def _paragraphs(text: str) -> list[str]:
    blocks = [
        part.strip()
        for part in re.split(r"\n\s*\n", str(text))
        if part.strip()
    ]
    if not blocks:
        return []

    result: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) <= 1:
            result.append(block)
            continue

        current: list[str] = []

        def flush() -> None:
            nonlocal current
            if current:
                result.append(" ".join(current).strip())
                current = []

        for line in lines:
            if _looks_like_layout_field(line):
                flush()
                result.append(line)
                continue
            current.append(line)
            if re.search(r"[.!?…]\s*$", line):
                flush()
        flush()

    return result or ([str(text).strip()] if str(text).strip() else [])


def _batches(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _wait_for_interactive(
    should_pause: Callable[[], bool] | None,
    progress: Callable[[int, int, str], None] | None,
    current: int,
    total: int,
) -> None:
    if should_pause is None:
        return
    announced = False
    while should_pause():
        if progress and not announced:
            progress(current, total, "Translation paused while Chat/Ask is active")
            announced = True
        time.sleep(0.25)


def _checkpoint_path(settings, sha256: str, target_lang: str) -> Path:
    return settings.workspace_dir / "translation_progress" / f"{sha256}.{target_lang}.json"


def _benchmark_path(settings, source_lang: str, target_lang: str) -> Path:
    return (
        settings.workspace_dir
        / "models"
        / "translation"
        / f"benchmark-{source_lang}-{target_lang}.json"
    )


def _load_checkpoint(
    settings,
    sha256: str,
    source_lang: str,
    target_lang: str,
    model_id: str,
) -> dict:
    path = _checkpoint_path(settings, sha256, target_lang)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    expected = (
        sha256,
        source_lang,
        target_lang,
        model_id,
        FAST_TRANSLATION_PIPELINE_VERSION,
    )
    actual = (
        data.get("document_sha256"),
        data.get("source_lang"),
        data.get("target_lang"),
        data.get("model"),
        data.get("pipeline_version"),
    )
    return data if actual == expected else {}


def _save_checkpoint(
    settings,
    sha256: str,
    source_lang: str,
    target_lang: str,
    model_id: str,
    translated_by_index: dict[int, tuple[int | None, str]],
) -> None:
    path = _checkpoint_path(settings, sha256, target_lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "document_sha256": sha256,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "engine": "ctranslate2-int8",
        "model": model_id,
        "pipeline_version": FAST_TRANSLATION_PIPELINE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sections": [
            {"index": index, "page": page, "text": text}
            for index, (page, text) in sorted(translated_by_index.items())
        ],
    }
    _atomic_json(path, data)


def _atomic_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
