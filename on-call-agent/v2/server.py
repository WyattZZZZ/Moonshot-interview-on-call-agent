from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ON_CALL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ON_CALL_ROOT.parent
V2_ROOT = ON_CALL_ROOT / "v2"
V1_ROOT = ON_CALL_ROOT / "v1"
for path in (V1_ROOT, ON_CALL_ROOT, V2_ROOT):
    path_text = str(path)
    while path_text in sys.path:
        sys.path.remove(path_text)
    sys.path.insert(0, path_text)

from database import chroma_store, db
from html_cleaner import clean_html
from chunker import ChunkRecord, build_chunks
from search import search_documents_semantic
from semantic import DEFAULT_EMBEDDING_MODEL, chunk_embedding_text, embed_texts


JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}
HTML_HEADERS = {"Content-Type": "text/html; charset=utf-8"}
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_HTML_CHARS = 1_000_000
MAX_DOC_ID_CHARS = 120
DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class APIError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        self.status = status
        self.message = message


class OnCallV2Handler(BaseHTTPRequestHandler):
    server_version = "on-call-agent-v2/2.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if path in {"/", "/health"}:
                self.send_json({"status": "ok", "version": "v2"})
            elif path == "/v2":
                self.send_html(v2_search_page())
            elif path == "/v2/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                with db.connection(self.server.db_path) as conn:
                    db.initialize(conn)
                    results = search_documents_semantic(query)
                self.send_json({"query": query, "results": results})
            elif path.startswith("/v2/documents/"):
                doc_id = unquote(path.removeprefix("/v2/documents/"))
                with db.connection(self.server.db_path) as conn:
                    db.initialize(conn)
                    document = db.get_document(conn, doc_id)
                if not document:
                    raise APIError(HTTPStatus.NOT_FOUND, "document not found")
                chunks = chroma_store.get_document_chunks(doc_id)
                document["chunk_count"] = len(chunks)
                document["chunks"] = [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "chunk_index": chunk["chunk_index"],
                        "heading": chunk.get("heading", ""),
                        "heading_path": chunk.get("heading_path", ""),
                        "text_preview": _preview(chunk.get("chunk_text", "")),
                    }
                    for chunk in chunks
                ]
                self.send_json(document)
            else:
                raise APIError(HTTPStatus.NOT_FOUND, "not found")
        except APIError as exc:
            self.send_error_json(exc.status, exc.message)
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") != "/v2/documents":
                raise APIError(HTTPStatus.NOT_FOUND, "not found")
            payload = self.read_json()
            document, chunks = upsert_document_from_payload(self.server.db_path, payload)
            self.send_json(
                {
                    "id": document["id"],
                    "title": document["title"],
                    "chunk_count": len(chunks),
                    "embedding_model": DEFAULT_EMBEDDING_MODEL,
                },
                HTTPStatus.CREATED,
            )
        except APIError as exc:
            self.send_error_json(exc.status, exc.message)
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid JSON body")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_DELETE(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/")
            if not path.startswith("/v2/documents/"):
                raise APIError(HTTPStatus.NOT_FOUND, "not found")
            doc_id = unquote(path.removeprefix("/v2/documents/"))
            with db.connection(self.server.db_path) as conn:
                db.initialize(conn)
                deleted = db.delete_document(conn, doc_id)
            chroma_store.delete_document(doc_id)
            if not deleted:
                raise APIError(HTTPStatus.NOT_FOUND, "document not found")
            self.send_json({"success": True})
        except APIError as exc:
            self.send_error_json(exc.status, exc.message)
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise APIError(HTTPStatus.BAD_REQUEST, "JSON body is required")
        if content_length > MAX_JSON_BYTES:
            self.rfile.read(content_length)
            raise APIError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"JSON body must be at most {MAX_JSON_BYTES} bytes")
        raw = self.rfile.read(content_length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise APIError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return data

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        for key, value in JSON_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        for key, value in HTML_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


class OnCallV2Server(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], db_path: Path) -> None:
        super().__init__(server_address, handler_class)
        self.db_path = db_path


def upsert_document_from_payload(db_path: Path, payload: dict) -> tuple[dict, list[ChunkRecord]]:
    doc_id = str(payload.get("id", "")).strip()
    html = payload.get("html")
    replace = bool(payload.get("replace", False))
    if not doc_id:
        raise APIError(HTTPStatus.BAD_REQUEST, "id is required")
    if len(doc_id) > MAX_DOC_ID_CHARS or not DOC_ID_RE.fullmatch(doc_id):
        raise APIError(
            HTTPStatus.BAD_REQUEST,
            "id must be 1-120 characters and contain only letters, numbers, dots, underscores, or hyphens",
        )
    if not isinstance(html, str) or not html.strip():
        raise APIError(HTTPStatus.BAD_REQUEST, "html is required")
    if len(html) > MAX_HTML_CHARS:
        raise APIError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"html must be at most {MAX_HTML_CHARS} characters")

    with db.connection(db_path) as conn:
        db.initialize(conn)
        if not replace and db.document_exists(conn, doc_id):
            raise APIError(HTTPStatus.CONFLICT, "document id already exists; pass replace=true to overwrite")

    title, clean_text = clean_html(html)
    if isinstance(payload.get("title"), str) and payload["title"].strip():
        title = payload["title"].strip()
    path = str(payload.get("path", "")).strip()

    chunks = build_chunks(html, title=title, doc_id=doc_id)
    if not chunks and clean_text.strip():
        chunks = [
            ChunkRecord(
                chunk_id=f"{doc_id}::0000",
                chunk_index=0,
                heading=title,
                heading_path=title,
                chunk_text=clean_text.strip(),
            )
        ]

    if not chunks:
        raise APIError(HTTPStatus.BAD_REQUEST, "html did not contain any chunkable content")

    chunk_embeddings = embed_texts(
        [chunk_embedding_text(chunk.heading_path, chunk.chunk_text) for chunk in chunks],
        model=DEFAULT_EMBEDDING_MODEL,
    )

    document = _store_document_and_chunks(
        db_path=db_path,
        doc_id=doc_id,
        title=title,
        html=html,
        clean_text=clean_text,
        path=path,
        chunks=chunks,
        chunk_embeddings=chunk_embeddings,
        embedding_model=DEFAULT_EMBEDDING_MODEL,
    )
    return document, chunks


def _store_document_and_chunks(
    *,
    db_path: Path,
    doc_id: str,
    title: str,
    html: str,
    clean_text: str,
    path: str,
    chunks: list[ChunkRecord],
    chunk_embeddings: list[list[float]],
    embedding_model: str,
) -> dict:
    with db.connection(db_path) as conn:
        db.initialize(conn)
        document = db.upsert_document(
            conn,
            doc_id=doc_id,
            title=title,
            html=html,
            clean_text=clean_text,
            semantic_profile=None,
            embedding=None,
            path=path,
        )
        db.clear_embedding(conn, doc_id)
        db.set_semantic_index_status(conn, doc_id, "pending")

    try:
        chroma_store.delete_document(doc_id)
        chroma_store.upsert_chunks(
            document_id=doc_id,
            title=title,
            path=path,
            embedding_model=embedding_model,
            chunks=[
                {
                    "chunk_id": chunk.chunk_id,
                    "chunk_index": chunk.chunk_index,
                    "heading": chunk.heading,
                    "heading_path": chunk.heading_path,
                    "chunk_text": chunk.chunk_text,
                }
                for chunk in chunks
            ],
            embeddings=chunk_embeddings,
        )
    except Exception as exc:
        with db.connection(db_path) as conn:
            db.initialize(conn)
            db.set_semantic_index_status(conn, doc_id, "failed", str(exc))
        raise

    with db.connection(db_path) as conn:
        db.initialize(conn)
        db.set_semantic_index_status(conn, doc_id, "ready")
    return document


def import_demo_data(db_path: Path, data_dir: Path, *, refresh: bool = False) -> tuple[int, int]:
    imported = 0
    skipped = 0
    for html_path in sorted(data_dir.glob("*.html")):
        doc_id = html_path.stem
        with db.connection(db_path) as conn:
            db.initialize(conn)
            existing = db.get_document(conn, doc_id)
        if not refresh and existing and chroma_store.get_document_chunks(doc_id):
            skipped += 1
            continue
        html = html_path.read_text(encoding="utf-8")
        title, clean_text = clean_html(html)
        chunks = build_chunks(html, title=title, doc_id=doc_id)
        if not chunks and clean_text.strip():
            chunks = [
                ChunkRecord(
                    chunk_id=f"{doc_id}::0000",
                    chunk_index=0,
                    heading=title,
                    heading_path=title,
                    chunk_text=clean_text.strip(),
                )
            ]
        if not chunks:
            skipped += 1
            continue
        chunk_embeddings = embed_texts(
            [chunk_embedding_text(chunk.heading_path, chunk.chunk_text) for chunk in chunks],
            model=DEFAULT_EMBEDDING_MODEL,
        )
        _store_document_and_chunks(
            db_path=db_path,
            doc_id=doc_id,
            title=title,
            html=html,
            clean_text=clean_text,
            path=str(html_path.relative_to(REPO_ROOT) if html_path.is_relative_to(REPO_ROOT) else html_path),
            chunks=chunks,
            chunk_embeddings=chunk_embeddings,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
        )
        imported += 1
    return imported, skipped


def v2_search_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>On-Call Agent v2</title>
  <style>
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #17202a; background: #f7f8fa; }
    main { max-width: 920px; margin: 0 auto; padding: 40px 20px; }
    h1 { font-size: 28px; margin: 0 0 20px; }
    form { display: flex; gap: 10px; margin-bottom: 18px; }
    input { flex: 1; min-width: 0; padding: 12px 14px; border: 1px solid #c9d1d9; border-radius: 6px; font-size: 16px; }
    button { padding: 12px 18px; border: 0; border-radius: 6px; background: #1f6feb; color: white; font-size: 16px; cursor: pointer; }
    .hint { color: #59636e; margin-bottom: 24px; }
    .result { background: white; border: 1px solid #d8dee4; border-radius: 8px; padding: 16px; margin: 12px 0; }
    .title { font-weight: 700; margin-bottom: 8px; }
    .meta { color: #59636e; font-size: 13px; margin-top: 10px; }
    .empty, .error { color: #59636e; padding: 18px 0; }
    .error { color: #b42318; }
  </style>
</head>
<body>
  <main>
    <h1>On-Call Agent v2</h1>
    <form id="search-form">
      <input id="query" name="q" value="服务器挂了" autocomplete="off" autofocus>
      <button type="submit">搜索</button>
    </form>
    <div class="hint">语义检索接口：<code>GET /v2/search?q=...</code></div>
    <section id="results"></section>
  </main>
  <script>
    const form = document.getElementById("search-form");
    const query = document.getElementById("query");
    const results = document.getElementById("results");

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[ch]));
    }

    async function runSearch(q) {
      results.innerHTML = '<div class="empty">搜索中...</div>';
      const response = await fetch(`/v2/search?q=${encodeURIComponent(q)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (!data.results.length) {
        results.innerHTML = '<div class="empty">没有结果</div>';
        return;
      }
      results.innerHTML = data.results.map(item => `
        <article class="result">
          <div class="title">${escapeHtml(item.title || item.id)}</div>
          <div>${escapeHtml(item.snippet || "")}</div>
          <div class="meta">${escapeHtml(item.id)} · score ${escapeHtml(item.score)} · ${escapeHtml(item.matched_chunk_heading_path || "")}</div>
        </article>
      `).join("");
    }

    form.addEventListener("submit", event => {
      event.preventDefault();
      const q = query.value.trim();
      if (!q) return;
      history.replaceState(null, "", `/v2?q=${encodeURIComponent(q)}`);
      runSearch(q).catch(error => {
        results.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
      });
    });

    const initial = new URLSearchParams(location.search).get("q");
    if (initial) query.value = initial;
    runSearch(query.value.trim()).catch(() => {
      results.innerHTML = '<div class="empty">服务已启动。导入 demo 后可直接搜索。</div>';
    });
  </script>
</body>
</html>"""


def _preview(text: str, size: int = 220) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= size:
        return cleaned
    return cleaned[: size - 1].rstrip() + "…"


def main() -> None:
    parser = argparse.ArgumentParser(description="on-call-agent v2 semantic/chroma HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=db.default_db_path())
    parser.add_argument("--import-demo", action="store_true", help="Import on-call-agent/data/*.html before serving")
    parser.add_argument("--refresh-demo", action="store_true", help="Overwrite existing demo documents during --import-demo")
    parser.add_argument("--demo-dir", type=Path, default=ON_CALL_ROOT / "data")
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with db.connection(args.db) as conn:
        db.initialize(conn)
    if args.import_demo:
        imported, skipped = import_demo_data(args.db, args.demo_dir, refresh=args.refresh_demo)
        print(f"Imported {imported} demo documents from {args.demo_dir}; skipped {skipped} existing documents")

    mimetypes.add_type("application/json", ".json")
    server = OnCallV2Server((args.host, args.port), OnCallV2Handler, args.db)
    print(f"Serving on http://{args.host}:{args.port} using {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
