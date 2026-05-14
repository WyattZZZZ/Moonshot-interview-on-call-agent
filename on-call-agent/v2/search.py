from __future__ import annotations

import sqlite3
from typing import Any

from v1.search import append_literal_matches, build_fts_query, make_plain_snippet

from semantic import build_query_vector, cosine_similarity, load_profile, load_vector


KEYWORD_WEIGHT = 0.58
SEMANTIC_WEIGHT = 0.42


def search_documents_hybrid(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    keyword_scores = _keyword_scores(conn, query, limit=max(limit * 4, 20))
    semantic_scores = _semantic_scores(conn, query)
    candidate_ids = set(keyword_scores) | set(semantic_scores)

    if not candidate_ids:
        literal_results: list[dict[str, Any]] = []
        append_literal_matches(conn, query=query, results=literal_results, seen=set(), limit=limit)
        return [
            {
                **item,
                "keyword_score": item.get("score", 0.0),
                "semantic_score": 0.0,
                "semantic_profile": None,
            }
            for item in literal_results
        ]

    placeholders = ",".join("?" for _ in candidate_ids)
    rows = conn.execute(
        f"""
        SELECT id, title, clean_text, semantic_profile
          FROM documents
         WHERE id IN ({placeholders})
        """,
        sorted(candidate_ids),
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        keyword_score = keyword_scores.get(row["id"], 0.0)
        semantic_score = semantic_scores.get(row["id"], 0.0)
        score = KEYWORD_WEIGHT * keyword_score + SEMANTIC_WEIGHT * semantic_score
        results.append(
            {
                "id": row["id"],
                "title": row["title"],
                "snippet": make_plain_snippet(row["clean_text"], query),
                "score": round(score, 4),
                "keyword_score": round(keyword_score, 4),
                "semantic_score": round(semantic_score, 4),
                "semantic_profile": load_profile(row["semantic_profile"]),
            }
        )

    results.sort(key=lambda item: (item["score"], item["keyword_score"], item["semantic_score"], item["id"]), reverse=True)
    return results[:limit]


def _keyword_scores(conn: sqlite3.Connection, query: str, limit: int) -> dict[str, float]:
    fts_query = build_fts_query(query)
    if not fts_query:
        return {}
    try:
        rows = conn.execute(
            """
            SELECT d.id,
                   bm25(document_fts) AS rank
              FROM document_fts
              JOIN documents d ON d.id = document_fts.doc_id
             WHERE document_fts MATCH ?
             ORDER BY rank
             LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    raw_scores = [max(float(-row["rank"]), 0.0) for row in rows]
    max_score = max(raw_scores, default=0.0)
    scores: dict[str, float] = {}
    for row, raw_score in zip(rows, raw_scores):
        scores[row["id"]] = raw_score / max_score if max_score > 0 else 1.0
    return scores


def _semantic_scores(conn: sqlite3.Connection, query: str) -> dict[str, float]:
    query_vector = build_query_vector(query)
    if not query_vector:
        return {}
    rows = conn.execute(
        """
        SELECT d.id, COALESCE(e.vector, d.embedding) AS vector
          FROM documents d
          LEFT JOIN embeddings e ON e.document_id = d.id
        """
    ).fetchall()
    scores: dict[str, float] = {}
    for row in rows:
        score = cosine_similarity(query_vector, load_vector(row["vector"]))
        if score > 0:
            scores[row["id"]] = score
    max_score = max(scores.values(), default=0.0)
    if max_score <= 0:
        return {}
    return {doc_id: score / max_score for doc_id, score in scores.items()}
