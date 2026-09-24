from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ExtractionResult:
    text: str
    method: str
    pages: list[dict]


def extract(path: Path, ocr_config: dict) -> ExtractionResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path, ocr_config)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix in {".txt", ".md"}:
        return ExtractionResult(
            text=path.read_text(encoding="utf-8", errors="replace"),
            method="plain-text",
            pages=[],
        )
    raise ValueError(f"Unsupported extension: {suffix}")


def _extract_docx(path: Path) -> ExtractionResult:
    from docx import Document
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs if p.text)
    return ExtractionResult(text=text, method="docx", pages=[])


def _extract_pdf(path: Path, ocr_config: dict) -> ExtractionResult:
    import fitz

    doc = fitz.open(path)
    pages: list[dict] = []
    all_text: list[str] = []
    ocr_used = False
    min_chars = int(ocr_config.get("min_text_chars_per_page", 80))

    try:
        for index, page in enumerate(doc):
            text = page.get_text("text").strip()
            method = "pdf-text"
            if len(text) < min_chars and bool(ocr_config.get("enabled", True)):
                ocr_text = _ocr_page(page, ocr_config)
                if len(ocr_text.strip()) > len(text):
                    text = ocr_text.strip()
                    method = "ocr"
                    ocr_used = True
            pages.append({"page": index + 1, "chars": len(text), "method": method})
            all_text.append(f"\n\n--- PAGE {index + 1} ---\n{text}")
    finally:
        doc.close()

    return ExtractionResult(
        text="".join(all_text).strip(),
        method="pdf+ocr" if ocr_used else "pdf-text",
        pages=pages,
    )


def _ocr_page(page, ocr_config: dict) -> str:
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    dpi = int(ocr_config.get("dpi", 220))
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    languages = str(ocr_config.get("languages", "eng+rus+ukr"))
    try:
        return pytesseract.image_to_string(image, lang=languages)
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError):
        return ""
