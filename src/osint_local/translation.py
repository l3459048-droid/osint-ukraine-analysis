from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

PAGE_RE = re.compile(r"(?:^|\n)\s*--- PAGE (\d+) ---\s*\n", re.MULTILINE)
SUPPORTED_LANGS = {"en": "English", "ru": "Russian", "uk": "Ukrainian"}


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


def translate_document(
    settings,
    db,
    sha256: str,
    *,
    source_lang: str = "auto",
    target_lang: str = "en",
    translator: Callable[[str, str, str], str] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
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
    if src == dst:
        raise RuntimeError("Source and target languages are the same")

    custom_translator = translator is not None
    if translator is None:
        if not argos_available():
            raise RuntimeError("Offline translation is not installed. Install: pip install -e '.[translate]'")
        if (src, dst) not in installed_pairs():
            if not bool(settings.translation.get("auto_install_models", True)):
                raise RuntimeError(f"Argos language pair {src}→{dst} is not installed")
            if progress:
                progress(0, 0, f"Installing language model {src}→{dst}…")
            from argostranslate import package as argos_package
            argos_package.update_package_index()
            available = argos_package.get_available_packages()
            package = next((p for p in available if p.from_code == src and p.to_code == dst), None)
            if package is None:
                raise RuntimeError(f"No Argos language model is available for {src}→{dst}")
            argos_package.install_from_path(package.download())
        from argostranslate import translate as argos_translate
        translator = lambda value, a, b: argos_translate.translate(value, a, b)

    sections = _sections(text)
    units: list[tuple[int | None, str]] = []
    for page, section_text in sections:
        for piece in _split_text(section_text, int(settings.translation.get("max_chars_per_request", 1800))):
            units.append((page, piece))
    if not units:
        units = [(None, text)]

    translated: list[tuple[int | None, str]] = []
    total = len(units)
    if progress:
        progress(0, total, "Preparing translation…")
    for index, (page, piece) in enumerate(units, 1):
        translated.append((page, translator(piece, src, dst)))
        if progress:
            label = f"Page {page}" if page is not None else "Document"
            progress(index, total, f"Translating {label}")

    output_dir = settings.translations_dir / dst
    output_dir.mkdir(parents=True, exist_ok=True)
    source_name = Path(doc["source_path"]).stem
    output_path = output_dir / f"{source_name}.{sha256[:10]}.{dst}.md"
    created_at = datetime.now(timezone.utc).isoformat()
    body = _render_markdown(doc["source_path"], sha256, src, dst, created_at, translated)
    _atomic_write(output_path, body)
    meta_path = output_path.with_suffix(output_path.suffix + ".json")
    metadata = {
        "document_sha256": sha256,
        "source_path": doc["source_path"],
        "source_lang": src,
        "target_lang": dst,
        "created_at": created_at,
        "engine": "custom" if custom_translator else "argos-translate",
        "output_path": str(output_path),
    }
    _atomic_write(meta_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    db.save_translation(
        sha256=sha256,
        source_lang=src,
        target_lang=dst,
        output_path=str(output_path),
        created_at=created_at,
        engine="custom" if custom_translator else "argos-translate",
    )
    return metadata


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
        pieces = [paragraph[i:i + max_chars] for i in range(0, len(paragraph), max_chars)] if len(paragraph) > max_chars else [paragraph]
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


def _render_markdown(source_path: str, sha256: str, src: str, dst: str, created_at: str, units: list[tuple[int | None, str]]) -> str:
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
    for page, text in units:
        if page != last_page and page is not None:
            lines.extend([f"## Page {page}", ""])
        lines.extend([text.strip(), ""])
        last_page = page
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
