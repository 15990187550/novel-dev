# Embedding 服务脚本

## 快速开始

### 1. 安装 xinference

```bash
# CPU 环境（推荐，足够跑 embedding）
pip install xinference

# 或 GPU 环境（有 NVIDIA GPU 时）
pip install "xinference[all]"
```

### 2. 启动 bge-m3 服务

```bash
./scripts/start-embedding-server.sh
```

首次运行会自动下载 `bge-m3` 模型（约 2GB，国内建议挂代理或换源）。

### 3. 配置 novel-dev

在 `llm_config.yaml` 中修改 embedding 配置：

```yaml
embedding:
  provider: openai_compatible
  model: bge-m3
  base_url: http://127.0.0.1:9997/v1
  timeout: 30
  retries: 3
  dimensions: 1024
```

### 4. 验证

```bash
curl http://127.0.0.1:9997/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"bge-m3","input":["你好世界"],"dimensions":1024}'
```

## 为什么选 bge-m3

- **中文最强**：BAAI 出品，在中文语义理解上远超 OpenAI text-embedding-3-small
- **完全免费**：本地运行，无 API 调用成本
- **维度可控**：支持 1024 维（默认），可通过 `dimensions` 调整
- **体积适中**：约 2GB，普通笔记本 CPU 即可流畅运行

## 备选方案

### 换其他模型

在 `start-embedding-server.sh` 中修改 `MODEL_NAME`：

| 模型 | 特点 | 体积 |
|------|------|------|
| `bge-m3` | 中英多语言，效果最好 | ~2GB |
| `bge-large-zh-v1.5` | 纯中文，效果也很好 | ~1.3GB |
| `gte-large` | 阿里出品，中文不错 | ~1.5GB |
| `nomic-embed-text-v1.5` | 轻量，CPU 快 | ~500MB |

### Docker 方式（不推荐，体积大）

```bash
docker run -p 9997:9997 \
  -v ~/.xinference:/root/.xinference \
  --gpus all \
  xprobe/xinference:latest \
  xinference-local --host 0.0.0.0 --port 9997
```

然后手动注册模型：

```bash
curl -X POST http://127.0.0.1:9997/v1/models \
  -H 'Content-Type: application/json' \
  -d '{
    "model_name": "bge-m3",
    "model_type": "embedding",
    "model_format": "pytorch"
  }'
```

## 常见问题

**Q: 模型下载太慢怎么办？**

设置 HuggingFace 镜像源：

```bash
export HF_ENDPOINT=https://hf-mirror.com
./scripts/start-embedding-server.sh
```

**Q: 内存不足怎么办？**

换用更小的模型：

```bash
MODEL_NAME=nomic-embed-text-v1.5 ./scripts/start-embedding-server.sh
```

**Q: 如何查看已注册的模型？**

```bash
curl http://127.0.0.1:9997/v1/models
```

**Q: 如何卸载模型？**

```bash
xinference terminate --model-uid bge-m3
```

**Q: 如何彻底停止服务？**

```bash
pkill -f xinference-local
```

## Local verification

Run the full local gate before handing off changes:

```bash
./scripts/verify_local.sh
```

It runs backend tests, Python compile checks, web tests, and the web build from the expected project directories.

## Generation Quality Summary

After a real or fake generation run exports a snapshot JSON, summarize quality gates with:

```bash
PYTHONPATH=src python3.11 -m novel_dev.testing.cli quality-summary \
  --input-json reports/test-runs/<run-id>/artifacts/generation_snapshot.json \
  --report-root reports/test-runs \
  --run-id <run-id>-quality
```

The command writes the standard `summary.json` and `summary.md` report. It fails the run when setting quality, synopsis quality, volume writability, or chapter quality gate checks contain blocking issues.
