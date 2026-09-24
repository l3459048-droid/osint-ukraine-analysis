from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

EXTRACTED_PAGE_RE = re.compile(r"(?:^|\n)\s*--- PAGE (\d+) ---\s*\n", re.MULTILINE)
TRANSLATED_PAGE_RE = re.compile(r"(?m)^## Page (\d+)\s*$")


@dataclass(frozen=True)
class ReaderPage:
    page: int | None
    original: str
    translation: str | None


@dataclass(frozen=True)
class ReaderView:
    pages: list[ReaderPage]
    selected_index: int
    translation_source: str | None

    @property
    def selected(self) -> ReaderPage | None:
        return self.pages[self.selected_index] if self.pages else None


def load_reader(settings, db, sha256: str, requested_page: int | None = None) -> ReaderView:
    text_path = settings.text_dir / f"{sha256}.txt"
    if not text_path.is_file():
        return ReaderView([], 0, None)

    original_sections = _extracted_sections(text_path.read_text(encoding="utf-8", errors="replace"))
    translation_row = next((row for row in db.list_translations(sha256) if row["target_lang"] == "ru"), None)
    translated: dict[int | None, str] = {}
    translation_source = None
    if translation_row:
        candidate = Path(translation_row["output_path"]).expanduser().resolve()
        try:
            candidate.relative_to(settings.translations_dir.resolve())
        except ValueError:
            candidate = Path()
        if candidate.is_file():
            translated = dict(_translated_sections(candidate.read_text(encoding="utf-8", errors="replace")))
            translation_source = translation_row["source_lang"]

    pages = [ReaderPage(page, text, translated.get(page)) for page, text in original_sections]
    selected_index = 0
    if requested_page is not None:
        for index, item in enumerate(pages):
            if item.page == requested_page:
                selected_index = index
                break
    return ReaderView(pages, selected_index, translation_source)


def _extracted_sections(text: str) -> list[tuple[int | None, str]]:
    matches = list(EXTRACTED_PAGE_RE.finditer(text))
    if not matches:
        value = text.strip()
        return [(None, value)] if value else []
    result: list[tuple[int | None, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip()
        if value:
            result.append((int(match.group(1)), value))
    return result


def _translated_sections(text: str) -> list[tuple[int | None, str]]:
    matches = list(TRANSLATED_PAGE_RE.finditer(text))
    if matches:
        result: list[tuple[int | None, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            value = text[start:end].strip()
            if value:
                result.append((int(match.group(1)), value))
        return result

    lines = text.splitlines()
    body_start = 0
    for index, line in enumerate(lines):
        if index == 0 and line.startswith("# Translation"):
            body_start = 1
            continue
        if line.startswith("- Source:") or line.startswith("- SHA-256:") or line.startswith("- Language:") or line.startswith("- Generated:"):
            body_start = index + 1
            continue
        if index >= body_start and line.strip():
            body_start = index
            break
    value = "\n".join(lines[body_start:]).strip()
    return [(None, value)] if value else []
