#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
API_GATEWAY_PORT="${API_GATEWAY_PORT:-8000}"
V1_PORT="${V1_PORT:-8001}"
V2_PORT="${V2_PORT:-8002}"
V3_PORT="${V3_PORT:-8003}"
V3_WS_PORT="${V3_WS_PORT:-8004}"
WEBUI_PORT="${WEBUI_PORT:-4173}"
DEMO_DIR="${DEMO_DIR:-../coding-exam/question-1/data}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-240}"

export HOST API_GATEWAY_PORT V1_PORT V2_PORT V3_PORT V3_WS_PORT WEBUI_PORT
export HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export ON_CALL_AGENT_CHROMA_DIR="${ON_CALL_AGENT_CHROMA_DIR:-./database/chroma}"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install uv first, then rerun this script." >&2
  exit 1
fi

check_port() {
  local port="$1"
  if python3 - "$HOST" "$port" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.2)
    sys.exit(0 if sock.connect_ex((host, port)) else 1)
PY
  then
    return 0
  fi
  echo "Port ${port} is already in use on ${HOST}. Set a different port env var or stop the existing process." >&2
  exit 1
}

wait_http() {
  local name="$1"
  local url="$2"
  local timeout="$3"
  echo "Waiting for ${name} at ${url}"
  python3 - "$url" "$timeout" <<'PY'
import sys
import time
import urllib.error
import urllib.request

url, timeout = sys.argv[1], float(sys.argv[2])
deadline = time.monotonic() + timeout
last = ""
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if 200 <= response.status < 500:
                sys.exit(0)
    except Exception as exc:
        last = str(exc)
    time.sleep(1)
print(f"Timed out waiting for {url}: {last}", file=sys.stderr)
sys.exit(1)
PY
}

wait_tcp() {
  local name="$1"
  local host="$2"
  local port="$3"
  local timeout="$4"
  echo "Waiting for ${name} at ${host}:${port}"
  python3 - "$host" "$port" "$timeout" <<'PY'
import socket
import sys
import time

host, port, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
deadline = time.monotonic() + timeout
while time.monotonic() < deadline:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        if sock.connect_ex((host, port)) == 0:
            sys.exit(0)
    time.sleep(0.5)
print(f"Timed out waiting for {host}:{port}", file=sys.stderr)
sys.exit(1)
PY
}

for port in "$API_GATEWAY_PORT" "$V1_PORT" "$V2_PORT" "$V3_PORT" "$V3_WS_PORT" "$WEBUI_PORT"; do
  check_port "$port"
done

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
}
trap cleanup EXIT INT TERM

echo "Syncing Python environment..."
uv sync

echo "Starting v1 on http://${HOST}:${V1_PORT}"
uv run python v1/server.py --host "$HOST" --port "$V1_PORT" --import-demo --demo-dir "$DEMO_DIR" &
pids+=("$!")

echo "Starting v2 on http://${HOST}:${V2_PORT}"
uv run python v2/server.py --host "$HOST" --port "$V2_PORT" --import-demo --demo-dir "$DEMO_DIR" &
pids+=("$!")

echo "Starting v3 on http://${HOST}:${V3_PORT}"
uv run python v3/server.py --host "$HOST" --port "$V3_PORT" --ws-port "$V3_WS_PORT" --data-dir "$DEMO_DIR" &
pids+=("$!")

echo "Starting API gateway on http://${HOST}:${API_GATEWAY_PORT}"
uv run python dev_gateway.py --host "$HOST" --port "$API_GATEWAY_PORT" --frontend-url "http://${HOST}:${WEBUI_PORT}/" &
pids+=("$!")

echo "Starting web UI on http://${HOST}:${WEBUI_PORT}"
uv run python -m http.server "$WEBUI_PORT" --bind "$HOST" --directory webui &
pids+=("$!")

wait_http "v1" "http://${HOST}:${V1_PORT}/health" "$STARTUP_TIMEOUT"
wait_http "v2" "http://${HOST}:${V2_PORT}/health" "$STARTUP_TIMEOUT"
wait_http "v3" "http://${HOST}:${V3_PORT}/health" "$STARTUP_TIMEOUT"
wait_tcp "v3 WebSocket" "$HOST" "$V3_WS_PORT" "$STARTUP_TIMEOUT"
wait_http "API gateway" "http://${HOST}:${API_GATEWAY_PORT}/health" "$STARTUP_TIMEOUT"
wait_http "web UI" "http://${HOST}:${WEBUI_PORT}/" "$STARTUP_TIMEOUT"

frontend_url="http://${HOST}:${WEBUI_PORT}/#v1"
echo
echo "All services are starting."
echo "Frontend: ${frontend_url}"
echo "Gateway:  http://${HOST}:${API_GATEWAY_PORT}"
echo
echo "Press Ctrl+C in this terminal to stop all services."

if [ "${NO_OPEN:-0}" = "1" ]; then
  :
elif command -v open >/dev/null 2>&1; then
  open "$frontend_url" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$frontend_url" >/dev/null 2>&1 || true
fi

wait
