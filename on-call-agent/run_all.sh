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
