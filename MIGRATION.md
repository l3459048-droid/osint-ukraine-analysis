# Migration to local-first v0.2

v0.2 is backward-compatible with the local v0.1 workspace.

The search index is built from the existing SQLite document registry and `workspace/text/<sha256>.txt` artifacts. Existing PDFs do **not** need to be OCRed or extracted again.

Recommended upgrade:

```bash
pip install -e '.[all]'
osint-local search "test" --mode lexical
osint-local index
osint-local status
```

The first search/index creates three additional tables in the existing SQLite database:

- `search_documents`
- `search_chunks`
- `search_embeddings`

Old Google Drive scripts remain legacy code and are not required by the local runtime.
