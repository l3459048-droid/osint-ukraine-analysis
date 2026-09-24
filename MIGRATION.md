# Migration from Xolthol/osint-ukraine-analysis

The fork now uses a local-first runtime through v0.3.

## Migration path

1. Keep the original repository history and legacy Google Drive scripts for reference.
2. Use `src/osint_local/`, `pyproject.toml`, `config.json` and `workspace/` as the active runtime.
3. Point `input_dir` at any folder on the PC; source documents do not need to live inside Git.
4. Run `osint-local scan` to extract/classify/chunk documents.
5. Optionally run `osint-local index` for multilingual semantic embeddings.
6. Run `osint-local serve` (or `start_local.bat`) for the v0.3 local Web UI.

Suggested active layout:

```text
osint-ukraine-analysis/
  src/osint_local/
  tests/
  config.example.json
  pyproject.toml
  start_local.bat
  start_local.sh

D:/OSINT/Documents/       # source collection
D:/OSINT/AnalysisData/    # SQLite + extracted artifacts
```

The old Google-specific files can later move under `legacy/google_drive/`, but v0.3 deliberately leaves them untouched so the migration remains reversible.

## Database compatibility

v0.1 SQLite databases are upgraded automatically. Documents processed by v0.1 without page-aware chunks are reprocessed once by v0.2/v0.3. v0.2 databases require no destructive migration for the v0.3 Web UI.
