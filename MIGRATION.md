# Migration from Xolthol/osint-ukraine-analysis

The fork now uses a local-first runtime through v0.4.1.

## Migration path

1. Keep the original repository history and legacy Google Drive scripts for reference.
2. Use `src/osint_local/`, `pyproject.toml`, `config.json` and `workspace/` as the active runtime.
3. Run `osint-local serve` (or `start_local.bat`). On a fresh install the Web UI creates the config and asks for the document folder.
4. Use `Scan` in the UI (or `osint-local scan`) to extract/classify/chunk documents.
5. Optionally install `.[search]` and use `Build/Update index` for multilingual semantic embeddings.
6. Change or open the source folder later from the compact Settings/UI controls.

The old Google-specific files can later move under `legacy/google_drive/`, but v0.4.1 leaves them untouched so the migration remains reversible.

## Database compatibility

v0.1 SQLite databases are upgraded automatically. Documents processed by v0.1 without page-aware chunks are reprocessed once by later versions. v0.2-v0.4 databases require no destructive migration for the v0.4.1 UX update.

## v0.5 translation

No database reset is required. The `translations` table is created automatically. Generated translations are stored outside the source folder by default and do not replace or modify source files.
