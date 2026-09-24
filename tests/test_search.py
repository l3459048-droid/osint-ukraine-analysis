from __future__ import annotations

import json
from pathlib import Path

from osint_local.config import load_settings
from osint_local.pipeline import LocalPipeline
from osint_local.search import SearchIndex, _split_pages


def make_config(tmp_path: Path) -> Path:
    config = {
        "input_dir": "inbox",
        "workspace_dir": "workspace",
        "allowed_extensions": [".txt"],
        "ocr": {"enabled": False},
        "classification": {"min_score": 1, "domains": {"Drones": ["fpv"]}},
        "search": {
            "chunk_chars": 200,
            "overlap_chars": 20,
            "min_chunk_chars": 20,
            "semantic_enabled": True,
            "model": "test-model",
            "batch_size": 4,
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class FakeEncoder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            lowered = text.casefold()
            if any(term in lowered for term in ("fpv", "drone", "unmanned")):
                vectors.append([1.0, 0.0])
            elif "artillery" in lowered:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.5, 0.5])
        return vectors


def test_page_markers_are_preserved():
    pages = _split_pages("--- PAGE 1 ---\nalpha\n\n--- PAGE 2 ---\nbravo")
    assert pages == [(1, "alpha"), (2, "bravo")]


def test_v01_text_artifact_is_searchable_without_reprocessing(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "report.txt"
    source.write_text("FPV drones target logistics vehicles.", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        processed = pipeline.process_file(source)
        assert processed.status == "processed"
    finally:
        pipeline.close()

    with SearchIndex(settings) as index:
        hits = index.search("FPV logistics", mode="lexical")
        assert hits
        assert hits[0].source_path == "report.txt"
        assert hits[0].backend == "lexical"


def test_semantic_index_uses_existing_chunks(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "drones.txt").write_text("FPV drone team operates forward.", encoding="utf-8")
    (settings.input_dir / "artillery.txt").write_text("Artillery conducts fire missions.", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
    finally:
        pipeline.close()

    with SearchIndex(settings) as index:
        count = index.build_embeddings(encoder=FakeEncoder())
        assert count == 2
        hits = index.search(
            "unmanned aircraft tactics",
            mode="semantic",
            encoder=FakeEncoder(),
            limit=2,
        )
        assert hits[0].source_path == "drones.txt"
        assert hits[0].score > hits[1].score


def test_auto_search_falls_back_to_lexical_when_index_is_incomplete(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "one.txt").write_text("FPV drone tactics", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
    finally:
        pipeline.close()

    with SearchIndex(settings) as index:
        index.build_embeddings(encoder=FakeEncoder())

    (settings.input_dir / "two.txt").write_text("FPV logistics adaptation", encoding="utf-8")
    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
    finally:
        pipeline.close()

    with SearchIndex(settings) as index:
        hits = index.search("FPV logistics", mode="auto")
        assert hits
        assert hits[0].backend == "lexical"
        assert hits[0].source_path == "two.txt"
