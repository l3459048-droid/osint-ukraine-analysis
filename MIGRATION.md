# Migration from Xolthol/osint-ukraine-analysis

The fork now uses the local-first runtime through v0.6.

## Active runtime

Use:

- `src/osint_local/`
- `pyproject.toml`
- `config.json`
- `workspace/`
- `translations/`

The legacy Google Drive scripts remain untouched for reversibility but are not part of the primary runtime.

## Upgrade behavior

Existing SQLite databases are upgraded in place. No database reset is required for v0.6. Existing extracted text, chunks, embeddings and translations remain usable.

New v0.6 capabilities are additive:

- original/Russian side-by-side reader;
- search links jump to the matching page;
- translation policy narrowed to EN/UK → RU;
- passive scan/index/one-document translation loop while `serve` runs;
- local RAG Q&A through Ollama.

Source documents remain read-only throughout the migration.
