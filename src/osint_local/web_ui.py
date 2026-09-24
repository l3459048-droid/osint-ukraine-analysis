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
<header class="topbar"><a class="brand" href="/">OSINT Local <span>v0.3</span></a><nav>
<a href="/search">Search</a><a href="/documents">Documents</a><a href="/api/stats">API</a>
</nav></header>
<main>{body}</main>
<footer>Local-first · source files stay on this computer</footer>
</body>
</html>"""


def _hero() -> str:
    return """<section class="hero"><div><div class="eyebrow">LOCAL KNOWLEDGE BASE</div>
<h1>Search your OSINT document archive.</h1>
<p>Documents, page-aware chunks, classifications and semantic search — served only from this computer by default.</p>
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
        return '<div class="empty">No processed documents yet. Run <code>osint-local scan</code>.</div>'
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
:root{color-scheme:dark;--bg:#0b0d10;--panel:#12161b;--panel2:#171c22;--text:#f2f5f7;--muted:#96a0aa;--line:#27303a;--accent:#7dd3fc;--accent2:#a7f3d0;--danger:#fda4af}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}.topbar{height:64px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 max(24px,calc((100vw - 1180px)/2));position:sticky;top:0;background:rgba(11,13,16,.94);backdrop-filter:blur(12px);z-index:10}.brand{font-weight:800;color:var(--text);text-decoration:none;font-size:18px}.brand span{font-size:11px;color:var(--accent);border:1px solid #24566b;border-radius:10px;padding:2px 6px;margin-left:5px}.topbar nav{display:flex;gap:20px}.topbar nav a,.panel-head a,.result-actions a,.chunk-head a{color:var(--muted);text-decoration:none}.topbar nav a:hover,.panel-head a:hover,.result-actions a:hover,.chunk-head a:hover{color:var(--accent)}main{max-width:1180px;margin:auto;padding:44px 24px 72px}.hero{padding:42px 0 32px}.hero h1,.page-head h1{font-size:clamp(32px,5vw,58px);letter-spacing:-.04em;line-height:1.04;margin:8px 0 14px;max-width:850px}.hero p,.page-head p{color:var(--muted);font-size:17px;max-width:780px}.eyebrow{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.16em}.page-head{margin-bottom:24px}.page-head h1{font-size:38px}.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:10px 0 24px}.stat{background:linear-gradient(180deg,var(--panel2),var(--panel));border:1px solid var(--line);border-radius:14px;padding:18px}.stat-value{font-size:27px;font-weight:800;overflow-wrap:anywhere}.stat-label{color:var(--muted);margin-top:4px}.search-form{display:grid;grid-template-columns:minmax(180px,1fr) 130px 78px 100px;gap:8px;margin:22px 0 28px}.search-form input,.search-form select,.search-form button{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:12px 13px;font:inherit}.search-form input:focus,.search-form select:focus{outline:2px solid #1f607b;border-color:var(--accent)}.search-form button,.button{background:var(--accent);color:#041014!important;font-weight:800;border:0!important;text-decoration:none;border-radius:10px;padding:12px 16px;cursor:pointer;display:inline-block}.button.secondary{background:var(--panel2);color:var(--text)!important;border:1px solid var(--line)!important}.two-col{display:grid;grid-template-columns:340px 1fr;gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:16px}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.panel h2{font-size:17px;margin:0}.category-list{display:flex;flex-direction:column}.category-list a{display:flex;justify-content:space-between;color:var(--text);text-decoration:none;border-top:1px solid var(--line);padding:11px 2px}.category-list a:first-child{border-top:0}.category-list b{color:var(--accent)}.doc-list{display:flex;flex-direction:column}.doc-card{display:flex;justify-content:space-between;align-items:center;gap:16px;border-top:1px solid var(--line);padding:13px 2px;color:var(--text);text-decoration:none}.doc-card:first-child{border-top:0}.doc-card strong{display:block;overflow-wrap:anywhere}.doc-card span:not(.arrow){display:block;color:var(--muted);font-size:13px;margin-top:3px}.arrow{color:var(--accent);font-size:22px}.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}.chip,.badge{border:1px solid var(--line);background:var(--panel);color:var(--muted);text-decoration:none;padding:7px 10px;border-radius:999px}.chip.active,.chip:hover,.badge:hover{color:var(--text);border-color:#456176}.badges{display:flex;gap:8px;flex-wrap:wrap}.badge b{color:var(--accent);margin-left:4px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;min-width:720px}th,td{text-align:left;border-bottom:1px solid var(--line);padding:11px 8px}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}td a{color:var(--text);text-decoration:none}td a:hover{color:var(--accent)}.results{display:flex;flex-direction:column;gap:10px}.result{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:17px}.result-meta{display:flex;gap:9px;flex-wrap:wrap;color:var(--muted);font-size:12px}.score{color:var(--accent2);font-weight:800}.result h3{margin:9px 0 6px;font-size:17px}.result h3 a{color:var(--text);text-decoration:none}.result p{margin:0;color:#d5dbe0}.result-actions{display:flex;gap:16px;margin-top:10px}.result-count{color:var(--muted);margin:-9px 0 15px}.doc-actions{display:flex;gap:8px;margin-bottom:18px}.doc-stats{margin-top:0}.meta-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.meta-grid div{background:var(--panel2);border-radius:9px;padding:12px;min-width:0}.meta-grid span{display:block;color:var(--muted);font-size:12px}.meta-grid strong{display:block;margin-top:3px;overflow-wrap:anywhere}.chunk{border-top:1px solid var(--line);padding:14px 0}.chunk:first-of-type{border-top:0}.chunk-head{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin-bottom:8px}.chunk pre{white-space:pre-wrap;word-break:break-word;background:#0d1116;border:1px solid #202933;border-radius:10px;padding:13px;margin:0;max-height:420px;overflow:auto;color:#dce2e7;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace}.alert{border:1px solid #713747;background:#2a151c;color:#fecdd3;padding:13px;border-radius:10px}.empty{color:var(--muted);padding:18px 4px}.pagination{display:flex;justify-content:space-between;margin-top:16px}footer{max-width:1180px;margin:auto;padding:22px 24px 42px;color:#65717c;border-top:1px solid var(--line)}code{background:#1a2027;border-radius:5px;padding:2px 5px}@media(max-width:800px){.stats-grid{grid-template-columns:repeat(2,1fr)}.two-col{grid-template-columns:1fr}.search-form{grid-template-columns:1fr 1fr}.search-form input{grid-column:1/-1}.meta-grid{grid-template-columns:1fr 1fr}.topbar nav a:last-child{display:none}}@media(max-width:480px){main{padding:28px 15px 52px}.topbar{padding:0 15px}.topbar nav{gap:12px}.stats-grid{grid-template-columns:1fr 1fr}.search-form{grid-template-columns:1fr}.search-form input{grid-column:auto}.meta-grid{grid-template-columns:1fr}.doc-actions{flex-direction:column}.hero{padding-top:18px}}
"""
