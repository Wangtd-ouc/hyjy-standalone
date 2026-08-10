#!/bin/bash
set -e

# 启动 HTTP 服务（含内置 Web 界面）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

source scripts/load_env.sh

PORT="${PORT:-5010}"
if [ -d ".venv" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

echo "[http_run] 启动会议纪要助手服务，端口 $PORT"
echo "[http_run] Web 界面: http://localhost:$PORT"
exec $PYTHON src/main.py -m http -p "$PORT"
