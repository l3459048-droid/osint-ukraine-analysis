# Migration from Xolthol/osint-ukraine-analysis

The fork now uses a local-first runtime through v0.4.

## Active workflow

1. Keep the original repository history and legacy Google Drive scripts for reference.
2. Use `src/osint_local/`, `pyproject.toml`, `config.json` and `workspace/` as the active runtime.
3. Point `input_dir` at any folder on the PC; source documents do not need to live inside Git.
4. Run `osint-local serve` (or `start_local.bat`).
5. Use **Scan** in the Web UI to process new/changed documents.
6. Use **Build index** when semantic-search dependencies are installed.
7. Use **Activity** only when you need operation details or recent errors.

Suggested layout:

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

The old Google-specific files can later move under `legacy/google_drive/`, but v0.4 still leaves them untouched so migration remains reversible.

## Database compatibility

v0.1 SQLite databases are upgraded automatically. v0.2/v0.3 databases require no destructive migration for v0.4. The UI action manager is in-memory only; it does not alter the persisted document/index schema.
