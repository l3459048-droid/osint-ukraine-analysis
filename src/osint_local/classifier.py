from __future__ import annotations

import re


def classify(text: str, config: dict) -> list[tuple[str, int]]:
    normalized = text.casefold()
    domains = config.get("domains", {})
    min_score = int(config.get("min_score", 1))
    result: list[tuple[str, int]] = []

    for domain, keywords in domains.items():
        score = 0
        for keyword in keywords:
            token = str(keyword).casefold().strip()
            if token:
                score += len(re.findall(re.escape(token), normalized))
        if score >= min_score:
            result.append((domain, score))

    return sorted(result, key=lambda item: (-item[1], item[0].casefold()))
