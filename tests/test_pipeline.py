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


def test_action_manager_scan_reports_progress(tmp_path: Path):
    import time
    from osint_local.actions import ActionManager

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "action.txt").write_text("fpv drone " * 30, encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        manager = ActionManager(pipeline)
        started = manager.start_scan()
        assert started["status"] == "running"
        deadline = time.time() + 5
        state = manager.snapshot()
        while state["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            state = manager.snapshot()
        assert state["status"] == "succeeded"
        assert state["result"]["files_seen"] == 1
        assert state["result"]["counts"]["processed"] == 1
        assert pipeline.db.document_count() == 1
    finally:
        pipeline.close()


def test_embedding_progress_callback(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "semantic.txt").write_text("fpv drone " * 80, encoding="utf-8")

    pipeline = LocalPipeline(settings)
    progress = []
    try:
        pipeline.scan()
        count = build_embeddings(
            pipeline.db,
            settings.search,
            encoder=FakeEncoder(),
            progress=lambda current, total: progress.append((current, total)),
        )
        assert count > 0
        assert progress[0][0] == 0
        assert progress[-1][0] == progress[-1][1] == count
    finally:
        pipeline.close()


def test_web_ui_scan_action_csrf_and_activity(tmp_path: Path):
    import re
    import time
    import urllib.error
    import urllib.parse
    import urllib.request
    from osint_local.web import create_server

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "from-ui.txt").write_text("fpv drone logistics " * 20, encoding="utf-8")

    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        server = create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert "Build index" in body
        assert "Activity" in body
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match
        csrf = match.group(1)

        bad = urllib.request.Request(
            base + "/actions/scan",
            data=urllib.parse.urlencode({"csrf": "bad"}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        try:
            urllib.request.urlopen(bad, timeout=5)
            assert False, "invalid CSRF should fail"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403

        request = urllib.request.Request(
            base + "/actions/scan",
            data=urllib.parse.urlencode({"csrf": csrf}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 202
            assert payload["action"]["kind"] == "scan"

        deadline = time.time() + 5
        activity = {"action": {"status": "running"}}
        while activity["action"]["status"] == "running" and time.time() < deadline:
            with urllib.request.urlopen(base + "/api/activity", timeout=5) as response:
                activity = json.loads(response.read().decode("utf-8"))
            time.sleep(0.02)
        assert activity["action"]["status"] == "succeeded"
        assert activity["stats"]["documents"] == 1

        with urllib.request.urlopen(base + "/", timeout=5) as response:
            body = response.read().decode("utf-8")
            assert "from-ui.txt" in body
            assert "Scan complete" in body
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()



def test_update_config_persists_input_dir_and_setup(tmp_path: Path):
    from osint_local.config import update_config

    config = make_config(tmp_path)
    chosen = tmp_path / "documents"
    chosen.mkdir()
    update_config(config, {"input_dir": str(chosen), "ui": {"setup_complete": True}})
    settings = load_settings(config)
    assert settings.input_dir == chosen.resolve()
    assert settings.ui["setup_complete"] is True


def test_web_settings_can_change_document_folder(tmp_path: Path):
    import re
    import urllib.parse
    import urllib.request
    from osint_local.web import create_server

    config = make_config(tmp_path)
    settings = load_settings(config)
    settings.input_dir.mkdir(parents=True)
    chosen = tmp_path / "new-documents"
    chosen.mkdir()

    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        server = create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/settings", timeout=5) as response:
            body = response.read().decode("utf-8")
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match
        csrf = match.group(1)

        request = urllib.request.Request(
            base + "/settings/input-dir",
            data=urllib.parse.urlencode({"csrf": csrf, "input_dir": str(chosen)}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 200
            assert Path(payload["input_dir"]) == chosen.resolve()

        assert server.settings.input_dir == chosen.resolve()
        assert pipeline.settings.input_dir == chosen.resolve()
        saved = json.loads(config.read_text(encoding="utf-8"))
        assert Path(saved["input_dir"]) == chosen.resolve()
        assert saved["ui"]["setup_complete"] is True
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_web_open_folder_uses_injected_opener(tmp_path: Path):
    import re
    import urllib.parse
    import urllib.request
    from osint_local.web import create_server

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    opened = []
    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        server = create_server(
            pipeline,
            "127.0.0.1",
            0,
            folder_opener=lambda path: opened.append(Path(path)),
            folder_picker=lambda path: None,
        )
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/", timeout=5) as response:
            body = response.read().decode("utf-8")
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match
        request = urllib.request.Request(
            base + "/actions/open-folder",
            data=urllib.parse.urlencode({"csrf": match.group(1)}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        assert opened == [settings.input_dir]
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()



def test_cli_serve_first_run_creates_setup_config(tmp_path: Path, monkeypatch):
    import sys
    import osint_local.cli as cli
    import osint_local.web as web

    config = tmp_path / "config.json"
    monkeypatch.setattr(sys, "argv", ["osint-local", "--config", str(config), "serve", "--no-open"])
    monkeypatch.setattr(web, "serve", lambda pipeline, **kwargs: None)
    assert cli.main() == 0
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved["ui"]["setup_complete"] is False
    assert (tmp_path / "inbox").is_dir()
    assert (tmp_path / "workspace").is_dir()


def test_index_state_reports_stale_and_current():
    from osint_local.web_ui import _index_state

    stale = _index_state(
        semantic_available=True,
        semantic_enabled=True,
        embedding_count=3,
        chunk_count=5,
    )
    current = _index_state(
        semantic_available=True,
        semantic_enabled=True,
        embedding_count=5,
        chunk_count=5,
    )
    assert stale[0].startswith("Index update needed")
    assert stale[1] == "Update index"
    assert current == ("Index current", "Index current", True)


def test_translation_saves_separate_page_aware_markdown(tmp_path: Path):
    from osint_local.translation import translate_document

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "manual.txt"
    source.write_text("English FPV report for translation.", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    progress = []
    try:
        processed = pipeline.process_file(source)
        assert processed.status == "processed"
        result = translate_document(
            settings,
            pipeline.db,
            processed.sha256,
            source_lang="en",
            target_lang="ru",
            translator=lambda text, src, dst: "ПЕРЕВОД: " + text,
            progress=lambda current, total, message: progress.append((current, total, message)),
        )
        output = Path(result["output_path"])
        assert output.is_file()
        assert output.parent == settings.translations_dir / "ru"
        assert output != source
        assert "ПЕРЕВОД:" in output.read_text(encoding="utf-8")
        rows = pipeline.db.list_translations(processed.sha256)
        assert rows[0]["target_lang"] == "ru"
        assert progress[-1][0] == progress[-1][1]
    finally:
        pipeline.close()


def test_translation_default_folder_is_sibling_of_input(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    assert settings.translations_dir == settings.input_dir.parent / "translations"
