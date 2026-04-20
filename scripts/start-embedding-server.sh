#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# 使用 xinference 本地启动 bge-m3 embedding 模型
# ------------------------------------------------------------------
# 前置依赖：
#   pip install "xinference[all]"
#
# 用法：
#   ./scripts/start-embedding-server.sh
#
# 首次运行会自动下载模型（约 2GB，依赖网络）
# ------------------------------------------------------------------

XINFERENCE_HOST="${XINFERENCE_HOST:-0.0.0.0}"
XINFERENCE_PORT="${XINFERENCE_PORT:-9997}"
MODEL_NAME="${MODEL_NAME:-bge-m3}"
MODEL_UID="${MODEL_UID:-bge-m3}"

BASE_URL="http://127.0.0.1:${XINFERENCE_PORT}/v1"

echo "=========================================="
echo "Embedding 服务启动脚本"
echo "=========================================="
echo ""

# ---- 1. 检查 xinference 是否安装 --------------------------------
if ! command -v xinference-local &>/dev/null; then
  echo "❌ xinference 未安装，请先执行："
  echo "   pip install \"xinference[all]\""
  echo ""
  echo "注意："
  echo "  - 若只有 CPU，去掉 [all]，安装基础版即可："
  echo "      pip install xinference"
  echo "  - 若有 NVIDIA GPU，确保已安装 CUDA 和 torch："
  echo "      pip install \"xinference[all]\""
  exit 1
fi

echo "✅ xinference 已安装"

# ---- 2. 检查服务是否已在运行 ------------------------------------
if curl -sf "${BASE_URL}/models" &>/dev/null; then
  echo "ℹ️  xinference 服务已在 ${BASE_URL} 运行"
else
  echo "🚀 启动 xinference 服务 (${XINFERENCE_HOST}:${XINFERENCE_PORT}) ..."
  xinference-local --host "${XINFERENCE_HOST}" --port "${XINFERENCE_PORT}" &
  PID=$!
  sleep 2

  # 等待服务就绪
  echo "⏳ 等待服务就绪 ..."
  for i in {1..30}; do
    if curl -sf "${BASE_URL}/models" &>/dev/null; then
      echo "✅ 服务已就绪"
      break
    fi
    if ! kill -0 $PID 2>/dev/null; then
      echo "❌ xinference 进程意外退出"
      exit 1
    fi
    sleep 1
  done
fi

# ---- 3. 检查模型是否已注册 --------------------------------------
if curl -sf "${BASE_URL}/models" | grep -q "\"${MODEL_UID}\"" 2>/dev/null; then
  echo "ℹ️  模型 ${MODEL_UID} 已注册"
else
  echo "🚀 注册 embedding 模型 ${MODEL_NAME} ..."
  echo "   首次下载约 2GB，请耐心等待 ..."
  xinference launch \
    --endpoint "http://127.0.0.1:${XINFERENCE_PORT}" \
    --model-name "${MODEL_NAME}" \
    --model-type embedding \
    --model-format pytorch \
    --size-in-billions 0 \
    --quantization none
fi

# ---- 4. 验证 ----------------------------------------------------
echo ""
echo "=========================================="
echo "✅ Embedding 服务已就绪"
echo "=========================================="
echo ""
echo "接口地址: ${BASE_URL}"
echo "模型 ID : ${MODEL_UID}"
echo ""
echo "请在 llm_config.yaml 中配置："
echo ""
cat <<YAML
embedding:
  provider: openai_compatible
  model: ${MODEL_UID}
  base_url: ${BASE_URL}
  timeout: 30
  retries: 3
  dimensions: 1024
YAML
echo ""
echo "测试命令："
echo "  curl ${BASE_URL}/embeddings -H 'Content-Type: application/json' \\"
echo "    -d '{\"model\":\"${MODEL_UID}\",\"input\":[\"你好\"],\"dimensions\":1024}'"
echo ""
echo "停止服务："
echo "  pkill -f xinference-local"
