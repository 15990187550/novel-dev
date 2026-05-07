#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"
DATASET="${DATASET:-minimal_builtin}"
REPORT_ROOT="${REPORT_ROOT:-${ROOT_DIR}/reports/test-runs}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
LLM_MODE="${LLM_MODE:-real_then_fake_on_external_block}"
STAGE="${STAGE:-}"
RUN_ID="${RUN_ID:-}"

args=(
  generation
  --dataset "${DATASET}"
  --llm-mode "${LLM_MODE}"
  --report-root "${REPORT_ROOT}"
  --api-base-url "${API_BASE_URL}"
)

if [[ -n "${STAGE}" ]]; then
  args+=(--stage "${STAGE}")
fi

if [[ -n "${RUN_ID}" ]]; then
  args+=(--run-id "${RUN_ID}")
fi

# User-provided CLI args are appended last so argparse keeps explicit values
# when an option is provided both by environment defaults and the command line.
args+=("$@")

cd "${ROOT_DIR}"
PYTHONPATH=src "${PYTHON_BIN}" -m novel_dev.testing.cli "${args[@]}"
