from __future__ import annotations

import importlib.util
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .fast_translation import (
    clear_fast_checkpoint,
    fast_model_ready,
    fast_ready_pairs,
    fast_translation_available,
    load_fast_benchmark,
    prepare_fast_model,
    translate_sections_fast,
    _paragraphs,
    _translation_quality_score,
)
from .translation_literals import translate_preserving_literals
from .quality_translation import (
    QUALITY_MODEL_ID,
    QualityTranslator,
    load_quality_benchmark,
    quality_model_ready,
    quality_translation_available,
)

PAGE_RE = re.compile(r"(?:^|\n)\s*--- PAGE (\d+) ---\s*\n", re.MULTILINE)
SUPPORTED_LANGS = {"en": "English", "ru": "Russian", "uk": "Ukrainian"}
ALLOWED_PAIRS = {("en", "ru"), ("uk", "ru")}


def argos_available() -> bool:
    return importlib.util.find_spec("argostranslate") is not None


def installed_pairs() -> set[tuple[str, str]]:
    if not argos_available():
        return set()
    from argostranslate import translate as argos_translate

    languages = {lang.code: lang for lang in argos_translate.get_installed_languages()}
    pairs: set[tuple[str, str]] = set()
    for src_code, src in languages.items():
        for dst_code, dst in languages.items():
            if src_code == dst_code:
                continue
            try:
                src.get_translation(dst)
            except Exception:
                continue
            pairs.add((src_code, dst_code))
    return pairs


def detect_language(text: str) -> str:
    sample = text[:12000].casefold()
    if re.search(r"[іїєґ]", sample):
        return "uk"
    cyrillic = len(re.findall(r"[а-яёіїєґ]", sample))
    latin = len(re.findall(r"[a-z]", sample))
    return "ru" if cyrillic > latin else "en"


class _QualityFallbackRouter:
    """Lazily compare prepared local Quality and Argos candidates."""

    def __init__(
        self,
        settings,
        source_lang: str,
        target_lang: str,
        *,
        progress: Callable[[int, int, str], None] | None = None,
        allow_model_install: bool = False,
    ) -> None:
        self.settings = settings
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.progress = progress
        self.allow_model_install = allow_model_install
        self._quality = None
        self._argos = None
        self._argos_failed = False
        self.last_engine = ""
        self.quality_candidate_calls = 0
        self.argos_candidate_calls = 0
        self.quality_selected = 0
        self.argos_selected = 0

        self.quality_ready = (
            bool(settings.translation.get("quality_engine_enabled", True))
            and quality_translation_available()
            and quality_model_ready(settings)
        )
        self.argos_ready = False
        if (
            bool(settings.translation.get("quality_fallback_enabled", True))
            and argos_available()
        ):
            pair_ready = (source_lang, target_lang) in installed_pairs()
            auto_install = bool(
                settings.translation.get("quality_fallback_auto_install", False)
            )
            self.argos_ready = pair_ready or (auto_install and allow_model_install)

    @property
    def available(self) -> bool:
        return self.quality_ready or self.argos_ready

    def __call__(self, value: str) -> str:
        candidates: list[tuple[int, str, str]] = []

        if self.quality_ready:
            try:
                if self._quality is None:
                    if self.progress:
                        self.progress(0, 0, "Loading Quality Translation · M2M100 418M…")
                    self._quality = QualityTranslator(
                        self.settings,
                        self.source_lang,
                        self.target_lang,
                    )
                output = self._quality.translate_text(value)
                self.quality_candidate_calls += 1
                if output:
                    candidates.append(
                        (
                            _translation_quality_score(
                                value,
                                output,
                                target_lang=self.target_lang,
                            ),
                            "m2m100-418m-int8",
                            output,
                        )
                    )
            except Exception:
                self.quality_ready = False

        if self.argos_ready and not self._argos_failed:
            try:
                if self._argos is None:
                    self._argos = _get_argos_translator(
                        self.source_lang,
                        self.target_lang,
                        self.settings,
                        allow_model_install=(
                            bool(
                                self.settings.translation.get(
                                    "quality_fallback_auto_install",
                                    False,
                                )
                            )
                            and self.allow_model_install
                        ),
                        progress=self.progress,
                    )
                output, _ = translate_preserving_literals(
                    value,
                    lambda fragment: self._argos(
                        fragment,
                        self.source_lang,
                        self.target_lang,
                    ),
                )
                self.argos_candidate_calls += 1
                if output:
                    candidates.append(
                        (
                            _translation_quality_score(
                                value,
                                output,
                                target_lang=self.target_lang,
                            ),
                            "argos-translate",
                            output,
                        )
                    )
            except Exception:
                self._argos_failed = True

        if not candidates:
            self.last_engine = ""
            return ""

        candidates.sort(key=lambda item: (item[0], 0 if item[1].startswith("m2m100") else 1))
        _score, self.last_engine, output = candidates[0]
        return output

    def record_selected(self) -> None:
        if self.last_engine.startswith("m2m100"):
            self.quality_selected += 1
        elif self.last_engine == "argos-translate":
            self.argos_selected += 1

    def metadata(self) -> dict:
        return {
            "quality_model": QUALITY_MODEL_ID if self.quality_ready or self.quality_candidate_calls else "",
            "quality_candidate_calls": self.quality_candidate_calls,
            "quality_selected": self.quality_selected,
            "argos_candidate_calls": self.argos_candidate_calls,
            "argos_selected": self.argos_selected,
            "selected_engines": {
                "m2m100-418m-int8": self.quality_selected,
                "argos-translate": self.argos_selected,
            },
            "quality_literal_segment_fallbacks": (
                int(getattr(self._quality, "literal_segment_fallbacks", 0))
                if self._quality is not None
                else 0
            ),
        }


def translate_document(
    settings,
    db,
    sha256: str,
    *,
    source_lang: str = "auto",
    target_lang: str = "ru",
    translator: Callable[[str, str, str], str] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    allow_model_install: bool = True,
    should_pause: Callable[[], bool] | None = None,
    engine: str | None = None,
) -> dict:
    doc = db.get_document(sha256)
    if not doc:
        raise RuntimeError("Document not found")
    text_path = settings.text_dir / f"{sha256}.txt"
    if not text_path.is_file():
        raise RuntimeError("Extracted text is missing. Run Scan first.")

    text = text_path.read_text(encoding="utf-8", errors="replace")
    src = detect_language(text) if source_lang == "auto" else source_lang
    dst = target_lang
    if src not in SUPPORTED_LANGS or dst not in SUPPORTED_LANGS:
        raise RuntimeError("Supported translation languages are en, ru and uk")
    if src == "ru":
        raise RuntimeError("Document already appears to be Russian")
    if (src, dst) not in ALLOWED_PAIRS:
        raise RuntimeError("Translation is limited to English→Russian and Ukrainian→Russian")

    sections = _sections(text)
    if not sections:
        sections = [(None, text)]

    selected_engine = str(engine or settings.translation.get("engine") or "auto").strip().casefold()
    if selected_engine not in {"auto", "fast", "quality", "argos"}:
        selected_engine = "auto"

    custom_translator = translator is not None
    engine_name = "custom"
    engine_meta: dict = {}
    used_fast_translation = False

    if custom_translator:
        translated = _translate_sections_legacy(
            sections,
            src,
            dst,
            translator,
            int(settings.translation.get("max_chars_per_request", 1800)),
            progress=progress,
            should_pause=should_pause,
        )
    else:
        translated = None

        wants_fast = selected_engine in {"auto", "fast"}
        if wants_fast and fast_translation_available():
            if not fast_model_ready(settings, src, dst) and allow_model_install:
                prepare_fast_model(
                    settings,
                    src,
                    dst,
                    progress=progress,
                    run_benchmark=True,
                )
            if fast_model_ready(settings, src, dst):
                if progress:
                    progress(0, len(sections), f"Using Fast Translation · CTranslate2 INT8 · {src}→{dst}")

                fallback_router = None
                quality_fallback = None
                if selected_engine == "auto":
                    fallback_router = _QualityFallbackRouter(
                        settings,
                        src,
                        dst,
                        progress=progress,
                        allow_model_install=allow_model_install,
                    )
                    if fallback_router.available:
                        quality_fallback = fallback_router

                used_fast_translation = True
                translated, fast_stats = translate_sections_fast(
                    settings,
                    sha256,
                    sections,
                    src,
                    dst,
                    progress=progress,
                    should_pause=should_pause,
                    fallback_translator=quality_fallback,
                )
                engine_name = fast_stats.engine
                engine_meta = {
                    "model": fast_stats.model,
                    "compute_type": fast_stats.compute_type,
                    "inter_threads": fast_stats.inter_threads,
                    "intra_threads": fast_stats.intra_threads,
                    "pages_per_minute": round(fast_stats.pages_per_minute, 2),
                    "elapsed_seconds": round(fast_stats.elapsed_seconds, 3),
                    "chars_translated": fast_stats.chars_translated,
                    "chars_per_second": round(fast_stats.chars_per_second, 2),
                    "page_batch": fast_stats.page_batch,
                    "quality_retries": fast_stats.quality_retries,
                    "quality_fallbacks": fast_stats.quality_fallbacks,
                    "quality_warnings": fast_stats.quality_warnings,
                    "literal_segment_fallbacks": fast_stats.literal_segment_fallbacks,
                }
                if fallback_router is not None:
                    router_meta = fallback_router.metadata()
                    engine_meta.update(router_meta)
                    if int(router_meta.get("quality_selected") or 0) > 0:
                        engine_name = "hybrid-ct2-quality"
                    elif int(router_meta.get("argos_selected") or 0) > 0:
                        engine_name = "hybrid-ct2-argos"
            elif selected_engine == "fast":
                raise RuntimeError(
                    f"Fast model {src}→{dst} is not prepared. Prepare it in System first."
                )
        elif selected_engine == "fast":
            raise RuntimeError(
                "Fast Translation dependencies are missing. Run the updater or install: "
                "pip install -e '.[fasttranslate]'"
            )

        if translated is None and selected_engine in {"auto", "quality"}:
            quality_ready = (
                quality_translation_available()
                and quality_model_ready(settings)
            )
            if quality_ready:
                if progress:
                    progress(0, len(sections), f"Using Quality Translation · M2M100 418M INT8 · {src}→{dst}")
                quality_engine = QualityTranslator(settings, src, dst)
                translated = _translate_sections_quality(
                    sections,
                    quality_engine,
                    progress=progress,
                    should_pause=should_pause,
                )
                engine_name = "m2m100-418m-int8"
                engine_meta = {
                    "model": QUALITY_MODEL_ID,
                    "compute_type": quality_engine.compute_type,
                    "literal_segment_fallbacks": quality_engine.literal_segment_fallbacks,
                }
            elif selected_engine == "quality":
                raise RuntimeError(
                    "Quality Translation model is not prepared. Prepare M2M100 in System first."
                )

        if translated is None:
            if progress:
                progress(0, len(sections), f"Using Argos fallback · {src}→{dst}")
            argos_translator = _get_argos_translator(
                src,
                dst,
                settings,
                allow_model_install=allow_model_install,
                progress=progress,
            )
            translated = _translate_sections_legacy(
                sections,
                src,
                dst,
                argos_translator,
                int(settings.translation.get("max_chars_per_request", 1800)),
                progress=progress,
                should_pause=should_pause,
            )
            engine_name = "argos-translate"

    output_dir = settings.translations_dir / dst
    output_dir.mkdir(parents=True, exist_ok=True)
    source_name = Path(doc["source_path"]).stem
    output_path = output_dir / f"{source_name}.{sha256[:10]}.{dst}.md"
    created_at = datetime.now(timezone.utc).isoformat()
    body = _render_markdown(doc["source_path"], sha256, src, dst, created_at, translated)
    _atomic_write(output_path, body)

    metadata = {
        "document_sha256": sha256,
        "source_path": doc["source_path"],
        "source_lang": src,
        "target_lang": dst,
        "created_at": created_at,
        "engine": engine_name,
        "output_path": str(output_path),
        **engine_meta,
    }
    meta_path = output_path.with_suffix(output_path.suffix + ".json")
    _atomic_write(meta_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    db.save_translation(
        sha256=sha256,
        source_lang=src,
        target_lang=dst,
        output_path=str(output_path),
        created_at=created_at,
        engine=engine_name,
    )
    if used_fast_translation:
        clear_fast_checkpoint(settings, sha256, dst)
    return metadata


def _get_argos_translator(
    src: str,
    dst: str,
    settings,
    *,
    allow_model_install: bool,
    progress: Callable[[int, int, str], None] | None,
) -> Callable[[str, str, str], str]:
    if not argos_available():
        raise RuntimeError(
            "Offline translation is not installed. Run the updater or install: pip install -e '.[translate]'"
        )
    if (src, dst) not in installed_pairs():
        if not allow_model_install or not bool(settings.translation.get("auto_install_models", True)):
            raise RuntimeError(f"Argos language pair {src}→{dst} is not installed")
        if progress:
            progress(0, 0, f"Installing Argos language model {src}→{dst}…")
        from argostranslate import package as argos_package

        argos_package.update_package_index()
        available = argos_package.get_available_packages()
        direct = next((p for p in available if p.from_code == src and p.to_code == dst), None)
        if direct is not None:
            argos_package.install_from_path(direct.download())
        elif src != "en" and dst != "en":
            route = []
            for a, b in ((src, "en"), ("en", dst)):
                package = next((p for p in available if p.from_code == a and p.to_code == b), None)
                if package is None:
                    raise RuntimeError(f"No Argos package route is available for {src}→{dst}")
                route.append(package)
            for package in route:
                argos_package.install_from_path(package.download())
        else:
            raise RuntimeError(f"No Argos language model is available for {src}→{dst}")

    from argostranslate import translate as argos_translate

    return lambda value, a, b: argos_translate.translate(value, a, b)


def _translate_sections_quality(
    sections: list[tuple[int | None, str]],
    engine: QualityTranslator,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> list[tuple[int | None, str]]:
    """Translate page-aware structural units without arbitrary character cuts."""
    translated: list[tuple[int | None, str]] = []
    total = len(sections)
    if progress:
        progress(0, total, "Preparing Quality Translation…")

    for index, (page, text) in enumerate(sections, 1):
        _wait_while_paused(should_pause, progress, index - 1, total)
        units = _paragraphs(text)
        outputs = engine.translate_texts(units) if units else []
        translated_text = "\n\n".join(
            output.strip() for output in outputs if output.strip()
        ).strip()
        translated.append((page, translated_text))
        if progress:
            label = f"Page {page}" if page is not None else "Document"
            progress(index, total, f"Quality Translation · {label}")
    return translated


def _translate_sections_legacy(
    sections: list[tuple[int | None, str]],
    src: str,
    dst: str,
    translator: Callable[[str, str, str], str],
    max_chars: int,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> list[tuple[int | None, str]]:
    units: list[tuple[int | None, str]] = []
    for page, section_text in sections:
        for piece in _split_text(section_text, max_chars):
            units.append((page, piece))
    if not units:
        units = sections

    translated: list[tuple[int | None, str]] = []
    total = len(units)
    if progress:
        progress(0, total, "Preparing translation…")
    for index, (page, piece) in enumerate(units, 1):
        _wait_while_paused(should_pause, progress, index - 1, total)
        translated.append((page, translator(piece, src, dst)))
        if progress:
            label = f"Page {page}" if page is not None else "Document"
            progress(index, total, f"Translating {label}")
    return translated


def _wait_while_paused(
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


def _sections(text: str) -> list[tuple[int | None, str]]:
    matches = list(PAGE_RE.finditer(text))
    if not matches:
        return [(None, text.strip())] if text.strip() else []
    sections: list[tuple[int | None, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip()
        if value:
            sections.append((int(match.group(1)), value))
    return sections


def _split_text(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    max_chars = max(300, max_chars)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    result: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = [
            paragraph[i:i + max_chars]
            for i in range(0, len(paragraph), max_chars)
        ] if len(paragraph) > max_chars else [paragraph]
        for piece in pieces:
            candidate = piece if not current else current + "\n\n" + piece
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    result.append(current)
                current = piece
    if current:
        result.append(current)
    return result


def _render_markdown(
    source_path: str,
    sha256: str,
    src: str,
    dst: str,
    created_at: str,
    units: list[tuple[int | None, str]],
) -> str:
    lines = [
        f"# Translation — {Path(source_path).name}",
        "",
        f"- Source: `{source_path}`",
        f"- SHA-256: `{sha256}`",
        f"- Language: `{src}` → `{dst}`",
        f"- Generated: `{created_at}`",
        "",
    ]
    last_page = object()
    for page, translated_text in units:
        if page != last_page and page is not None:
            lines.extend([f"## Page {page}", ""])
        lines.extend([translated_text.strip(), ""])
        last_page = page
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def translation_queue_status(settings, db, *, available_pairs=None, limit: int = 500) -> dict:
    """Return lightweight EN/UK → RU translation queue statistics."""
    argos_pairs = set(available_pairs) if available_pairs is not None else (
        installed_pairs() if argos_available() else set()
    )
    fast_pairs = fast_ready_pairs(settings) if fast_translation_available() else set()
    quality_pairs = (
        {("en", "ru"), ("uk", "ru")}
        if quality_translation_available() and quality_model_ready(settings)
        else set()
    )
    ready_pairs = argos_pairs | fast_pairs | quality_pairs

    eligible = 0
    translated = 0
    ready = 0
    blocked = 0
    russian = 0
    unknown = 0
    scanned = 0

    for doc in db.list_documents(limit=max(1, min(5000, int(limit)))):
        scanned += 1
        sha256 = doc["sha256"]
        src = str(doc["language"] or "").strip().casefold()
        if not src:
            text_path = settings.text_dir / f"{sha256}.txt"
            if not text_path.is_file():
                unknown += 1
                continue
            src = detect_language(text_path.read_text(encoding="utf-8", errors="replace"))

        if src == "ru":
            russian += 1
            continue
        if src not in {"en", "uk"}:
            unknown += 1
            continue

        eligible += 1
        if db.get_translation(sha256, src, "ru"):
            translated += 1
        elif (src, "ru") in ready_pairs:
            ready += 1
        else:
            blocked += 1

    benchmarks = {
        src: load_fast_benchmark(settings, src, "ru")
        for src in ("en", "uk")
        if fast_model_ready(settings, src, "ru")
    }
    return {
        "scanned": scanned,
        "eligible": eligible,
        "translated": translated,
        "pending": ready + blocked,
        "ready": ready,
        "blocked": blocked,
        "russian": russian,
        "unknown": unknown,
        "pairs": sorted(f"{src}->{dst}" for src, dst in ready_pairs if dst == "ru"),
        "engine": str(settings.translation.get("engine") or "auto"),
        "fast_available": fast_translation_available(),
        "fast_pairs": sorted(f"{src}->{dst}" for src, dst in fast_pairs),
        "fast_benchmarks": benchmarks,
        "quality_available": quality_translation_available(),
        "quality_ready": quality_model_ready(settings),
        "quality_benchmark": load_quality_benchmark(settings),
    }


def next_passive_translation(
    settings,
    db,
    *,
    progress=None,
    translator=None,
    available_pairs=None,
    should_pause: Callable[[], bool] | None = None,
) -> dict | None:
    """Translate at most one EN/UK document without downloading models in the background."""
    argos_pairs = set(available_pairs) if available_pairs is not None else (
        installed_pairs() if argos_available() else set()
    )
    fast_pairs = fast_ready_pairs(settings) if fast_translation_available() else set()
    quality_pairs = (
        {("en", "ru"), ("uk", "ru")}
        if quality_translation_available() and quality_model_ready(settings)
        else set()
    )
    selected_engine = str(settings.translation.get("engine") or "auto").strip().casefold()

    for doc in db.list_documents(limit=5000):
        sha256 = doc["sha256"]
        src = str(doc["language"] or "").strip().casefold()
        text_path = settings.text_dir / f"{sha256}.txt"
        if not src:
            if not text_path.is_file():
                continue
            src = detect_language(text_path.read_text(encoding="utf-8", errors="replace"))
        if src not in {"en", "uk"}:
            continue
        if db.get_translation(sha256, src, "ru"):
            continue

        pair = (src, "ru")
        if translator is None:
            if selected_engine == "fast" and pair not in fast_pairs:
                continue
            if selected_engine == "quality" and pair not in quality_pairs:
                continue
            if selected_engine == "argos" and pair not in argos_pairs:
                continue
            if (
                selected_engine == "auto"
                and pair not in fast_pairs
                and pair not in quality_pairs
                and pair not in argos_pairs
            ):
                continue

        return translate_document(
            settings,
            db,
            sha256,
            source_lang=src,
            target_lang="ru",
            translator=translator,
            progress=progress,
            allow_model_install=False,
            should_pause=should_pause,
            engine=selected_engine,
        )
    return None
