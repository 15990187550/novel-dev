#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/src/novel_dev/web"

echo "==> Python tests"
(
  cd "${ROOT_DIR}"
  PYTHONPATH=src python3.11 -m pytest -q
)

echo "==> Python compile check"
(
  cd "${ROOT_DIR}"
  PYTHONPATH=src python3.11 -m compileall -q src/novel_dev
)

echo "==> Fake generation flow"
(
  cd "${ROOT_DIR}"
  PYTHONPATH=src python3.11 -m pytest tests/generation/test_minimal_generation_flow.py -q
)

echo "==> Web tests"
(
  cd "${WEB_DIR}"
  npm run test
)

echo "==> Web build"
(
  cd "${WEB_DIR}"
  npm run build
)

echo "==> Local verification complete"
