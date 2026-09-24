# Migration from Xolthol/osint-ukraine-analysis

Recommended first migration:

1. Add `src/osint_local`, `pyproject.toml`, the config template and tests.
2. Stop using `setup_gdrive.py` and `sync_gdrive.py` as the main runtime.
3. Move old Google-specific files under `legacy/google_drive/` instead of deleting them immediately.
4. Point `input_dir` at any folder on the PC; source documents do not have to live inside the Git repository.
5. Keep `workspace/` and the source folder out of Git.

Suggested shape:

```text
osint-ukraine-analysis/
  src/osint_local/
  tests/
  config.example.json
  pyproject.toml
  inbox/            # optional, gitignored
  workspace/        # generated, gitignored
  legacy/
    google_drive/
      setup_gdrive.py
      sync_gdrive.py
      GUIDE_GOOGLE_DRIVE.md
```

Next layers should consume the SQLite state and extracted text rather than reading arbitrary folders directly: language detection -> semantic embeddings -> claim/entity extraction -> cited synthesis -> local web UI.
