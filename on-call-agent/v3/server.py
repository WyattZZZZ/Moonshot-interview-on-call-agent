from __future__ import annotations

import asyncio
import argparse
import json
import mimetypes
import os
import queue
import sys
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection


ON_CALL_ROOT = Path(__file__).resolve().parents[1]
V3_ROOT = Path(__file__).resolve().parent
for import_path in (ON_CALL_ROOT, V3_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from database import db
from agent import run_chat, run_chat_stream
from retrieval import CandidateWeights
from runtime import RuntimeErrorResponse
from tools import DEFAULT_DATA_DIR


JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}
HTML_HEADERS = {"Content-Type": "text/html; charset=utf-8"}
MAX_JSON_BYTES = 2 * 1024 * 1024
WEBSOCKET_CLOSE_SESSION_ERROR = 4404


class APIError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        self.status = status
        self.message = message


class ChatSessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> str:
        session_id = uuid.uuid4().hex
        with self._lock:
            self._sessions[session_id] = payload
        return session_id

    def pop(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._sessions.pop(session_id, None)


class OnCallV3Handler(BaseHTTPRequestHandler):
    server_version = "on-call-agent-v3/3.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in {"/", "/health"}:
            self.send_json({"status": "ok", "version": "v3"})
        elif path == "/v3":
            self.send_html(v3_chat_page())
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") == "/v3/chat":
                payload = self.read_json()
                result = self.execute_chat(payload)
                self.send_json(result)
            elif parsed.path.rstrip("/") == "/v3/chat/session":
                payload = self.read_json()
                session = self.create_session(payload)
                self.send_json(session)
            else:
                raise APIError(HTTPStatus.NOT_FOUND, "not found")
        except APIError as exc:
            self.send_error_json(exc.status, exc.message)
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid JSON body")
        except RuntimeErrorResponse as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, str(exc))
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def execute_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        message, history, weights = self.parse_chat_payload(payload)
        return run_chat(
            message=message,
            history=history,
            weights=weights,
            db_path=self.server.db_path,
            data_dir=self.server.data_dir,
        )

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        message, history, weights = self.parse_chat_payload(payload)
        session_id = self.server.session_store.create(
            {
                "message": message,
                "history": history,
                "weights": {
                    "keyword": weights.keyword,
                    "semantic": weights.semantic,
                },
            }
        )
        return {
            "session_id": session_id,
            "ws_url": self.server.websocket_url,
        }

    def parse_chat_payload(self, payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]], CandidateWeights]:
        message = str(payload.get("message", "")).strip()
        if not message:
            raise APIError(HTTPStatus.BAD_REQUEST, "message is required")
        history = payload.get("history", [])
        if history is None:
            history = []
        if not isinstance(history, list):
            raise APIError(HTTPStatus.BAD_REQUEST, "history must be an array")
        weights = CandidateWeights.from_payload(_weights_payload(payload))
        return message, history, weights

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


class OnCallV3Server(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        db_path: Path,
        data_dir: Path,
        ws_port: int,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.db_path = db_path
        self.data_dir = data_dir
        self.session_store = ChatSessionStore()
        self.websocket_host = _public_host(server_address[0])
        self.websocket_port = ws_port
        self.websocket_url = f"ws://{self.websocket_host}:{self.websocket_port}/v3/chat/ws"


def _public_host(host: str) -> str:
    if host in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return host


def _weights_payload(payload: dict) -> dict:
    if isinstance(payload.get("weights"), dict):
        return payload["weights"]
    return {
        "keyword": payload.get("keyword_weight", payload.get("lexical_weight", payload.get("lexical"))),
        "semantic": payload.get("semantic_weight", payload.get("semantic")),
    }


async def websocket_chat_handler(connection: ServerConnection, server: OnCallV3Server) -> None:
    try:
        raw = await connection.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if not isinstance(raw, str):
            await connection.send(json.dumps({"type": "error", "message": "invalid handshake payload"}, ensure_ascii=False))
            await connection.close(WEBSOCKET_CLOSE_SESSION_ERROR, "invalid handshake payload")
            return
        try:
            handshake = json.loads(raw)
        except json.JSONDecodeError:
            await connection.send(json.dumps({"type": "error", "message": "invalid handshake JSON"}, ensure_ascii=False))
            await connection.close(WEBSOCKET_CLOSE_SESSION_ERROR, "invalid handshake JSON")
            return
        session_id = str(handshake.get("session_id", "")).strip()
        if not session_id:
            await connection.send(json.dumps({"type": "error", "message": "session_id is required"}, ensure_ascii=False))
            await connection.close(WEBSOCKET_CLOSE_SESSION_ERROR, "session_id is required")
            return

        session = server.session_store.pop(session_id)
        if session is None:
            await connection.send(json.dumps({"type": "error", "message": "unknown or expired session"}, ensure_ascii=False))
            await connection.close(WEBSOCKET_CLOSE_SESSION_ERROR, "unknown or expired session")
            return

        event_queue: "queue.Queue[object]" = queue.Queue()
        sentinel = object()

        def emit(event: dict[str, Any]) -> None:
            event_queue.put(event)

        def worker() -> None:
            try:
                run_chat_stream(
                    message=session["message"],
                    history=session["history"],
                    weights=CandidateWeights.from_payload(session.get("weights")),
                    db_path=server.db_path,
                    data_dir=server.data_dir,
                    emit=emit,
                )
            except Exception as exc:
                event_queue.put({"type": "error", "message": str(exc)})
            finally:
                event_queue.put(sentinel)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            event = await asyncio.to_thread(event_queue.get)
            if event is sentinel:
                break
            await connection.send(json.dumps(event, ensure_ascii=False))

        await connection.close()
    except Exception as exc:
        try:
            await connection.send(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
        finally:
            await connection.close()


def start_websocket_server(server: OnCallV3Server) -> threading.Thread:
    def run() -> None:
        async def main() -> None:
            async with websockets.serve(
                lambda connection: websocket_chat_handler(connection, server),
                server.websocket_host,
                server.websocket_port,
                origins=None,
            ):
                await asyncio.Future()

        asyncio.run(main())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def v3_chat_page() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>On-Call Agent v3</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px; max-width: 920px; }
    form { display: grid; gap: 12px; }
    textarea { min-height: 110px; padding: 10px 12px; font-size: 16px; }
    button { width: fit-content; padding: 10px 14px; font-size: 16px; }
    pre { white-space: pre-wrap; background: #f5f5f5; padding: 16px; border-radius: 8px; }
    .weights { display: flex; gap: 12px; align-items: center; }
  </style>
</head>
<body>
  <h1>On-Call Agent v3</h1>
  <form id="chat">
    <textarea name="message" placeholder="数据库主从延迟超过30秒怎么处理？"></textarea>
    <label class="weights">词频权重 <input name="lexical" type="range" min="0" max="100" value="50"> <span id="weight">50 / 50</span></label>
    <button>Send</button>
  </form>
  <pre id="output">No chat yet</pre>
  <script>
    const form = document.querySelector("#chat");
    const output = document.querySelector("#output");
    const weight = document.querySelector("#weight");
    const slider = form.elements.lexical;
    slider.addEventListener("input", () => weight.textContent = `${slider.value} / ${100 - Number(slider.value)}`);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const lexical = Number(slider.value) / 100;
      output.textContent = "Thinking...";
      const res = await fetch("/v3/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({
          message: form.elements.message.value,
          lexical_weight: lexical,
          semantic_weight: 1 - lexical
        })
      });
      output.textContent = JSON.stringify(await res.json(), null, 2);
    });
  </script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="on-call-agent v3 Moonshot tool-using agent API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ws-port", type=int, default=int(os.environ.get("V3_WS_PORT", 8004)))
    parser.add_argument("--db", type=Path, default=db.default_db_path())
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    with db.connection(args.db) as conn:
        db.initialize(conn)

    mimetypes.add_type("application/json", ".json")
    server = OnCallV3Server((args.host, args.port), OnCallV3Handler, args.db, args.data_dir, args.ws_port)
    websocket_thread = start_websocket_server(server)
    print(f"Serving v3 on http://{args.host}:{args.port} using {args.db}; data dir {args.data_dir}")
    print(f"WebSocket stream on ws://{server.websocket_host}:{server.websocket_port}/v3/chat/ws")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
    finally:
        websocket_thread.join(timeout=0)
        server.server_close()


if __name__ == "__main__":
    main()
