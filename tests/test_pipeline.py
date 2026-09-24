from __future__ import annotations

import json
import threading
from pathlib import Path

from osint_local.chunking import build_chunks
from osint_local.config import load_settings
from osint_local.pipeline import LocalPipeline
from osint_local.search import build_embeddings, search_chunks


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
                "Artillery": ["artillery"],
            },
        },
        "search": {
            "chunk_chars": 200,
            "overlap_chars": 20,
            "min_chunk_chars": 20,
            "semantic_enabled": True,
            "model": "test-model",
            "batch_size": 4,
            "auto_embed": False,
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_process_and_skip_unchanged(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "report.txt"
    source.write_text("FPV drone report " * 20, encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        first = pipeline.process_file(source)
        second = pipeline.process_file(source)
        assert first.status == "processed"
        assert second.status == "skipped"
        assert (settings.text_dir / f"{first.sha256}.txt").exists()
        metadata = json.loads((settings.metadata_dir / f"{first.sha256}.json").read_text())
        assert metadata["classifications"][0]["domain"] == "Drones"
        assert metadata["chunks"] >= 1
        assert pipeline.db.stats()["chunks"] >= 1
    finally:
        pipeline.close()


def test_duplicate_content_not_reprocessed(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    a = settings.input_dir / "a.txt"
    b = settings.input_dir / "b.txt"
    a.write_text("same fpv content", encoding="utf-8")
    b.write_text("same fpv content", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        one = pipeline.process_file(a)
        two = pipeline.process_file(b)
        assert one.status == "processed"
        assert two.status == "duplicate"
        assert one.sha256 == two.sha256
    finally:
        pipeline.close()


def test_default_config_contains_domains_and_search(tmp_path: Path):
    settings = load_settings(tmp_path / "missing-config.json")
    assert "Drones" in settings.classification["domains"]
    assert settings.search["semantic_enabled"] is True
    assert settings.search["chunk_chars"] > settings.search["overlap_chars"]


def test_pipeline_can_process_from_worker_thread(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "threaded.txt"
    source.write_text("fpv", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    result = []
    try:
        thread = threading.Thread(target=lambda: result.append(pipeline.process_file(source)))
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert result[0].status == "processed"
    finally:
        pipeline.close()


def test_chunking_preserves_page_numbers():
    pages = [
        {"page": 1, "text": "Alpha " * 80},
        {"page": 2, "text": "Bravo " * 80},
    ]
    chunks = build_chunks(
        pages,
        "",
        {"chunk_chars": 220, "overlap_chars": 30, "min_chunk_chars": 20},
    )
    assert len(chunks) >= 4
    assert {chunk.page for chunk in chunks} == {1, 2}
    assert all(chunk.text for chunk in chunks)


def test_lexical_search_returns_source_and_chunk(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "drones.txt").write_text(
        "FPV drones are used for reconnaissance and logistics attacks.", encoding="utf-8"
    )
    (settings.input_dir / "artillery.txt").write_text(
        "Artillery batteries conduct fire missions.", encoding="utf-8"
    )

    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
        hits = search_chunks(
            pipeline.db,
            "FPV logistics",
            settings.search,
            mode="lexical",
            limit=3,
        )
        assert hits
        assert hits[0].source_path == "drones.txt"
        assert hits[0].backend == "lexical"
    finally:
        pipeline.close()


class FakeEncoder:
    def encode(self, texts):
        vectors = []
        for text in texts:
            normalized = text.casefold()
            if any(term in normalized for term in ("fpv", "drone", "unmanned", "бпла")):
                vectors.append([1.0, 0.0])
            elif "artillery" in normalized:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.5, 0.5])
        return vectors


def test_semantic_index_and_search_with_injected_encoder(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "drones.txt").write_text(
        "FPV drone teams operate close to the front.", encoding="utf-8"
    )
    (settings.input_dir / "artillery.txt").write_text(
        "Artillery fire is coordinated by observers.", encoding="utf-8"
    )

    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
        indexed = build_embeddings(pipeline.db, settings.search, encoder=FakeEncoder())
        assert indexed >= 2
        hits = search_chunks(
            pipeline.db,
            "unmanned aircraft tactics",
            settings.search,
            mode="semantic",
            encoder=FakeEncoder(),
            limit=2,
        )
        assert hits[0].source_path == "drones.txt"
        assert hits[0].backend == "semantic"
        assert hits[0].score > hits[1].score
    finally:
        pipeline.close()


def test_v01_document_is_automatically_reprocessed_for_v02_chunks(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "legacy.txt"
    source.write_text("legacy fpv report", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        first = pipeline.process_file(source)
        assert first.status == "processed"
        with pipeline.db._lock:
            pipeline.db.conn.execute(
                "UPDATE documents SET pipeline_version=1 WHERE sha256=?", (first.sha256,)
            )
            pipeline.db.conn.execute(
                "DELETE FROM chunks WHERE document_sha256=?", (first.sha256,)
            )
            pipeline.db.conn.commit()
        second = pipeline.process_file(source)
        assert second.status == "processed"
        assert pipeline.db.stats()["chunks"] >= 1
    finally:
        pipeline.close()


def test_auto_search_falls_back_when_semantic_index_is_partial(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "one.txt").write_text("fpv drone logistics", encoding="utf-8")
    (settings.input_dir / "two.txt").write_text("artillery observer", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
        rows = pipeline.db.chunks_for_embedding(settings.search["model"])
        assert len(rows) >= 2
        vector = FakeEncoder().encode([rows[0]["text"]])[0]
        from osint_local.search import _normalize_vector, _vector_to_blob

        normalized = _normalize_vector(vector)
        pipeline.db.save_embeddings(
            [(rows[0]["id"], settings.search["model"], len(normalized), _vector_to_blob(normalized))]
        )
        hits = search_chunks(
            pipeline.db,
            "fpv logistics",
            settings.search,
            mode="auto",
            encoder=FakeEncoder(),
        )
        assert hits
        assert hits[0].backend == "lexical"
    finally:
        pipeline.close()


def test_web_ui_dashboard_search_document_and_range_source(tmp_path: Path):
    import urllib.request
    from osint_local.web import create_server

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "drones.txt"
    source.write_text("FPV drones support logistics reconnaissance.", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        result = pipeline.process_file(source)
        assert result.status == "processed"
        server = create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
            assert "OSINT Local" in body
            assert "Drones" in body

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/search?q=fpv+logistics&mode=lexical", timeout=5
        ) as response:
            body = response.read().decode("utf-8")
            assert "drones.txt" in body
            assert "Context" in body

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/documents/{result.sha256}", timeout=5
        ) as response:
            body = response.read().decode("utf-8")
            assert "Open source file" in body
            assert "Extracted chunks" in body

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/source/{result.sha256}",
            headers={"Range": "bytes=0-2"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 206
            assert response.read() == b"FPV"

        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/search?q=fpv&mode=lexical", timeout=5
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert payload["results"][0]["source_path"] == "drones.txt"
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()
