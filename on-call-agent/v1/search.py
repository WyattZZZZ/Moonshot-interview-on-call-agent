from __future__ import annotations

import re
import sqlite3
from typing import Any

from database.tokenizer import tokenize_for_search


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")


def build_fts_query(raw_query: str) -> str | None:
    tokens = tokenize_for_search(raw_query)
    if not tokens:
        return None
    return " OR ".join(f'"{token.replace(chr(34), chr(34) + chr(34))}"' for token in tokens)


def make_plain_snippet(text: str, query: str, size: int = 140) -> str:
    if not text:
        return ""
    lowered = text.lower()
    candidates = TOKEN_RE.findall(query) or [query]
    positions = [lowered.find(part.lower()) for part in candidates if part and lowered.find(part.lower()) >= 0]
    pos = min(positions) if positions else 0
    start = max(0, pos - size // 3)
    end = min(len(text), start + size)
    snippet = text[start:end].replace("\n", " ")
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet += "..."
    return snippet


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def append_literal_matches(
    conn: sqlite3.Connection,
    *,
    query: str,
    results: list[dict[str, Any]],
    seen: set[str],
    limit: int,
) -> None:
    terms = [query, *TOKEN_RE.findall(query)]
    patterns = [f"%{escape_like(term)}%" for term in terms if term]
    if not patterns:
        return

    clauses = " OR ".join(["title LIKE ? ESCAPE '\\' OR clean_text LIKE ? ESCAPE '\\'"] * len(patterns))
    params: list[Any] = []
    for pattern in patterns:
        params.extend([pattern, pattern])
    params.append(limit * 3)
    rows = conn.execute(
        f"""
        SELECT id, title, clean_text
          FROM documents
         WHERE {clauses}
         ORDER BY updated_at DESC
         LIMIT ?
        """,
        params,
    ).fetchall()
    for row in rows:
        if row["id"] in seen:
            continue
        results.append(
            {
                "id": row["id"],
                "title": row["title"],
                "snippet": make_plain_snippet(row["clean_text"], query),
                "score": 0.05,
            }
        )
        seen.add(row["id"])
        if len(results) >= limit:
            return


def search_documents(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    fts_query = build_fts_query(query)
    if fts_query:
        try:
            rows = conn.execute(
                """
                SELECT d.id,
                       d.title,
                       d.clean_text,
                       bm25(document_fts) AS rank
                  FROM document_fts
                  JOIN documents d ON d.id = document_fts.doc_id
                 WHERE document_fts MATCH ?
                 ORDER BY rank
                 LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            raw_scores = [max(float(-row["rank"]), 0.0) for row in rows]
            max_score = max(raw_scores, default=0.0)
            for row, raw_score in zip(rows, raw_scores):
                score = raw_score / max_score if max_score > 0 else 1.0
                results.append(
                    {
                        "id": row["id"],
                        "title": row["title"],
                        "snippet": make_plain_snippet(row["clean_text"], query),
                        "score": round(max(score, 0.1), 4),
                    }
                )
                seen.add(row["id"])
        except sqlite3.OperationalError:
            pass

    append_literal_matches(conn, query=query, results=results, seen=seen, limit=limit)
    return results
