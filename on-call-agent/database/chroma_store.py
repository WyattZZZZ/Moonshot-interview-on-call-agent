from __future__ import annotations

import os
from threading import Lock
from pathlib import Path
from typing import Any

import chromadb


DATABASE_DIR = Path(__file__).resolve().parent
DEFAULT_CHROMA_DIR = DATABASE_DIR / "chroma"
COLLECTION_NAME = "v2_chunks"
_CACHE_LOCK = Lock()
_CLIENTS: dict[Path, chromadb.PersistentClient] = {}
_COLLECTIONS: dict[Path, Any] = {}


def default_chroma_path() -> Path:
    return Path(os.environ.get("ON_CALL_AGENT_CHROMA_DIR", DEFAULT_CHROMA_DIR)).resolve()


def _client() -> chromadb.PersistentClient:
    path = default_chroma_path()
    path.mkdir(parents=True, exist_ok=True)
    with _CACHE_LOCK:
        client = _CLIENTS.get(path)
        if client is None:
            client = chromadb.PersistentClient(path=str(path))
            _CLIENTS[path] = client
        return client


def get_collection():
    path = default_chroma_path()
    with _CACHE_LOCK:
        collection = _COLLECTIONS.get(path)
        if collection is not None:
            return collection
    client = _client()
    collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    with _CACHE_LOCK:
        _COLLECTIONS[path] = collection
    return collection


def upsert_chunks(
    *,
    document_id: str,
    title: str,
    path: str,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
    embedding_model: str | None = None,
) -> None:
    if not chunks:
        return
    collection = get_collection()
    ids = [chunk["chunk_id"] for chunk in chunks]
    documents = [chunk["chunk_text"] for chunk in chunks]
    metadatas = [
        {
            "document_id": document_id,
            "chunk_id": chunk["chunk_id"],
            "chunk_index": int(chunk["chunk_index"]),
            "heading": chunk.get("heading", ""),
            "heading_path": chunk.get("heading_path", ""),
            "title": title,
            "path": path,
            "embedding_model": embedding_model or "",
            "chunk_count": len(chunks),
        }
        for chunk in chunks
    ]
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )


def delete_document(document_id: str) -> None:
    collection = get_collection()
    collection.delete(where={"document_id": document_id})


def get_document_chunks(document_id: str) -> list[dict[str, Any]]:
    collection = get_collection()
    result = collection.get(where={"document_id": document_id}, include=["documents", "metadatas"])
    ids = result.get("ids", []) or []
    documents = result.get("documents", []) or []
    metadatas = result.get("metadatas", []) or []
    chunks: list[dict[str, Any]] = []
    for chunk_id, document, metadata in zip(ids, documents, metadatas):
        item = dict(metadata or {})
        item["chunk_id"] = chunk_id
        item["chunk_text"] = document or ""
        chunks.append(item)
    chunks.sort(key=lambda item: int(item.get("chunk_index", 0)))
    return chunks


def query(
    *,
    embedding: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    collection = get_collection()
    count = collection.count()
    if count <= 0:
        return []
    result = collection.query(
        query_embeddings=[embedding],
        n_results=max(1, min(limit, count)),
        include=["documents", "metadatas", "distances"],
    )
    ids = result.get("ids", [[]])[0] or []
    documents = result.get("documents", [[]])[0] or []
    metadatas = result.get("metadatas", [[]])[0] or []
    distances = result.get("distances", [[]])[0] or []
    rows: list[dict[str, Any]] = []
    for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        row = dict(metadata or {})
        row["chunk_id"] = chunk_id
        row["chunk_text"] = document or ""
        row["distance"] = float(distance)
        rows.append(row)
    return rows
