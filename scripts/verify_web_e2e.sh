#!/usr/bin/env bash
set -uo pipefail

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
COMMANDS_LOG="${TEST_RUN_REPORT_DIR}/commands.log"
ENV_JSON="${TEST_RUN_REPORT_DIR}/env.json"
SUMMARY_JSON="${TEST_RUN_REPORT_DIR}/summary.json"
SUMMARY_MD="${TEST_RUN_REPORT_DIR}/summary.md"
STARTED_AT="$(date +%s)"

mkdir -p "${ARTIFACT_DIR}"
: >"${COMMANDS_LOG}"

json_escape() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "${value}"
}

duration_seconds() {
  local now
  now="$(date +%s)"
  printf '%s' "$((now - STARTED_AT))"
}

log_command() {
  printf '+ %s\n' "$*" >>"${COMMANDS_LOG}"
}

run_cmd() {
  log_command "$*"
  "$@"
}

write_env() {
  cat >"${ENV_JSON}" <<EOF
{
  "entrypoint": "scripts/verify_web_e2e.sh",
  "run_id": "$(json_escape "${RUN_ID}")",
  "api_base_url": "$(json_escape "${API_BASE_URL}")",
  "web_host": "$(json_escape "${WEB_HOST}")",
  "web_port": "$(json_escape "${WEB_PORT}")",
  "test_run_report_dir": "$(json_escape "${TEST_RUN_REPORT_DIR}")",
  "artifact_dir": "$(json_escape "${ARTIFACT_DIR}")"
}
EOF
}

write_summary() {
  local status="$1"
  local issue_id="${2:-}"
  local issue_type="${3:-}"
  local issue_stage="${4:-}"
  local issue_message="${5:-}"
  local reproduce="${6:-}"
  local duration
  duration="$(duration_seconds)"

  if [[ -z "${issue_id}" ]]; then
    cat >"${SUMMARY_JSON}" <<EOF
{
  "run_id": "$(json_escape "${RUN_ID}")",
  "entrypoint": "scripts/verify_web_e2e.sh",
  "status": "$(json_escape "${status}")",
  "duration_seconds": ${duration},
  "issues": []
}
EOF
    cat >"${SUMMARY_MD}" <<EOF
# Web E2E Test Run ${RUN_ID}

- Entrypoint: \`scripts/verify_web_e2e.sh\`
- Status: \`${status}\`
- Duration: \`${duration}s\`

## Issues

No issues recorded.
EOF
    return
  fi

  cat >"${SUMMARY_JSON}" <<EOF
{
  "run_id": "$(json_escape "${RUN_ID}")",
  "entrypoint": "scripts/verify_web_e2e.sh",
  "status": "$(json_escape "${status}")",
  "duration_seconds": ${duration},
  "issues": [
    {
      "id": "$(json_escape "${issue_id}")",
      "type": "$(json_escape "${issue_type}")",
      "severity": "high",
      "stage": "$(json_escape "${issue_stage}")",
      "message": "$(json_escape "${issue_message}")",
      "reproduce": "$(json_escape "${reproduce}")"
    }
  ]
}
EOF
  cat >"${SUMMARY_MD}" <<EOF
# Web E2E Test Run ${RUN_ID}

- Entrypoint: \`scripts/verify_web_e2e.sh\`
- Status: \`${status}\`
- Duration: \`${duration}s\`

## Issues

### ${issue_id} \`${issue_type}\`

- Severity: \`high\`
- Stage: \`${issue_stage}\`
- Message: ${issue_message}
- Reproduce: \`${reproduce}\`
EOF
}

write_env

HEALTH_CMD=(curl -fsS "${API_BASE_URL}/healthz")
if ! run_cmd "${HEALTH_CMD[@]}" >/dev/null; then
  echo "API health check failed at ${API_BASE_URL}/healthz"
  write_summary \
    "failed" \
    "WEB-E2E-001" \
    "SYSTEM_BUG" \
    "preflight_health" \
    "API health check failed at ${API_BASE_URL}/healthz" \
    "${HEALTH_CMD[*]}"
  exit 1
fi

log_command "cd ${WEB_DIR}"
cd "${WEB_DIR}"
INSTALL_CMD=(npm install --prefer-offline --no-audit --fund=false)
if ! run_cmd "${INSTALL_CMD[@]}"; then
  write_summary \
    "failed" \
    "WEB-E2E-FLOW" \
    "TEST_INFRA" \
    "npm_install" \
    "npm install failed for web E2E dependencies" \
    "${INSTALL_CMD[*]}"
  exit 1
fi

log_command "VITE_API_PROXY_TARGET=${API_BASE_URL} npm run dev -- --host ${WEB_HOST} --port ${WEB_PORT} --strictPort"
VITE_API_PROXY_TARGET="${API_BASE_URL}" npm run dev -- --host "${WEB_HOST}" --port "${WEB_PORT}" --strictPort >"${VITE_LOG}" 2>&1 &
VITE_PID="$!"
trap 'kill "${VITE_PID}" >/dev/null 2>&1 || true' EXIT

VITE_URL="http://${WEB_HOST}:${WEB_PORT}/"
log_command "curl -fsS ${VITE_URL}"
for _ in {1..60}; do
  if ! kill -0 "${VITE_PID}" >/dev/null 2>&1; then
    echo "Vite dev server exited before becoming ready. See ${VITE_LOG}"
    write_summary \
      "failed" \
      "WEB-E2E-FLOW" \
      "TEST_INFRA" \
      "vite_dev_server" \
      "Vite dev server exited before becoming ready. See ${VITE_LOG}" \
      "VITE_API_PROXY_TARGET=${API_BASE_URL} npm run dev -- --host ${WEB_HOST} --port ${WEB_PORT} --strictPort"
    exit 1
  fi

  if curl -fsS "${VITE_URL}" >/dev/null; then
    break
  fi

  sleep 1
done

if ! curl -fsS "${VITE_URL}" >/dev/null; then
  echo "Vite dev server did not become ready at ${VITE_URL}. See ${VITE_LOG}"
  write_summary \
    "failed" \
    "WEB-E2E-FLOW" \
    "TEST_INFRA" \
    "vite_dev_server" \
    "Vite dev server did not become ready at ${VITE_URL}. See ${VITE_LOG}" \
    "curl -fsS ${VITE_URL}"
  exit 1
fi

export PLAYWRIGHT_BASE_URL="${VITE_URL}"
export TEST_RUN_REPORT_DIR

FLOW_CMD="PLAYWRIGHT_OUTPUT_DIR=${ARTIFACT_DIR}/flow-results PLAYWRIGHT_HTML_REPORT=${ARTIFACT_DIR}/flow-report npm run test:e2e"
log_command "${FLOW_CMD}"
PLAYWRIGHT_OUTPUT_DIR="${ARTIFACT_DIR}/flow-results" \
PLAYWRIGHT_HTML_REPORT="${ARTIFACT_DIR}/flow-report" \
  npm run test:e2e
FLOW_STATUS="$?"
if [[ "${FLOW_STATUS}" -ne 0 ]]; then
  write_summary \
    "failed" \
    "WEB-E2E-FLOW" \
    "SYSTEM_BUG" \
    "playwright_flow" \
    "Playwright flow command failed with exit status ${FLOW_STATUS}" \
    "${FLOW_CMD}"
  exit "${FLOW_STATUS}"
fi

VISUAL_CMD="PLAYWRIGHT_OUTPUT_DIR=${ARTIFACT_DIR}/visual-results PLAYWRIGHT_HTML_REPORT=${ARTIFACT_DIR}/visual-report npm run test:visual"
log_command "${VISUAL_CMD}"
PLAYWRIGHT_OUTPUT_DIR="${ARTIFACT_DIR}/visual-results" \
PLAYWRIGHT_HTML_REPORT="${ARTIFACT_DIR}/visual-report" \
  npm run test:visual
VISUAL_STATUS="$?"
if [[ "${VISUAL_STATUS}" -ne 0 ]]; then
  write_summary \
    "failed" \
    "WEB-E2E-VISUAL" \
    "VISUAL_REGRESSION" \
    "playwright_visual" \
    "Playwright visual command failed with exit status ${VISUAL_STATUS}" \
    "${VISUAL_CMD}"
  exit "${VISUAL_STATUS}"
fi

write_summary "passed"
