from __future__ import annotations

import os
from threading import Lock
from typing import Iterable


if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

DEFAULT_EMBEDDING_MODEL = os.environ.get("ON_CALL_AGENT_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
DEFAULT_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_MODEL_LOCK = Lock()
_MODEL = None
_MODEL_NAME = None


def get_model(model_name: str = DEFAULT_EMBEDDING_MODEL):
    global _MODEL, _MODEL_NAME
    with _MODEL_LOCK:
        if _MODEL is None or _MODEL_NAME != model_name:
            from sentence_transformers import SentenceTransformer

            _MODEL = SentenceTransformer(model_name)
            _MODEL_NAME = model_name
        return _MODEL


def embed_texts(texts: Iterable[str], *, model: str = DEFAULT_EMBEDDING_MODEL) -> list[list[float]]:
    normalized = [text.replace("\n", " ").strip() for text in texts]
    if not normalized:
        return []
    model_obj = get_model(model)
    vectors = model_obj.encode(
        normalized,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [list(map(float, vector)) for vector in vectors]


def embed_text(text: str, *, model: str = DEFAULT_EMBEDDING_MODEL) -> list[float]:
    return embed_texts([text], model=model)[0]


def embed_query_text(text: str, *, model: str = DEFAULT_EMBEDDING_MODEL) -> list[float]:
    query = text.replace("\n", " ").strip()
    if not query:
        return embed_text("", model=model)
    return embed_text(f"{DEFAULT_QUERY_INSTRUCTION}{query}", model=model)


def chunk_embedding_text(heading_path: str, chunk_text: str) -> str:
    pieces = [heading_path.strip(), chunk_text.strip()]
    return "\n".join(piece for piece in pieces if piece)
