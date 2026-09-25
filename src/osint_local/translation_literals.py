from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable

# Match immutable facts before broad numeric tokens. The order matters.
_LITERAL_RE = re.compile(
    r"https?://[^\s<>()]+"
    r"|\b[a-fA-F0-9]{32,64}\b"
    r"|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b"
    r"|\b(?:QF-LLL|EHEA|ECTS|ЕКТС|FQ|НРК|УД|J\d+)\b"
    r"|\b\d+(?:[.,:/-]\d+)+\b"
    r"|\b\d+(?:[.,]\d+)?\b",
    re.IGNORECASE | re.UNICODE,
)


@dataclass(frozen=True)
class ProtectedLiteral:
    placeholder: str
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class LiteralProtection:
    source: str
    masked_text: str
    literals: tuple[ProtectedLiteral, ...]

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.literals)


def protect_literals(text: str) -> LiteralProtection:
    source = str(text or "")
    matches = list(_LITERAL_RE.finditer(source))
    if not matches:
        return LiteralProtection(source, source, ())

    pieces: list[str] = []
    literals: list[ProtectedLiteral] = []
    last = 0
    for index, match in enumerate(matches, 1):
        placeholder = f"ZXQLIT{index:04d}QXZ"
        pieces.append(source[last:match.start()])
        pieces.append(placeholder)
        literals.append(
            ProtectedLiteral(
                placeholder=placeholder,
                value=match.group(0),
                start=match.start(),
                end=match.end(),
            )
        )
        last = match.end()
    pieces.append(source[last:])
    return LiteralProtection(source, "".join(pieces), tuple(literals))


def restore_literals(protection: LiteralProtection, translated: str) -> tuple[str, bool]:
    value = str(translated or "")
    if not protection.literals:
        return value, True

    positions: list[int] = []
    for item in protection.literals:
        if value.count(item.placeholder) != 1:
            return value, False
        positions.append(value.index(item.placeholder))
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        return value, False

    for item in protection.literals:
        value = value.replace(item.placeholder, item.value, 1)
    return value, True


def extract_protected_literals(text: str) -> tuple[str, ...]:
    return protect_literals(text).values


def missing_protected_literals(source: str, translated: str) -> tuple[str, ...]:
    output = str(translated or "")
    required = Counter(extract_protected_literals(source))
    missing: list[str] = []
    for literal, count in required.items():
        present = output.count(literal)
        if present < count:
            missing.extend([literal] * (count - present))
    return tuple(missing)


def _translate_fragment_preserving_whitespace(
    fragment: str,
    translate_raw: Callable[[str], str],
) -> str:
    if not fragment:
        return ""
    leading = fragment[: len(fragment) - len(fragment.lstrip())]
    trailing = fragment[len(fragment.rstrip()) :]
    core = fragment.strip()
    if not core:
        return fragment
    translated = str(translate_raw(core) or "").strip()
    return leading + translated + trailing


def translate_preserving_literals(
    text: str,
    translate_raw: Callable[[str], str],
) -> tuple[str, bool]:
    """Translate text while guaranteeing protected literals are restored exactly.

    The normal path masks literals so the model keeps sentence context. If the
    model mutates a placeholder, fall back to translating only the text spans
    between literals and splice the original literal values back unchanged.
    The returned boolean is True when the normal masked path survived intact.
    """
    protection = protect_literals(text)
    if not protection.literals:
        return str(translate_raw(protection.source) or ""), True

    masked_output = str(translate_raw(protection.masked_text) or "")
    restored, intact = restore_literals(protection, masked_output)
    if intact:
        return restored, True

    pieces: list[str] = []
    cursor = 0
    for item in protection.literals:
        pieces.append(
            _translate_fragment_preserving_whitespace(
                protection.source[cursor:item.start],
                translate_raw,
            )
        )
        pieces.append(item.value)
        cursor = item.end
    pieces.append(
        _translate_fragment_preserving_whitespace(
            protection.source[cursor:],
            translate_raw,
        )
    )
    return "".join(pieces), False
