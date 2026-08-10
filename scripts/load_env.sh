#!/bin/bash
# 加载项目 .env 环境变量
if [ -f ".env" ]; then
  set -a
  source .env
  set +a
else
  echo "[load_env] 未找到 .env，请先复制 .env.example 并填写配置"
fi
