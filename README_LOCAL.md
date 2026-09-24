# OSINT Local — v0.4

Local-first document ingestion, search and a minimal action-oriented Web UI for the OSINT Ukraine Analysis fork.

## Current pipeline

- recursively reads a configurable local folder;
- accepts PDF, DOCX, TXT and Markdown;
- fingerprints content with SHA-256 and skips unchanged/duplicate files;
- extracts embedded PDF/DOCX/TXT text;
- optionally OCRs sparse/scanned PDF pages with local Tesseract;
- classifies documents with configurable multilingual keywords;
- creates page-aware overlapping chunks;
- stores documents, classes, chunks and embeddings in SQLite;
- supports lexical search without ML dependencies;
- optionally builds multilingual semantic embeddings with Sentence Transformers;
- serves a dependency-free local Web UI with Python's standard library;
- runs Scan and Build index as serialized background UI actions with progress;
- shows recent processing errors in a collapsed Activity section;
- exposes local read-only JSON endpoints for stats/search/activity;
- never modifies or deletes the source document.

## Install

Python 3.10+:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e '.[all]'
```

For a lightweight lexical-only installation, `pip install -e .` is enough. OCR and semantic search remain optional extras (`.[ocr]`, `.[search]`).

## Start

```bash
osint-local init
# edit config.json once if needed
osint-local serve
```

Default address:

```text
http://127.0.0.1:8080
```

On Windows, `start_local.bat` starts the Web UI using `.venv` when present. Linux/macOS can use `./start_local.sh`.

## v0.4 UI workflow

The primary dashboard deliberately exposes only three library actions:

1. **Scan** — process new or changed supported files.
2. **Build index** — add missing semantic embeddings when the optional search dependency is installed.
3. **Refresh** — reload the current state.

Scan/index run on a background worker and the dashboard polls `/api/activity` for progress. Only one long-running action is allowed at a time. When an action completes, the dashboard refreshes its statistics automatically.

Secondary information is collapsed under **Activity**, including the last action result and recent processing errors.

## Web safety

The server binds to loopback by default. CLI refuses a non-local bind unless `--allow-network` is supplied explicitly.

State-changing Web UI endpoints use POST plus a random server-session CSRF token. The search/stats/activity API remains read-only.

## Semantic indexing

The UI button calls the same indexer as:

```bash
osint-local index
```

`auto` search uses semantic ranking only when the configured model has embeddings for all current chunks. A partial/stale index falls back to lexical search until indexing completes.

## API

```text
GET /api/stats
GET /api/search?q=electronic+warfare&mode=auto&limit=10
GET /api/activity
```

The API is intended as a stable local bridge for later desktop packaging and automation.
