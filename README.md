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

```bash
# 安装
pip install -e ".[dev]"

# 配置 LLM 提供商
# 编辑 llm_config.yaml，或在网页端 /config 配置
export MOONSHOT_API_KEY=...
export ANTHROPIC_API_KEY=...

# 启动服务
PYTHONPATH=src python3.11 -m uvicorn novel_dev.api:app --reload

# 或启动 MCP 服务
PYTHONPATH=src python3.11 -m novel_dev.mcp_server

# 运行测试
PYTHONPATH=src python3.11 -m pytest tests/ -q
```

## API

REST API：`http://localhost:8000/api/`
Web UI：`http://localhost:8000/`

主要接口：
- `POST /api/novels/{id}/documents/upload` — 上传设定/风格文档
- `POST /api/novels/{id}/brainstorm` — 生成大纲
- `POST /api/novels/{id}/volume_plan` — 分卷规划
- `POST /api/novels/{id}/chapters/{cid}/draft` — 生成章节草稿
- `POST /api/novels/{id}/advance` — 推进流水线阶段
- `POST /api/novels/{id}/export` — 导出 Markdown

## 配置

`llm_config.yaml` 控制每个 Agent 的 LLM 设置：

```yaml
agents:
  brainstorm_agent:
    provider: anthropic
    model: claude-opus-4-6
    fallback:
      provider: openai_compatible
      model: gpt-4.1
```

## License

MIT
