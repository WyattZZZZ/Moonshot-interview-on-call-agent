from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

CORS_HEADERS = {
    "access-control-allow-origin",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "access-control-expose-headers",
    "access-control-max-age",
    "access-control-allow-credentials",
}

CORS_RESPONSE_HEADERS = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"),
    ("Access-Control-Allow-Headers", "Content-Type, Accept"),
)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "on-call-agent-dev-gateway/1.0"

    def do_GET(self) -> None:
        if self.path.rstrip("/") in {"", "/"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", self.server.frontend_url)
            self.end_headers()
            return
        self.proxy()

    def do_POST(self) -> None:
        self.proxy()

    def do_DELETE(self) -> None:
        self.proxy()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.end_headers()

    def proxy(self) -> None:
        target_base = self.target_base()
        if not target_base:
            self.send_json_error(HTTPStatus.NOT_FOUND, "gateway route not found")
            return

        body = self.read_body()
        target_url = target_base + self.path
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }
        request = urllib.request.Request(
            target_url,
            data=body if self.command in {"POST", "PUT", "PATCH", "DELETE"} else None,
            headers=headers,
            method=self.command,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.server.timeout) as response:
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in CORS_HEADERS:
                        self.send_header(key, value)
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() not in CORS_HEADERS:
                    self.send_header(key, value)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(payload)
        except urllib.error.URLError as exc:
            self.send_json_error(HTTPStatus.BAD_GATEWAY, f"upstream unavailable: {exc.reason}")

    def target_base(self) -> str | None:
        path = urlsplit(self.path).path
        if path.startswith("/v1"):
            return self.server.v1_url
        if path.startswith("/v2"):
            return self.server.v2_url
        if path.startswith("/v3"):
            return self.server.v3_url
        if path == "/health":
            return self.server.v1_url
        return None

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else b""

    def send_cors_headers(self) -> None:
        for key, value in CORS_RESPONSE_HEADERS:
            self.send_header(key, value)

    def send_json_error(self, status: HTTPStatus, message: str) -> None:
        payload = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


class GatewayServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], frontend_url: str, timeout: float) -> None:
        super().__init__(address, GatewayHandler)
        host = address[0]
        self.v1_url = f"http://{host}:{env_int('V1_PORT', 8001)}"
        self.v2_url = f"http://{host}:{env_int('V2_PORT', 8002)}"
        self.v3_url = f"http://{host}:{env_int('V3_PORT', 8003)}"
        self.frontend_url = frontend_url
        self.timeout = timeout


def main() -> None:
    parser = argparse.ArgumentParser(description="Local development gateway for on-call-agent")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=env_int("API_GATEWAY_PORT", 8000))
    parser.add_argument("--frontend-url", default=f"http://127.0.0.1:{env_int('WEBUI_PORT', 4173)}/")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    server = GatewayServer((args.host, args.port), args.frontend_url, args.timeout)
    print(f"Gateway: http://{args.host}:{args.port}")
    print(f"  /v1 -> {server.v1_url}")
    print(f"  /v2 -> {server.v2_url}")
    print(f"  /v3 -> {server.v3_url}")
    print(f"  /   -> {server.frontend_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGateway shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
