# novel-dev

AI 驱动的小说创作系统。通过多 Agent 流水线，从设定文档到成品章节的完整自动化写作。

## 架构

```
脑暴 -> 分卷规划 -> 上下文准备 -> 草稿写作 -> 评审 -> 编辑 -> 快速审查 -> 归档 -> 导出
```

**Agent（12 个，全部 LLM 驱动）：**

- **BrainstormAgent** — 根据设定文档生成大纲
- **VolumePlannerAgent** — 分卷规划，带自评循环
- **ContextAgent** — 两步 RAG 场景上下文构建（分析需求 → 查库 → 生成场景描述）
- **WriterAgent** — 逐节拍写作
- **CriticAgent** — 五维度章节评分
- **EditorAgent** — 逐节拍润色
- **FastReviewAgent** — 一致性与连贯性检查
- **LibrarianAgent** — 世界状态提取
- **SettingExtractorAgent** — 设定文档结构化提取
- **StyleProfilerAgent** — 写作风格分析
- **FileClassifier** — 文档类型分类

**技术栈：** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic, Vue 3 SPA

## 快速开始

### 一键安装（自动启动所有依赖服务）

```bash
chmod +x install.sh
./install.sh
```

安装脚本会自动：
1. 安装 PostgreSQL + pgvector（如未安装）
2. 启动数据库服务
3. 创建 `novel_dev` 数据库并启用向量扩展
4. 安装 Python 依赖
5. 运行数据库迁移
6. 启动 Embedding 服务（bge-m3）

### 手动安装

```bash
# 安装依赖
pip install -e ".[dev]"

# 启动 PostgreSQL + pgvector（需要自行配置）
# 创建数据库：
#   createdb novel_dev
#   psql -d novel_dev -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 配置环境变量
export DATABASE_URL="postgresql+asyncpg://用户名@localhost/novel_dev"

# 运行迁移
alembic upgrade head

# 启动 Embedding 服务（后台运行）
python3 embedding_server.py &

# 启动 API 服务
PYTHONPATH=src python3.11 -m uvicorn novel_dev.api:app --reload
```

### 配置 LLM

编辑 `llm_config.yaml`，或设置环境变量：
```bash
export ANTHROPIC_API_KEY=...
export MOONSHOT_API_KEY=...
export KIMI_API_KEY=...
export MINIMAX_API_KEY=...
export DEEPSEEK_API_KEY=...
```

`llm_config.yaml` 中的模型配置会通过 `api_key_env` 引用 `KIMI_API_KEY`、`MINIMAX_API_KEY` 和 `DEEPSEEK_API_KEY`。

## 服务地址

- **API 服务**: `http://localhost:8000/api/`
- **Web UI**: `http://localhost:8000/`
- **Embedding 服务**: `http://127.0.0.1:9997`
- **数据库**: `postgresql://用户名@localhost/novel_dev`

## License

MIT
