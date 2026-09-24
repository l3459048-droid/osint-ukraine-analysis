from __future__ import annotations

import re
from dataclasses import dataclass

PAGE_RE = re.compile(r"(?:^|\n)\s*--- PAGE (\d+) ---\s*\n")


@dataclass(frozen=True)
class Chunk:
    page: int | None
    chunk_index: int
    start_char: int
    end_char: int
    text: str


def build_chunks(text: str, config: dict) -> list[Chunk]:
    max_chars = max(200, int(config.get("chunk_chars", 1200)))
    overlap = min(max(0, int(config.get("overlap_chars", 180))), max_chars // 2)
    min_chars = max(1, int(config.get("min_chunk_chars", 80)))
    chunks: list[Chunk] = []
    index = 0
    for page, page_text in split_pages(text):
        for start, end, piece in _chunk_text(page_text, max_chars, overlap, min_chars):
            chunks.append(Chunk(page, index, start, end, piece))
            index += 1
    return chunks


def split_pages(text: str) -> list[tuple[int | None, str]]:
    matches = list(PAGE_RE.finditer(text))
    if not matches:
        stripped = text.strip()
        return [(None, stripped)] if stripped else []
    pages: list[tuple[int | None, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        page_text = text[start:end].strip()
        if page_text:
            pages.append((int(match.group(1)), page_text))
    return pages


def _chunk_text(text: str, max_chars: int, overlap: int, min_chars: int):
    text = text.strip()
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            floor = min(hard_end, start + min_chars)
            best = max(
                text.rfind("\n\n", floor, hard_end),
                text.rfind(". ", floor, hard_end),
                text.rfind("! ", floor, hard_end),
                text.rfind("? ", floor, hard_end),
                text.rfind("\n", floor, hard_end),
                text.rfind(" ", floor, hard_end),
            )
            if best > start:
                end = best + (2 if text[best:best + 2] in {". ", "! ", "? "} else 1)
        piece = text[start:end].strip()
        if piece:
            yield start, end, piece
        if end >= len(text):
            break
        next_start = max(0, end - overlap)
        start = end if next_start <= start else next_start
