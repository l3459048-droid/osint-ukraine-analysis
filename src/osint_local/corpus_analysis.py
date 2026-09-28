from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import date, datetime, timezone
from typing import Any, Callable

ANALYZER_VERSION = 2

DATE_DMY_RE = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})[.\-/](?P<month>\d{1,2})[.\-/](?P<year>(?:19|20|21)\d{2})(?!\d)"
)
DATE_YMD_RE = re.compile(
    r"(?<!\d)(?P<year>(?:19|20|21)\d{2})[.\-/](?P<month>\d{1,2})[.\-/](?P<day>\d{1,2})(?!\d)"
)

MONTHS = {
    "january": 1, "jan": 1, "января": 1, "січня": 1,
    "february": 2, "feb": 2, "февраля": 2, "лютого": 2,
    "march": 3, "mar": 3, "марта": 3, "березня": 3,
    "april": 4, "apr": 4, "апреля": 4, "квітня": 4,
    "may": 5, "мая": 5, "травня": 5,
    "june": 6, "jun": 6, "июня": 6, "червня": 6,
    "july": 7, "jul": 7, "июля": 7, "липня": 7,
    "august": 8, "aug": 8, "августа": 8, "серпня": 8,
    "september": 9, "sep": 9, "sept": 9, "сентября": 9, "вересня": 9,
    "october": 10, "oct": 10, "октября": 10, "жовтня": 10,
    "november": 11, "nov": 11, "ноября": 11, "листопада": 11,
    "december": 12, "dec": 12, "декабря": 12, "грудня": 12,
}
_MONTH_ALT = "|".join(sorted((re.escape(key) for key in MONTHS), key=len, reverse=True))
DATE_NAMED_DMY_RE = re.compile(
    rf"(?<!\w)(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_ALT})\s*,?\s*(?P<year>(?:19|20|21)\d{{2}})(?!\w)",
    re.IGNORECASE,
)
DATE_NAMED_MDY_RE = re.compile(
    rf"(?<!\w)(?P<month>{_MONTH_ALT})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(?P<year>(?:19|20|21)\d{{2}})(?!\w)",
    re.IGNORECASE,
)

NUMBER = r"(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?"
UNIT_ALIASES = {
    "%": "%",
    "percent": "%",
    "percentage": "%",
    "відсотків": "%",
    "процентів": "%",
    "процентов": "%",
    "km": "km",
    "км": "km",
    "kilometer": "km",
    "kilometers": "km",
    "кілометрів": "km",
    "километров": "km",
    "m": "m",
    "м": "m",
    "meter": "m",
    "meters": "m",
    "метрів": "m",
    "метров": "m",
    "kg": "kg",
    "кг": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "кілограмів": "kg",
    "килограммов": "kg",
    "t": "t",
    "т": "t",
    "ton": "t",
    "tons": "t",
    "tonne": "t",
    "tonnes": "t",
    "тонн": "t",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
    "годин": "h",
    "часов": "h",
    "day": "day",
    "days": "day",
    "днів": "day",
    "дней": "day",
    "month": "month",
    "months": "month",
    "місяців": "month",
    "месяцев": "month",
    "year": "year",
    "years": "year",
    "років": "year",
    "лет": "year",
    "credit": "credit",
    "credits": "credit",
    "кредит": "credit",
    "кредитів": "credit",
    "кредитов": "credit",
    "ects": "ECTS",
    "єктс": "ECTS",
    "usd": "USD",
    "eur": "EUR",
    "uah": "UAH",
    "грн": "UAH",
    "rub": "RUB",
    "руб": "RUB",
    "people": "people",
    "persons": "people",
    "осіб": "people",
    "человек": "people",
}
_UNIT_ALT = "|".join(
    sorted((re.escape(key) for key in UNIT_ALIASES), key=len, reverse=True)
)
METRIC_RE = re.compile(
    rf"(?<![\w.])(?P<number>{NUMBER})\s*(?P<unit>{_UNIT_ALT})(?!\w)",
    re.IGNORECASE,
)

ACRONYM_RE = re.compile(
    r"(?<![\w-])(?P<value>[A-ZА-ЯЁІЇЄҐ]{2,12}(?:-[A-ZА-ЯЁІЇЄҐ0-9]{1,8})?)(?![\w-])"
)
ACRONYM_STOP = {
    "PDF", "DOCX", "TXT", "MD", "HTTP", "HTTPS", "UTF", "SHA",
    "ECTS", "ЄКТС", "FQ", "EHEA", "LLL", "QF", "ID", "URL",
}

PERSON_ALLCAPS_RE = re.compile(
    r"(?<!\w)(?P<name>[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ’'\-]{1,30}\s+[A-ZА-ЯЁІЇЄҐ]{2,30})(?!\w)"
)
PERSON_PATRONYMIC_RE = re.compile(
    r"(?<!\w)(?P<name>"
    r"[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ’'\-]{1,30}\s+"
    r"[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ’'\-]{1,30}"
    r"(?:\s+[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ’'\-]{1,30}"
    r"(?:ович|евич|євич|івич|овна|евна|євна|івна|ївна))?"
    r")"
)

ORG_KEYWORDS = {
    "ministry", "міністерство", "министерство",
    "university", "університет", "университет",
    "academy", "академія", "академия",
    "institute", "інститут", "институт",
    "department", "департамент", "кафедра",
    "faculty", "факультет",
    "agency", "агентство",
    "service", "служба",
    "brigade", "бригада",
    "command", "командування", "командование",
    "corps", "корпус",
    "company", "компанія", "компания",
    "foundation", "фонд",
    "administration", "адміністрація", "администрация",
}
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁёІіЇїЄєҐґ][\w’'\-]*", re.UNICODE)

CLAIM_CUE_RE = re.compile(
    r"\b(?:is|are|was|were|has|have|had|will|can|may|must|should|"
    r"requires?|provides?|indicates?|shows?|reports?|reported|states?|stated|"
    r"announced?|approved|signed|enters?|entered|starts?|started|begins?|began|"
    r"includes?|contains?|increased?|decreased?|destroyed|launched|according\s+to|"
    r"є|становить|має|буде|може|повинен|повинна|повинні|слід|"
    r"вимагає|забезпечує|передбачає|вводиться|затверджено|затвердив|підписав|"
    r"починається|містить|включає|збільшив|зменшив|знищено|"
    r"повідомив|повідомила|заявив|заявила|зазначив|зазначила|"
    r"является|составляет|имеет|будет|может|должен|должна|должны|следует|"
    r"требует|обеспечивает|предусматривает|вводится|утверждено|утвердил|подписал|"
    r"начинается|содержит|включает|увеличил|уменьшил|уничтожено|"
    r"сообщил|сообщила|заявил|заявила|указал|указала)\b",
    re.IGNORECASE,
)
ATTRIBUTION_CUE_RE = re.compile(
    r"\b(?:according\s+to|reports?|reported|states?|stated|announced?|said|"
    r"повідомив|повідомила|заявив|заявила|зазначив|зазначила|"
    r"сообщил|сообщила|заявил|заявила|указал|указала)\b",
    re.IGNORECASE,
)
FORECAST_CUE_RE = re.compile(
    r"\b(?:will|expected|planned|forecast|projected|"
    r"буде|очікується|планується|прогнозується|"
    r"будет|ожидается|планируется|прогнозируется)\b",
    re.IGNORECASE,
)
RECOMMENDATION_CUE_RE = re.compile(
    r"\b(?:should|must|needs?\s+to|requires?|recommended|"
    r"слід|повинен|повинна|повинні|необхідно|рекомендовано|"
    r"следует|должен|должна|должны|необходимо|рекомендуется)\b",
    re.IGNORECASE,
)
CLAIM_NOISE_RE = re.compile(r"_{3,}|\.{5,}|(?:\b\w{1,12}_\b\s*){2,}", re.IGNORECASE)


def analysis_is_stale(db) -> bool:
    latest = db.latest_corpus_analysis_run()
    if not latest:
        return True
    try:
        details = json.loads(str(latest["details_json"] or "{}"))
    except (TypeError, json.JSONDecodeError):
        details = {}
    return (
        int(latest["analyzer_version"] or 0) != ANALYZER_VERSION
        or int(latest["document_count"] or 0) != db.document_count()
        or int(latest["chunk_count"] or 0) != db.chunk_count()
        or str(details.get("chunk_signature") or "") != db.chunk_signature()
    )


def build_corpus_evidence(
    db,
    analysis_config: dict,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    should_pause: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    started = _now()
    document_count = db.document_count()
    chunk_count = db.chunk_count()
    run_id = db.begin_corpus_analysis_run(
        started_at=started,
        analyzer_version=ANALYZER_VERSION,
        document_count=document_count,
        chunk_count=chunk_count,
    )

    batch_size = max(25, int(analysis_config.get("batch_size", 500) or 500))
    context_chars = max(40, int(analysis_config.get("context_chars", 140) or 140))
    max_per_chunk = max(
        10,
        int(analysis_config.get("max_evidence_per_chunk", 80) or 80),
    )
    extract_dates = bool(analysis_config.get("extract_dates", True))
    extract_entities = bool(analysis_config.get("extract_entities", True))
    extract_metrics = bool(analysis_config.get("extract_metrics", True))
    extract_claims = bool(analysis_config.get("extract_claims", True))
    max_claims_per_chunk = max(
        1,
        int(analysis_config.get("max_claims_per_chunk", 12) or 12),
    )

    evidence: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    docs_with_evidence: set[str] = set()
    processed = 0
    start_time = time.monotonic()

    try:
        if progress:
            progress(0, max(1, chunk_count), "Extracting corpus evidence…")

        for batch in db.chunk_batches(batch_size=batch_size):
            _wait_while_paused(should_pause, progress, processed, chunk_count)
            for row in batch:
                items = extract_chunk_evidence(
                    str(row["text"] or ""),
                    document_sha256=str(row["document_sha256"]),
                    chunk_id=int(row["id"]),
                    page=row["page"],
                    context_chars=context_chars,
                    extract_dates=extract_dates,
                    extract_entities=extract_entities,
                    extract_metrics=extract_metrics,
                    extract_claims=extract_claims,
                    max_claims=max_claims_per_chunk,
                )
                if len(items) > max_per_chunk:
                    items = sorted(
                        items,
                        key=lambda item: (
                            -float(item["confidence"]),
                            int(item["start_offset"]),
                            item["kind"],
                        ),
                    )[:max_per_chunk]
                    items.sort(key=lambda item: int(item["start_offset"]))

                evidence.extend(items)
                if items:
                    docs_with_evidence.add(str(row["document_sha256"]))
                    counts.update(item["kind"] for item in items)

                processed += 1
                if progress and (
                    processed == chunk_count
                    or processed % max(1, min(100, batch_size)) == 0
                ):
                    progress(
                        processed,
                        max(1, chunk_count),
                        f"Corpus evidence · {processed}/{chunk_count} chunks",
                    )

        finished = _now()
        details = {
            "analyzer_version": ANALYZER_VERSION,
            "chunk_signature": db.chunk_signature(),
            "documents_with_evidence": len(docs_with_evidence),
            "counts": dict(counts),
            "elapsed_seconds": round(time.monotonic() - start_time, 3),
        }
        db.replace_corpus_evidence(
            run_id=run_id,
            finished_at=finished,
            evidence=evidence,
            details_json=json.dumps(details, ensure_ascii=False),
        )
        if progress:
            progress(
                max(1, chunk_count),
                max(1, chunk_count),
                "Corpus evidence ready",
            )
        return {
            "run_id": run_id,
            "documents": document_count,
            "chunks": chunk_count,
            "documents_with_evidence": len(docs_with_evidence),
            "evidence": len(evidence),
            "dates": int(counts.get("date", 0)),
            "entities": int(counts.get("entity", 0)),
            "metrics": int(counts.get("metric", 0)),
            "claims": int(counts.get("claim", 0)),
            **details,
        }
    except Exception as exc:
        db.fail_corpus_analysis_run(
            run_id,
            finished_at=_now(),
            error=str(exc),
        )
        raise


def extract_chunk_evidence(
    text: str,
    *,
    document_sha256: str,
    chunk_id: int,
    page: int | None,
    context_chars: int = 140,
    extract_dates: bool = True,
    extract_entities: bool = True,
    extract_metrics: bool = True,
    extract_claims: bool = True,
    max_claims: int = 12,
) -> list[dict[str, Any]]:
    text = str(text or "")
    if not text.strip():
        return []

    items: list[dict[str, Any]] = []
    if extract_dates:
        items.extend(
            _extract_dates(
                text,
                document_sha256=document_sha256,
                chunk_id=chunk_id,
                page=page,
                context_chars=context_chars,
            )
        )
    if extract_metrics:
        items.extend(
            _extract_metrics(
                text,
                document_sha256=document_sha256,
                chunk_id=chunk_id,
                page=page,
                context_chars=context_chars,
            )
        )
    if extract_entities:
        items.extend(
            _extract_entities(
                text,
                document_sha256=document_sha256,
                chunk_id=chunk_id,
                page=page,
                context_chars=context_chars,
            )
        )
    if extract_claims:
        items.extend(
            _extract_claims(
                text,
                document_sha256=document_sha256,
                chunk_id=chunk_id,
                page=page,
                context_chars=context_chars,
                limit=max(1, int(max_claims)),
            )
        )

    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        key = (
            item["kind"],
            item.get("subtype", ""),
            item["normalized_value"],
            int(item["start_offset"]),
            int(item["end_offset"]),
        )
        old = deduped.get(key)
        if old is None or float(item["confidence"]) > float(old["confidence"]):
            deduped[key] = item
    return sorted(
        deduped.values(),
        key=lambda item: (
            int(item["start_offset"]),
            item["kind"],
            item.get("subtype", ""),
        ),
    )


def _extract_claims(
    text: str,
    *,
    document_sha256: str,
    chunk_id: int,
    page: int | None,
    context_chars: int,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for start, end, sentence in _sentence_spans(text):
        compact = re.sub(r"\s+", " ", sentence).strip()
        if not _is_claim_candidate(compact):
            continue

        cue = CLAIM_CUE_RE.search(compact)
        if not cue:
            continue

        subtype = "assertion_candidate"
        if ATTRIBUTION_CUE_RE.search(compact):
            subtype = "attributed_candidate"
        elif FORECAST_CUE_RE.search(compact):
            subtype = "forecast_candidate"
        elif RECOMMENDATION_CUE_RE.search(compact):
            subtype = "recommendation_candidate"

        confidence = 0.58
        if DATE_DMY_RE.search(compact) or DATE_YMD_RE.search(compact):
            confidence += 0.07
        if DATE_NAMED_DMY_RE.search(compact) or DATE_NAMED_MDY_RE.search(compact):
            confidence += 0.07
        if METRIC_RE.search(compact):
            confidence += 0.07
        if ORG_KEYWORDS.intersection(
            token.group(0).casefold() for token in WORD_RE.finditer(compact)
        ):
            confidence += 0.05
        if PERSON_ALLCAPS_RE.search(compact) or PERSON_PATRONYMIC_RE.search(compact):
            confidence += 0.05
        if subtype == "attributed_candidate":
            confidence += 0.06

        candidates.append(
            _item(
                text,
                start,
                end,
                document_sha256=document_sha256,
                chunk_id=chunk_id,
                page=page,
                kind="claim",
                subtype=subtype,
                value=compact,
                normalized_value=_normalize_claim(compact),
                confidence=min(0.86, confidence),
                context_chars=context_chars,
                metadata={
                    "method": "declarative_rule_v1",
                    "cue": cue.group(0),
                    "candidate": True,
                },
            )
        )

    candidates.sort(
        key=lambda item: (
            -float(item["confidence"]),
            int(item["start_offset"]),
        )
    )
    selected = candidates[:limit]
    selected.sort(key=lambda item: int(item["start_offset"]))
    return selected


def _sentence_spans(text: str):
    length = len(text)
    start = 0
    index = 0
    while index < length:
        boundary = False
        char = text[index]
        if char in ".!?":
            next_index = index + 1
            boundary = next_index >= length or text[next_index].isspace()
        elif char == "\n" and index + 1 < length and text[index + 1] == "\n":
            boundary = True

        if boundary:
            end = index + 1
            raw = text[start:end]
            left_trim = len(raw) - len(raw.lstrip())
            right_trimmed = raw.rstrip()
            sentence_start = start + left_trim
            sentence_end = start + len(right_trimmed)
            if sentence_end > sentence_start:
                yield sentence_start, sentence_end, text[sentence_start:sentence_end]
            index += 1
            while index < length and text[index].isspace():
                index += 1
            start = index
            continue
        index += 1

    if start < length:
        raw = text[start:]
        left_trim = len(raw) - len(raw.lstrip())
        right_trimmed = raw.rstrip()
        sentence_start = start + left_trim
        sentence_end = start + len(right_trimmed)
        if sentence_end > sentence_start:
            yield sentence_start, sentence_end, text[sentence_start:sentence_end]


def _is_claim_candidate(sentence: str) -> bool:
    if not 45 <= len(sentence) <= 520:
        return False
    words = WORD_RE.findall(sentence)
    if not 7 <= len(words) <= 90:
        return False
    if CLAIM_NOISE_RE.search(sentence):
        return False
    letters = [char for char in sentence if char.isalpha()]
    if letters:
        uppercase = sum(char.isupper() for char in letters)
        if len(sentence) < 180 and uppercase / len(letters) > 0.72:
            return False
    if sentence.rstrip().endswith(":"):
        return False
    return bool(CLAIM_CUE_RE.search(sentence))


def _normalize_claim(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = value.rstrip(" .!?;:")
    return value.casefold()


def _extract_dates(
    text: str,
    *,
    document_sha256: str,
    chunk_id: int,
    page: int | None,
    context_chars: int,
) -> list[dict[str, Any]]:
    items = []
    for regex, order, confidence in (
        (DATE_DMY_RE, "dmy", 0.99),
        (DATE_YMD_RE, "ymd", 0.99),
        (DATE_NAMED_DMY_RE, "named_dmy", 0.98),
        (DATE_NAMED_MDY_RE, "named_mdy", 0.97),
    ):
        for match in regex.finditer(text):
            try:
                if order in {"named_dmy", "named_mdy"}:
                    month = MONTHS[match.group("month").casefold()]
                else:
                    month = int(match.group("month"))
                parsed = date(
                    int(match.group("year")),
                    month,
                    int(match.group("day")),
                )
            except (KeyError, TypeError, ValueError):
                continue
            items.append(
                _item(
                    text,
                    match.start(),
                    match.end(),
                    document_sha256=document_sha256,
                    chunk_id=chunk_id,
                    page=page,
                    kind="date",
                    subtype="calendar",
                    value=match.group(0),
                    normalized_value=parsed.isoformat(),
                    confidence=confidence,
                    context_chars=context_chars,
                    metadata={"format": order},
                )
            )
    return items


def _extract_metrics(
    text: str,
    *,
    document_sha256: str,
    chunk_id: int,
    page: int | None,
    context_chars: int,
) -> list[dict[str, Any]]:
    items = []
    for match in METRIC_RE.finditer(text):
        number = _normalize_number(match.group("number"))
        unit_raw = match.group("unit").casefold().strip().rstrip(".")
        unit = UNIT_ALIASES.get(unit_raw)
        if unit is None:
            continue
        normalized = f"{number} {unit}".strip()
        items.append(
            _item(
                text,
                match.start(),
                match.end(),
                document_sha256=document_sha256,
                chunk_id=chunk_id,
                page=page,
                kind="metric",
                subtype=_metric_subtype(unit),
                value=match.group(0),
                normalized_value=normalized,
                confidence=0.96,
                context_chars=context_chars,
                metadata={"number": number, "unit": unit},
            )
        )
    return items


def _extract_entities(
    text: str,
    *,
    document_sha256: str,
    chunk_id: int,
    page: int | None,
    context_chars: int,
) -> list[dict[str, Any]]:
    items = []
    person_spans: list[tuple[int, int]] = []

    for match in PERSON_ALLCAPS_RE.finditer(text):
        name = _clean_entity(match.group("name"))
        if _valid_person(name):
            person_spans.append((match.start("name"), match.end("name")))
            items.append(
                _item(
                    text,
                    match.start("name"),
                    match.end("name"),
                    document_sha256=document_sha256,
                    chunk_id=chunk_id,
                    page=page,
                    kind="entity",
                    subtype="person",
                    value=name,
                    normalized_value=_normalize_entity(name),
                    confidence=0.88,
                    context_chars=context_chars,
                    metadata={"method": "name_allcaps"},
                )
            )

    for match in PERSON_PATRONYMIC_RE.finditer(text):
        name = _clean_entity(match.group("name"))
        if _valid_patronymic_person(name):
            person_spans.append((match.start("name"), match.end("name")))
            items.append(
                _item(
                    text,
                    match.start("name"),
                    match.end("name"),
                    document_sha256=document_sha256,
                    chunk_id=chunk_id,
                    page=page,
                    kind="entity",
                    subtype="person",
                    value=name,
                    normalized_value=_normalize_entity(name),
                    confidence=0.82,
                    context_chars=context_chars,
                    metadata={"method": "patronymic"},
                )
            )

    for match in ACRONYM_RE.finditer(text):
        value = match.group("value").strip()
        if value.casefold().upper() in ACRONYM_STOP:
            continue
        if any(
            match.start("value") >= start and match.end("value") <= end
            for start, end in person_spans
        ):
            continue
        cyrillic_only = all(
            ("А" <= char <= "Я") or char in "ЁІЇЄҐ"
            for char in value
            if char.isalpha()
        )
        if cyrillic_only and len(value.replace("-", "")) > 4:
            continue
        items.append(
            _item(
                text,
                match.start("value"),
                match.end("value"),
                document_sha256=document_sha256,
                chunk_id=chunk_id,
                page=page,
                kind="entity",
                subtype="acronym",
                value=value,
                normalized_value=value.upper(),
                confidence=0.68,
                context_chars=context_chars,
                metadata={"method": "acronym"},
            )
        )

    items.extend(
        _organization_items(
            text,
            document_sha256=document_sha256,
            chunk_id=chunk_id,
            page=page,
            context_chars=context_chars,
        )
    )
    return items


def _organization_items(
    text: str,
    *,
    document_sha256: str,
    chunk_id: int,
    page: int | None,
    context_chars: int,
) -> list[dict[str, Any]]:
    items = []
    for segment_match in re.finditer(r"[^\n.!?;]{2,240}", text):
        segment = segment_match.group(0)
        tokens = list(WORD_RE.finditer(segment))
        if not tokens:
            continue
        keyword_indexes = [
            index
            for index, token in enumerate(tokens)
            if token.group(0).casefold() in ORG_KEYWORDS
        ]
        for keyword_index in keyword_indexes:
            start_index = max(0, keyword_index - 7)
            end_index = min(len(tokens), keyword_index + 7)
            phrase_start = tokens[start_index].start()
            phrase_end = tokens[end_index - 1].end()
            phrase = _clean_entity(segment[phrase_start:phrase_end])
            words = phrase.split()
            if not (2 <= len(words) <= 14):
                continue
            if len(phrase) > 180:
                continue
            absolute_start = segment_match.start() + phrase_start
            absolute_end = segment_match.start() + phrase_end
            items.append(
                _item(
                    text,
                    absolute_start,
                    absolute_end,
                    document_sha256=document_sha256,
                    chunk_id=chunk_id,
                    page=page,
                    kind="entity",
                    subtype="organization",
                    value=phrase,
                    normalized_value=_normalize_entity(phrase),
                    confidence=0.74,
                    context_chars=context_chars,
                    metadata={"method": "organization_keyword"},
                )
            )
    return items


def _item(
    text: str,
    start: int,
    end: int,
    *,
    document_sha256: str,
    chunk_id: int,
    page: int | None,
    kind: str,
    subtype: str,
    value: str,
    normalized_value: str,
    confidence: float,
    context_chars: int,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "document_sha256": document_sha256,
        "chunk_id": int(chunk_id),
        "page": page,
        "kind": kind,
        "subtype": subtype,
        "value": value,
        "normalized_value": normalized_value,
        "context": _context(text, start, end, context_chars),
        "start_offset": int(start),
        "end_offset": int(end),
        "confidence": float(confidence),
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
    }


def _context(text: str, start: int, end: int, context_chars: int) -> str:
    left = max(0, int(start) - context_chars)
    right = min(len(text), int(end) + context_chars)
    value = re.sub(r"\s+", " ", text[left:right]).strip()
    return value


def _normalize_number(value: str) -> str:
    value = str(value or "").replace("\u00a0", " ").strip()
    value = re.sub(r"(?<=\d)\s+(?=\d)", "", value)
    value = value.replace(",", ".")
    return value


def _metric_subtype(unit: str) -> str:
    if unit in {"USD", "EUR", "UAH", "RUB"}:
        return "currency"
    if unit == "%":
        return "percentage"
    if unit in {"day", "month", "year", "h"}:
        return "duration"
    if unit in {"km", "m"}:
        return "distance"
    if unit in {"kg", "t"}:
        return "mass"
    if unit in {"credit", "ECTS"}:
        return "education"
    if unit == "people":
        return "people"
    return "measurement"


def _clean_entity(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;:.()[]{}")
    return value


def _normalize_entity(value: str) -> str:
    value = _clean_entity(value).casefold()
    value = re.sub(r"[^0-9a-zа-яёіїєґ’'\- ]+", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _valid_person(name: str) -> bool:
    parts = name.split()
    if len(parts) != 2:
        return False
    return len(parts[0]) >= 2 and len(parts[1]) >= 2


def _valid_patronymic_person(name: str) -> bool:
    parts = name.split()
    if len(parts) < 2 or len(parts) > 3:
        return False
    last = parts[-1].casefold()
    patronymic = (
        "ович", "евич", "євич", "івич",
        "овна", "евна", "євна", "івна", "ївна",
    )
    if any(last.endswith(suffix) for suffix in patronymic):
        return True
    # Two-word surname + given-name candidates are accepted only when both
    # tokens are title-cased; this keeps confidence conservative.
    return len(parts) == 2 and all(part[:1].isupper() for part in parts)


def _wait_while_paused(
    should_pause: Callable[[], bool] | None,
    progress: Callable[[int, int, str], None] | None,
    current: int,
    total: int,
) -> None:
    if should_pause is None:
        return
    announced = False
    while should_pause():
        if progress is not None and not announced:
            progress(current, max(1, total), "Corpus analysis paused for Chat/Ask…")
            announced = True
        time.sleep(0.2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
