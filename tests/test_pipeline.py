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
    assert settings.qa["model"] == "qwen3:1.7b"
    assert settings.qa["num_ctx"] == 4096
    assert settings.qa["think"] is False
    assert settings.qa["keep_alive"] == 0


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
    text = "--- PAGE 1 ---\n" + ("Alpha " * 80) + "\n\n--- PAGE 2 ---\n" + ("Bravo " * 80)
    chunks = build_chunks(
        text,
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
            assert "Read" in body

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


def test_web_ui_process_now_action_csrf_and_activity(tmp_path: Path):
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
        assert "Process now" in body
        assert "Activity" in body
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match
        csrf = match.group(1)

        bad = urllib.request.Request(
            base + "/actions/maintenance",
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
            base + "/actions/maintenance",
            data=urllib.parse.urlencode({"csrf": csrf}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            assert response.status == 202
            assert payload["action"]["kind"] == "maintenance"

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
            assert "Library updated" in body
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
        assert pipeline.db.translation_document_count(target_lang="ru") == 1
        assert pipeline.db.stats()["translations_ru"] == 1
        assert progress[-1][0] == progress[-1][1]
    finally:
        pipeline.close()


def test_translation_default_folder_is_sibling_of_input(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    assert settings.translations_dir == settings.input_dir.parent / "translations"



def test_translation_restricted_to_english_or_ukrainian_to_russian(tmp_path: Path):
    import pytest
    from osint_local.translation import translate_document

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "english.txt"
    source.write_text("English source document.", encoding="utf-8")
    pipeline = LocalPipeline(settings)
    try:
        processed = pipeline.process_file(source)
        with pytest.raises(RuntimeError, match="English→Russian"):
            translate_document(
                settings, pipeline.db, processed.sha256,
                source_lang="en", target_lang="uk",
                translator=lambda text, src, dst: text,
            )
    finally:
        pipeline.close()


def test_passive_translation_processes_only_one_document_per_cycle(tmp_path: Path):
    from osint_local.translation import next_passive_translation

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "one.txt").write_text("English drone report one.", encoding="utf-8")
    (settings.input_dir / "two.txt").write_text("English drone report two.", encoding="utf-8")
    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
        first = next_passive_translation(
            settings, pipeline.db,
            translator=lambda text, src, dst: "RU " + text,
            available_pairs={("en", "ru")},
        )
        assert first is not None
        translated_after_first = sum(len(pipeline.db.list_translations(row["sha256"])) for row in pipeline.db.list_documents(limit=10))
        assert translated_after_first == 1
        second = next_passive_translation(
            settings, pipeline.db,
            translator=lambda text, src, dst: "RU " + text,
            available_pairs={("en", "ru")},
        )
        assert second is not None
        translated_after_second = sum(len(pipeline.db.list_translations(row["sha256"])) for row in pipeline.db.list_documents(limit=10))
        assert translated_after_second == 2
    finally:
        pipeline.close()


def test_reader_aligns_original_and_russian_translation_by_page(tmp_path: Path):
    from osint_local.reader import load_reader
    from osint_local.translation import translate_document

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "paged.txt"
    source.write_text("--- PAGE 1 ---\nEnglish page one.\n\n--- PAGE 2 ---\nEnglish page two.", encoding="utf-8")
    pipeline = LocalPipeline(settings)
    try:
        processed = pipeline.process_file(source)
        translate_document(
            settings, pipeline.db, processed.sha256,
            source_lang="en", target_lang="ru",
            translator=lambda text, src, dst: "РУ " + text,
        )
        reader = load_reader(settings, pipeline.db, processed.sha256, 2)
        assert reader.selected is not None
        assert reader.selected.page == 2
        assert "English page two" in reader.selected.original
        assert "РУ" in (reader.selected.translation or "")
    finally:
        pipeline.close()


def test_qa_uses_retrieved_document_sources_with_local_client(tmp_path: Path):
    from osint_local.qa import ask_documents

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "qa.txt"
    source.write_text("FPV drones are used for reconnaissance and logistics observation.", encoding="utf-8")
    pipeline = LocalPipeline(settings)
    try:
        processed = pipeline.process_file(source)
        assert processed.status == "processed"
        captured = {}

        def fake_chat(base_url, model, messages):
            captured["model"] = model
            captured["messages"] = messages
            return "FPV drones are used for reconnaissance [1]."

        progress_events = []
        result = ask_documents(
            pipeline.db,
            "What are FPV drones used for?",
            settings.search,
            {"base_url": "http://127.0.0.1:11434", "model": "fake-local", "top_k": 4, "max_context_chars": 5000},
            chat_client=fake_chat,
            progress=progress_events.append,
        )
        assert "[1]" in result.answer
        assert result.sources[0].source_path == "qa.txt"
        assert captured["model"] == "fake-local"
        assert "qa.txt" in captured["messages"][1]["content"]
        assert progress_events == ["searching", "reviewing", "generating", "done"]
    finally:
        pipeline.close()


def test_background_maintenance_scans_without_parallel_user_action(tmp_path: Path):
    import time
    from osint_local.actions import ActionManager

    config = json.loads(make_config(tmp_path).read_text(encoding="utf-8"))
    config["background"] = {"enabled": True, "interval_seconds": 120, "auto_index": False}
    config["translation"] = {"passive_enabled": False}
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    settings = load_settings(cfg)
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "passive.txt").write_text("fpv drone passive", encoding="utf-8")
    pipeline = LocalPipeline(settings)
    try:
        manager = ActionManager(pipeline)
        state = manager.start_maintenance()
        assert state["kind"] == "maintenance"
        deadline = time.time() + 5
        state = manager.snapshot()
        while state["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            state = manager.snapshot()
        assert state["status"] == "succeeded"
        assert pipeline.db.document_count() == 1
    finally:
        pipeline.close()


def test_failed_document_is_retried_on_next_scan(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "retry.txt"
    source.write_text("fpv retry test", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        stat = source.stat()
        sha256 = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
        pipeline.db.upsert_processing(
            sha256=sha256,
            source_path="retry.txt",
            source_size=stat.st_size,
            source_mtime_ns=stat.st_mtime_ns,
            extension=".txt",
        )
        pipeline.db.mark_error(sha256, "synthetic failure")
        assert pipeline.db.error_count() == 1
        assert pipeline.db.find_current_source("retry.txt", stat.st_size, stat.st_mtime_ns) is None
        result = pipeline.process_file(source)
        assert result.status == "processed"
        assert pipeline.db.error_count() == 0
    finally:
        pipeline.close()


def test_web_ask_runs_in_background_and_preserves_result(tmp_path: Path, monkeypatch):
    import re
    import time
    import urllib.parse
    import urllib.request

    import osint_local.web as web
    from osint_local.qa import QAResult
    from osint_local.search import SearchHit

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        hit = SearchHit(
            score=1.0,
            backend="lexical",
            document_sha256="a" * 64,
            source_path="qa.txt",
            page=1,
            chunk_index=0,
            text="FPV drones are mentioned in reconnaissance context.",
        )

        def fake_ask(db, question, search_config, qa_config, *, progress=None, **kwargs):
            if progress:
                progress("searching")
                progress("generating")
            time.sleep(0.05)
            if progress:
                progress("done")
            return QAResult(question, "Test answer [1].", "fake-local", [hit])

        monkeypatch.setattr(web, "ask_documents", fake_ask)
        server = web.create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/ask", timeout=5) as response:
            body = response.read().decode("utf-8")
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match
        csrf = match.group(1)

        request = urllib.request.Request(
            base + "/api/ask",
            data=urllib.parse.urlencode({"csrf": csrf, "q": "What about FPV?"}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            state = json.loads(response.read().decode("utf-8"))
            assert response.status == 202
            assert state["status"] == "running"

        deadline = time.time() + 5
        state = {"status": "running"}
        while state["status"] == "running" and time.time() < deadline:
            with urllib.request.urlopen(base + "/api/ask-status", timeout=5) as response:
                state = json.loads(response.read().decode("utf-8"))
            time.sleep(0.02)

        assert state["status"] == "succeeded"
        assert "Test answer" in state["html"]
        assert "qa.txt" in state["html"]

        with urllib.request.urlopen(base + "/api/ask-status", timeout=5) as response:
            persisted = json.loads(response.read().decode("utf-8"))
        assert persisted["status"] == "succeeded"
        assert persisted["html"] == state["html"]
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_v08_performance_profiles_migrate_and_apply(tmp_path: Path):
    from osint_local.config import performance_profile_patch, update_config

    config = make_config(tmp_path)
    settings = load_settings(config)
    assert settings.performance["profile"] == "economy"
    assert settings.search["batch_size"] == 12
    assert settings.background["interval_seconds"] == 90
    assert settings.translation["max_per_cycle"] == 1
    assert settings.qa["top_k"] == 5
    assert settings.qa["keep_alive"] == 0

    update_config(config, performance_profile_patch("balanced"))
    settings = load_settings(config)
    assert settings.performance["profile"] == "balanced"
    assert settings.search["batch_size"] == 32
    assert settings.background["interval_seconds"] == 60
    assert settings.translation["max_per_cycle"] == 2
    assert settings.qa["top_k"] == 6
    assert settings.qa["keep_alive"] == "5m"


def test_v08_translation_queue_reports_ready_and_translated(tmp_path: Path):
    from osint_local.translation import translation_queue_status, translate_document

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "english.txt").write_text(
        "English FPV drone logistics report.", encoding="utf-8"
    )
    (settings.input_dir / "ukrainian.txt").write_text(
        "Український звіт про дрони і логістику.", encoding="utf-8"
    )
    (settings.input_dir / "russian.txt").write_text(
        "Русский отчет о беспилотниках и логистике.", encoding="utf-8"
    )

    pipeline = LocalPipeline(settings)
    try:
        pipeline.scan()
        english = next(
            row for row in pipeline.db.list_documents(limit=20)
            if row["source_path"] == "english.txt"
        )
        translate_document(
            settings,
            pipeline.db,
            english["sha256"],
            source_lang="en",
            target_lang="ru",
            translator=lambda text, src, dst: "РУ " + text,
        )
        queue = translation_queue_status(
            settings,
            pipeline.db,
            available_pairs={("en", "ru"), ("uk", "ru")},
        )
        assert queue["eligible"] == 2
        assert queue["translated"] == 1
        assert queue["ready"] == 1
        assert queue["pending"] == 1
        assert queue["blocked"] == 0
        assert queue["russian"] == 1
    finally:
        pipeline.close()


def test_v08_web_can_switch_profile_and_render_system_status(tmp_path: Path, monkeypatch):
    import re
    import urllib.parse
    import urllib.request
    import osint_local.web as web

    config = make_config(tmp_path)
    settings = load_settings(config)
    settings.input_dir.mkdir(parents=True)
    (settings.input_dir / "status.txt").write_text(
        "English FPV status document.", encoding="utf-8"
    )
    pipeline = LocalPipeline(settings)
    pipeline.scan()
    server = None
    thread = None
    try:
        monkeypatch.setattr(web, "ollama_models", lambda *args, **kwargs: ["qwen3:1.7b"])
        monkeypatch.setattr(web, "argos_available", lambda: False)
        monkeypatch.setattr(
            web,
            "translation_queue_status",
            lambda *args, **kwargs: {
                "scanned": 1,
                "eligible": 1,
                "translated": 0,
                "pending": 1,
                "ready": 0,
                "blocked": 1,
                "russian": 0,
                "unknown": 0,
                "pairs": [],
            },
        )

        server = web.create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/settings", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert "Performance profile" in body
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match

        request = urllib.request.Request(
            base + "/settings/performance",
            data=urllib.parse.urlencode(
                {"csrf": match.group(1), "profile": "balanced"}
            ).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["profile"] == "balanced"
        assert server.settings.performance["profile"] == "balanced"
        assert server.settings.translation["max_per_cycle"] == 2

        with urllib.request.urlopen(base + "/system", timeout=5) as response:
            system_body = response.read().decode("utf-8")
        assert "Translation queue" in system_body
        assert "Index queue" in system_body
        assert "Balanced" in system_body
        assert "qwen3:1.7b" in system_body
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_qa_compare_mode_diversifies_document_sources(tmp_path: Path, monkeypatch):
    import osint_local.qa as qa
    from osint_local.search import SearchHit

    hits = [
        SearchHit(1.0, "hybrid", "a" * 64, "a.txt", 1, 0, "Alpha one."),
        SearchHit(0.9, "hybrid", "a" * 64, "a.txt", 2, 1, "Alpha two."),
        SearchHit(0.8, "hybrid", "a" * 64, "a.txt", 3, 2, "Alpha three."),
        SearchHit(0.7, "hybrid", "b" * 64, "b.txt", 1, 0, "Beta one."),
        SearchHit(0.6, "hybrid", "c" * 64, "c.txt", 1, 0, "Gamma one."),
    ]
    monkeypatch.setattr(qa, "search_chunks", lambda *args, **kwargs: hits)

    class DummyDB:
        pass

    captured = {}

    def fake_chat(base_url, model, messages):
        captured["messages"] = messages
        return "Comparison [1] [3]."

    result = qa.ask_documents(
        DummyDB(),
        "Compare the reports",
        {},
        {
            "base_url": "http://127.0.0.1:11434",
            "model": "fake-local",
            "top_k": 3,
            "max_context_chars": 12000,
        },
        analysis_mode="compare",
        chat_client=fake_chat,
    )
    assert result.mode == "compare"
    assert len({hit.document_sha256 for hit in result.sources}) >= 3
    assert "Сравни сведения" in captured["messages"][0]["content"]


def test_qa_contradictions_mode_uses_cautious_instruction(tmp_path: Path, monkeypatch):
    import osint_local.qa as qa
    from osint_local.search import SearchHit

    monkeypatch.setattr(
        qa,
        "search_chunks",
        lambda *args, **kwargs: [
            SearchHit(1.0, "hybrid", "a" * 64, "a.txt", 1, 0, "Claim A."),
            SearchHit(0.9, "hybrid", "b" * 64, "b.txt", 1, 0, "Claim B."),
        ],
    )

    captured = {}

    def fake_chat(base_url, model, messages):
        captured["system"] = messages[0]["content"]
        return "No clear contradiction."

    result = qa.ask_documents(
        object(),
        "Есть ли противоречия?",
        {},
        {
            "base_url": "http://127.0.0.1:11434",
            "model": "fake-local",
            "top_k": 5,
            "max_context_chars": 8000,
        },
        analysis_mode="contradictions",
        chat_client=fake_chat,
    )
    assert result.mode == "contradictions"
    assert "Не называй обычные различия формулировок противоречием" in captured["system"]


def test_web_ask_page_exposes_analysis_modes(tmp_path: Path):
    import urllib.request
    from osint_local.web import create_server

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        server = create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ask", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert 'value="quick"' in body
        assert 'value="deep"' in body
        assert 'value="compare"' in body
        assert 'value="contradictions"' in body
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_language_is_backfilled_for_existing_documents(tmp_path: Path):
    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "legacy.txt"
    source.write_text("English legacy FPV report.", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    try:
        processed = pipeline.process_file(source)
        pipeline.db.conn.execute(
            "UPDATE documents SET language=NULL WHERE sha256=?",
            (processed.sha256,),
        )
        pipeline.db.conn.commit()
    finally:
        pipeline.close()

    reopened = LocalPipeline(settings)
    try:
        row = reopened.db.get_document(processed.sha256)
        assert row["language"] == "en"
    finally:
        reopened.close()


def test_general_chat_is_separate_from_document_retrieval(monkeypatch):
    import osint_local.chat as chat

    captured = {}

    def fake_ollama(base_url, model, messages, qa_config):
        captured["messages"] = messages
        return "Обычный локальный ответ."

    monkeypatch.setattr(chat, "_ollama_chat", fake_ollama)
    result = chat.chat_local(
        "Расскажи про Python",
        [{"role": "user", "content": "Привет"}, {"role": "assistant", "content": "Здравствуйте"}],
        {"base_url": "http://127.0.0.1:11434", "model": "fake-local"},
    )
    assert result.answer == "Обычный локальный ответ."
    assert result.model == "fake-local"
    system = captured["messages"][0]["content"]
    assert "нет доступа к библиотеке документов" in system
    assert "нет доступа" in system
    assert captured["messages"][-1]["content"] == "Расскажи про Python"


def test_web_chat_keeps_and_clears_history(tmp_path: Path, monkeypatch):
    import re
    import time
    import urllib.parse
    import urllib.request

    import osint_local.web as web
    from osint_local.chat import ChatResult

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        monkeypatch.setattr(
            web,
            "chat_local",
            lambda message, history, qa_config: ChatResult(
                answer="Ответ на: " + message,
                model="fake-local",
            ),
        )
        server = web.create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/chat", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert "does not search documents" in body
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match
        csrf = match.group(1)

        req = urllib.request.Request(
            base + "/api/chat",
            data=urllib.parse.urlencode({"csrf": csrf, "message": "Привет"}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 202

        deadline = time.time() + 5
        state = {"status": "running"}
        while state["status"] == "running" and time.time() < deadline:
            with urllib.request.urlopen(base + "/api/chat-status", timeout=5) as response:
                state = json.loads(response.read().decode("utf-8"))
            time.sleep(0.02)

        assert state["status"] == "succeeded"
        assert "Привет" in state["html"]
        assert "Ответ на: Привет" in state["html"]
        assert len(state["history"]) == 2

        req = urllib.request.Request(
            base + "/api/chat-clear",
            data=urllib.parse.urlencode({"csrf": csrf}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            cleared = json.loads(response.read().decode("utf-8"))
        assert cleared["history"] == []
        assert cleared["status"] == "idle"
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_web_ask_filters_are_passed_to_retrieval(tmp_path: Path, monkeypatch):
    import re
    import time
    import urllib.parse
    import urllib.request

    import osint_local.web as web
    from osint_local.qa import QAResult
    from osint_local.search import SearchHit

    settings = load_settings(make_config(tmp_path))
    (settings.input_dir / "reports").mkdir(parents=True)
    source = settings.input_dir / "reports" / "english.txt"
    source.write_text("FPV English report.", encoding="utf-8")
    pipeline = LocalPipeline(settings)
    pipeline.scan()
    doc = pipeline.db.list_documents(limit=10)[0]
    captured = {}
    server = None
    thread = None

    def fake_ask(db, question, search_config, qa_config, *, analysis_mode="quick", filters=None, progress=None, **kwargs):
        captured["filters"] = filters or {}
        if progress:
            progress("done")
        hit = SearchHit(1.0, "lexical", doc["sha256"], doc["source_path"], 1, 0, "FPV English report.")
        return QAResult(question, "Filtered answer [1].", "fake-local", [hit], analysis_mode)

    try:
        monkeypatch.setattr(web, "ask_documents", fake_ask)
        server = web.create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/ask", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert "Last 30 days" in body
        assert "Specific documents" in body
        assert "English" in body
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        assert match

        payload = {
            "csrf": match.group(1),
            "q": "FPV?",
            "mode": "quick",
            "period": "30",
            "domain": "Drones",
            "folder": "reports",
            "language": "en",
            "documents": doc["sha256"],
        }
        req = urllib.request.Request(
            base + "/api/ask",
            data=urllib.parse.urlencode(payload).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 202

        deadline = time.time() + 5
        while "filters" not in captured and time.time() < deadline:
            time.sleep(0.02)

        filters = captured["filters"]
        assert filters["domain"] == "Drones"
        assert filters["source_prefix"] == "reports"
        assert filters["language"] == "en"
        assert filters["document_sha256s"] == [doc["sha256"]]
        assert isinstance(filters["date_from_ns"], int)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_fast_translation_resumes_from_saved_section_checkpoint(tmp_path: Path, monkeypatch):
    import osint_local.fast_translation as fast

    settings = load_settings(make_config(tmp_path))
    calls = []
    fail_once = {"value": True}

    class FakeFastTranslator:
        model_id = "fake/opus"
        compute_type = "int8"
        inter_threads = 1
        intra_threads = 2

        def __init__(self, settings, source_lang, target_lang="ru"):
            self.model_id = "fake/opus"
            self.compute_type = "int8"
            self.inter_threads = 1
            self.intra_threads = 2

        def translate_texts(self, texts):
            calls.append(list(texts))
            if fail_once["value"] and len(calls) == 2:
                raise RuntimeError("synthetic interruption")
            return ["RU " + value for value in texts]

    monkeypatch.setattr(fast, "FastTranslator", FakeFastTranslator)
    sections = [(1, "page one"), (2, "page two"), (3, "page three")]
    try:
        fast.translate_sections_fast(
            settings,
            "a" * 64,
            sections,
            "en",
            "ru",
        )
        assert False, "first run should be interrupted"
    except RuntimeError as exc:
        assert "synthetic interruption" in str(exc)

    assert len(calls) == 2
    fail_once["value"] = False
    translated, stats = fast.translate_sections_fast(
        settings,
        "a" * 64,
        sections,
        "en",
        "ru",
    )
    assert [page for page, _ in translated] == [1, 2, 3]
    assert translated[0][1] == "RU page one"
    assert stats.pages_translated == 2
    assert len(calls) == 4


def test_translation_waits_while_interactive_work_is_active():
    import threading
    import time

    from osint_local.translation import _translate_sections_legacy

    gate = threading.Event()
    gate.set()
    translated_calls = []

    def translator(text, src, dst):
        translated_calls.append(text)
        return "RU " + text

    result = {}

    def run():
        result["value"] = _translate_sections_legacy(
            [(1, "first page")],
            "en",
            "ru",
            translator,
            1800,
            should_pause=gate.is_set,
        )

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.1)
    assert translated_calls == []
    gate.clear()
    thread.join(timeout=2)
    assert translated_calls == ["first page"]
    assert result["value"][0][1] == "RU first page"


def test_chat_marks_interactive_gate_until_generation_finishes(tmp_path: Path, monkeypatch):
    import threading
    import time

    import osint_local.web as web
    from osint_local.chat import ChatResult

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    pipeline = LocalPipeline(settings)
    server = None
    entered = threading.Event()
    release = threading.Event()

    def fake_chat(message, history, qa_config):
        entered.set()
        release.wait(2)
        return ChatResult("done", "fake-local")

    try:
        monkeypatch.setattr(web, "chat_local", fake_chat)
        server = web.create_server(pipeline, "127.0.0.1", 0)
        server.chat.start("hello")
        assert entered.wait(1)
        assert server.interactive.active() is True
        release.set()

        deadline = time.time() + 2
        while server.chat.snapshot()["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
        assert server.chat.snapshot()["status"] == "succeeded"
        assert server.interactive.active() is False
    finally:
        release.set()
        if server is not None:
            server.server_close()
        pipeline.close()


def test_web_can_start_fast_translation_model_setup(tmp_path: Path, monkeypatch):
    import re
    import time
    import urllib.parse
    import urllib.request

    import osint_local.web as web

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    pipeline = LocalPipeline(settings)
    server = None
    thread = None

    def fake_prepare(settings, source_lang, target_lang="ru", *, progress=None, run_benchmark=True):
        if progress:
            progress(0, 0, "Preparing fake model…")
        return {
            "ready": True,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "model": "fake/opus",
            "benchmark": {"estimated_pages_per_minute": 25.0},
        }

    try:
        monkeypatch.setattr(web, "fast_translation_available", lambda: True)
        monkeypatch.setattr(web, "prepare_fast_model", fake_prepare)
        server = web.create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with urllib.request.urlopen(base + "/system", timeout=5) as response:
            body = response.read().decode("utf-8")
        csrf = re.search(r'name="csrf" value="([^"]+)"', body).group(1)

        req = urllib.request.Request(
            base + "/actions/prepare-fast-translation",
            data=urllib.parse.urlencode({"csrf": csrf, "source_lang": "en"}).encode(),
            headers={"X-Requested-With": "fetch"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert response.status == 202
        assert payload["action"]["kind"] == "translation-setup"

        deadline = time.time() + 2
        state = server.fast_setup.snapshot()
        while state["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            state = server.fast_setup.snapshot()
        assert state["status"] == "succeeded"
        assert state["result"]["source_lang"] == "en"
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_fast_translation_setup_can_start_while_maintenance_is_running(tmp_path: Path, monkeypatch):
    import threading
    import time

    import osint_local.web as web

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    pipeline = LocalPipeline(settings)
    server = None
    maintenance_entered = threading.Event()
    release_maintenance = threading.Event()
    prepare_entered = threading.Event()

    def fake_maintenance():
        maintenance_entered.set()
        release_maintenance.wait(2)
        return {
            "files_seen": 0,
            "counts": {},
            "embedded_chunks": 0,
            "translated": [],
        }

    def fake_prepare(settings, source_lang, target_lang="ru", *, progress=None, run_benchmark=True):
        prepare_entered.set()
        if progress:
            progress(1, 1, "Fast Translation ready")
        return {
            "ready": True,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "model": "fake/opus",
        }

    try:
        monkeypatch.setattr(web, "prepare_fast_model", fake_prepare)
        server = web.create_server(pipeline, "127.0.0.1", 0)
        monkeypatch.setattr(server.actions, "_run_maintenance", fake_maintenance)

        server.actions.start_maintenance()
        assert maintenance_entered.wait(1)
        assert server.actions.snapshot()["status"] == "running"
        assert server.actions.snapshot()["kind"] == "maintenance"

        state = server.fast_setup.start("en")
        assert state["status"] == "running"
        assert prepare_entered.wait(1)

        deadline = time.time() + 2
        state = server.fast_setup.snapshot()
        while state["status"] == "running" and time.time() < deadline:
            time.sleep(0.02)
            state = server.fast_setup.snapshot()

        assert state["status"] == "succeeded"
        assert state["result"]["source_lang"] == "en"
        assert server.actions.snapshot()["status"] == "running"
    finally:
        release_maintenance.set()
        if server is not None:
            server.server_close()
        pipeline.close()


def test_translation_http_response_declares_utf8_and_preserves_cyrillic(tmp_path: Path):
    import threading
    import urllib.request

    from osint_local.translation import translate_document
    from osint_local.web import create_server

    settings = load_settings(make_config(tmp_path))
    settings.input_dir.mkdir(parents=True)
    source = settings.input_dir / "ukrainian.txt"
    source.write_text("Тестовий український документ.", encoding="utf-8")

    pipeline = LocalPipeline(settings)
    server = None
    thread = None
    try:
        processed = pipeline.process_file(source)
        result = translate_document(
            settings,
            pipeline.db,
            processed.sha256,
            source_lang="uk",
            target_lang="ru",
            translator=lambda text, src, dst: "Русский перевод — проверка кодировки",
        )
        assert Path(result["output_path"]).read_text(encoding="utf-8").startswith("# Translation —")

        server = create_server(pipeline, "127.0.0.1", 0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        url = f"http://127.0.0.1:{port}/translation/{processed.sha256}/uk/ru"
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.headers.get_content_type() == "text/markdown"
            assert response.headers.get_content_charset() == "utf-8"
            body = response.read().decode("utf-8")
        assert "Translation —" in body
        assert "Русский перевод — проверка кодировки" in body
        assert "â€”" not in body
        assert "Ð" not in body
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
        pipeline.close()


def test_prepare_fast_model_repairs_missing_tokenizer_assets_without_reconversion(tmp_path: Path, monkeypatch):
    import osint_local.fast_translation as fast

    settings = load_settings(make_config(tmp_path))
    model_dir = fast.fast_model_dir(settings, "uk", "ru")
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "model.bin").write_bytes(b"converted-weights")
    (model_dir / "config.json").write_text("{}", encoding="utf-8")

    cache_dir = tmp_path / "hf-cache"
    cache_dir.mkdir()
    (cache_dir / "source.spm").write_bytes(b"source-tokenizer")
    (cache_dir / "target.spm").write_bytes(b"target-tokenizer")

    downloads = []

    def fake_download(model_id, filename):
        downloads.append((model_id, filename))
        return cache_dir / filename

    monkeypatch.setattr(fast, "fast_translation_available", lambda: True)
    monkeypatch.setattr(fast, "_download_model_asset", fake_download)

    result = fast.prepare_fast_model(
        settings,
        "uk",
        "ru",
        run_benchmark=False,
    )

    assert result["ready"] is True
    assert (model_dir / "model.bin").read_bytes() == b"converted-weights"
    assert (model_dir / "source.spm").read_bytes() == b"source-tokenizer"
    assert (model_dir / "target.spm").read_bytes() == b"target-tokenizer"
    assert [filename for _, filename in downloads] == ["source.spm", "target.spm"]
    assert fast.fast_model_ready(settings, "uk", "ru") is True


def test_sentencepiece_loader_uses_bytes_for_unicode_windows_paths(tmp_path: Path):
    import osint_local.fast_translation as fast

    tokenizer_dir = tmp_path / "проекты" / "модели"
    tokenizer_dir.mkdir(parents=True)
    tokenizer_path = tokenizer_dir / "source.spm"
    tokenizer_path.write_bytes(b"serialized-sentencepiece-model")

    seen = {}

    class FakeProcessor:
        def LoadFromSerializedProto(self, payload):
            seen["payload"] = payload
            return True

    class FakeSpm:
        SentencePieceProcessor = FakeProcessor

    processor = fast._load_sentencepiece_processor(FakeSpm, tokenizer_path)

    assert isinstance(processor, FakeProcessor)
    assert seen["payload"] == b"serialized-sentencepiece-model"
