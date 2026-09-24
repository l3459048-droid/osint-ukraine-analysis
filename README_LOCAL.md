# OSINT Local — v0.2

Local-first document ingestion and search for `osint-ukraine-analysis`.

## What v0.2 adds

v0.1 already ingests local PDF/DOCX/TXT/Markdown files, extracts text, optionally runs local OCR, fingerprints documents with SHA-256, classifies them and stores state in SQLite.

v0.2 adds a search layer **on top of the existing v0.1 artifacts**:

- page-aware chunks for PDFs;
- lightweight lexical search with no ML dependency;
- optional multilingual semantic embeddings with Sentence Transformers;
- search results containing source path, PDF page and matching fragment;
- a separate search index inside the same `workspace/osint.db`;
- automatic reuse of documents already processed by v0.1 — no re-extraction required.

## Install

Python 3.10+:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -e .
```

For OCR:

```bash
pip install -e '.[ocr]'
```

For semantic search:

```bash
pip install -e '.[search]'
```

Or both:

```bash
pip install -e '.[all]'
```

The current `sentence-transformers` 6.x line supports Python 3.10+, and the default model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. The model supports multilingual sentence similarity. On its first use Sentence Transformers may download model files; after they are cached, inference runs locally. `search.model` can also be a local model directory for fully offline operation.

## First run

```bash
osint-local init
```

Point `config.json` at any local directories:

```json
{
  "input_dir": "D:/OSINT/Documents",
  "workspace_dir": "D:/OSINT/AnalysisData"
}
```

Process documents:

```bash
osint-local scan
```

## Search without ML

Lexical search works without Sentence Transformers. The first search automatically creates/updates chunks from already extracted `text/<sha256>.txt` files:

```bash
osint-local search "FPV logistics" --mode lexical
```

For PDFs, v0.2 recognizes the `--- PAGE N ---` markers written by the v0.1 extractor, so results retain page numbers without reprocessing the source PDF.

## Semantic search

Install the search extra, then build embeddings:

```bash
pip install -e '.[search]'
osint-local index
```

Search automatically switches to semantic mode only when **all current chunks** have embeddings. This prevents newly ingested but not-yet-embedded documents from silently disappearing from results.

```bash
osint-local search "изменение тактики применения FPV"
osint-local search "electronic warfare against drones" --limit 5
```

Force a mode:

```bash
osint-local search "air defense" --mode lexical
osint-local search "air defense" --mode semantic
```

JSON output:

```bash
osint-local search "FPV" --json
```

Example:

```text
[1] 0.8124 semantic | reports/fpv-study.pdf — page 14
Operators increasingly use relay platforms to extend FPV range ...
```

## Updating the index

After new documents are ingested, run:

```bash
osint-local index
```

`index` first synchronizes chunks, then embeds only chunks that do not yet have an embedding. Existing vectors are reused.

To rebuild everything:

```bash
osint-local index --force
```

To build chunks only, without loading an ML model:

```bash
osint-local index --chunks-only
```

## Continuous ingestion

```bash
osint-local watch
```

The watcher remains lightweight and does not load the semantic model. New documents are extracted normally; the next `search` refreshes the text chunks automatically, and the next `index` adds their embeddings.

## Diagnostics

```bash
osint-local status
osint-local doctor
```

The source folder is treated as read-only. Generated text, metadata, chunks and embeddings live in the workspace.
