from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Pt


PAGE_HEADING_RE = re.compile(r"^## Page (\\d+)\\s*$", re.MULTILINE)


def export_translation_docx(
    settings,
    db,
    sha256: str,
    source_lang: str,
    target_lang: str = "ru",
) -> Path:
    row = db.get_translation(sha256, source_lang, target_lang)
    if not row:
        raise RuntimeError("Translation not found")

    markdown_path = Path(row["output_path"]).expanduser().resolve()
    translations_root = settings.translations_dir.resolve()
    try:
        markdown_path.relative_to(translations_root)
    except ValueError as exc:
        raise RuntimeError("Invalid translation path") from exc
    if not markdown_path.is_file():
        raise RuntimeError("Translation file is missing")

    document_row = db.get_document(sha256)
    if not document_row:
        raise RuntimeError("Document not found")

    markdown = markdown_path.read_text(encoding="utf-8", errors="replace")
    title, units = _parse_translation_markdown(markdown)

    document = Document()
    document.core_properties.title = title
    document.core_properties.subject = (
        f"OSINT Local translation {source_lang} → {target_lang}"
    )
    document.core_properties.author = "OSINT Local"
    document.styles["Normal"].font.size = Pt(11)

    document.add_heading(title, level=0)
    for label, value in (
        ("Source", document_row["source_path"]),
        ("SHA-256", sha256),
        ("Language", f"{source_lang} → {target_lang}"),
        ("Generated", row["created_at"] or ""),
        ("Engine", row["engine"] or "unknown"),
    ):
        paragraph = document.add_paragraph()
        paragraph.add_run(f"{label}: ").bold = True
        paragraph.add_run(str(value))

    if units:
        document.add_paragraph()

    first_page = True
    for page, text in units:
        if page is not None:
            if not first_page:
                document.add_page_break()
            document.add_heading(f"Page {page}", level=1)
            first_page = False
        _append_text(document, text)

    output_path = markdown_path.with_suffix(".docx")
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    document.save(tmp_path)
    tmp_path.replace(output_path)
    return output_path


def _parse_translation_markdown(
    markdown: str,
) -> tuple[str, list[tuple[int | None, str]]]:
    lines = markdown.splitlines()
    title = "Translation"
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or title

    body_start = 1
    for index, line in enumerate(lines):
        if line.startswith("- Generated:"):
            body_start = index + 1
            break
    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1

    body = "\n".join(lines[body_start:]).strip()
    if not body:
        return title, []

    matches = list(PAGE_HEADING_RE.finditer(body))
    if not matches:
        return title, [(None, body)]

    units: list[tuple[int | None, str]] = []
    prefix = body[:matches[0].start()].strip()
    if prefix:
        units.append((None, prefix))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        text = body[start:end].strip()
        if text:
            units.append((int(match.group(1)), text))
    return title, units


def _append_text(document: Document, text: str) -> None:
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n", text)
        if block.strip()
    ]
    for block in blocks:
        paragraph = document.add_paragraph()
        for index, line in enumerate(block.splitlines()):
            if index:
                paragraph.add_run().add_break(WD_BREAK.LINE)
            paragraph.add_run(line)
