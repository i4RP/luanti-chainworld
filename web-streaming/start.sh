#!/bin/bash
# ChainWorld Web Streaming - Startup Script
# This starts the web streaming server that enables browser-based play

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LUANTI_ROOT="$(dirname "$SCRIPT_DIR")"

export LUANTI_BIN="${LUANTI_ROOT}/bin/luanti"
export LUANTI_ROOT="${LUANTI_ROOT}"
export WORLD_DIR="${LUANTI_ROOT}/worlds/chainworld_test"

echo "=== ChainWorld Web Streaming Server ==="
echo "Luanti binary: ${LUANTI_BIN}"
echo "Luanti root:   ${LUANTI_ROOT}"
echo "World dir:     ${WORLD_DIR}"
echo ""
echo "Starting server on http://0.0.0.0:8080"
echo "Players can connect from their browser."
echo ""

cd "${SCRIPT_DIR}"
python3 -m uvicorn server:app --host 0.0.0.0 --port 8080 --reload
