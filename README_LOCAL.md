# OSINT Local — v0.5

Local-first document ingestion, search and minimal desktop-like Web UI for the OSINT Ukraine Analysis fork.

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
- lets the user choose/open the document folder from the UI;
- reports semantic-index freshness as a compact status;
- optionally translates processed documents offline with Argos Translate;
- saves translations separately next to the source-folder tree;
- never modifies or deletes source documents.

## Layout

```text
<any document folder>/           <- source documents, read-only
translations/                    <- generated translations, separate from sources
workspace/
  osint.db                       <- documents, chunks, classes, embeddings
  text/<sha256>.txt              <- extracted text
  metadata/<sha256>.json
  logs/osint-local.log
```

## Install

Python 3.10+:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
```

Optional OCR:

```bash
pip install -e '.[ocr]'
```

Optional semantic search:

```bash
pip install -e '.[search]'
```

Optional offline translation:

```bash
pip install -e '.[translate]'
```

Argos language models are installed per language pair. The first requested pair can be downloaded automatically; subsequent translations use the installed local model. UI v0.5 exposes English, Russian and Ukrainian.

Everything:

```bash
pip install -e '.[all]'
```

## Start

The shortest first-run path is now:

```bash
osint-local serve
```

If `config.json` does not exist, it is created automatically and the home page shows a small first-run folder chooser. The user can use the system folder dialog or paste a path manually. Settings remain available later from the top navigation.

Default address:

```text
http://127.0.0.1:8080
```

On Windows, after installation, `start_local.bat` starts the Web UI using `.venv` when present. Linux/macOS can use `./start_local.sh`.

## Minimal UI actions

The dashboard intentionally keeps a small action row:

```text
Scan | Build/Update index | Folder | Settings
```

The semantic state is derived from the current chunk/embedding coverage:

- `Index not built` — no embeddings yet;
- `Index update needed` — new chunks are not embedded yet;
- `Index current` — the configured model covers the current chunk set;
- `Semantic unavailable` — optional Sentence Transformers dependency is not installed.

Long-running Scan/Index jobs remain serialized and report compact progress through `/api/activity`.

## Folder handling

The selected `input_dir` is persisted to `config.json`. The server swaps to the new source folder without changing `workspace_dir`, so the database and derived artifacts stay in one predictable place.

The `Folder` action opens the current source directory through the OS file manager. The native folder chooser is launched in a child Python process so GUI toolkits do not interfere with the threaded HTTP server. If tkinter is unavailable, the manual path field remains the fallback.

## Semantic indexing

```bash
osint-local index
osint-local search "изменения тактики применения FPV"
```

`auto` search uses semantic ranking only when the configured model has embeddings for all current chunks. A partial/stale index falls back to lexical search until indexing completes.

## API

```text
GET /api/stats
GET /api/search?q=electronic+warfare&mode=auto&limit=10
GET /api/activity
```


## Translation

Translations are generated from the already extracted text, so OCR/extraction does not need to run again. The source file stays read-only. Results are stored as Markdown under `translations/<target-language>/` and tracked in SQLite by source SHA-256 and language pair. PDF page boundaries are retained as Markdown headings.

```bash
osint-local translate <SHA256> --from auto --to ru
```

The Web UI exposes the same operation on each document page.
