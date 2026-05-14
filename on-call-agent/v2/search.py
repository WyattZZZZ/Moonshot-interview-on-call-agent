from __future__ import annotations

from typing import Any

from database import chroma_store

from semantic import embed_query_text


def search_documents_semantic(query: str, limit: int = 10) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    query_embedding = embed_query_text(query)
    chunk_rows = chroma_store.query(embedding=query_embedding, limit=max(limit * 6, 30))
    documents: dict[str, dict[str, Any]] = {}
    for row in chunk_rows:
        doc_id = str(row.get("document_id", "")).strip()
        if not doc_id:
            continue
        similarity = _distance_to_similarity(row.get("distance"))
        current = documents.get(doc_id)
        if current is None or similarity > current["score"]:
            documents[doc_id] = {
                "id": doc_id,
                "title": str(row.get("title", "")).strip(),
                "snippet": _make_snippet(str(row.get("chunk_text", ""))),
                "score": round(similarity, 4),
                "matched_chunk_id": row.get("chunk_id"),
                "matched_chunk_index": row.get("chunk_index"),
                "matched_chunk_heading": str(row.get("heading", "")).strip(),
                "matched_chunk_heading_path": str(row.get("heading_path", "")).strip(),
                "matched_chunk": {
                    "id": row.get("chunk_id"),
                    "heading": str(row.get("heading", "")).strip(),
                    "heading_path": str(row.get("heading_path", "")).strip(),
                    "snippet": _make_snippet(str(row.get("chunk_text", ""))),
                },
                "chunk_count": _safe_int(row.get("chunk_count")),
            }

    if not documents:
        return []

    results = sorted(
        documents.values(),
        key=lambda item: (item["score"], item.get("matched_chunk_index", 0), item["id"]),
        reverse=True,
    )
    return results[:limit]


def _distance_to_similarity(distance: Any) -> float:
    try:
        return max(0.0, min(1.0, 1.0 - float(distance)))
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _make_snippet(text: str, size: int = 220) -> str:
    stripped = " ".join(text.split())
    if len(stripped) <= size:
        return stripped
    return stripped[: size - 1].rstrip() + "…"
