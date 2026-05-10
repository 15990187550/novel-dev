#!/usr/bin/env bash

novel_dev_load_env() {
  local env_file="${1:-.env}"
  if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
  fi
}

novel_dev_require_env() {
  local missing=()
  local name
  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("${name}")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    echo "缺少必要环境变量: ${missing[*]}" >&2
    echo "请在 .env 或当前 shell 环境中配置后重试。" >&2
    exit 1
  fi
}
