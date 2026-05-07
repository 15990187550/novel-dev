#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/src/novel_dev/web"

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-5173}"
REPORT_ROOT="${REPORT_ROOT:-${ROOT_DIR}/reports/test-runs}"
RUN_ID="${RUN_ID:-$(date +%Y-%m-%dT%H%M%S)-web-e2e}"
TEST_RUN_REPORT_DIR="${TEST_RUN_REPORT_DIR:-${REPORT_ROOT}/${RUN_ID}}"
ARTIFACT_DIR="${TEST_RUN_REPORT_DIR}/artifacts"
VITE_LOG="${ARTIFACT_DIR}/vite.log"

mkdir -p "${ARTIFACT_DIR}"

if ! curl -fsS "${API_BASE_URL}/healthz" >/dev/null; then
  echo "API health check failed at ${API_BASE_URL}/healthz"
  exit 1
fi

cd "${WEB_DIR}"
npm install --prefer-offline --no-audit --fund=false

VITE_API_PROXY_TARGET="${API_BASE_URL}" npm run dev -- --host "${WEB_HOST}" --port "${WEB_PORT}" --strictPort >"${VITE_LOG}" 2>&1 &
VITE_PID="$!"
trap 'kill "${VITE_PID}" >/dev/null 2>&1 || true' EXIT

VITE_URL="http://${WEB_HOST}:${WEB_PORT}/"
for _ in {1..60}; do
  if ! kill -0 "${VITE_PID}" >/dev/null 2>&1; then
    echo "Vite dev server exited before becoming ready. See ${VITE_LOG}"
    exit 1
  fi

  if curl -fsS "${VITE_URL}" >/dev/null; then
    break
  fi

  sleep 1
done

if ! curl -fsS "${VITE_URL}" >/dev/null; then
  echo "Vite dev server did not become ready at ${VITE_URL}. See ${VITE_LOG}"
  exit 1
fi

export PLAYWRIGHT_BASE_URL="${VITE_URL}"
export TEST_RUN_REPORT_DIR

PLAYWRIGHT_OUTPUT_DIR="${ARTIFACT_DIR}/flow-results" \
PLAYWRIGHT_HTML_REPORT="${ARTIFACT_DIR}/flow-report" \
  npm run test:e2e

PLAYWRIGHT_OUTPUT_DIR="${ARTIFACT_DIR}/visual-results" \
PLAYWRIGHT_HTML_REPORT="${ARTIFACT_DIR}/visual-report" \
  npm run test:visual
