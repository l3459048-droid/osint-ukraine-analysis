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
<header class="topbar"><a class="brand" href="/">OSINT Local <span>v0.5</span></a><nav>
<a href="/search">Search</a><a href="/documents">Documents</a><a href="/settings">Settings</a>
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
        for name, label in (("auto", "Auto"), ("lexical", "Lexical"), ("semantic", "Semantic"))
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
) -> str:
    running = action.get("status") == "running"
    current = int(action.get("current") or 0)
    total = int(action.get("total") or 0)
    percent = int((current / total) * 100) if total else 0
    status = action.get("message") or "Ready"
    if running and total:
        status = f"{status} · {current}/{total}"
    index_status, index_label, index_permanent_disabled = _index_state(
        semantic_available=semantic_available,
        semantic_enabled=semantic_enabled,
        embedding_count=embedding_count,
        chunk_count=chunk_count,
    )
    index_disabled = running or index_permanent_disabled
    buttons_disabled = " disabled" if running else ""
    index_disabled_attr = " disabled" if index_disabled else ""
    index_permanent_attr = ' data-permanent-disabled="1"' if index_permanent_disabled else ""
    return f"""<section class="action-panel" data-action-panel>
<div class="action-copy"><strong>Library</strong><span data-action-status>{_e(status)}</span></div>
<div class="action-buttons">
<form action="/actions/scan" method="post" data-action-form><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit"{buttons_disabled}>Scan</button></form>
<form action="/actions/index" method="post" data-action-form><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="secondary" type="submit"{index_disabled_attr}{index_permanent_attr}>{_e(index_label)}</button></form>
<form action="/actions/open-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="ghost-action" type="submit">Folder</button></form>
<a class="button ghost" href="/settings">Settings</a>
</div>
<div class="action-meta"><span>{_e(index_status)}</span><span class="path-note" title="{_e(input_dir)}">{_e(input_dir)}</span></div>
<div class="progress-track{' running' if running and not total else ''}" aria-hidden="true"><span data-action-progress style="width:{percent}%"></span></div>
</section>"""


def _setup_panel(csrf_token: str, input_dir) -> str:
    return f"""<section class="setup-panel">
<div><div class="eyebrow">FIRST RUN</div><h2>Choose your document folder</h2><p>OSINT Local reads this folder recursively. Your originals stay untouched.</p></div>
<div class="setup-actions">
<form action="/settings/pick-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit">Choose folder</button></form>
<form class="path-form" action="/settings/input-dir" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><input name="input_dir" value="{_e(input_dir)}" aria-label="Document folder"><button class="secondary" type="submit">Save path</button></form>
</div></section>"""


def _settings_panel(csrf_token: str, input_dir, workspace_dir, translations_dir=None, *, semantic_available: bool, semantic_enabled: bool, embedding_count: int, chunk_count: int) -> str:
    index_status, _, _ = _index_state(
        semantic_available=semantic_available,
        semantic_enabled=semantic_enabled,
        embedding_count=embedding_count,
        chunk_count=chunk_count,
    )
    return f"""<section class="panel settings-panel">
<div class="settings-row"><div><span class="setting-label">Documents</span><strong>{_e(input_dir)}</strong><p>Source files are read-only.</p></div><div class="settings-actions"><form action="/settings/pick-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button type="submit">Choose folder</button></form><form action="/actions/open-folder" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="secondary" type="submit">Open</button></form></div></div>
<form class="settings-path" action="/settings/input-dir" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><input name="input_dir" value="{_e(input_dir)}"><button class="secondary" type="submit">Save path</button></form>
<div class="settings-row"><div><span class="setting-label">Workspace</span><strong>{_e(workspace_dir)}</strong><p>Database, extracted text and index. Managed automatically.</p></div></div>
<div class="settings-row"><div><span class="setting-label">Semantic index</span><strong>{_e(index_status)}</strong><p>{embedding_count} embeddings for {chunk_count} chunks.</p></div></div>
<div class="settings-row"><div><span class="setting-label">Translations</span><strong>{_e(translations_dir or "translations")}</strong><p>Offline translations are saved separately from source files.</p></div><div class="settings-actions"><form action="/actions/open-translations" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="secondary" type="submit">Open</button></form></div></div>
</section>"""


def _translation_panel(csrf_token: str, sha256: str, translations, *, available: bool, pairs: set[tuple[str, str]], action: dict) -> str:
    running_here = action.get("status") == "running" and action.get("kind") == "translate"
    pair_note = ", ".join(f"{a}→{b}" for a, b in sorted(pairs)) if pairs else "No language pairs installed"
    disabled = " disabled" if running_here else ""
    source_options = "".join(
        f'<option value="{code}"{" selected" if code == "auto" else ""}>{label}</option>'
        for code, label in (("auto", "Auto"), ("en", "English"), ("ru", "Russian"), ("uk", "Ukrainian"))
    )
    target_options = "".join(
        f'<option value="{code}"{" selected" if code == "ru" else ""}>{label}</option>'
        for code, label in (("en", "English"), ("ru", "Russian"), ("uk", "Ukrainian"))
    )
    rows = []
    for row in translations:
        rows.append(
            f'<a class="translation-item" href="/translation/{_e(sha256)}/{_e(row["source_lang"])}/{_e(row["target_lang"])}" target="_blank">'
            f'<span>{_e(row["source_lang"])} → {_e(row["target_lang"])}</span><small>{_e((row["created_at"] or "")[:19])}</small></a>'
        )
    saved = "".join(rows) if rows else '<span class="translation-empty">No saved translations yet.</span>'
    availability = "Offline engine ready" if available else "Install optional offline translation support"
    status = action.get("message") if running_here else ""
    return f"""<section class="panel translation-panel" data-translation-panel>
<div class="panel-head"><div><h2>Translate</h2><span class="panel-subtle">{_e(availability)} · {_e(pair_note)}</span></div><form action="/actions/open-translations" method="post"><input type="hidden" name="csrf" value="{_e(csrf_token)}"><button class="tiny-button" type="submit">Folder</button></form></div>
<form class="translation-form" action="/actions/translate" method="post">
<input type="hidden" name="csrf" value="{_e(csrf_token)}"><input type="hidden" name="sha256" value="{_e(sha256)}">
<label>From<select name="source_lang">{source_options}</select></label><span class="translation-arrow">→</span>
<label>To<select name="target_lang">{target_options}</select></label><button type="submit"{disabled}>Translate</button>
</form>
<div class="translation-status">{_e(status)}</div>
<div class="translation-list">{saved}</div>
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


def _classification_badges(classes) -> str:
    if not classes:
        return '<div class="empty">No classifications.</div>'
    return '<div class="badges">' + "".join(
        f'<a class="badge" href="/documents?{urlencode({"domain": row["domain"]})}">{_e(row["domain"])} <b>{row["score"]}</b></a>'
        for row in classes
    ) + "</div>"


def _document_cards(rows, db) -> str:
    if not rows:
        return '<div class="empty">No processed documents yet. Use <strong>Scan</strong> on the home page.</div>'
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
    doc_link = f'/documents/{hit.document_sha256}#chunk-{hit.chunk_index}'
    source_link = f'/source/{hit.document_sha256}' + (f'#page={hit.page}' if hit.page is not None else "")
    location = hit.source_path + (f" · page {hit.page}" if hit.page is not None else "")
    snippet = _e(" ".join(hit.text.split()))
    return f"""<article class="result">
<div class="result-meta"><span class="score">{hit.score:.4f}</span><span>{_e(hit.backend)}</span><span>{_e(location)}</span></div>
<h3><a href="{doc_link}">{_e(hit.source_path)}</a></h3>
<p>{snippet}</p>
<div class="result-actions"><a href="{doc_link}">Context</a><a href="{source_link}" target="_blank" rel="noreferrer">Source{f' · p.{hit.page}' if hit.page is not None else ''}</a></div>
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
:root{color-scheme:dark;--bg:#0b0d10;--panel:#12161b;--panel2:#171c22;--text:#f2f5f7;--muted:#96a0aa;--line:#27303a;--accent:#7dd3fc;--accent2:#a7f3d0;--danger:#fda4af}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}.topbar{height:64px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1180px)/2));position:sticky;top:0;background:rgba(11,13,16,.94);backdrop-filter:blur(12px);z-index:10}.brand{font-weight:800;color:var(--text);text-decoration:none;font-size:18px}.brand span{font-size:11px;color:var(--accent);border:1px solid #24566b;border-radius:10px;padding:2px 6px;margin-left:5px}.topbar nav{display:flex;gap:20px}.topbar nav a,.panel-head a,.result-actions a,.chunk-head a{color:var(--muted);text-decoration:none}.topbar nav a:hover,.panel-head a:hover,.result-actions a:hover,.chunk-head a:hover{color:var(--accent)}main{max-width:1180px;margin:auto;padding:44px 24px 72px}.hero{padding:42px 0 32px}.hero h1,.page-head h1{font-size:clamp(32px,5vw,58px);letter-spacing:-.04em;line-height:1.04;margin:8px 0 14px;max-width:850px}.hero p,.page-head p{color:var(--muted);font-size:17px;max-width:780px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.16em}.page-head{margin-bottom:24px}.page-head h1{font-size:38px}.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:10px 0 24px}.stat{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:14px;padding:18px}.stat-value{font-size:27px;font-weight:800;overflow-wrap:anywhere}.stat-label{color:var(--muted);margin-top:4px}.search-form{display:grid;grid-template-columns:minmax(180px,1fr) 130px 78px 100px;gap:8px;margin:22px 0 28px}.search-form input,.search-form select,.search-form button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:12px 13px;font:inherit}.search-form input:focus,.search-form select:focus{outline:2px solid #1f607b;border-color:var(--accent)}.search-form button,.button{background:var(--accent);color:#041014!important;font-weight:800;border:0!important;text-decoration:none;border-radius:10px;padding:12px 16px;cursor:pointer;display:inline-block}.button.secondary{background:var(--panel2);color:var(--text)!important;border:1px solid var(--line)!important}.two-col{display:grid;grid-template-columns:340px 1fr;gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.panel h2{font-size:17px;margin:0}.category-list{display:flex;flex-direction:column}.category-list a{display:flex;justify-content:space-between;color:var(--text);text-decoration:none;border-top:1px solid var(--line);padding:11px 2px}.category-list a:first-child{border-top:0}.category-list b{color:var(--accent)}.doc-list{display:flex;flex-direction:column}.doc-card{display:flex;justify-content:space-between;align-items:center;gap:16px;border-top:1px solid var(--line);padding:13px 2px;color:var(--text);text-decoration:none}.doc-card:first-child{border-top:0}.doc-card strong{display:block;overflow-wrap:anywhere}.doc-card span:not(.arrow){display:block;color:var(--muted);font-size:13px;margin-top:3px}.arrow{color:var(--accent);font-size:22px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}.chip,.badge{border:1px solid var(--line);background:var(--panel);color:var(--muted);text-decoration:none;padding:7px 10px;border-radius:999px}.chip.active,.chip:hover,.badge:hover{color:var(--text);border-color:#456176}.badges{display:flex;gap:8px;flex-wrap:wrap}.badge b{color:var(--accent);margin-left:4px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:720px}th,td{text-align:left;border-bottom:1px solid var(--line);padding:11px 8px}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}td a{color:var(--text);text-decoration:none}td a:hover{color:var(--accent)}.results{display:flex;flex-direction:column;gap:10px}.result{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:17px}.result-meta{display:flex;gap:9px;flex-wrap:wrap;color:var(--muted);font-size:12px}.score{color:var(--accent2);font-weight:800}.result h3{margin:9px 0 6px;font-size:17px}.result h3 a{color:var(--text);text-decoration:none}.result p{margin:0;color:#d5dbe0}.result-actions{display:flex;gap:16px;margin-top:10px}.result-count{color:var(--muted);margin:-9px 0 15px}.doc-actions{display:flex;gap:8px;margin-bottom:18px}.doc-stats{margin-top:0}.meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.meta-grid div{background:var(--panel2);border-radius:9px;padding:12px;min-width:0}.meta-grid span{display:block;color:var(--muted);font-size:12px}.meta-grid strong{display:block;margin-top:3px;overflow-wrap:anywhere}.chunk{border-top:1px solid var(--line);padding:14px 0}.chunk:first-of-type{border-top:0}.chunk-head{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-bottom:8px}.chunk pre{white-space:pre-wrap;word-break:break-word;background:#0d1116;border:1px solid #202933;border-radius:10px;padding:13px;margin:0;max-height:420px;overflow:auto;color:#dce2e7;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.alert{border:1px solid #713747;background:#2a151c;color:#fecdd3;padding:13px;border-radius:10px}.empty{color:var(--muted);padding:18px 4px}.pagination{display:flex;justify-content:space-between;margin-top:16px}footer{max-width:1180px;margin:auto;padding:22px 24px 42px;color:#65717c;border-top:1px solid var(--line)}code{background:#1a2027;border-radius:5px;padding:2px 5px}@media(max-width:800px){.stats-grid{grid-template-columns:repeat(2,1fr)}.two-col{grid-template-columns:1fr}.search-form{grid-template-columns:1fr 1fr}.search-form input{grid-column:1/-1}.meta-grid{grid-template-columns:1fr 1fr}.topbar nav a:nth-last-child(-n+1){display:none}}@media(max-width:480px){main{padding:28px 15px 52px}.topbar{padding:0 15px}.topbar nav{gap:12px}.stats-grid{grid-template-columns:1fr 1fr}.search-form{grid-template-columns:1fr}.search-form input{grid-column:auto}.meta-grid{grid-template-columns:1fr}.doc-actions{flex-direction:column}.hero{padding-top:18px}}

.action-panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:0 0 18px;display:grid;grid-template-columns:minmax(180px,1fr) auto;gap:10px 18px;align-items:center}.action-copy{display:flex;align-items:baseline;gap:12px;min-width:0}.action-copy strong{font-size:16px}.action-copy span{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.action-buttons{display:flex;align-items:center;gap:8px}.action-buttons form{margin:0}.action-buttons button{font:inherit}.action-buttons .secondary{background:var(--panel2);color:var(--text);border:1px solid var(--line)}.button.ghost{background:transparent!important;color:var(--muted)!important;border:1px solid transparent!important}.button.ghost:hover{color:var(--text)!important}.action-buttons button:disabled{opacity:.45;cursor:not-allowed}.action-meta{grid-column:1/-1;color:var(--muted);font-size:12px;display:flex;gap:12px;flex-wrap:wrap}.action-hint{color:#c0cad2}.progress-track{grid-column:1/-1;height:3px;background:#1c242c;border-radius:999px;overflow:hidden}.progress-track span{display:block;height:100%;background:var(--accent);transition:width .2s ease}.progress-track.running span{width:32%!important;animation:indeterminate 1.1s ease-in-out infinite}@keyframes indeterminate{0%{transform:translateX(-120%)}100%{transform:translateX(320%)}}.activity-panel{border:1px solid var(--line);border-radius:12px;background:var(--panel);margin:18px 0}.activity-panel summary{cursor:pointer;color:var(--muted);padding:12px 15px;user-select:none}.activity-body{border-top:1px solid var(--line);padding:15px;display:grid;grid-template-columns:1fr 1fr;gap:18px}.activity-last>span{display:block;color:var(--muted);font-size:12px}.activity-last>strong{display:block;margin-top:3px}.activity-last p{color:var(--muted);margin:7px 0}.activity-result{white-space:pre-wrap;word-break:break-word;background:#0d1116;border:1px solid #202933;border-radius:8px;padding:10px;font-size:12px}.activity-errors h3{margin:0 0 8px;font-size:13px}.activity-errors ul{list-style:none;margin:0;padding:0}.activity-errors li{border-top:1px solid var(--line);padding:8px 0}.activity-errors li:first-child{border-top:0}.activity-errors li strong,.activity-errors li span{display:block}.activity-errors li span{color:var(--muted);font-size:12px;margin-top:2px}.empty.compact{padding:4px 0}.action-error{color:var(--danger)!important}
@media(max-width:700px){.action-panel{grid-template-columns:1fr}.action-buttons{grid-column:1/-1;flex-wrap:wrap}.activity-body{grid-template-columns:1fr}}
.setup-panel{display:grid;grid-template-columns:minmax(220px,1fr) minmax(320px,1.2fr);gap:18px;align-items:center;background:linear-gradient(180deg,#121a20,var(--panel));border:1px solid #2c5365;border-radius:14px;padding:18px;margin:0 0 18px}.setup-panel h2{margin:5px 0 4px;font-size:20px}.setup-panel p,.settings-row p{margin:4px 0 0;color:var(--muted);font-size:13px}.setup-actions{display:flex;flex-direction:column;gap:8px;align-items:stretch}.setup-actions form,.settings-actions form{margin:0}.setup-actions button,.settings-panel button,.ghost-action{font:inherit;border-radius:9px;padding:10px 13px;cursor:pointer}.setup-actions button,.settings-panel button{background:var(--accent);color:#041014;border:0;font-weight:800}.setup-actions .secondary,.settings-panel .secondary{background:var(--panel2);color:var(--text);border:1px solid var(--line)}.path-form,.settings-path{display:grid;grid-template-columns:minmax(160px,1fr) auto;gap:8px}.path-form input,.settings-path input{background:#0d1116;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:10px 11px;font:inherit;min-width:0}.ghost-action{background:transparent;color:var(--muted);border:1px solid transparent}.ghost-action:hover{color:var(--text)}.path-note{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:min(620px,65vw)}.settings-panel{padding:0}.settings-row{display:flex;justify-content:space-between;gap:18px;align-items:center;padding:17px 18px;border-top:1px solid var(--line)}.settings-row:first-child{border-top:0}.settings-row strong{display:block;overflow-wrap:anywhere}.setting-label{display:block;color:var(--muted);font-size:12px;margin-bottom:4px}.settings-actions{display:flex;gap:8px;flex-shrink:0}.settings-path{padding:0 18px 17px}.action-buttons .ghost-action{padding:12px 10px}.action-buttons form:not([data-action-form]){margin:0}.panel-subtle{display:block;color:var(--muted);font-size:12px;margin-top:3px}.translation-form{display:flex;align-items:end;gap:8px;flex-wrap:wrap}.translation-form label{color:var(--muted);font-size:11px;display:flex;flex-direction:column;gap:4px}.translation-form select{background:#0d1116;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:inherit;min-width:120px}.translation-form button,.tiny-button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px 12px;font:inherit;cursor:pointer}.translation-form button{background:var(--accent);color:#041014;border-color:transparent;font-weight:800}.translation-form button:disabled{opacity:.45}.translation-arrow{color:var(--muted);padding-bottom:9px}.translation-list{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.translation-item{border:1px solid var(--line);border-radius:9px;padding:7px 9px;text-decoration:none;color:var(--text);display:flex;gap:8px;align-items:center}.translation-item small,.translation-empty,.translation-status{color:var(--muted);font-size:12px}.translation-status{min-height:18px;margin-top:8px}@media(max-width:760px){.setup-panel{grid-template-columns:1fr}.settings-row{align-items:flex-start;flex-direction:column}.settings-actions{width:100%;flex-wrap:wrap}.path-form,.settings-path{grid-template-columns:1fr}.path-note{max-width:85vw}}
"""


UI_SCRIPT = r"""
(() => {
  const translationPanel = document.querySelector('[data-translation-panel]');
  if (translationPanel) {
    const form = translationPanel.querySelector('.translation-form');
    const status = translationPanel.querySelector('.translation-status');
    let translationWasRunning = false;
    async function pollTranslation() {
      try {
        const response = await fetch('/api/activity', {cache: 'no-store'});
        if (response.ok) {
          const data = await response.json();
          const state = data.action || {};
          const running = state.kind === 'translate' && state.status === 'running';
          if (running) {
            let message = state.message || 'Translating…';
            if (state.total) message += ` · ${state.current}/${state.total}`;
            status.textContent = message;
          } else if (translationWasRunning && state.kind === 'translate') {
            status.textContent = state.error || state.message || 'Translation complete';
            if (state.status === 'succeeded') setTimeout(() => location.reload(), 500);
          }
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
        status.textContent = (data.action && data.action.message) || 'Starting…';
      } catch (error) {
        status.textContent = error.message || 'Translation failed';
        if (button) button.disabled = false;
      }
    });
    pollTranslation();
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
