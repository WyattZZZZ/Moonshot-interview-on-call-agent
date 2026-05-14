from __future__ import annotations

import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ON_CALL_ROOT = Path(__file__).resolve().parents[1]
V1_ROOT = ON_CALL_ROOT / "v1"
V2_ROOT = ON_CALL_ROOT / "v2"
REPO_ROOT = ON_CALL_ROOT.parent

for import_path in (ON_CALL_ROOT,):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from database import db


SearchFn = Callable[[str, int], list[dict[str, Any]]]
CANDIDATE_THRESHOLD = 0.75


@dataclass(frozen=True)
class CandidateWeights:
    keyword: float = 0.5
    semantic: float = 0.5

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "CandidateWeights":
        payload = payload or {}
        raw_keyword = payload.get("keyword", payload.get("v1", payload.get("lexical", 0.5)))
        raw_semantic = payload.get("semantic", payload.get("v2", 0.5))
        keyword = _coerce_weight(raw_keyword, 0.5)
        semantic = _coerce_weight(raw_semantic, 0.5)
        total = keyword + semantic
        if total <= 0:
            return cls()
        return cls(keyword=keyword / total, semantic=semantic / total)


def build_candidates(
    *,
    query: str,
    weights: CandidateWeights,
    db_path: Path,
    limit: int = 10,
    threshold: float = CANDIDATE_THRESHOLD,
    keyword_search: SearchFn | None = None,
    semantic_search: SearchFn | None = None,
) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []

    keyword_fn = keyword_search or (lambda raw_query, raw_limit: _keyword_search(db_path, raw_query, raw_limit))
    semantic_fn = semantic_search or _semantic_search
    with ThreadPoolExecutor(max_workers=2) as executor:
        keyword_future = executor.submit(keyword_fn, query, limit)
        semantic_future = executor.submit(semantic_fn, query, limit)
        keyword_results = _normalize_scores(keyword_future.result())
        semantic_results = _normalize_scores(semantic_future.result())

    merged: dict[str, dict[str, Any]] = {}
    for item in keyword_results:
        doc_id = str(item.get("id", "")).strip()
        if not doc_id:
            continue
        entry = merged.setdefault(doc_id, _base_candidate(item))
        entry["keyword_score"] = _score(item.get("score"))
        entry["keyword_snippet"] = item.get("snippet", "")

    for item in semantic_results:
        doc_id = str(item.get("id", "")).strip()
        if not doc_id:
            continue
        entry = merged.setdefault(doc_id, _base_candidate(item))
        if not entry.get("title") and item.get("title"):
            entry["title"] = item.get("title")
        entry["semantic_score"] = _score(item.get("score"))
        entry["semantic_snippet"] = item.get("snippet", "")
        entry["matched_chunk_heading"] = item.get("matched_chunk_heading", "")
        entry["matched_chunk_heading_path"] = item.get("matched_chunk_heading_path", "")

    candidates: list[dict[str, Any]] = []
    for doc_id, entry in merged.items():
        combined = weights.keyword * entry["keyword_score"] + weights.semantic * entry["semantic_score"]
        entry["combined_score"] = round(combined, 4)
        entry["filename"] = _filename_for_doc(entry)
        entry["summary"] = _summary_for_candidate(entry)
        if entry["combined_score"] >= threshold:
            candidates.append(entry)

    candidates.sort(key=lambda item: (item["combined_score"], item["semantic_score"], item["keyword_score"]), reverse=True)
    return candidates[:limit]


def _keyword_search(db_path: Path, query: str, limit: int) -> list[dict[str, Any]]:
    module = _load_module("v3_v1_search", V1_ROOT / "search.py", expected_attrs=("search_documents",))
    with db.connection(db_path) as conn:
        db.initialize(conn)
        return module.search_documents(conn, query, limit=limit)


def _semantic_search(query: str, limit: int) -> list[dict[str, Any]]:
    if str(V2_ROOT) not in sys.path:
        sys.path.insert(0, str(V2_ROOT))
    module = _load_module("v3_v2_search", V2_ROOT / "search.py", expected_attrs=("search_documents_semantic",))
    return module.search_documents_semantic(query, limit=limit)


def _load_module(name: str, path: Path, *, expected_attrs: tuple[str, ...] = ()):
    existing = sys.modules.get(name)
    if existing is not None and all(hasattr(existing, attr) for attr in expected_attrs):
        return existing
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _base_candidate(item: dict[str, Any]) -> dict[str, Any]:
    doc_id = str(item.get("id", "")).strip()
    return {
        "id": doc_id,
        "title": str(item.get("title", "")).strip(),
        "path": str(item.get("path", "")).strip(),
        "filename": "",
        "summary": "",
        "keyword_score": 0.0,
        "semantic_score": 0.0,
        "combined_score": 0.0,
    }


def _filename_for_doc(item: dict[str, Any]) -> str:
    path = str(item.get("path", "")).strip()
    if path:
        return Path(path).name
    doc_id = str(item.get("id", "")).strip()
    return doc_id if Path(doc_id).suffix else f"{doc_id}.html"


def _summary_for_candidate(item: dict[str, Any]) -> str:
    pieces = [
        str(item.get("semantic_snippet", "")).strip(),
        str(item.get("keyword_snippet", "")).strip(),
        str(item.get("matched_chunk_heading_path", "")).strip(),
    ]
    summary = " ".join(piece for piece in pieces if piece)
    return _squash(summary)[:500]


def _squash(text: str) -> str:
    return " ".join(text.split())


def _coerce_weight(value: Any, default: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _score(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_scores(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_score = max((_score(item.get("score")) for item in results), default=0.0)
    if max_score <= 0:
        return results
    normalized: list[dict[str, Any]] = []
    for item in results:
        copied = dict(item)
        copied["score"] = _score(copied.get("score")) / max_score
        normalized.append(copied)
    return normalized
