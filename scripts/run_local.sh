#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/src/novel_dev/web"
LOG_DIR="${LOG_DIR:-/tmp/novel-dev}"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
EMBEDDING_HOST="${EMBEDDING_HOST:-127.0.0.1}"
EMBEDDING_PORT="${EMBEDDING_PORT:-9997}"
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://$(whoami)@localhost/novel_dev}"

API_LOG="${LOG_DIR}/api.log"
EMBEDDING_LOG="${LOG_DIR}/embedding.log"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少命令: $1"
    exit 1
  fi
}

start_detached() {
  local session_name="$1"
  local log_file="$2"
  shift 2

  if command -v screen >/dev/null 2>&1; then
    screen -S "${session_name}" -X quit >/dev/null 2>&1 || true
    screen -dmS "${session_name}" bash -lc '
      exec "$@" >>"$0" 2>&1
    ' "${log_file}" "$@"
  elif command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" </dev/null >"${log_file}" 2>&1 &
  else
    nohup bash -lc '
      "$@" </dev/null >>"$0" 2>&1 &
      disown || true
    ' "${log_file}" "$@" >/dev/null 2>&1 &
  fi
}

wait_for_http() {
  local url="$1"
  local name="$2"

  for _ in {1..60}; do
    if curl -s -o /dev/null "$url"; then
      echo "${name} 已就绪: ${url}"
      return 0
    fi
    sleep 1
  done

  echo "${name} 启动超时，请查看日志: ${LOG_DIR}"
  exit 1
}

echo "==> 检查运行环境"
require_cmd "${PYTHON_BIN}"
require_cmd npm
require_cmd curl
require_cmd pkill
require_cmd alembic

mkdir -p "${LOG_DIR}"

echo "==> 停止旧服务"
pkill -f "embedding_server.py" >/dev/null 2>&1 || true
pkill -f "uvicorn novel_dev.api:app" >/dev/null 2>&1 || true

echo "==> 重建后端依赖"
cd "${ROOT_DIR}"
"${PYTHON_BIN}" -m pip install -e '.[dev]'

echo "==> 运行数据库迁移"
DATABASE_URL="${DATABASE_URL}" alembic upgrade heads

echo "==> 重建前端依赖与产物"
cd "${WEB_DIR}"
npm install
npm run build

echo "==> 启动 Embedding 服务"
cd "${ROOT_DIR}"
start_detached "novel-dev-embedding" "${EMBEDDING_LOG}" env \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  "${PYTHON_BIN}" embedding_server.py
wait_for_http "http://${EMBEDDING_HOST}:${EMBEDDING_PORT}/v1/models" "Embedding 服务"

echo "==> 启动 API 服务"
start_detached "novel-dev-api" "${API_LOG}" env \
  PYTHONPATH=src \
  DATABASE_URL="${DATABASE_URL}" \
  "${PYTHON_BIN}" -m uvicorn novel_dev.api:app --host "${API_HOST}" --port "${API_PORT}"
wait_for_http "http://${API_HOST}:${API_PORT}/" "API 服务"

echo ""
echo "系统已更新到当前代码的最新构建状态"
echo "API: http://${API_HOST}:${API_PORT}/"
echo "Embedding: http://${EMBEDDING_HOST}:${EMBEDDING_PORT}/v1/models"
echo "日志目录: ${LOG_DIR}"
