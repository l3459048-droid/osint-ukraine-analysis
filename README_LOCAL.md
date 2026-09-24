# OSINT Local — v0.6

Local-first runtime for the OSINT Ukraine Analysis fork.

## Current pipeline

- local recursive PDF/DOCX/TXT/MD ingestion;
- SHA-256 deduplication and incremental processing;
- embedded-text extraction plus optional local Tesseract OCR;
- multilingual keyword classification;
- page-aware chunking;
- SQLite document/chunk/embedding/translation state;
- lexical search and optional multilingual semantic search;
- local Web UI without a web-framework dependency;
- page-targeted search results;
- side-by-side original/Russian reader;
- offline EN→RU and UK→RU translation with Argos Translate;
- passive one-document-at-a-time translation queue;
- passive scan/index maintenance while Web UI is running;
- local RAG Q&A through Ollama with source/page references;
- source files remain read-only.

## Layout

```text
<any document folder>/           # read-only originals
translations/ru/                 # generated Russian translations
workspace/
  osint.db
  text/<sha256>.txt
  metadata/<sha256>.json
  logs/osint-local.log
```

## Install

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
```

Optional layers:

```bash
pip install -e '.[ocr]'
pip install -e '.[search]'
pip install -e '.[translate]'
# or
pip install -e '.[all]'
```

## Run

```bash
osint-local serve
```

Default URL: `http://127.0.0.1:8080`.

## Passive maintenance

When `serve` is used, the background loop periodically asks the same serialized ActionManager to:

1. run an incremental scan;
2. embed missing chunks if semantic search is installed;
3. translate at most one eligible EN/UK document to Russian when the required Argos route is already installed.

No translation model is downloaded by the passive worker.

## Q&A

`Ask` retrieves relevant chunks from the whole current library, then sends only those grounded fragments to a local Ollama `/api/chat` endpoint. The response is shown together with source document/page links. If Ollama is unavailable, the UI still shows retrieved source fragments instead of pretending to have generated an answer.

CLI:

```bash
osint-local ask "question about the collection"
```

## Translation

Only `en → ru` and `uk → ru` are accepted. Ukrainian may pivot through English when direct Argos packages are unavailable. Generated Markdown preserves PDF page headings and is stored separately from originals.

```bash
osint-local translate <SHA256> --from auto
```
