#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
DATASET="${DATASET:-minimal_builtin}"
REPORT_ROOT="${REPORT_ROOT:-${ROOT_DIR}/reports/test-runs}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
LLM_MODE="${LLM_MODE:-real_then_fake_on_external_block}"
ACCEPTANCE_SCOPE="${ACCEPTANCE_SCOPE:-real-contract}"
STAGE="${STAGE:-}"
RUN_ID="${RUN_ID:-}"

args=(
  generation
  --dataset "${DATASET}"
  --llm-mode "${LLM_MODE}"
  --report-root "${REPORT_ROOT}"
  --api-base-url "${API_BASE_URL}"
)

if [[ "${ACCEPTANCE_SCOPE}" == "real-contract" || "${ACCEPTANCE_SCOPE}" == "real-e2e-export" ]]; then
  args+=(--acceptance-scope "${ACCEPTANCE_SCOPE}")
fi

if [[ -n "${STAGE}" ]]; then
  args+=(--stage "${STAGE}")
fi

if [[ -n "${RUN_ID}" ]]; then
  args+=(--run-id "${RUN_ID}")
fi

# User-provided CLI args are appended last so explicit CLI values override
# wrapper defaults. Invalid ACCEPTANCE_SCOPE env values are omitted above so
# they do not fail parsing before a later explicit --acceptance-scope.
args+=("$@")

cd "${ROOT_DIR}"
PYTHONPATH=src "${PYTHON_BIN}" -m novel_dev.testing.cli "${args[@]}"
