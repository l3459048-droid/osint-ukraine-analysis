from __future__ import annotations

import html
import json
from urllib.parse import urlencode

def _layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)} · OSINT Local</title>
<style>{CSS}</style>
</head>
<body>
<header class="topbar"><a class="brand" href="/">OSINT Local <span>v0.9.19</span></a><nav>
<a href="/search">Search</a><a href="/ask">Ask</a><a href="/chat">Chat</a><a href="/documents">Documents</a><a href="/taxonomy">Corpus</a><a href="/system">System</a><a href="/settings">Settings</a>
</nav></header>
<main>{body}</main>
<footer>Local-first · source files stay on this computer</footer>
<script>{UI_SCRIPT}</script>
</body>
</html>"""


def _hero() -> str:
    return """<section class="hero"><div><div class="eyebrow">LOCAL KNOWLEDGE BASE</div>
<h1>Your document archive, ready to search.</h1>
<p>Scan local files, build the optional semantic index, and search everything from one local screen.</p>
</div></section>"""


def _page_header(title: str, subtitle: str) -> str:
    return f'<section class="page-head"><h1>{_e(title)}</h1><p>{_e(subtitle)}</p></section>'


def _stat_card(label, value) -> str:
    return f'<div class="stat"><div class="stat-value">{_e(value)}</div><div class="stat-label">{_e(label)}</div></div>'


def _search_form(q: str, mode: str, limit: int) -> str:
    options = "".join(
        f'<option value="{name}"{" selected" if name == mode else ""}>{label}</option>'
        for name, label in (("auto", "Auto"), ("hybrid", "Hybrid"), ("lexical", "Lexical"), ("semantic", "Semantic"))
    )
    return f"""<form class="search-form" action="/search" method="get">
<input name="q" value="{_e(q)}" placeholder="Search documents…" autofocus>
<select name="mode">{options}</select>
<input class="limit" name="limit" type="number" min="1" max="100" value="{int(limit)}" aria-label="Limit">
<button type="submit">Search</button></form>"""



def _index_state(*, semantic_available: bool, semantic_enabled: bool, embedding_count: int, chunk_count: int) -> tuple[str, str, bool]:
    if not semantic_enabled:
        return "Semantic disabled", "Build index", True
    if not semantic_available:
        return "Semantic unavailable", "Build index", True
    if chunk_count == 0:
        return "No content to index", "Build index", True
    if embedding_count <= 0:
        return "Index not built", "Build index", False
    if embedding_count < chunk_count:
        return f"Index update needed · {embedding_count}/{chunk_count}", "Update index", False
    return "Index current", "Index current", True


def _action_panel(
    csrf_token: str,
    action: dict,
    *,
    semantic_available: bool,
    semantic_ready: bool,
    semantic_enabled: bool,
    embedding_count: int,
    chunk_count: int,
    input_dir,
    background_enabled: bool = True,
    background_interval: int = 60,
) -> str:
    running = action.get("status") == "running"
    current = int(action.get("current") or 0)
    total = int(action.get("total") or 0)
    percent = int((current / total) * 100) if total else 0
    status = action.get("message") or "Ready"
    if running and total:
        status = f"{status} · {current}/{total}"
    index_status, _, _ = _index_state(
        semantic_available=semantic_available,
        semantic_enabled=semantic_enabled,
        embedding_count=embedding_count,
        chunk_count=chunk_count,
    )
    buttons_disabled = " disabled" if running else ""
    automation = (
        f"Automatic · every {int(background_interval)}s"
        if background_enabled
        else "Automatic processing off"
    )
    return f"""<section class="action-panel" data-action-panel>
<div class="action-copy"><strong>Library</strong><span data-action-status>{_e(status)}</span></div>
<div class="action-buttons">
<form action="/actions/maintenance" method="post" data-action-form><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit"{buttons_disabled}>Process now</button></form>
<form action="/actions/open-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="ghost-action" type="submit">Folder</button></form>
<a class="button ghost" href="/settings">Settings</a>
</div>
<div class="action-meta"><span>{_e(automation)} · {_e(index_status)}</span><span class="path-note" title="{_e(input_dir)}">{_e(input_dir)}</span></div>
<div class="progress-track{' running' if running and not total else ''}" aria-hidden="true"><span data-action-progress style="width:{percent}%"></span></div>
</section>"""

def _setup_panel(csrf_token: str, input_dir) -> str:
    return f"""<section class="setup-panel">
<div><div class="eyebrow">FIRST RUN</div><h2>Choose your document folder</h2><p>OSINT Local reads this folder recursively. Your originals stay untouched.</p></div>
<div class="setup-actions">
<form action="/settings/pick-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit">Choose folder</button></form>
<form class="path-form" action="/settings/input-dir" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><input name="input_dir" value="{_e(input_dir)}" aria-label="Document folder"><button class="secondary" type="submit">Save path</button></form>
</div></section>"""


def _settings_panel(
    csrf_token: str,
    input_dir,
    workspace_dir,
    translations_dir=None,
    *,
    semantic_available: bool,
    semantic_enabled: bool,
    embedding_count: int,
    chunk_count: int,
    background_enabled: bool = True,
    background_interval: int = 120,
    passive_translation: bool = True,
    qa_base_url: str = "http://127.0.0.1:11434",
    performance_profile: str = "economy",
    performance_profiles: dict | None = None,
) -> str:
    index_status, _, _ = _index_state(
        semantic_available=semantic_available,
        semantic_enabled=semantic_enabled,
        embedding_count=embedding_count,
        chunk_count=chunk_count,
    )
    profiles = performance_profiles or {}
    options = "".join(
        f'<option value="{_e(name)}"{" selected" if name == performance_profile else ""}>{_e(item.get("label", name.title()))}</option>'
        for name, item in profiles.items()
    )
    selected = profiles.get(performance_profile, {})
    profile_note = selected.get("description", "")
    return f"""<section class="panel settings-panel">
<div class="settings-row"><div><span class="setting-label">Documents</span><strong>{_e(input_dir)}</strong><p>Source files are read-only.</p></div><div class="settings-actions"><form action="/settings/pick-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit">Choose folder</button></form><form action="/actions/open-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="secondary" type="submit">Open</button></form></div></div>
<form class="settings-path" action="/settings/input-dir" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><input name="input_dir" value="{_e(input_dir)}"><button class="secondary" type="submit">Save path</button></form>
<div class="settings-row"><div><span class="setting-label">Performance profile</span><strong>{_e(selected.get("label", performance_profile.title()))}</strong><p>{_e(profile_note)}</p></div><div class="settings-actions"><form class="profile-form" action="/settings/performance" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><select name="profile">{options}</select><button type="submit">Apply</button></form></div></div>
<div class="settings-row"><div><span class="setting-label">Workspace</span><strong>{_e(workspace_dir)}</strong><p>Database, extracted text and index. Managed automatically.</p></div></div>
<div class="settings-row"><div><span class="setting-label">Semantic index</span><strong>{_e(index_status)}</strong><p>{embedding_count} embeddings for {chunk_count} chunks.</p></div></div>
<div class="settings-row"><div><span class="setting-label">Translations</span><strong>{_e(translations_dir or "translations")}</strong><p>Only English/Ukrainian → Russian. Originals are never changed.</p></div><div class="settings-actions"><form action="/actions/open-translations" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="secondary" type="submit">Open</button></form></div></div>
<div class="settings-row"><div><span class="setting-label">Automatic processing</span><strong>{"On" if background_enabled else "Off"}</strong><p>Checks for new/changed files, updates the index and translates up to the profile limit every {int(background_interval)}s{"" if passive_translation else " (translation disabled)"}.</p></div></div>
<div class="settings-row"><div><span class="setting-label">Local Q&A</span><strong>{_e(qa_base_url)}</strong><p>Questions use retrieved document fragments and a local Ollama model.</p></div></div>
</section>"""


def _system_panel(status: dict, csrf_token: str) -> str:
    queue = status.get("translation_queue") or {}
    ollama_models = status.get("ollama_models") or []
    pairs = queue.get("pairs") or []
    fast_pairs = set(queue.get("fast_pairs") or [])
    fast_available = bool(queue.get("fast_available"))
    benchmarks = queue.get("fast_benchmarks") or {}
    action = status.get("action") or {}
    translation = status.get("translation") or {}
    fast_setup = status.get("fast_setup") or {}
    quality_setup = status.get("quality_setup") or {}
    quality_ready = bool(queue.get("quality_ready"))
    quality_available = bool(queue.get("quality_available"))
    quality_benchmark = queue.get("quality_benchmark") or {}
    current_activity = translation if translation.get("status") in {"running", "failed"} else action
    action_message = current_activity.get("error") or current_activity.get("message") or "Ready"
    fast_message = fast_setup.get("error") or fast_setup.get("message") or ""
    quality_message = quality_setup.get("error") or quality_setup.get("message") or ""
    semantic = "Ready" if status.get("semantic_available") else "Not installed"
    ollama = "Ready" if status.get("ollama_reachable") else "Unavailable"
    tesseract = status.get("tesseract") or "Not found"
    model_text = ", ".join(ollama_models) if ollama_models else "No local models detected"
    pair_text = ", ".join(pairs) if pairs else "No EN/UK → RU pair installed"
    background_state = "Paused for interactive work" if status.get("interactive_busy") else (
        "On" if status.get("background_enabled") else "Off"
    )

    def fast_pair(lang: str, label: str) -> str:
        pair = f"{lang}->ru"
        ready = pair in fast_pairs
        benchmark = benchmarks.get(lang) or {}
        if ready and benchmark:
            ppm = benchmark.get("estimated_pages_per_minute")
            hundred = benchmark.get("estimated_100_pages_minutes")
            detail = f"Benchmark: ~{ppm} pages/min · 100 pages ~{hundred} min"
        elif ready:
            detail = "INT8 model ready. Benchmark will appear after setup/benchmark."
        else:
            detail = "One-time download + INT8 conversion required."
        if ready:
            button = '<span class="ready-mark">Ready</span>'
        elif fast_available:
            button = (
                f'<form class="fast-setup-form" action="/actions/prepare-fast-translation" method="post" data-fast-setup>'
                f'<input type="hidden" name="csrf" value="{_e(csrf_token)}">'
                f'<input type="hidden" name="source_lang" value="{lang}">'
                '<button type="submit">Prepare</button></form>'
            )
        else:
            button = '<span class="panel-subtle">Run updater</span>'
        return (
            '<div class="fast-pair"><div><strong>' + _e(label) + ' → Russian</strong>'
            '<small>' + _e(detail) + '</small></div>' + button + '</div>'
        )

    quality_detail = "One-time ~2 GB model download + INT8 conversion required."
    if quality_ready:
        quality_detail = "M2M100 418M INT8 ready for suspicious segments."
        quality_row = quality_benchmark.get("quality") or {}
        fast_row = quality_benchmark.get("fast") or {}
        if quality_row:
            quality_detail += (
                f" Reference similarity {quality_row.get('mean_reference_similarity', 'n/a')}"
                f" · {quality_row.get('chars_per_second', 'n/a')} chars/s."
            )
        if fast_row:
            quality_detail += (
                f" OPUS reference similarity {fast_row.get('mean_reference_similarity', 'n/a')}."
            )

    if quality_ready:
        quality_button = '<span class="ready-mark">Ready</span>'
    elif quality_available:
        quality_button = (
            f'<form class="fast-setup-form" action="/actions/prepare-quality-translation" method="post" data-quality-setup>'
            f'<input type="hidden" name="csrf" value="{_e(csrf_token)}">'
            '<button type="submit">Prepare Quality</button></form>'
        )
    else:
        quality_button = '<span class="panel-subtle">Run updater</span>'

    return f"""<section class="stats-grid">
{_stat_card("Documents", status.get("documents", 0))}
{_stat_card("Index queue", status.get("index_pending", 0))}
{_stat_card("Translation queue", queue.get("pending", 0))}
{_stat_card("Errors", status.get("errors", 0))}
</section>
<section class="panel system-panel">
<div class="panel-head"><div><h2>Processing</h2><span class="panel-subtle">{_e(status.get("performance_label") or status.get("performance_profile") or "Economy")}</span></div>
<form action="/actions/maintenance" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit">Process now</button></form></div>
<div class="system-grid">
<div><span>Current activity</span><strong>{_e(action_message)}</strong><small>{_e(current_activity.get("kind") or "idle")} · {_e(current_activity.get("status") or "idle")}</small></div>
<div><span>Semantic search</span><strong>{_e(semantic)}</strong><small>{status.get("embedding_count", 0)}/{status.get("chunks", 0)} chunks embedded</small></div>
<div><span>Translation</span><strong>{queue.get("translated", 0)} translated · {queue.get("pending", 0)} pending</strong><small>{_e(pair_text)}{f' · {queue.get("blocked", 0)} blocked' if queue.get("blocked") else ""}</small></div>
<div><span>Ollama</span><strong>{_e(ollama)}</strong><small>{_e(model_text)}</small></div>
<div><span>OCR / Tesseract</span><strong>{_e("Ready" if status.get("tesseract") else "Not found")}</strong><small>{_e(tesseract)}</small></div>
<div><span>Automatic cycle</span><strong>{_e(background_state)}</strong><small>Every {int(status.get("background_interval", 0))}s</small></div>
<div><span>Adaptive taxonomy</span><strong>{int(status.get("taxonomy_categories", 0))} categories · {int(status.get("taxonomy_topics", 0))} topics</strong><small>{"Rebuild needed" if status.get("taxonomy_stale") else "Current"} · <a href="/taxonomy">Open Corpus</a></small></div>
</div>
</section>
<section class="panel fast-translation-panel">
<div class="panel-head"><div><h2>Fast Translation</h2><span class="panel-subtle">CTranslate2 INT8 · batched CPU translation</span></div></div>
<div class="fast-status" data-fast-status>{_e(fast_message if fast_setup.get("status") in {"running", "failed"} else "")}</div>
{fast_pair("en", "English")}
{fast_pair("uk", "Ukrainian")}
<div class="ask-filter-note">After a pair is prepared, automatic translation prefers Fast Translation. Chat and Ask pause translation at safe batch boundaries.</div>
</section>
<section class="panel fast-translation-panel">
<div class="panel-head"><div><h2>Quality Translation</h2><span class="panel-subtle">M2M100 418M · CTranslate2 INT8 · manual Quality or Auto fallback</span></div></div>
<div class="fast-status" data-quality-status>{_e(quality_message if quality_setup.get("status") in {"running", "failed"} else "")}</div>
<div class="fast-pair"><div><strong>English / Ukrainian → Russian</strong><small>{_e(quality_detail)}</small></div>{quality_button}</div>
<div class="ask-filter-note">Manual Quality translates the full document with M2M100. Auto keeps OPUS as the fast path and loads Quality only after the quality gate rejects a segment. Protected dates, numbers, URLs and neutral codes are restored exactly before scoring.</div>
</section>"""

def _translation_panel(
    csrf_token: str,
    sha256: str,
    translations,
    *,
    available: bool,
    pairs: set[tuple[str, str]],
    quality_ready: bool,
    source_extension: str = "",
    action: dict,
) -> str:
    running_here = (
        action.get("status") == "running"
        and action.get("kind") == "translate"
        and action.get("sha256") == sha256
    )
    useful_pairs = sorted(pair for pair in pairs if pair in {("en", "ru"), ("uk", "ru")})
    pair_note = ", ".join(f"{a}→ru" for a, _ in useful_pairs) if useful_pairs else "EN→RU / UK→RU models not installed yet"
    disabled = " disabled" if running_here else ""
    source_options = "".join(
        f'<option value="{code}"{" selected" if code == "auto" else ""}>{label}</option>'
        for code, label in (("auto", "Auto"), ("en", "English"), ("uk", "Ukrainian"))
    )
    default_engine = "quality" if quality_ready else "auto"
    engine_options = "".join(
        f'<option value="{code}"{" selected" if code == default_engine else ""}>{label}</option>'
        for code, label in (
            ("auto", "Auto · Fast + quality gate"),
            ("quality", "Quality · M2M100 418M"),
            ("fast", "Fast · OPUS"),
        )
    )
    rows = []
    for row in translations:
        if row["target_lang"] != "ru":
            continue
        pdf_link = (
            f'<a class="translation-export" href="/translation-export/{_e(sha256)}/{_e(row["source_lang"])}/ru/pdf-layout" download>PDF · layout</a>'
            if str(source_extension or "").casefold() == ".pdf"
            else ""
        )
        rows.append(
            f'<div class="translation-entry">'
            f'<a class="translation-item" href="/translation/{_e(sha256)}/{_e(row["source_lang"])}/ru" target="_blank">'
            f'<span>{_e(row["source_lang"])} → ru</span><small>{_e((row["created_at"] or "")[:19])} · {_e(row["engine"] or "unknown")}</small></a>'
            f'<a class="translation-export" href="/translation-export/{_e(sha256)}/{_e(row["source_lang"])}/ru/docx" download>DOCX</a>'
            f'{pdf_link}'
            f'</div>'
        )
    saved = "".join(rows) if rows else '<span class="translation-empty">No Russian translation saved yet.</span>'
    availability = "Offline engine ready" if available else "Install optional offline translation support"
    status = action.get("message") if running_here else ""
    return f"""<section class="panel translation-panel" data-translation-panel>
<div class="panel-head"><div><h2>Translate to Russian</h2><span class="panel-subtle">{_e(availability)} · {_e(pair_note)}</span></div><form action="/actions/open-translations" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="tiny-button" type="submit">Folder</button></form></div>
<form class="translation-form" action="/actions/translate" method="post">
<input type="hidden" name="csrf" value="{_e(csrf_token)}"><input type="hidden" name="sha256" value="{_e(sha256)}"><input type="hidden" name="target_lang" value="ru">
<label>From<select name="source_lang">{source_options}</select></label><span class="translation-arrow">→</span>
<label>To<span class="fixed-target">Russian</span></label>
<label>Engine<select name="engine">{engine_options}</select></label>
<button type="submit"{disabled}>Translate</button>
</form>
<div class="ask-filter-note">For important documents choose Quality. Auto keeps OPUS fast and invokes Quality only when the quality gate detects a problem. Protected dates, numbers, URLs and neutral codes remain exact. For PDFs, a Quality re-translation also creates the block map required by PDF · layout export.</div>
<div class="translation-status">{_e(status)}</div>
<div class="translation-list">{saved}</div>
</section>"""


def _ask_form(
    question: str,
    csrf_token: str = "",
    analysis_mode: str = "quick",
    *,
    categories=None,
    taxonomy_categories=None,
    taxonomy_topics=None,
    folders=None,
    documents=None,
) -> str:
    modes = (
        ("quick", "Быстро"),
        ("deep", "Глубокий анализ"),
        ("compare", "Сравнить документы"),
        ("contradictions", "Найти противоречия"),
    )
    mode_options = "".join(
        f'<option value="{name}"{" selected" if name == analysis_mode else ""}>{label}</option>'
        for name, label in modes
    )
    category_options = '<option value="">All rule-based categories</option>' + "".join(
        f'<option value="{_e(row["domain"])}">{_e(row["domain"])} ({int(row["documents"])})</option>'
        for row in (categories or [])
    )
    taxonomy_category_options = '<option value="">All adaptive categories</option>' + "".join(
        f'<option value="{_e(row["category_key"])}">{_e(row["name"])} ({int(row["document_count"])})</option>'
        for row in (taxonomy_categories or [])
    )
    taxonomy_topic_options = '<option value="">All discovered topics</option>' + "".join(
        f'<option value="{_e(row["topic_key"])}">{_e(row["name"])} ({int(row["document_count"])})</option>'
        for row in (taxonomy_topics or [])
    )
    folder_options = '<option value="">All folders</option>' + "".join(
        f'<option value="{_e(folder)}">{_e(folder)}</option>' for folder in (folders or [])
    )
    document_options = "".join(
        f'<option value="{_e(row["sha256"])}">{_e(row["source_path"])}</option>'
        for row in (documents or [])
    ) or '<option value="" disabled>No documents available</option>'
    return f"""<form class="ask-form" action="/api/ask" method="post" data-ask-form>
<input type="hidden" name="csrf" value="{_e(csrf_token)}">
<input type="hidden" name="documents" value="" data-documents-value>
<textarea name="q" rows="3" placeholder="Ask across your documents…">{_e(question)}</textarea>
<div class="ask-side"><select name="mode" aria-label="Analysis mode">{mode_options}</select><button type="submit">Ask</button></div>
<details class="ask-filters">
<summary>Filters <span>date · category · folder · documents · language</span></summary>
<div class="ask-filter-grid">
<label>Period<select name="period"><option value="">Any time</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last year</option></select></label>
<label>From<input type="date" name="date_from"></label>
<label>To<input type="date" name="date_to"></label>
<label>Rule category<select name="domain">{category_options}</select></label>
<label>Adaptive category<select name="taxonomy_category">{taxonomy_category_options}</select></label>
<label>Topic<select name="taxonomy_topic">{taxonomy_topic_options}</select></label>
<label>Folder<select name="folder">{folder_options}</select></label>
<label>Language<select name="language"><option value="">Any language</option><option value="en">English</option><option value="uk">Ukrainian</option><option value="ru">Russian</option></select></label>
<label class="ask-documents">Specific documents<select name="documents_multi" multiple size="6" data-documents-select>{document_options}</select></label>
</div>
<div class="ask-filter-note">Date filters use the source file modification date. Adaptive categories/topics come from the Corpus taxonomy. Custom From/To dates override the period shortcut. Multiple filters are combined.</div>
</details>
</form>
<div class="ask-hint">Быстро — короткий ответ · Глубокий — больше источников · Сравнение и противоречия — приоритет нескольким документам.</div>
<div class="ask-status" data-ask-status hidden></div>
<div class="ask-results" data-ask-results></div>"""


def _chat_messages(history, model: str = "", *, error: str = "") -> str:
    parts = ['<section class="panel chat-panel"><div class="panel-head"><div><h2>Conversation</h2>']
    subtitle = "Local model" + (f" · {model}" if model else "")
    parts.append(f'<span class="panel-subtle">{_e(subtitle)}</span></div></div>')
    if error:
        parts.append(f'<div class="alert">{_e(error)}</div>')
    if not history:
        parts.append('<div class="empty">No messages yet. Chat is separate from the document library and has no internet access.</div>')
    else:
        parts.append('<div class="chat-history">')
        for item in history:
            role = "assistant" if item.get("role") == "assistant" else "user"
            label = "Qwen" if role == "assistant" else "You"
            parts.append(
                f'<div class="chat-message {role}"><span>{label}</span><div>{_e(item.get("content") or "")}</div></div>'
            )
        parts.append("</div>")
    parts.append("</section>")
    return "".join(parts)


def _chat_panel(csrf_token: str, state: dict) -> str:
    history = state.get("history") or []
    html = state.get("html") or _chat_messages(history, state.get("model") or "", error=state.get("error") or "")
    return f"""<div data-chat-root>
<div class="chat-results" data-chat-results>{html}</div>
<div class="chat-status" data-chat-status{" hidden" if state.get("status") not in {"running", "failed"} else ""}>{_e(state.get("message") or "")}</div>
<form class="chat-form" action="/api/chat" method="post" data-chat-form>
<input type="hidden" name="csrf" value="{_e(csrf_token)}">
<textarea name="message" rows="3" placeholder="Напиши что-нибудь…"></textarea>
<div class="chat-actions"><button type="submit">Send</button></div>
</form>
<form action="/api/chat-clear" method="post" class="chat-clear-form" data-chat-clear>
<input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="secondary" type="submit">Clear conversation</button>
</form>
<div class="ask-filter-note">Chat uses the local Ollama model only. It does not search your documents or the internet.</div>
</div>"""


def _qa_answer(result, error: str = "", fallback_hits=None) -> str:
    parts = []
    if error:
        parts.append(f'<div class="alert">{_e(error)}</div>')
    if result is not None:
        mode_labels = {
            "quick": "Быстро",
            "deep": "Глубокий анализ",
            "compare": "Сравнение",
            "contradictions": "Противоречия",
        }
        mode_label = mode_labels.get(getattr(result, "mode", "quick"), "Быстро")
        parts.append('<section class="panel qa-answer"><div class="panel-head"><div><h2>Answer</h2><span class="panel-subtle">Local model · ' + _e(result.model) + ' · ' + _e(mode_label) + '</span></div></div>')
        parts.append(f'<div class="answer-text">{_e(result.answer)}</div></section>')
        hits = result.sources
    else:
        hits = fallback_hits or []
    if hits:
        parts.append('<section class="panel"><div class="panel-head"><h2>Sources</h2></div><div class="qa-sources">')
        for index, hit in enumerate(hits, 1):
            page = f" · p.{hit.page}" if hit.page is not None else ""
            link = f'/documents/{hit.document_sha256}' + (f'?page={hit.page}#reader' if hit.page is not None else '#reader')
            parts.append(f'<a class="qa-source" href="{link}"><b>[{index}]</b><span>{_e(hit.source_path + page)}</span></a>')
        parts.append('</div></section>')
    return "".join(parts)


def _reader_panel(sha256: str, reader, source_url: str) -> str:
    page = reader.selected
    if page is None:
        return '<section class="panel" id="reader"><div class="empty">No extracted text available.</div></section>'
    index = reader.selected_index
    prev_link = ""
    next_link = ""
    if index > 0:
        prev_page = reader.pages[index - 1].page
        prev_link = f'<a href="/documents/{sha256}' + (f'?page={prev_page}' if prev_page is not None else '') + '#reader">← Previous</a>'
    if index + 1 < len(reader.pages):
        next_page = reader.pages[index + 1].page
        next_link = f'<a href="/documents/{sha256}' + (f'?page={next_page}' if next_page is not None else '') + '#reader">Next →</a>'
    page_label = f"Page {page.page}" if page.page is not None else "Document"
    source_link = source_url + (f'#page={page.page}' if page.page is not None else '')
    translation = page.translation
    if translation:
        right = f'<pre>{_e(translation)}</pre>'
    else:
        right = '<div class="reader-empty">Russian translation is not ready yet. Passive translation will pick eligible EN/UK documents one at a time while the app is open.</div>'
    return f"""<section class="panel reader-panel" id="reader">
<div class="panel-head"><div><h2>Reader</h2><span class="panel-subtle">{_e(page_label)} · original ↔ Russian</span></div><div class="reader-nav">{prev_link}<a href="{source_link}" target="_blank" rel="noreferrer">Open source</a>{next_link}</div></div>
<div class="reader-grid"><div><div class="reader-label">Original</div><pre>{_e(page.original)}</pre></div><div><div class="reader-label">Русский</div>{right}</div></div>
</section>"""

def _activity_details(action: dict, errors: list[dict]) -> str:
    status = action.get("status") or "idle"
    kind = action.get("kind") or "—"
    message = action.get("error") or action.get("message") or "No actions yet."
    result = action.get("result")
    result_html = ""
    if result:
        result_html = f'<pre class="activity-result">{_e(json.dumps(result, ensure_ascii=False, indent=2))}</pre>'
    if errors:
        error_rows = "".join(
            f'<li><strong>{_e(row.get("source_path") or "Unknown")}</strong><span>{_e(row.get("error") or "Unknown error")}</span></li>'
            for row in errors
        )
        errors_html = f'<div class="activity-errors"><h3>Recent processing errors</h3><ul>{error_rows}</ul></div>'
    else:
        errors_html = '<div class="empty compact">No processing errors.</div>'
    return f"""<details class="activity-panel"><summary>Activity</summary>
<div class="activity-body"><div class="activity-last"><span>Last action</span><strong>{_e(kind)} · {_e(status)}</strong><p>{_e(message)}</p>{result_html}</div>{errors_html}</div>
</details>"""

def _category_list(categories: list[dict]) -> str:
    if not categories:
        return '<div class="empty">No classifications yet.</div>'
    return '<div class="category-list">' + "".join(
        f'<a href="/documents?{urlencode({"domain": row["domain"]})}"><span>{_e(row["domain"])}</span><b>{row["documents"]}</b></a>'
        for row in categories
    ) + "</div>"


def _adaptive_category_list(categories) -> str:
    if not categories:
        return '<div class="empty">No adaptive categories yet.</div>'
    return '<div class="category-list">' + "".join(
        f'<a href="/taxonomy?{urlencode({"category": row["category_key"]})}"><span>{_e(row["name"])}</span><b>{int(row["document_count"])}</b></a>'
        for row in categories
    ) + "</div>"


def _classification_badges(classes) -> str:
    if not classes:
        return '<div class="empty">No classifications.</div>'
    return '<div class="badges">' + "".join(
        f'<a class="badge" href="/documents?{urlencode({"domain": row["domain"]})}">{_e(row["domain"])} <b>{row["score"]}</b></a>'
        for row in classes
    ) + "</div>"


def _taxonomy_badges(taxonomy: dict) -> str:
    categories = taxonomy.get("categories") or []
    topics = taxonomy.get("topics") or []
    if not categories and not topics:
        return '<div class="empty">Adaptive taxonomy has not assigned this document yet.</div>'

    parts = ['<div class="badges">']
    for row in categories[:4]:
        parts.append(
            f'<a class="badge" href="/taxonomy?{urlencode({"category": row["category_key"]})}">'
            f'{_e(row["name"])} <b>{float(row["score"]):.2f}</b></a>'
        )
    for row in topics[:8]:
        parts.append(
            f'<a class="badge" href="/taxonomy?{urlencode({"topic": row["topic_key"]})}">'
            f'{_e(row["name"])} <b>{float(row["score"]):.2f}</b></a>'
        )
    parts.append("</div>")
    return "".join(parts)


def _taxonomy_panel(
    csrf_token: str,
    *,
    categories,
    topics,
    documents,
    counts: dict,
    latest_run,
    action: dict,
    selected_category: str = "",
    selected_topic: str = "",
) -> str:
    running = (
        action.get("status") == "running"
        and action.get("kind") in {"taxonomy", "maintenance"}
    )
    disabled = " disabled" if running else ""
    details = {}
    if latest_run:
        try:
            details = json.loads(latest_run["details_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            details = {}

    coverage = float(details.get("coverage") or 0.0)
    latest_text = (
        str(latest_run["finished_at"] or latest_run["started_at"] or "")
        if latest_run else "Not built yet"
    )
    status = action.get("message") if running else (
        f"Last rebuild: {latest_text}" if latest_run else "Build the semantic index, then rebuild taxonomy."
    )

    category_rows = []
    for row in categories:
        active = " active" if row["category_key"] == selected_category else ""
        category_rows.append(
            f'<a class="chip{active}" href="/taxonomy?{urlencode({"category": row["category_key"]})}">'
            f'{_e(row["name"])} · {int(row["document_count"])}</a>'
        )
    categories_html = "".join(category_rows) or '<span class="translation-empty">No adaptive categories yet.</span>'

    topic_rows = []
    for row in topics:
        active = " active" if row["topic_key"] == selected_topic else ""
        topic_rows.append(
            f'<a class="badge{active}" href="/taxonomy?{urlencode({"topic": row["topic_key"]})}">'
            f'{_e(row["name"])} <b>{int(row["document_count"])}</b></a>'
        )
    topics_html = "".join(topic_rows) or '<span class="translation-empty">No discovered topics yet.</span>'

    docs_html = _taxonomy_document_cards(documents) if documents else (
        '<div class="empty">Select a category or topic to view matching documents.</div>'
    )

    return f"""<section class="stats-grid">
{_stat_card("Adaptive categories", counts.get("categories", 0))}
{_stat_card("Discovered topics", counts.get("topics", 0))}
{_stat_card("Assigned documents", counts.get("assigned_documents", 0))}
{_stat_card("Coverage", f"{coverage * 100:.1f}%")}
</section>
<section class="panel">
<div class="panel-head"><div><h2>Adaptive Corpus Taxonomy</h2><span class="panel-subtle">{_e(status)}</span></div>
<form action="/actions/taxonomy" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit"{disabled}>Rebuild taxonomy</button></form></div>
<div class="ask-filter-note">Categories and topics are discovered from document-level semantic embeddings. Rebuilds do not re-run OCR, PDF extraction or translation. Local Qwen names clusters when available; deterministic keyword labels are used as fallback.</div>
</section>
<section class="panel"><div class="panel-head"><h2>Categories</h2><span class="panel-subtle">Broad semantic groups</span></div><div class="filters">{categories_html}</div></section>
<section class="panel"><div class="panel-head"><h2>Topics</h2><span class="panel-subtle">More specific discovered themes</span></div><div class="badges">{topics_html}</div></section>
<section class="panel"><div class="panel-head"><h2>Documents</h2><span class="panel-subtle">Selected adaptive category/topic</span></div>{docs_html}</section>"""


def _taxonomy_document_cards(rows) -> str:
    cards = []
    for row in rows:
        score = float(row["taxonomy_score"] or 0.0)
        cards.append(
            f'<a class="doc-card" href="/documents/{row["sha256"]}"><div>'
            f'<strong>{_e(row["source_path"])}</strong>'
            f'<span>semantic match {score:.3f} · {_e(row["extension"])} · {_e(row["processed_at"] or "")}</span>'
            '</div><span class="arrow">→</span></a>'
        )
    return '<div class="doc-list">' + "".join(cards) + "</div>"


def _document_cards(rows, db) -> str:
    if not rows:
        return '<div class="empty">No processed documents yet. Automatic processing will pick up supported files from the selected folder.</div>'
    cards = []
    for row in rows:
        classes = db.get_classifications(row["sha256"])
        top = classes[0]["domain"] if classes else "Unclassified"
        cards.append(
            f'<a class="doc-card" href="/documents/{row["sha256"]}"><div><strong>{_e(row["source_path"])}</strong>'
            f'<span>{_e(top)} · {_e(row["extension"])} · {_e(row["processed_at"] or "")}</span></div>'
            '<span class="arrow">→</span></a>'
        )
    return '<div class="doc-list">' + "".join(cards) + "</div>"


def _document_table(rows, db) -> str:
    if not rows:
        return '<div class="empty">No documents in this view.</div>'
    body = []
    for row in rows:
        classes = db.get_classifications(row["sha256"])
        top = classes[0]["domain"] if classes else "—"
        body.append(
            f'<tr><td><a href="/documents/{row["sha256"]}">{_e(row["source_path"])}</a></td>'
            f'<td>{_e(top)}</td><td>{_e(row["extension"])}</td><td>{row["text_chars"]}</td>'
            f'<td>{_e((row["processed_at"] or "")[:19])}</td></tr>'
        )
    return """<div class="table-wrap"><table><thead><tr><th>Document</th><th>Top category</th><th>Type</th><th>Chars</th><th>Processed</th></tr></thead><tbody>""" + "".join(body) + "</tbody></table></div>"


def _domain_filter(categories: list[dict], selected: str | None) -> str:
    links = [f'<a class="chip{" active" if not selected else ""}" href="/documents">All</a>']
    for row in categories:
        active = " active" if selected == row["domain"] else ""
        links.append(
            f'<a class="chip{active}" href="/documents?{urlencode({"domain": row["domain"]})}">{_e(row["domain"])} ({row["documents"]})</a>'
        )
    return '<div class="filters">' + "".join(links) + "</div>"


def _pagination(page: int, per_page: int, total: int, domain: str | None) -> str:
    if total <= per_page:
        return ""
    links = []
    if page > 1:
        params = {"page": page - 1}
        if domain:
            params["domain"] = domain
        links.append(f'<a class="button secondary" href="/documents?{urlencode(params)}">← Previous</a>')
    if page * per_page < total:
        params = {"page": page + 1}
        if domain:
            params["domain"] = domain
        links.append(f'<a class="button secondary" href="/documents?{urlencode(params)}">Next →</a>')
    return '<div class="pagination">' + "".join(links) + "</div>"


def _search_hit(hit) -> str:
    doc_link = f'/documents/{hit.document_sha256}' + (f'?page={hit.page}#reader' if hit.page is not None else '#reader')
    source_link = f'/source/{hit.document_sha256}' + (f'#page={hit.page}' if hit.page is not None else "")
    location = hit.source_path + (f" · page {hit.page}" if hit.page is not None else "")
    snippet = _e(" ".join(hit.text.split()))
    return f"""<article class="result">
<div class="result-meta"><span class="score">{hit.score:.4f}</span><span>{_e(hit.backend)}</span><span>{_e(location)}</span></div>
<h3><a href="{doc_link}">{_e(hit.source_path)}</a></h3>
<p>{snippet}</p>
<div class="result-actions"><a href="{doc_link}">Read</a><a href="{source_link}" target="_blank" rel="noreferrer">Source{f' · p.{hit.page}' if hit.page is not None else ''}</a></div>
</article>"""


def _chunk_card(chunk, source_url: str) -> str:
    page = chunk["page"]
    page_link = source_url + (f"#page={page}" if page is not None else "")
    page_label = f"Page {page}" if page is not None else "Document"
    return f"""<article class="chunk" id="chunk-{chunk['chunk_index']}">
<div class="chunk-head"><span>Chunk {chunk['chunk_index']}</span><a href="{page_link}" target="_blank" rel="noreferrer">{page_label}</a></div>
<pre>{_e(chunk['text'])}</pre></article>"""


def _metadata_grid(metadata: dict, doc) -> str:
    fields = [
        ("Source path", doc["source_path"]),
        ("Extension", doc["extension"]),
        ("Size", _human_bytes(doc["source_size"])),
        ("Processed", doc["processed_at"] or "—"),
        ("Extraction", doc["extraction_method"] or "—"),
        ("Language", doc["language"] or metadata.get("language") or "—"),
        ("Pages", len(metadata.get("pages") or [])),
    ]
    return '<div class="meta-grid">' + "".join(
        f'<div><span>{_e(label)}</span><strong>{_e(value)}</strong></div>' for label, value in fields
    ) + "</div>"


def _human_bytes(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _safe_json(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    return values[0] if values else ""


def _e(value) -> str:
    return html.escape(str(value), quote=True)


CSS = r"""
:root{color-scheme:dark;--bg:#0b0d10;--panel:#12161b;--panel2:#171c22;--text:#f2f5f7;--muted:#96a0aa;--line:#27303a;--accent:#7dd3fc;--accent2:#a7f3d0;--danger:#fda4af}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}.topbar{height:64px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1180px)/2));position:sticky;top:0;background:rgba(11,13,16,.94);backdrop-filter:blur(12px);z-index:10}.brand{font-weight:800;color:var(--text);text-decoration:none;font-size:18px}.brand span{font-size:11px;color:var(--accent);border:1px solid #24566b;border-radius:10px;padding:2px 6px;margin-left:5px}.topbar nav{display:flex;gap:20px}.topbar nav a,.panel-head a,.result-actions a,.chunk-head a{color:var(--muted);text-decoration:none}.topbar nav a:hover,.panel-head a:hover,.result-actions a:hover,.chunk-head a:hover{color:var(--accent)}main{max-width:1180px;margin:auto;padding:44px 24px 72px}.hero{padding:42px 0 32px}.hero h1,.page-head h1{font-size:clamp(32px,5vw,58px);letter-spacing:-.04em;line-height:1.04;margin:8px 0 14px;max-width:850px}.hero p,.page-head p{color:var(--muted);font-size:17px;max-width:780px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.16em}.page-head{margin-bottom:24px}.page-head h1{font-size:38px}.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:10px 0 24px}.stat{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:14px;padding:18px}.stat-value{font-size:27px;font-weight:800;overflow-wrap:anywhere}.stat-label{color:var(--muted);margin-top:4px}.search-form{display:grid;grid-template-columns:minmax(180px,1fr) 130px 78px 100px;gap:8px;margin:22px 0 28px}.search-form input,.search-form select,.search-form button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:12px 13px;font:inherit}.search-form input:focus,.search-form select:focus{outline:2px solid #1f607b;border-color:var(--accent)}.search-form button,.button{background:var(--accent);color:#041014!important;font-weight:800;border:0!important;text-decoration:none;border-radius:10px;padding:12px 16px;cursor:pointer;display:inline-block}.button.secondary{background:var(--panel2);color:var(--text)!important;border:1px solid var(--line)!important}.two-col{display:grid;grid-template-columns:340px 1fr;gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.panel h2{font-size:17px;margin:0}.category-list{display:flex;flex-direction:column}.category-list a{display:flex;justify-content:space-between;color:var(--text);text-decoration:none;border-top:1px solid var(--line);padding:11px 2px}.category-list a:first-child{border-top:0}.category-list b{color:var(--accent)}.doc-list{display:flex;flex-direction:column}.doc-card{display:flex;justify-content:space-between;align-items:center;gap:16px;border-top:1px solid var(--line);padding:13px 2px;color:var(--text);text-decoration:none}.doc-card:first-child{border-top:0}.doc-card strong{display:block;overflow-wrap:anywhere}.doc-card span:not(.arrow){display:block;color:var(--muted);font-size:13px;margin-top:3px}.arrow{color:var(--accent);font-size:22px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}.chip,.badge{border:1px solid var(--line);background:var(--panel);color:var(--muted);text-decoration:none;padding:7px 10px;border-radius:999px}.chip.active,.chip:hover,.badge.active,.badge:hover{color:var(--text);border-color:#456176}.badges{display:flex;gap:8px;flex-wrap:wrap}.badge b{color:var(--accent);margin-left:4px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:720px}th,td{text-align:left;border-bottom:1px solid var(--line);padding:11px 8px}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}td a{color:var(--text);text-decoration:none}td a:hover{color:var(--accent)}.results{display:flex;flex-direction:column;gap:10px}.result{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:17px}.result-meta{display:flex;gap:9px;flex-wrap:wrap;color:var(--muted);font-size:12px}.score{color:var(--accent2);font-weight:800}.result h3{margin:9px 0 6px;font-size:17px}.result h3 a{color:var(--text);text-decoration:none}.result p{margin:0;color:#d5dbe0}.result-actions{display:flex;gap:16px;margin-top:10px}.result-count{color:var(--muted);margin:-9px 0 15px}.doc-actions{display:flex;gap:8px;margin-bottom:18px}.doc-stats{margin-top:0}.meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.meta-grid div{background:var(--panel2);border-radius:9px;padding:12px;min-width:0}.meta-grid span{display:block;color:var(--muted);font-size:12px}.meta-grid strong{display:block;margin-top:3px;overflow-wrap:anywhere}.chunk{border-top:1px solid var(--line);padding:14px 0}.chunk:first-of-type{border-top:0}.chunk-head{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-bottom:8px}.chunk pre{white-space:pre-wrap;word-break:break-word;background:#0d1116;border:1px solid #202933;border-radius:10px;padding:13px;margin:0;max-height:420px;overflow:auto;color:#dce2e7;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.alert{border:1px solid #713747;background:#2a151c;color:#fecdd3;padding:13px;border-radius:10px}.empty{color:var(--muted);padding:18px 4px}.pagination{display:flex;justify-content:space-between;margin-top:16px}footer{max-width:1180px;margin:auto;padding:22px 24px 42px;color:#65717c;border-top:1px solid var(--line)}code{background:#1a2027;border-radius:5px;padding:2px 5px}@media(max-width:800px){.stats-grid{grid-template-columns:repeat(2,1fr)}.two-col{grid-template-columns:1fr}.search-form{grid-template-columns:1fr 1fr}.search-form input{grid-column:1/-1}.meta-grid{grid-template-columns:1fr 1fr}.topbar nav a:nth-last-child(-n+2){display:none}} .profile-form{display:flex;gap:8px;align-items:center}.profile-form select{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px 10px}.system-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.system-grid>div{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:13px}.system-grid span,.system-grid small{display:block;color:var(--muted);font-size:12px}.system-grid strong{display:block;margin:4px 0;overflow-wrap:anywhere}@media(max-width:700px){.system-grid{grid-template-columns:1fr}}
@media(max-width:480px){main{padding:28px 15px 52px}.topbar{padding:0 15px}.topbar nav{gap:12px}.stats-grid{grid-template-columns:1fr 1fr}.search-form{grid-template-columns:1fr}.search-form input{grid-column:auto}.meta-grid{grid-template-columns:1fr}.doc-actions{flex-direction:column}.hero{padding-top:18px}}

.action-panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:0 0 18px;display:grid;grid-template-columns:minmax(180px,1fr) auto;gap:10px 18px;align-items:center}.action-copy{display:flex;align-items:baseline;gap:12px;min-width:0}.action-copy strong{font-size:16px}.action-copy span{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.action-buttons{display:flex;align-items:center;gap:8px}.action-buttons form{margin:0}.action-buttons button{font:inherit}.action-buttons .secondary{background:var(--panel2);color:var(--text);border:1px solid var(--line)}.button.ghost{background:transparent!important;color:var(--muted)!important;border:1px solid transparent!important}.button.ghost:hover{color:var(--text)!important}.action-buttons button:disabled{opacity:.45;cursor:not-allowed}.action-meta{grid-column:1/-1;color:var(--muted);font-size:12px;display:flex;gap:12px;flex-wrap:wrap}.action-hint{color:#c0cad2}.progress-track{grid-column:1/-1;height:3px;background:#1c242c;border-radius:999px;overflow:hidden}.progress-track span{display:block;height:100%;background:var(--accent);transition:width .2s ease}.progress-track.running span{width:32%!important;animation:indeterminate 1.1s ease-in-out infinite}@keyframes indeterminate{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}.activity-panel{border:1px solid var(--line);border-radius:12px;background:var(--panel);margin:18px 0}.activity-panel summary{cursor:pointer;color:var(--muted);padding:12px 15px;user-select:none}.activity-body{border-top:1px solid var(--line);padding:15px;display:grid;grid-template-columns:1fr 1fr;gap:18px}.activity-last>span{display:block;color:var(--muted);font-size:12px}.activity-last>strong{display:block;margin-top:3px}.activity-last p{color:var(--muted);margin:7px 0}.activity-result{white-space:pre-wrap;word-break:break-word;background:#0d1116;border:1px solid #202933;border-radius:8px;padding:10px;font-size:12px}.activity-errors h3{margin:0 0 8px;font-size:13px}.activity-errors ul{list-style:none;margin:0;padding:0}.activity-errors li{border-top:1px solid var(--line);padding:8px 0}.activity-errors li:first-child{border-top:0}.activity-errors li strong,.activity-errors li span{display:block}.activity-errors li span{color:var(--muted);font-size:12px;margin-top:2px}.empty.compact{padding:4px 0}.action-error{color:var(--danger)!important}
@media(max-width:700px){.action-panel{grid-template-columns:1fr}.action-buttons{grid-column:1/-1;flex-wrap:wrap}.activity-body{grid-template-columns:1fr}}
.setup-panel{display:grid;grid-template-columns:minmax(220px,1fr) minmax(320px,1.2fr);gap:18px;align-items:center;background:linear-gradient(180deg,#121a20,var(--panel));border:1px solid #2c5365;border-radius:14px;padding:18px;margin:0 0 18px}.setup-panel h2{margin:5px 0 4px;font-size:20px}.setup-panel p,.settings-row p{margin:4px 0 0;color:var(--muted);font-size:13px}.setup-actions{display:flex;flex-direction:column;gap:8px;align-items:stretch}.setup-actions form,.settings-actions form{margin:0}.setup-actions button,.settings-panel button,.ghost-action{font:inherit;border-radius:9px;padding:10px 13px;cursor:pointer}.setup-actions button,.settings-panel button{background:var(--accent);color:#041014;border:0;font-weight:800}.setup-actions .secondary,.settings-panel .secondary{background:var(--panel2);color:var(--text);border:1px solid var(--line)}.path-form,.settings-path{display:grid;grid-template-columns:minmax(160px,1fr) auto;gap:8px}.path-form input,.settings-path input{background:#0d1116;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:10px 11px;font:inherit;min-width:0}.ghost-action{background:transparent;color:var(--muted);border:1px solid transparent}.ghost-action:hover{color:var(--text)}.path-note{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:min(620px,65vw)}.settings-panel{padding:0}.settings-row{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:17px 18px;border-top:1px solid var(--line)}.settings-row:first-child{border-top:0}.settings-row strong{display:block;overflow-wrap:anywhere}.setting-label{display:block;color:var(--muted);font-size:12px;margin-bottom:4px}.settings-actions{display:flex;gap:8px;flex-shrink:0}.settings-path{padding:0 18px 17px}.action-buttons .ghost-action{padding:12px 10px}.action-buttons form:not([data-action-form]){margin:0}.panel-subtle{display:block;color:var(--muted);font-size:12px;margin-top:3px}.translation-form{display:flex;align-items:end;gap:8px;flex-wrap:wrap}.translation-form label{color:var(--muted);font-size:11px;display:flex;flex-direction:column;gap:4px}.translation-form select{background:#0d1116;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:inherit;min-width:120px}.translation-form button,.tiny-button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 12px;font:inherit;cursor:pointer}.translation-form button{background:var(--accent);color:#041014;border-color:transparent;font-weight:800}.translation-form button:disabled{opacity:.45}.translation-arrow{color:var(--muted);padding-bottom:9px}.translation-list{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.translation-entry{display:flex;align-items:stretch;border:1px solid var(--line);border-radius:9px;overflow:hidden}.translation-item{padding:7px 9px;text-decoration:none;color:var(--text);display:flex;gap:8px;align-items:center}.translation-export{display:flex;align-items:center;padding:7px 9px;border-left:1px solid var(--line);background:var(--panel2);color:var(--accent);font-size:11px;font-weight:800;text-decoration:none}.translation-export:hover{background:#1d252d}.translation-item small,.translation-empty,.translation-status{color:var(--muted);font-size:12px}.translation-status{min-height:18px;margin-top:8px}@media(max-width:760px){.setup-panel{grid-template-columns:1fr}.settings-row{align-items:flex-start;flex-direction:column}.settings-actions{width:100%;flex-wrap:wrap}.path-form,.settings-path{grid-template-columns:1fr}.path-note{max-width:85vw}}
.ask-form{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:stretch;margin:0 0 8px}.ask-form textarea{background:#0d1116;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:13px;font:inherit;resize:vertical;min-height:78px}.ask-side{display:flex;flex-direction:column;gap:8px;min-width:190px}.ask-side select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font:inherit}.ask-form button{background:var(--accent);color:#041014;border:0;border-radius:10px;padding:0 22px;min-height:42px;font:inherit;font-weight:800;cursor:pointer}.ask-hint{color:var(--muted);font-size:12px;margin:0 0 14px}.answer-text{white-space:pre-wrap;line-height:1.65}.qa-sources{display:flex;flex-direction:column}.qa-source{display:flex;gap:10px;padding:10px 0;border-top:1px solid var(--line);text-decoration:none;color:var(--text)}.qa-source:first-child{border-top:0}.qa-source b{color:var(--accent)}.reader-panel{scroll-margin-top:80px}.reader-nav{display:flex;gap:12px;flex-wrap:wrap}.reader-grid{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid var(--line)}.reader-grid>div{min-width:0;padding:14px}.reader-grid>div+div{border-left:1px solid var(--line)}.reader-grid pre{white-space:pre-wrap;word-break:break-word;line-height:1.55;margin:8px 0 0;max-height:65vh;overflow:auto}.reader-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.reader-empty{color:var(--muted);padding:18px 0;line-height:1.5}.fixed-target{display:block;background:#0d1116;border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:120px;color:var(--text)}@media(max-width:800px){.reader-grid{grid-template-columns:1fr}.reader-grid>div+div{border-left:0;border-top:1px solid var(--line)}.ask-form{grid-template-columns:1fr}.ask-side{min-width:0}.ask-form button{padding:12px}}

.fast-pair{display:flex;align-items:center;justify-content:space-between;gap:16px;border-top:1px solid var(--line);padding:13px 2px}.fast-pair:first-of-type{border-top:0}.fast-pair strong,.fast-pair small{display:block}.fast-pair small{color:var(--muted);margin-top:3px}.fast-pair form{margin:0}.fast-pair button{background:var(--accent);color:#041014;border:0;border-radius:9px;padding:9px 13px;font:inherit;font-weight:800;cursor:pointer}.ready-mark{color:var(--accent2);font-weight:800}.fast-status{color:var(--muted);font-size:13px;min-height:20px}.fast-status.action-error{color:var(--danger)}.ask-filters{grid-column:1/-1;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:0 12px}.ask-filters summary{cursor:pointer;color:var(--muted);padding:10px 2px}.ask-filters summary span{font-size:12px;margin-left:6px}.ask-filter-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:4px 0 12px}.ask-filter-grid label{display:flex;flex-direction:column;gap:5px;color:var(--muted);font-size:12px}.ask-filter-grid input,.ask-filter-grid select{background:#0d1116;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px;font:inherit}.ask-documents{grid-column:1/-1}.ask-documents select{min-height:120px}.ask-filter-note{color:var(--muted);font-size:12px;margin:0 0 12px}.chat-form{display:grid;grid-template-columns:1fr auto;gap:10px;margin-top:12px}.chat-form textarea{background:#0d1116;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:13px;font:inherit;resize:vertical;min-height:78px}.chat-form button{background:var(--accent);color:#041014;border:0;border-radius:10px;padding:0 22px;font:inherit;font-weight:800;cursor:pointer}.chat-actions{display:flex}.chat-clear-form{margin:8px 0 10px}.chat-clear-form button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px 12px;cursor:pointer}.chat-history{display:flex;flex-direction:column;gap:10px}.chat-message{max-width:88%;border:1px solid var(--line);border-radius:12px;padding:11px 13px}.chat-message.user{align-self:flex-end;background:#10202a}.chat-message.assistant{align-self:flex-start;background:var(--panel2)}.chat-message>span{display:block;color:var(--muted);font-size:11px;margin-bottom:5px}.chat-message>div{white-space:pre-wrap;overflow-wrap:anywhere}.chat-status{color:var(--muted);font-size:13px;margin:8px 0}.chat-status.action-error{color:var(--danger)}@media(max-width:800px){.ask-filter-grid{grid-template-columns:1fr 1fr}.chat-form{grid-template-columns:1fr}.chat-form button{padding:12px}}@media(max-width:520px){.ask-filter-grid{grid-template-columns:1fr}}
"""


UI_SCRIPT = r"""
(() => {
  const translationPanel = document.querySelector('[data-translation-panel]');
  if (translationPanel) {
    const form = translationPanel.querySelector('.translation-form');
    const status = translationPanel.querySelector('.translation-status');
    const submitButton = form ? form.querySelector('button[type="submit"]') : null;
    const documentSha = form ? (form.querySelector('input[name="sha256"]')?.value || '') : '';
    let translationWasRunning = false;
    async function pollTranslation() {
      try {
        const response = await fetch('/api/activity', {cache: 'no-store'});
        if (response.ok) {
          const data = await response.json();
          const state = data.translation || data.action || {};
          const sameDocument = !state.sha256 || state.sha256 === documentSha;
          const running = sameDocument && state.kind === 'translate' && state.status === 'running';
          if (running) {
            let message = state.message || 'Translating…';
            if (state.total) message += ` · ${state.current}/${state.total}`;
            status.textContent = message;
          } else if (translationWasRunning && sameDocument && state.kind === 'translate') {
            status.textContent = state.error || state.message || 'Translation complete';
            if (state.status === 'succeeded') {
              setTimeout(() => location.reload(), 500);
            } else if (submitButton) {
              submitButton.disabled = false;
            }
          }
          if (submitButton && !running && !translationWasRunning) submitButton.disabled = false;
          translationWasRunning = running;
        }
      } catch (_) {}
      setTimeout(pollTranslation, translationWasRunning ? 700 : 3000);
    }
    if (form) form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button');
      if (button) button.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: 'POST', body: new URLSearchParams(new FormData(form)),
          headers: {'X-Requested-With': 'fetch'},
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Translation failed');
        translationWasRunning = true;
        const state = data.translation || data.action || {};
        status.textContent = state.message || 'Starting…';
      } catch (error) {
        status.textContent = error.message || 'Translation failed';
        if (button) button.disabled = false;
      }
    });
    pollTranslation();
  }

  const fastSetupForms = [...document.querySelectorAll('[data-fast-setup]')];
  if (fastSetupForms.length) {
    const fastStatus = document.querySelector('[data-fast-status]');
    let fastSetupRunning = false;

    async function pollFastSetup() {
      try {
        const response = await fetch('/api/activity', {cache: 'no-store'});
        if (response.ok) {
          const data = await response.json();
          const state = data.fast_setup || {};
          const relevant = state.kind === 'translation-setup';
          fastSetupRunning = relevant && state.status === 'running';
          fastSetupForms.forEach(form => {
            const button = form.querySelector('button');
            if (button) button.disabled = fastSetupRunning;
          });
          if (relevant && fastStatus) {
            fastStatus.textContent = state.error || state.message || '';
            fastStatus.classList.toggle('action-error', state.status === 'failed');
          }
          if (relevant && state.status === 'succeeded') {
            setTimeout(() => location.reload(), 500);
            return;
          }
        }
      } catch (_) {}
      setTimeout(pollFastSetup, fastSetupRunning ? 700 : 3000);
    }

    fastSetupForms.forEach(form => form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button');
      if (button) button.disabled = true;
      if (fastStatus) {
        fastStatus.classList.remove('action-error');
        fastStatus.textContent = 'Preparing Fast Translation model…';
      }
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new URLSearchParams(new FormData(form)),
          headers: {'X-Requested-With': 'fetch'},
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Fast Translation setup failed');
        fastSetupRunning = true;
        const state = data.fast_setup || data.action || {};
        if (fastStatus) fastStatus.textContent = state.message || 'Starting…';
      } catch (error) {
        if (button) button.disabled = false;
        if (fastStatus) {
          fastStatus.classList.add('action-error');
          fastStatus.textContent = error.message || 'Fast Translation setup failed';
        }
      }
    }));
    pollFastSetup();
  }

  const qualitySetupForms = [...document.querySelectorAll('[data-quality-setup]')];
  if (qualitySetupForms.length) {
    const qualityStatus = document.querySelector('[data-quality-status]');
    let qualitySetupRunning = false;

    async function pollQualitySetup() {
      try {
        const response = await fetch('/api/activity', {cache: 'no-store'});
        if (response.ok) {
          const data = await response.json();
          const state = data.quality_setup || {};
          const relevant = state.kind === 'quality-translation-setup';
          qualitySetupRunning = relevant && state.status === 'running';
          qualitySetupForms.forEach(form => {
            const button = form.querySelector('button');
            if (button) button.disabled = qualitySetupRunning;
          });
          if (relevant && qualityStatus) {
            qualityStatus.textContent = state.error || state.message || '';
            qualityStatus.classList.toggle('action-error', state.status === 'failed');
          }
          if (relevant && state.status === 'succeeded') {
            setTimeout(() => location.reload(), 500);
            return;
          }
        }
      } catch (_) {}
      setTimeout(pollQualitySetup, qualitySetupRunning ? 700 : 3000);
    }

    qualitySetupForms.forEach(form => form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('button');
      if (button) button.disabled = true;
      if (qualityStatus) {
        qualityStatus.classList.remove('action-error');
        qualityStatus.textContent = 'Preparing M2M100 Quality Translation model…';
      }
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new URLSearchParams(new FormData(form)),
          headers: {'X-Requested-With': 'fetch'},
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Quality Translation setup failed');
        qualitySetupRunning = true;
        const state = data.quality_setup || data.action || {};
        if (qualityStatus) qualityStatus.textContent = state.message || 'Starting…';
      } catch (error) {
        if (button) button.disabled = false;
        if (qualityStatus) {
          qualityStatus.classList.add('action-error');
          qualityStatus.textContent = error.message || 'Quality Translation setup failed';
        }
      }
    }));
    pollQualitySetup();
  }

  const askForm = document.querySelector('[data-ask-form]');
  if (askForm) {
    const askStatus = document.querySelector('[data-ask-status]');
    const askResults = document.querySelector('[data-ask-results]');
    const askButton = askForm.querySelector('button[type="submit"]');
    let askRunning = false;
    let lastQuestion = '';
    let lastMode = '';

    function renderAsk(state) {
      const status = state.status || 'idle';
      askRunning = status === 'running';
      if (askButton) askButton.disabled = askRunning;

      if (askRunning) {
        if (askStatus) {
          askStatus.hidden = false;
          askStatus.classList.remove('action-error');
          askStatus.textContent = state.message || 'Обрабатываю вопрос…';
        }
        return;
      }

      if (status === 'succeeded') {
        if (askStatus) {
          askStatus.hidden = false;
          askStatus.classList.remove('action-error');
          askStatus.textContent = state.message || 'Готово';
        }
        if (askResults && state.html) askResults.innerHTML = state.html;
        return;
      }

      if (status === 'failed') {
        if (askStatus) {
          askStatus.hidden = false;
          askStatus.classList.add('action-error');
          askStatus.textContent = state.message || state.error || 'Не удалось получить ответ';
        }
        if (askResults && state.html) askResults.innerHTML = state.html;
      }
    }

    async function pollAsk() {
      try {
        const response = await fetch('/api/ask-status', {cache: 'no-store'});
        if (response.ok) {
          const state = await response.json();
          const sameRequest = state.question === lastQuestion && (!lastMode || state.mode === lastMode);
          if (!lastQuestion || sameRequest || state.status === 'running') {
            renderAsk(state);
          }
        }
      } catch (_) {}
      setTimeout(pollAsk, askRunning ? 700 : 2500);
    }

    askForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const question = (askForm.querySelector('textarea[name="q"]') || {}).value || '';
      lastQuestion = question.trim();
      const modeSelect = askForm.querySelector('select[name="mode"]');
      lastMode = modeSelect ? modeSelect.value : 'quick';
      if (!lastQuestion) return;
      if (askResults) askResults.innerHTML = '';
      if (askStatus) {
        askStatus.hidden = false;
        askStatus.classList.remove('action-error');
        askStatus.textContent = 'Запускаю локальный анализ…';
      }
      if (askButton) askButton.disabled = true;
      try {
        const formData = new FormData(askForm);
        const documentsSelect = askForm.querySelector('[data-documents-select]');
        const documentsValue = [...(documentsSelect ? documentsSelect.selectedOptions : [])]
          .map(option => option.value).filter(Boolean).join(',');
        formData.set('documents', documentsValue);
        const response = await fetch(askForm.action, {
          method: 'POST',
          body: new URLSearchParams(formData),
          headers: {'X-Requested-With': 'fetch'},
        });
        const state = await response.json();
        if (!response.ok) throw new Error(state.error || 'Ask failed');
        renderAsk(state);
      } catch (error) {
        askRunning = false;
        if (askButton) askButton.disabled = false;
        if (askStatus) {
          askStatus.hidden = false;
          askStatus.classList.add('action-error');
          askStatus.textContent = error.message || 'Ask failed';
        }
      }
    });

    pollAsk();
  }

  const chatForm = document.querySelector('[data-chat-form]');
  if (chatForm) {
    const chatRoot = document.querySelector('[data-chat-root]');
    const chatStatus = document.querySelector('[data-chat-status]');
    const chatResults = document.querySelector('[data-chat-results]');
    const chatButton = chatForm.querySelector('button[type="submit"]');
    const clearForm = document.querySelector('[data-chat-clear]');
    let chatRunning = false;

    function renderChat(state) {
      chatRunning = state.status === 'running';
      if (chatButton) chatButton.disabled = chatRunning;
      if (clearForm) {
        const clearButton = clearForm.querySelector('button');
        if (clearButton) clearButton.disabled = chatRunning;
      }
      if (chatStatus) {
        chatStatus.hidden = !(chatRunning || state.status === 'failed');
        chatStatus.classList.toggle('action-error', state.status === 'failed');
        chatStatus.textContent = state.error || state.message || '';
      }
      if (chatResults && state.html) chatResults.innerHTML = state.html;
      if (state.status === 'succeeded') {
        const textarea = chatForm.querySelector('textarea[name="message"]');
        if (textarea) textarea.value = '';
      }
    }

    async function pollChat() {
      try {
        const response = await fetch('/api/chat-status', {cache: 'no-store'});
        if (response.ok) renderChat(await response.json());
      } catch (_) {}
      setTimeout(pollChat, chatRunning ? 700 : 2500);
    }

    chatForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const textarea = chatForm.querySelector('textarea[name="message"]');
      if (!textarea || !textarea.value.trim()) return;
      if (chatStatus) {
        chatStatus.hidden = false;
        chatStatus.classList.remove('action-error');
        chatStatus.textContent = 'Ollama формирует ответ…';
      }
      if (chatButton) chatButton.disabled = true;
      try {
        const response = await fetch(chatForm.action, {
          method: 'POST',
          body: new URLSearchParams(new FormData(chatForm)),
          headers: {'X-Requested-With': 'fetch'},
        });
        const state = await response.json();
        if (!response.ok) throw new Error(state.error || 'Chat failed');
        renderChat(state);
      } catch (error) {
        chatRunning = false;
        if (chatButton) chatButton.disabled = false;
        if (chatStatus) {
          chatStatus.hidden = false;
          chatStatus.classList.add('action-error');
          chatStatus.textContent = error.message || 'Chat failed';
        }
      }
    });

    if (clearForm) clearForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        const response = await fetch(clearForm.action, {
          method: 'POST',
          body: new URLSearchParams(new FormData(clearForm)),
          headers: {'X-Requested-With': 'fetch'},
        });
        const state = await response.json();
        if (!response.ok) throw new Error(state.error || 'Clear failed');
        renderChat(state);
      } catch (error) {
        if (chatStatus) {
          chatStatus.hidden = false;
          chatStatus.classList.add('action-error');
          chatStatus.textContent = error.message || 'Clear failed';
        }
      }
    });

    pollChat();
  }

  const panel = document.querySelector('[data-action-panel]');
  if (!panel) return;
  const statusEl = panel.querySelector('[data-action-status]');
  const progressEl = panel.querySelector('[data-action-progress]');
  const progressTrack = progressEl ? progressEl.parentElement : null;
  const forms = [...panel.querySelectorAll('[data-action-form]')];
  let wasRunning = false;
  let reloadScheduled = false;

  function apply(state) {
    const running = state.status === 'running';
    let message = state.error || state.message || 'Ready';
    if (running && state.total) message += ` · ${state.current}/${state.total}`;
    statusEl.textContent = message;
    statusEl.classList.toggle('action-error', state.status === 'failed');
    forms.forEach(form => {
      const button = form.querySelector('button');
      if (button) button.disabled = running || button.dataset.permanentDisabled === '1';
    });
    if (progressEl && progressTrack) {
      if (running && !state.total) {
        progressTrack.classList.add('running');
        progressEl.style.width = '32%';
      } else {
        progressTrack.classList.remove('running');
        const pct = state.total ? Math.min(100, Math.round((state.current / state.total) * 100)) : 0;
        progressEl.style.width = `${pct}%`;
      }
    }
    if (wasRunning && state.status === 'succeeded' && !reloadScheduled) {
      reloadScheduled = true;
      setTimeout(() => location.reload(), 650);
    }
    wasRunning = running;
  }

  async function poll() {
    try {
      const response = await fetch('/api/activity', {cache: 'no-store'});
      if (response.ok) {
        const data = await response.json();
        apply(data.action || {});
      }
    } catch (_) {}
    setTimeout(poll, wasRunning ? 700 : 4000);
  }

  forms.forEach(form => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new URLSearchParams(new FormData(form)),
          headers: {'X-Requested-With': 'fetch'},
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Action failed');
        apply(data.action || {});
      } catch (error) {
        statusEl.textContent = error.message || 'Action failed';
        statusEl.classList.add('action-error');
      }
    });
  });

  poll();
})();
"""

# v0.4.1 UX additions are intentionally compact

# v0.8 status UI

