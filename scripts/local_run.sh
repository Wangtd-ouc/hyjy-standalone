#!/bin/bash
set -e

# 命令行模式：直接生成会议纪要
usage() {
  echo "用法: $0 [-i <输入>]"
  echo "  -i <输入>   会议记录原文（纯文本或 JSON），不传则默认问候"
  echo "  -h          帮助"
}

input=""
while getopts "i:h" opt; do
  case "$opt" in
    i) input="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

source scripts/load_env.sh

if [ -d ".venv" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

exec $PYTHON src/main.py -m flow -i "$input"
