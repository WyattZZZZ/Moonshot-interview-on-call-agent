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
if str(ON_CALL_ROOT) not in sys.path:
    sys.path.insert(0, str(ON_CALL_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import db
from html_cleaner import clean_html
from search import search_documents


JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_HTML_CHARS = 1_000_000
MAX_DOC_ID_CHARS = 120
DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class APIError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        self.status = status
        self.message = message


class OnCallHandler(BaseHTTPRequestHandler):
    server_version = "on-call-agent-v1/1.0"

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
                self.send_json({"status": "ok"})
            elif path == "/v1":
                self.send_html(INDEX_HTML)
            elif path == "/v1/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                with db.connection(self.server.db_path) as conn:
                    db.initialize(conn)
                    results = search_documents(conn, query)
                self.send_json({"query": query, "results": results})
            elif path.startswith("/v1/documents/"):
                doc_id = unquote(path.removeprefix("/v1/documents/"))
                with db.connection(self.server.db_path) as conn:
                    db.initialize(conn)
                    document = db.get_document(conn, doc_id)
                if not document:
                    raise APIError(HTTPStatus.NOT_FOUND, "document not found")
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
            if parsed.path.rstrip("/") != "/v1/documents":
                raise APIError(HTTPStatus.NOT_FOUND, "not found")
            payload = self.read_json()
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

            title, clean_text = clean_html(html)
            if isinstance(payload.get("title"), str) and payload["title"].strip():
                title = payload["title"].strip()
            path = str(payload.get("path", "")).strip()
            with db.connection(self.server.db_path) as conn:
                db.initialize(conn)
                if not replace and db.document_exists(conn, doc_id):
                    raise APIError(HTTPStatus.CONFLICT, "document id already exists; pass replace=true to overwrite")
                document = db.upsert_document(
                    conn,
                    doc_id=doc_id,
                    title=title,
                    html=html,
                    clean_text=clean_text,
                    path=path,
                )
            self.send_json({"id": document["id"], "title": document["title"]}, HTTPStatus.CREATED)
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
            if not path.startswith("/v1/documents/"):
                raise APIError(HTTPStatus.NOT_FOUND, "not found")
            doc_id = unquote(path.removeprefix("/v1/documents/"))
            with db.connection(self.server.db_path) as conn:
                db.initialize(conn)
                deleted = db.delete_document(conn, doc_id)
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
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


class OnCallServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], db_path: Path) -> None:
        super().__init__(server_address, handler_class)
        self.db_path = db_path


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>On-Call Agent v1</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px; max-width: 860px; }
    form { display: flex; gap: 8px; }
    input { flex: 1; padding: 10px 12px; font-size: 16px; }
    button { padding: 10px 14px; font-size: 16px; }
    li { margin: 16px 0; }
    mark { background: #fff3a3; }
  </style>
</head>
<body>
  <h1>On-Call Agent v1</h1>
  <form id="search"><input name="q" placeholder="搜索 OOM、故障、CDN、&"><button>Search</button></form>
  <ol id="results"></ol>
  <script>
    const form = document.querySelector("#search");
    const results = document.querySelector("#results");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const q = new FormData(form).get("q");
      const res = await fetch(`/v1/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      results.innerHTML = data.results.map((item) => `<li><strong>${item.title}</strong><br>${item.snippet}</li>`).join("");
    });
  </script>
</body>
</html>"""


def import_demo_data(db_path: Path, data_dir: Path, *, refresh: bool = False) -> tuple[int, int]:
    imported = 0
    skipped = 0
    with db.connection(db_path) as conn:
        db.initialize(conn)
        for html_path in sorted(data_dir.glob("*.html")):
            doc_id = html_path.stem
            if not refresh and db.get_document(conn, doc_id):
                skipped += 1
                continue
            html = html_path.read_text(encoding="utf-8")
            title, clean_text = clean_html(html)
            db.upsert_document(
                conn,
                doc_id=doc_id,
                title=title,
                html=html,
                clean_text=clean_text,
                path=str(html_path.relative_to(REPO_ROOT) if html_path.is_relative_to(REPO_ROOT) else html_path),
            )
            imported += 1
    return imported, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="on-call-agent v1 HTTP API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", type=Path, default=db.default_db_path())
    parser.add_argument("--import-demo", action="store_true", help="Import coding-exam/question-1/data/*.html before serving")
    parser.add_argument("--refresh-demo", action="store_true", help="Overwrite existing demo documents during --import-demo")
    parser.add_argument("--demo-dir", type=Path, default=REPO_ROOT / "coding-exam/question-1/data")
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with db.connection(args.db) as conn:
        db.initialize(conn)
    if args.import_demo:
        imported, skipped = import_demo_data(args.db, args.demo_dir, refresh=args.refresh_demo)
        print(f"Imported {imported} demo documents from {args.demo_dir}; skipped {skipped} existing documents")

    mimetypes.add_type("application/json", ".json")
    server = OnCallServer((args.host, args.port), OnCallHandler, args.db)
    print(f"Serving on http://{args.host}:{args.port} using {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
