#!/bin/bash
set -e

# 安装依赖：优先 uv，回退 pip
if command -v uv &>/dev/null; then
  echo "[setup] uv 模式安装依赖"
  uv sync --frozen 2>/dev/null || uv sync
else
  echo "[setup] pip 模式安装依赖"
  python3 -m venv .venv
  ./.venv/bin/pip install -r requirements.txt
fi
