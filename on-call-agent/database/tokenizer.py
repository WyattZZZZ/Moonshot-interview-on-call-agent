from __future__ import annotations

import re

try:
    import jieba
except ImportError as exc:  # pragma: no cover - exercised when dependency is missing locally.
    raise RuntimeError("jieba is required for Chinese keyword search. Install with: pip install jieba") from exc


ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize_for_search(text: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in jieba.cut_for_search(text):
        token = raw.strip()
        if not token:
            continue
        normalized = token.lower() if ASCII_TOKEN_RE.fullmatch(token) else token
        if normalized not in seen:
            tokens.append(normalized)
            seen.add(normalized)
    return tokens


def tokenized_text(text: str) -> str:
    return " ".join(tokenize_for_search(text))
