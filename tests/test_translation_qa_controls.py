from __future__ import annotations

import io
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib import error, parse, request

import pytest

from osint_local.config import load_settings, update_config
from osint_local.pipeline import LocalPipeline
from osint_local.search import SearchHit, build_embeddings


@pytest.fixture
def pipeline(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "allowed_extensions": [".txt"],
        "performance": {"profile": "economy"},
        "ocr": {"enabled": False},
        "background": {"enabled": False, "auto_index": False},
        "search": {"semantic_enabled": False, "model": "test-model"},
        "translation": {"engine": "fast", "fast_page_batch": 1, "fast_text_batch": 1},
    }), encoding="utf-8")
    instance = LocalPipeline(load_settings(config))
    instance.settings.input_dir.mkdir(parents=True, exist_ok=True)
    yield instance
    instance.close()


@pytest.fixture
def web_server(pipeline, monkeypatch):
    import osint_local.web as web

    monkeypatch.setattr(web, "ollama_models", lambda *a, **k: ["qwen3:1.7b", "test-local:8b"])
    server = web.create_server(pipeline, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def post(base, path, data):
    req = request.Request(base + path, data=parse.urlencode(data).encode(),
                          headers={"X-Requested-With": "fetch"}, method="POST")
    with request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_passive_toggle_persists_and_keeps_existing_translation(web_server, pipeline):
    server, base = web_server
    source = pipeline.settings.input_dir / "saved.txt"
    source.write_text("This English report describes infrastructure maintenance.", encoding="utf-8")
    doc = pipeline.process_file(source)
    from osint_local.translation import translate_document
    saved = translate_document(pipeline.settings, pipeline.db, doc.sha256, source_lang="en",
                               translator=lambda text, a, b: "Готовый перевод")
    saved_bytes = Path(saved["output_path"]).read_bytes()
    for enabled in (False, True):
        payload = post(base, "/settings/passive-translation", {
            "csrf": server.csrf_token, "enabled": str(enabled).lower(),
        })
        assert payload["passive_translation_enabled"] is enabled
        assert server.settings.translation["passive_enabled"] is enabled
        assert pipeline.settings.translation["passive_enabled"] is enabled
        assert load_settings(pipeline.settings.config_path).translation["passive_enabled"] is enabled
        assert Path(saved["output_path"]).read_bytes() == saved_bytes
        assert pipeline.db.get_translation(doc.sha256, "en", "ru")
    with request.urlopen(base + "/system", timeout=5) as response:
        html = response.read().decode("utf-8")
    assert "Passive translation" in html
    assert "/settings/passive-translation" in html
    assert "Apply model" in html


@pytest.mark.parametrize("data,status", [
    ({"csrf": "wrong", "enabled": "false"}, 403),
    ({"enabled": "sometimes"}, 400),
])
def test_passive_toggle_rejects_invalid_request(web_server, pipeline, data, status):
    server, base = web_server
    if "csrf" not in data:
        data = {**data, "csrf": server.csrf_token}
    with pytest.raises(error.HTTPError) as caught:
        post(base, "/settings/passive-translation", data)
    assert caught.value.code == status
    assert pipeline.settings.translation["passive_enabled"] is True


def test_local_model_selector_preserves_other_settings(web_server, pipeline):
    server, base = web_server
    post(base, "/settings/passive-translation", {"csrf": server.csrf_token, "enabled": "false"})
    assert post(base, "/settings/qa-model", {"csrf": server.csrf_token, "model": "test-local:8b"})["model"] == "test-local:8b"
    persisted = load_settings(pipeline.settings.config_path)
    assert persisted.qa["model"] == "test-local:8b"
    assert persisted.translation["passive_enabled"] is False
    with pytest.raises(error.HTTPError) as caught:
        post(base, "/settings/qa-model", {"csrf": server.csrf_token, "model": "not-installed"})
    assert caught.value.code == 400
    assert pipeline.settings.qa["model"] == "test-local:8b"


def test_passive_stop_keeps_fast_checkpoint_and_embeddings(pipeline, monkeypatch):
    import osint_local.fast_translation as fast
    import osint_local.translation as translation

    source = pipeline.settings.input_dir / "queued.txt"
    source.write_text("This English report discusses document translation and analysis.", encoding="utf-8")
    doc = pipeline.process_file(source)
    text_path = pipeline.settings.text_dir / f"{doc.sha256}.txt"
    text_path.write_text("--- PAGE 1 ---\nFirst paragraph.\n--- PAGE 2 ---\nSecond paragraph.", encoding="utf-8")
    build_embeddings(pipeline.db, pipeline.settings.search,
                     encoder=SimpleNamespace(encode=lambda texts: [[1.0, 0.0] for text in texts]))
    before = [row["vector"] for row in pipeline.db.iter_embeddings("test-model")]
    live_settings = [pipeline.settings]
    calls = []

    class FakeFast:
        model_id = "fake/opus"
        compute_type = "int8"
        inter_threads = intra_threads = 1

        def __init__(self, *a, **k):
            pass

        def translate_texts(self, texts):
            calls.extend(texts)
            if len(calls) == 1:
                live_settings[0] = replace(pipeline.settings, translation={**pipeline.settings.translation, "passive_enabled": False})
            return ["Перевод " + text for text in texts]

    monkeypatch.setattr(fast, "FastTranslator", FakeFast)
    monkeypatch.setattr(translation, "fast_translation_available", lambda: True)
    monkeypatch.setattr(translation, "fast_ready_pairs", lambda settings: {("en", "ru")})
    monkeypatch.setattr(translation, "fast_model_ready", lambda *a: True)
    monkeypatch.setattr(translation, "quality_translation_available", lambda: False)
    stop = lambda: not live_settings[0].translation["passive_enabled"]
    assert translation.next_passive_translation(pipeline.settings, pipeline.db,
        available_pairs=set(), should_stop=stop) is None
    assert pipeline.db.get_translation(doc.sha256, "en", "ru") is None
    assert fast._checkpoint_path(pipeline.settings, doc.sha256, "ru").is_file()
    assert calls == ["First paragraph."]
    live_settings[0] = pipeline.settings
    result = translation.next_passive_translation(pipeline.settings, pipeline.db,
        available_pairs=set(), should_stop=stop)
    assert result["source_path"] == "queued.txt"
    assert calls == ["First paragraph.", "Second paragraph."]
    assert not fast._checkpoint_path(pipeline.settings, doc.sha256, "ru").exists()
    assert [row["vector"] for row in pipeline.db.iter_embeddings("test-model")] == before


def test_maintenance_reads_live_toggle_after_analysis(pipeline, monkeypatch):
    import osint_local.actions as actions

    source = pipeline.settings.input_dir / "analysis.txt"
    source.write_text("This report records events for document analysis.", encoding="utf-8")

    def analysis(*a, **k):
        update_config(pipeline.settings.config_path, {"translation": {"passive_enabled": False}})
        pipeline.settings = load_settings(pipeline.settings.config_path)
        return {"evidence": 1}

    monkeypatch.setattr(actions, "build_corpus_evidence", analysis)
    monkeypatch.setattr(actions, "next_passive_translation", lambda *a, **k: pytest.fail("disabled translation started"))
    result = actions.ActionManager(pipeline)._run_maintenance()
    assert result["analysis"] == {"evidence": 1}
    assert result["translated"] == []


def quality_engine(results):
    from osint_local.quality_translation import QualityTranslator

    engine = object.__new__(QualityTranslator)
    engine.source_lang, engine.target_lang = "en", "ru"
    engine.max_input_tokens, engine.segment_tokens, engine.batch_tokens = 480, 240, 1024
    engine.sp = SimpleNamespace(encode=lambda text, **k: text.split(), decode=lambda tokens: " ".join(tokens))
    engine.translator = SimpleNamespace(translate_batch=lambda *a, **k: results)
    return engine


@pytest.mark.parametrize("results,detail", [
    ([], "incomplete batch"),
    ([SimpleNamespace(hypotheses=[])], "empty segment"),
    ([SimpleNamespace(hypotheses=[["__ru__", "</s>"]])], "empty segment"),
    ([SimpleNamespace(hypotheses=[["Слово"] * 64])], "decoding limit"),
])
def test_quality_rejects_partial_outputs(results, detail):
    with pytest.raises(RuntimeError, match=detail):
        quality_engine(results)._translate_raw("Hello world.")


def test_quality_removes_model_control_tokens():
    engine = quality_engine([SimpleNamespace(hypotheses=[["__ru__", "Привет", "мир", "</s>", "<pad>"]])])
    assert engine._translate_raw("Hello world.") == "Привет мир"


def test_quality_keeps_form_fillers_and_numeric_cells_without_inference():
    engine = quality_engine([])
    assert engine.translate_text("________________") == "________________"
    assert engine.translate_text("01.09.2026") == "01.09.2026"


def test_quality_counts_untranslated_prose_as_warning():
    engine = quality_engine([SimpleNamespace(hypotheses=[["This is the original English sentence without translation."]])])
    engine.literal_segment_fallbacks = 0
    assert "English" in engine.translate_text("This is the original English sentence without translation.")
    assert engine.quality_warnings == 1


def test_quality_self_test_rejects_unchanged_english(pipeline, monkeypatch, tmp_path):
    import sys
    import osint_local.quality_translation as quality

    engine = quality_engine([SimpleNamespace(hypotheses=[["Hello world."]])])
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(Translator=lambda *a, **k: engine.translator))
    monkeypatch.setattr(quality, "_load_sentencepiece", lambda path: engine.sp)
    with pytest.raises(RuntimeError, match="did not return Russian"):
        quality._validate_quality_model_files(pipeline.settings, tmp_path)
    assert not (tmp_path / quality.QUALITY_VALIDATION_FILE).exists()


def test_quality_empty_output_does_not_replace_saved_translation(pipeline, monkeypatch):
    import osint_local.translation as translation

    source = pipeline.settings.input_dir / "quality.txt"
    source.write_text("This English source needs a complete translation.", encoding="utf-8")
    doc = pipeline.process_file(source)
    saved = translation.translate_document(pipeline.settings, pipeline.db, doc.sha256,
        source_lang="en", translator=lambda *a: "Существующий перевод")
    path = Path(saved["output_path"])
    previous = path.read_bytes()
    monkeypatch.setattr(translation, "quality_translation_available", lambda: True)
    monkeypatch.setattr(translation, "quality_model_ready", lambda settings: True)
    monkeypatch.setattr(translation, "QualityTranslator", lambda *a: SimpleNamespace(translate_texts=lambda texts: [""]))
    with pytest.raises(RuntimeError, match="empty text"):
        translation.translate_document(pipeline.settings, pipeline.db, doc.sha256, source_lang="en", engine="quality")
    assert path.read_bytes() == previous
    assert pipeline.db.get_translation(doc.sha256, "en", "ru")["engine"] == "custom"


def hit(doc="a", text="Evidence text.", index=0):
    return SearchHit(1.0, "hybrid", doc * 64, f"{doc}.pdf", 1, index, text)


def test_ask_budget_keeps_question_and_multiple_documents(monkeypatch):
    import osint_local.qa as qa

    hits = [hit(text="Служебная строка. " * 1000 + "ИНФРАСТРУКТУРА: факт A."),
            hit("b", "Infrastructure: fact B."), hit("c", "Infrastructure: fact C.")]
    monkeypatch.setattr(qa, "search_chunks", lambda *a, **k: hits)
    captured = {}

    def client(base, model, messages):
        captured["messages"] = messages
        return "Сопоставление [1] [2] [3]."

    result = qa.ask_documents(object(), "ИНФРАСТРУКТУРА", {},
        {"model": "test", "num_ctx": 2048, "max_context_chars": 2000, "max_answer_tokens": 256},
        analysis_mode="compare", chat_client=client)
    assert len(result.sources) == 3
    assert "ИНФРАСТРУКТУРА" in result.sources[0].text
    messages = captured["messages"]
    assert qa._estimate_tokens("".join(m["content"] for m in messages)) + 256 + 128 <= 2048
    assert "Вопрос:\nИНФРАСТРУКТУРА" in messages[1]["content"]
    assert result.warnings
    assert len(result.sources[0].text) < len(hits[0].text)


def test_ask_deduplicates_repeated_passages_and_diversifies():
    from osint_local.qa import _diversify_hits

    text = " ".join(f"word{i}" for i in range(100))
    hits = [hit(text=text), hit(text=text, index=1), hit(text=text + " suffix", index=2),
            hit(text="Different passage", index=3), hit("b", text), hit("c", text)]
    selected = _diversify_hits(hits, 4, max_per_document=2)
    assert [item.document_sha256[0] for item in selected] == ["a", "b", "c", "a"]
    assert [item.chunk_index for item in selected if item.document_sha256.startswith("a")] == [0, 3]


def test_ask_missing_sources_never_calls_model(monkeypatch):
    import osint_local.qa as qa

    monkeypatch.setattr(qa, "search_chunks", lambda *a, **k: [])
    result = qa.ask_documents(object(), "Вопрос?", {}, {}, filters={"language": "uk"},
        chat_client=lambda *a: pytest.fail("model called without evidence"))
    assert not result.sources
    assert "не найдены" in result.answer
    assert "фильтрах" in result.answer


@pytest.mark.parametrize("answer,expected", [
    ("Факт [99].", "отсутствующие"), ("Факт без ссылки.", "не привела ссылок"),
])
def test_ask_marks_missing_or_invalid_citations(monkeypatch, answer, expected):
    import osint_local.qa as qa

    monkeypatch.setattr(qa, "search_chunks", lambda *a, **k: [hit()])
    result = qa.ask_documents(object(), "Что сказано?", {}, {"model": "test"}, chat_client=lambda *a: answer)
    assert any(expected in warning for warning in result.warnings)


def test_qa_links_only_valid_references_and_escapes_evidence():
    from osint_local.qa import QAResult
    from osint_local.web_ui import _qa_answer

    result = QAResult("Вопрос", "Ответ [1] [99] <script>bad()</script>", "test", [hit(text="<img src=x onerror=bad()>")])
    html = _qa_answer(result)
    assert 'href="#qa-source-1"' in html
    assert 'href="#qa-source-99"' not in html
    assert 'id="qa-source-1"' in html
    assert "&lt;script&gt;" in html and "&lt;img" in html
    assert "<script>" not in html and "<img " not in html


def test_ollama_receives_reserved_answer_budget_and_reports_model_error(monkeypatch):
    import osint_local.qa as qa

    captured = {}

    def open_request(req, **kwargs):
        captured.update(json.loads(req.data))
        raise error.HTTPError(req.full_url, 404, "not found", {}, io.BytesIO(b'{"error":"model test not found"}'))

    monkeypatch.setattr(qa.request, "urlopen", open_request)
    with pytest.raises(RuntimeError, match="model test not found"):
        qa._ollama_chat("http://127.0.0.1:11434", "test", [], {"num_ctx": 4096, "max_answer_tokens": 512})
    assert captured["options"]["num_predict"] == 512
    assert captured["options"]["temperature"] == 0.1
