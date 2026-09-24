# OSINT Local — v0.1

Local-first replacement for the Google Drive ingestion layer in `Xolthol/osint-ukraine-analysis`.

## What it does now

- watches a local folder recursively;
- accepts PDF, DOCX, TXT and Markdown;
- fingerprints every document with SHA-256;
- skips unchanged files and deduplicates identical content;
- extracts embedded PDF text and DOCX/TXT text;
- optionally OCRs sparse/scanned PDF pages with local Tesseract;
- performs basic configurable keyword classification;
- writes immutable text and metadata artifacts keyed by hash;
- stores processing state in SQLite;
- never modifies or deletes the source document.

## Layout

```text
inbox/                 <- put source documents here
workspace/
  osint.db              <- processing state
  text/<sha256>.txt     <- extracted text
  metadata/<sha256>.json
  logs/osint-local.log
```

## Install

Python 3.10+:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
```

For local OCR:

```bash
pip install -e '.[ocr]'
```

`pytesseract` is only a Python wrapper. Install the Tesseract executable separately and the desired language data (`eng`, `rus`, `ukr`). If Tesseract is absent, ordinary PDF text extraction still works.

## Start

```bash
osint-local init
# edit config.json if needed
osint-local doctor
osint-local scan
osint-local watch
```

Any local directory can be used, including one outside the repository:

```json
{
  "input_dir": "D:/OSINT/Documents",
  "workspace_dir": "D:/OSINT/AnalysisData"
}
```

The input directory is treated as read-only. Document identity is based on SHA-256 content rather than filename.
