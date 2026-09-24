from __future__ import annotations

import json
from pathlib import Path

from osint_local.config import load_settings
from osint_local.pipeline import LocalPipeline


def make_config(tmp_path: Path) -> Path:
    config = {
        "input_dir": "inbox",
        "workspace_dir": "workspace",
        "allowed_extensions": [".txt"],
        "ocr": {"enabled": False},
        "classification": {
            "min_score": 1,
            "domains": {
                "Drones": ["fpv", "drone"],
                "Artillery": ["artillery"]
            }
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_process_and_skip_unchanged(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "report.txt"
    source.write_text("FPV drone report", encoding="utf-8")

    p = LocalPipeline(settings)
    try:
        first = p.process_file(source)
        second = p.process_file(source)
        assert first.status == "processed"
        assert second.status == "skipped"
        assert (settings.text_dir / f"{first.sha256}.txt").exists()
        metadata = json.loads((settings.metadata_dir / f"{first.sha256}.json").read_text())
        assert metadata["classifications"][0]["domain"] == "Drones"
    finally:
        p.close()


def test_duplicate_content_not_reprocessed(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    a = settings.input_dir / "a.txt"
    b = settings.input_dir / "b.txt"
    a.write_text("same fpv content", encoding="utf-8")
    b.write_text("same fpv content", encoding="utf-8")

    p = LocalPipeline(settings)
    try:
        one = p.process_file(a)
        two = p.process_file(b)
        assert one.status == "processed"
        assert two.status == "duplicate"
        assert one.sha256 == two.sha256
    finally:
        p.close()


def test_default_config_contains_domains(tmp_path: Path):
    settings = load_settings(tmp_path / "missing-config.json")
    assert "Drones" in settings.classification["domains"]


def test_pipeline_can_process_from_worker_thread(tmp_path: Path):
    import threading

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "threaded.txt"
    source.write_text("fpv", encoding="utf-8")

    p = LocalPipeline(settings)
    result = []
    try:
        thread = threading.Thread(target=lambda: result.append(p.process_file(source)))
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert result[0].status == "processed"
    finally:
        p.close()
