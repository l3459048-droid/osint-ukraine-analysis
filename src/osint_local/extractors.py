from __future__ import annotations

import io
import re
import unicodedata
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


def _normalize_pdf_text(text: str) -> str:
    value = unicodedata.normalize("NFC", str(text or ""))
    value = value.replace("\u00a0", " ").replace("\u202f", " ")
    value = value.replace("\u00ad", "")
    value = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return value.strip()


def _pdf_text_quality(text: str, *, min_chars: int = 80) -> dict:
    value = _normalize_pdf_text(text)
    visible = [char for char in value if not char.isspace()]
    visible_count = len(visible)
    if visible_count == 0:
        return {
            "score": 0.0,
            "visible_chars": 0,
            "letters": 0,
            "words": 0,
            "replacement_chars": 0,
            "control_chars": 0,
            "form_fill_ratio": 0.0,
        }

    letters = sum(char.isalpha() for char in visible)
    digits = sum(char.isdigit() for char in visible)
    words = re.findall(r"[^\W_]{2,}", value, flags=re.UNICODE)
    replacement_chars = value.count("\ufffd")
    control_chars = sum(
        unicodedata.category(char).startswith("C")
        for char in value
        if char not in "\n\t"
    )
    mojibake_markers = sum(value.count(marker) for marker in ("Ã", "Â", "Ð", "Ñ"))
    repeated_noise = sum(
        len(match.group(0))
        for match in re.finditer(r"([^\s_])\1{5,}", value)
    )
    form_fill_ratio = value.count("_") / max(1, visible_count)
    legible_ratio = (letters + digits) / max(1, visible_count)

    score = 1.0
    if visible_count < min_chars:
        score -= min(0.45, ((min_chars - visible_count) / max(1, min_chars)) * 0.45)
    if legible_ratio < 0.45:
        score -= min(0.30, (0.45 - legible_ratio) * 0.9)
    if len(words) < 4 and visible_count >= min_chars:
        score -= 0.12
    score -= min(0.45, replacement_chars / max(1, visible_count) * 8.0)
    score -= min(0.45, control_chars / max(1, len(value)) * 10.0)
    score -= min(0.35, mojibake_markers / max(1, visible_count) * 5.0)
    score -= min(0.25, repeated_noise / max(1, visible_count) * 1.5)
    if form_fill_ratio > 0.35:
        score -= min(0.12, (form_fill_ratio - 0.35) * 0.5)

    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "visible_chars": visible_count,
        "letters": letters,
        "words": len(words),
        "replacement_chars": replacement_chars,
        "control_chars": control_chars,
        "form_fill_ratio": round(form_fill_ratio, 4),
    }


def _native_pdf_page_text(page) -> str:
    try:
        text = page.get_text("text", sort=True)
    except TypeError:
        text = page.get_text("text")
    return _normalize_pdf_text(text)


def _same_visual_row(a: dict, b: dict) -> bool:
    a_height = max(1.0, float(a["y1"]) - float(a["y0"]))
    b_height = max(1.0, float(b["y1"]) - float(b["y0"]))
    overlap = min(float(a["y1"]), float(b["y1"])) - max(float(a["y0"]), float(b["y0"]))
    center_delta = abs(
        (float(a["y0"]) + float(a["y1"])) / 2.0
        - (float(b["y0"]) + float(b["y1"])) / 2.0
    )
    return (
        overlap >= min(a_height, b_height) * 0.35
        or center_delta <= max(2.0, min(a_height, b_height) * 0.45)
    )


def _layout_pdf_page_text(page) -> tuple[str, dict]:
    """Rebuild page text from positioned PDF lines instead of creator order."""
    try:
        import fitz

        flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
        data = page.get_text("dict", sort=True, flags=flags)
    except (AttributeError, TypeError):
        try:
            data = page.get_text("dict", sort=True)
        except (AttributeError, TypeError):
            return "", {"layout_lines": 0, "layout_rows": 0, "multi_part_rows": 0}

    lines: list[dict] = []
    for block in data.get("blocks", []):
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = _normalize_pdf_text("".join(str(span.get("text") or "") for span in spans))
            text = re.sub(r"[ \t]+", " ", text).strip()
            if not text:
                continue
            bbox = line.get("bbox") or (0.0, 0.0, 0.0, 0.0)
            if len(bbox) < 4:
                continue
            lines.append({
                "x0": float(bbox[0]),
                "y0": float(bbox[1]),
                "x1": float(bbox[2]),
                "y1": float(bbox[3]),
                "text": text,
            })

    if not lines:
        return "", {"layout_lines": 0, "layout_rows": 0, "multi_part_rows": 0}

    lines.sort(key=lambda item: (item["y0"], item["x0"]))
    rows: list[list[dict]] = []
    for line in lines:
        if rows and any(_same_visual_row(existing, line) for existing in rows[-1]):
            rows[-1].append(line)
        else:
            rows.append([line])

    rendered: list[str] = []
    multi_part_rows = 0
    for row in rows:
        row.sort(key=lambda item: item["x0"])
        if len(row) > 1:
            multi_part_rows += 1
        pieces: list[str] = []
        previous_x1: float | None = None
        for item in row:
            if previous_x1 is not None:
                gap = float(item["x0"]) - previous_x1
                pieces.append("    " if gap >= 14.0 else " ")
            pieces.append(str(item["text"]))
            previous_x1 = max(float(item["x1"]), previous_x1 or float(item["x1"]))
        rendered.append("".join(pieces).strip())

    return _normalize_pdf_text("\n".join(rendered)), {
        "layout_lines": len(lines),
        "layout_rows": len(rows),
        "multi_part_rows": multi_part_rows,
    }


def _prefer_layout_text(native_text: str, layout_text: str) -> bool:
    native_visible = len(re.sub(r"\s+", "", str(native_text or "")))
    layout_visible = len(re.sub(r"\s+", "", str(layout_text or "")))
    if layout_visible == 0:
        return False
    if native_visible == 0:
        return True
    ratio = layout_visible / native_visible
    if not 0.82 <= ratio <= 1.18:
        return False
    native_quality = _pdf_text_quality(native_text)["score"]
    layout_quality = _pdf_text_quality(layout_text)["score"]
    return layout_quality >= native_quality - 0.03


def _should_probe_ocr(
    metrics: dict,
    *,
    min_chars: int,
    quality_threshold: float,
) -> bool:
    return (
        int(metrics.get("visible_chars") or 0) < min_chars
        or float(metrics.get("score") or 0.0) < quality_threshold
        or int(metrics.get("replacement_chars") or 0) > 0
        or int(metrics.get("control_chars") or 0) > 0
    )


def _prefer_ocr(
    native_metrics: dict,
    ocr_metrics: dict,
    *,
    min_chars: int,
    improvement_margin: float,
) -> bool:
    native_chars = int(native_metrics.get("visible_chars") or 0)
    ocr_chars = int(ocr_metrics.get("visible_chars") or 0)
    native_score = float(native_metrics.get("score") or 0.0)
    ocr_score = float(ocr_metrics.get("score") or 0.0)

    if ocr_chars == 0:
        return False
    if native_chars == 0:
        return True
    if native_chars < min_chars <= ocr_chars and ocr_score >= native_score:
        return True
    if ocr_chars < max(20, int(native_chars * 0.60)):
        return False
    return ocr_score >= native_score + improvement_margin


def _extract_pdf(path: Path, ocr_config: dict) -> ExtractionResult:
    import fitz

    doc = fitz.open(path)
    pages: list[dict] = []
    all_text: list[str] = []
    ocr_used = False
    min_chars = int(ocr_config.get("min_text_chars_per_page", 80))
    quality_threshold = float(ocr_config.get("quality_threshold", 0.72))
    improvement_margin = float(ocr_config.get("ocr_improvement_margin", 0.08))
    ocr_enabled = bool(ocr_config.get("enabled", True))

    try:
        for index, page in enumerate(doc):
            native_text = _native_pdf_page_text(page)
            native_metrics = _pdf_text_quality(native_text, min_chars=min_chars)
            layout_text, layout_meta = _layout_pdf_page_text(page)
            layout_metrics = _pdf_text_quality(layout_text, min_chars=min_chars)
            layout_used = _prefer_layout_text(native_text, layout_text)

            text = layout_text if layout_used else native_text
            selected_native_metrics = layout_metrics if layout_used else native_metrics
            method = "pdf-layout" if layout_used else "pdf-text"
            ocr_text = ""
            ocr_metrics = None

            should_probe = ocr_enabled and _should_probe_ocr(
                selected_native_metrics,
                min_chars=min_chars,
                quality_threshold=quality_threshold,
            )
            if should_probe:
                ocr_text = _normalize_pdf_text(_ocr_page(page, ocr_config))
                ocr_metrics = _pdf_text_quality(ocr_text, min_chars=min_chars)
                if _prefer_ocr(
                    selected_native_metrics,
                    ocr_metrics,
                    min_chars=min_chars,
                    improvement_margin=improvement_margin,
                ):
                    text = ocr_text
                    method = "ocr"
                    ocr_used = True

            selected_metrics = (
                ocr_metrics if method == "ocr" and ocr_metrics is not None
                else selected_native_metrics
            )
            pages.append({
                "page": index + 1,
                "chars": len(text),
                "method": method,
                "quality_score": selected_metrics["score"],
                "native_chars": len(native_text),
                "native_quality_score": native_metrics["score"],
                "layout_chars": len(layout_text),
                "layout_quality_score": layout_metrics["score"],
                "layout_used": layout_used,
                **layout_meta,
                "ocr_checked": bool(should_probe),
                "ocr_chars": len(ocr_text) if should_probe else 0,
                "ocr_quality_score": (
                    ocr_metrics["score"] if ocr_metrics is not None else None
                ),
            })
            all_text.append(f"\n\n--- PAGE {index + 1} ---\n{text}")
    finally:
        doc.close()

    layout_used_anywhere = any(page.get("layout_used") for page in pages)
    return ExtractionResult(
        text="".join(all_text).strip(),
        method=(
            "pdf+ocr" if ocr_used
            else "pdf-layout" if layout_used_anywhere
            else "pdf-text"
        ),
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
