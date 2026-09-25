from __future__ import annotations

import importlib.util
import json
import shutil
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Sequence

from .translation_literals import missing_protected_literals, translate_preserving_literals

QUALITY_MODEL_ID = "facebook/m2m100_418M"
QUALITY_MODEL_FILES = ("model.bin", "config.json")
QUALITY_TOKENIZER_FILES = (
    "sentencepiece.bpe.model",
    "vocab.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
)
QUALITY_BEAM_SIZE = 5

QUALITY_BENCHMARK_CASES = (
    (
        "МІНІСТЕРСТВО ОСВІТИ І НАУКИ УКРАЇНИ",
        "МИНИСТЕРСТВО ОБРАЗОВАНИЯ И НАУКИ УКРАИНЫ",
    ),
    (
        "ОПИС ОСВІТНЬОЇ ПРОГРАМИ",
        "ОПИСАНИЕ ОБРАЗОВАТЕЛЬНОЙ ПРОГРАММЫ",
    ),
    (
        "Освітня програма вводиться в дію з 01.09.2026 р.",
        "Образовательная программа вводится в действие с 01.09.2026 г.",
    ),
    ("ПЕРЕДМОВА", "ПРЕДИСЛОВИЕ"),
    ("ЛИСТ ПОГОДЖЕННЯ", "ЛИСТ СОГЛАСОВАНИЯ"),
    (
        "Обсяг освітньої програми 240 кредитів ЄКТС. Спеціальність J3 Туризм та рекреація.",
        "Объем образовательной программы 240 кредитов ЕКТС. Специальность J3 Туризм и рекреация.",
    ),
)


def quality_translation_available() -> bool:
    return all(
        importlib.util.find_spec(name) is not None
        for name in (
            "ctranslate2",
            "sentencepiece",
            "transformers",
            "huggingface_hub",
            "torch",
            "accelerate",
        )
    )


def quality_model_dir(settings) -> Path:
    return settings.workspace_dir / "models" / "translation" / "quality-m2m100-418m-int8"


def quality_benchmark_path(settings) -> Path:
    return (
        settings.workspace_dir
        / "models"
        / "translation"
        / "benchmark-quality-uk-ru.json"
    )


def _usable_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def quality_model_ready(settings) -> bool:
    path = quality_model_dir(settings)
    return all(_usable_file(path / name) for name in QUALITY_MODEL_FILES) and _usable_file(
        path / "sentencepiece.bpe.model"
    )


def _download_asset(filename: str) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=QUALITY_MODEL_ID, filename=filename))


def _ensure_tokenizer_assets(
    output_dir: Path,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    missing = [name for name in QUALITY_TOKENIZER_FILES if not _usable_file(output_dir / name)]
    for index, filename in enumerate(missing, 1):
        if progress:
            progress(index - 1, len(missing), f"Restoring Quality tokenizer asset {filename}…")
        cached = _download_asset(filename)
        if not _usable_file(cached):
            raise RuntimeError(f"Downloaded Quality tokenizer asset is empty: {filename}")
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


def prepare_quality_model(
    settings,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    run_benchmark: bool = True,
) -> dict:
    if not quality_translation_available():
        raise RuntimeError(
            "Quality Translation dependencies are missing. Run UPDATE_OSINT.cmd."
        )

    output_dir = quality_model_dir(settings)
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    if not quality_model_ready(settings):
        if all(_usable_file(output_dir / name) for name in QUALITY_MODEL_FILES):
            if progress:
                progress(0, 0, "Repairing Quality Translation tokenizer files…")
            _ensure_tokenizer_assets(output_dir, progress=progress)
        else:
            temp_dir = output_dir.with_name(output_dir.name + ".tmp")
            shutil.rmtree(temp_dir, ignore_errors=True)
            if progress:
                progress(
                    0,
                    0,
                    "Downloading and converting M2M100 418M Quality model to INT8…",
                )
            try:
                import ctranslate2

                converter = ctranslate2.converters.TransformersConverter(
                    QUALITY_MODEL_ID,
                    copy_files=list(QUALITY_TOKENIZER_FILES),
                    low_cpu_mem_usage=True,
                )
                converter.convert(
                    str(temp_dir),
                    quantization=str(
                        settings.translation.get("quality_compute_type") or "int8"
                    ),
                    force=True,
                )
                _ensure_tokenizer_assets(temp_dir, progress=progress)
                if output_dir.exists():
                    shutil.rmtree(output_dir)
                temp_dir.replace(output_dir)
            except Exception as exc:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise RuntimeError(f"Quality model setup failed: {exc}") from exc

    if not quality_model_ready(settings):
        raise RuntimeError("Quality model is incomplete after setup")

    result = {
        "ready": True,
        "model": QUALITY_MODEL_ID,
        "path": str(output_dir),
        "compute_type": str(settings.translation.get("quality_compute_type") or "int8"),
    }
    if run_benchmark:
        if progress:
            progress(0, 0, "Benchmarking OPUS vs Quality Translation…")
        result["benchmark"] = benchmark_quality_translation(settings)
    if progress:
        progress(1, 1, "Quality Translation ready")
    return result


def _load_sentencepiece(path: Path):
    import sentencepiece as spm

    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Cannot read Quality tokenizer: {path}: {exc}") from exc
    processor = spm.SentencePieceProcessor()
    try:
        loaded = processor.LoadFromSerializedProto(payload)
    except Exception as exc:
        raise RuntimeError(f"Cannot load Quality tokenizer: {exc}") from exc
    if loaded is False:
        raise RuntimeError("Cannot load Quality tokenizer")
    return processor


class QualityTranslator:
    def __init__(self, settings, source_lang: str, target_lang: str = "ru"):
        if source_lang not in {"en", "uk"} or target_lang != "ru":
            raise RuntimeError("Quality Translation supports en/uk → ru")
        if not quality_model_ready(settings):
            raise RuntimeError("Quality Translation model is not prepared")

        import ctranslate2
        from .fast_translation import choose_threading

        self.settings = settings
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model_id = QUALITY_MODEL_ID
        self.model_dir = quality_model_dir(settings)
        self.compute_type = str(settings.translation.get("quality_compute_type") or "int8")
        self.inter_threads, self.intra_threads = choose_threading(settings)
        self.max_input_tokens = max(
            96,
            min(900, int(settings.translation.get("quality_max_input_tokens", 480) or 480)),
        )
        self.segment_tokens = max(
            64,
            min(
                self.max_input_tokens - 1,
                int(settings.translation.get("quality_segment_tokens", 240) or 240),
            ),
        )
        self.batch_tokens = max(
            256,
            int(settings.translation.get("quality_batch_tokens", 1024) or 1024),
        )
        self.literal_segment_fallbacks = 0
        self.translator = ctranslate2.Translator(
            str(self.model_dir),
            device="cpu",
            compute_type=self.compute_type,
            inter_threads=self.inter_threads,
            intra_threads=self.intra_threads,
        )
        self.sp = _load_sentencepiece(self.model_dir / "sentencepiece.bpe.model")

    def _plain_windows(self, text: str) -> list[list[str]]:
        from .fast_translation import _clean_translation_unit, _semantic_units

        source_prefix = f"__{self.source_lang}__"
        # Transformers-converted M2M100 expects the same special-token shape
        # as M2M100Tokenizer: [src_lang] X [eos]. Neither token is implicitly
        # added by CTranslate2 for Transformers models.
        content_limit = max(1, self.max_input_tokens - 2)
        sentence_limit = min(content_limit, self.segment_tokens)
        windows: list[list[str]] = []

        # M2M100 is used here as the quality tier, so keep semantic units
        # sentence/form-line sized instead of packing several sentences into
        # one large request. Only an individually long unit is token-split.
        for raw_unit in _semantic_units(text):
            unit = _clean_translation_unit(raw_unit)
            if not unit:
                continue
            tokens = list(self.sp.encode(unit, out_type=str))
            if not tokens:
                continue
            for start in range(0, len(tokens), sentence_limit):
                window = tokens[start:start + sentence_limit]
                if window:
                    windows.append([source_prefix] + window + ["</s>"])
        return windows

    def _translate_raw(self, text: str) -> str:
        windows = self._plain_windows(text)
        if not windows:
            return ""

        target_token = f"__{self.target_lang}__"
        longest = max(len(window) for window in windows)
        max_decoding_length = max(64, min(640, int(longest * 1.9) + 32))
        results = self.translator.translate_batch(
            windows,
            target_prefix=[[target_token] for _ in windows],
            max_batch_size=self.batch_tokens,
            batch_type="tokens",
            beam_size=QUALITY_BEAM_SIZE,
            repetition_penalty=1.0,
            no_repeat_ngram_size=0,
            max_input_length=self.max_input_tokens,
            max_decoding_length=max_decoding_length,
        )

        decoded: list[str] = []
        for result in results:
            pieces = list(result.hypotheses[0] if result.hypotheses else [])
            if pieces and pieces[0] == target_token:
                pieces = pieces[1:]
            value = self.sp.decode(pieces).strip()
            if value:
                decoded.append(value)
        return " ".join(decoded).strip()

    def translate_text(self, text: str) -> str:
        translated, placeholders_intact = translate_preserving_literals(
            str(text),
            self._translate_raw,
        )
        if not placeholders_intact:
            self.literal_segment_fallbacks += 1
        return translated.strip()

    def translate_texts(self, texts: Sequence[str]) -> list[str]:
        return [self.translate_text(str(text)) for text in texts]


def _reference_similarity(expected: str, actual: str) -> float:
    return round(
        SequenceMatcher(
            None,
            " ".join(str(expected).casefold().split()),
            " ".join(str(actual).casefold().split()),
        ).ratio(),
        4,
    )


def _engine_benchmark(name: str, translator, sources: list[str], references: list[str]) -> dict:
    from .fast_translation import _translation_quality_score

    started = time.perf_counter()
    outputs = translator.translate_texts(sources)
    elapsed = max(0.001, time.perf_counter() - started)
    chars = sum(len(value) for value in sources)
    rows = []
    for source, expected, output in zip(sources, references, outputs):
        rows.append(
            {
                "source": source,
                "expected": expected,
                "output": output,
                "quality_score": _translation_quality_score(source, output, target_lang="ru"),
                "reference_similarity": _reference_similarity(expected, output),
                "missing_literals": list(missing_protected_literals(source, output)),
            }
        )
    return {
        "engine": name,
        "elapsed_seconds": round(elapsed, 3),
        "chars_per_second": round(chars / elapsed, 1),
        "mean_quality_score": round(
            sum(row["quality_score"] for row in rows) / max(1, len(rows)),
            3,
        ),
        "mean_reference_similarity": round(
            sum(row["reference_similarity"] for row in rows) / max(1, len(rows)),
            4,
        ),
        "cases": rows,
    }


def benchmark_quality_translation(settings) -> dict:
    from .fast_translation import FastTranslator, fast_model_ready

    sources = [source for source, _ in QUALITY_BENCHMARK_CASES]
    references = [expected for _, expected in QUALITY_BENCHMARK_CASES]
    quality = QualityTranslator(settings, "uk", "ru")
    result = {
        "source_lang": "uk",
        "target_lang": "ru",
        "quality_model": QUALITY_MODEL_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "quality": _engine_benchmark("m2m100-418m-int8", quality, sources, references),
    }
    if fast_model_ready(settings, "uk", "ru"):
        fast = FastTranslator(settings, "uk", "ru")
        result["fast"] = _engine_benchmark(
            "opus-ct2-int8",
            fast,
            sources,
            references,
        )

    path = quality_benchmark_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return result


def load_quality_benchmark(settings) -> dict | None:
    path = quality_benchmark_path(settings)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None
