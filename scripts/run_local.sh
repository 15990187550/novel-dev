#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/src/novel_dev/web"
LOG_DIR="${LOG_DIR:-/tmp/novel-dev}"
PIP_INSTALL_MODE="${PIP_INSTALL_MODE:-auto}"

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

python_env_ready() {
  "${PYTHON_BIN}" - <<'PY' >/dev/null 2>&1
import importlib

modules = [
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "pgvector",
    "fastapi",
    "uvicorn",
    "pydantic",
    "anthropic",
    "openai",
    "mcp",
    "sentence_transformers",
    "torch",
]

for name in modules:
    importlib.import_module(name)
PY
}

ensure_backend_dependencies() {
  case "${PIP_INSTALL_MODE}" in
    never)
      echo "==> 跳过后端依赖安装 (PIP_INSTALL_MODE=never)"
      return 0
      ;;
    auto)
      if python_env_ready; then
        echo "==> 后端依赖已满足，跳过 pip install"
        return 0
      fi
      ;;
    always)
      ;;
    *)
      echo "不支持的 PIP_INSTALL_MODE: ${PIP_INSTALL_MODE} (允许值: auto/always/never)"
      exit 1
      ;;
  esac

  if ! "${PYTHON_BIN}" -m pip show wheel >/dev/null 2>&1; then
    echo "==> 安装 wheel 构建依赖"
    "${PYTHON_BIN}" -m pip install wheel
  fi

  echo "==> 重建后端依赖"
  "${PYTHON_BIN}" -m pip install -e '.[dev]' --no-build-isolation
}

repair_legacy_alembic_revision() {
  DATABASE_URL="${DATABASE_URL}" "${PYTHON_BIN}" - <<'PY'
import asyncio
import os

import asyncpg
from sqlalchemy.engine import make_url

LEGACY_REVISION = "20260422_add_brainstorm_workspace"
CANONICAL_REVISION = "20260422_bw_workspace"


async def main() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    if not url.drivername.startswith("postgresql+asyncpg"):
        return

    conn = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host or "localhost",
        port=url.port or 5432,
        database=url.database,
    )
    try:
        try:
            rows = await conn.fetch("select version_num from alembic_version")
        except Exception:
            return

        versions = {row["version_num"] for row in rows}
        if LEGACY_REVISION not in versions:
            return

        if CANONICAL_REVISION in versions:
            await conn.execute(
                "delete from alembic_version where version_num = $1",
                LEGACY_REVISION,
            )
            print(f"==> 已移除旧 Alembic revision 别名: {LEGACY_REVISION}")
            return

        await conn.execute(
            "update alembic_version set version_num = $1 where version_num = $2",
            CANONICAL_REVISION,
            LEGACY_REVISION,
        )
        print(
            "==> 已将旧 Alembic revision 别名修正为当前版本: "
            f"{LEGACY_REVISION} -> {CANONICAL_REVISION}"
        )
    finally:
        await conn.close()


asyncio.run(main())
PY
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

cd "${ROOT_DIR}"
ensure_backend_dependencies

echo "==> 运行数据库迁移"
repair_legacy_alembic_revision
DATABASE_URL="${DATABASE_URL}" alembic upgrade heads

echo "==> 重建前端依赖与产物"
cd "${WEB_DIR}"
npm install --prefer-offline --no-audit --fund=false
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
