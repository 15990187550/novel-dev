# novel-dev

AI-powered novel writing system. Generate Chinese web novels through a structured multi-agent pipeline.

## Architecture

```
Brainstorm -> Volume Plan -> Context Preparation -> Draft -> Review -> Edit -> Fast Review -> Librarian -> Export
```

**Agents:** 12 specialized agents, all LLM-driven
- BrainstormAgent: Synopsis generation from setting documents
- VolumePlannerAgent: Volume/chapter planning with self-review loop
- ContextAgent: Two-step RAG for rich scene context (analyze needs -> query DB -> generate description)
- WriterAgent: Beat-by-beat draft generation
- CriticAgent: 5-dimension chapter scoring
- EditorAgent: Beat-level polishing
- FastReviewAgent: Consistency and cohesion check
- LibrarianAgent: World-state extraction
- SettingExtractorAgent: Structured extraction from setting docs
- StyleProfilerAgent: Writing style analysis
- FileClassifier: Document type classification

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Pydantic, Vue 3 SPA

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Configure LLM providers
# Edit llm_config.yaml or use the web UI at /config
export MOONSHOT_API_KEY=...
export ANTHROPIC_API_KEY=...

# Start server
PYTHONPATH=src python3.11 -m uvicorn novel_dev.api:app --reload

# Or start MCP server
PYTHONPATH=src python3.11 -m novel_dev.mcp_server

# Run tests
PYTHONPATH=src python3.11 -m pytest tests/ -q
```

## API

REST API at `http://localhost:8000/api/`
Web UI at `http://localhost:8000/`

Key endpoints:
- `POST /api/novels/{id}/documents/upload` - Upload setting/style documents
- `POST /api/novels/{id}/brainstorm` - Generate synopsis
- `POST /api/novels/{id}/volume_plan` - Plan volume structure
- `POST /api/novels/{id}/chapters/{cid}/draft` - Generate chapter draft
- `POST /api/novels/{id}/advance` - Advance pipeline phase
- `POST /api/novels/{id}/export` - Export to markdown

## Configuration

`llm_config.yaml` controls per-agent LLM settings:
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
