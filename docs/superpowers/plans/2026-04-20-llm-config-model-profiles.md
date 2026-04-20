# LLM Config Model Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `llm_config.yaml` to use global `models` profiles with per-agent references, eliminating duplicate `base_url`/`provider`/`model` configuration.

**Architecture:** Add a `models` top-level section to YAML where each profile defines provider/model/base_url. Agents reference profiles via `model: <profile_name>`. `LLMFactory._resolve_config()` merges defaults → model profile → agent → task, with fallback inheriting agent base config.

**Tech Stack:** Python, Pydantic, PyYAML, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `llm_config.yaml` | Rewrite | Production LLM configuration with new models+agents structure |
| `src/novel_dev/llm/models.py` | Modify | `TaskConfig.provider`/`model`/`base_url` → `Optional[str]` |
| `src/novel_dev/llm/factory.py` | Modify | Rewrite `_resolve_config()`, add `_build_task_config_with_models()` |
| `src/novel_dev/api/config_routes.py` | Modify | Remove `TaskConfig.model_validate(defaults)` validation; validate full config instead |
| `tests/llm/test_factory.py` | Modify | Update `temp_yaml` fixture to new format; update assertions |
| `tests/fixtures/test_embed_config.yaml` | Modify | Update `defaults` (remove `provider`) |
| `tests/test_api/test_config_routes.py` | Modify | Update test payloads to new config format |

---

### Task 1: Make TaskConfig fields optional for intermediate parsing

**Files:**
- Modify: `src/novel_dev/llm/models.py:24-32`
- Test: `tests/llm/test_factory.py` (pass-through)

- [ ] **Step 1: Modify `TaskConfig` to make provider/model/base_url Optional**

```python
class TaskConfig(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 2
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    fallback: Optional["TaskConfig"] = None
```

- [ ] **Step 2: Run tests to ensure no regressions**

Run: `PYTHONPATH=src python3.11 -m pytest tests/llm/test_factory.py -v`
Expected: All pass (fields were required but always provided in tests)

- [ ] **Step 3: Commit**

```bash
git add src/novel_dev/llm/models.py
git commit -m "refactor(llm): make TaskConfig provider/model/base_url optional"
```

---

### Task 2: Rewrite LLMFactory config resolution

**Files:**
- Modify: `src/novel_dev/llm/factory.py:88-113` (`_build_task_config` and `_resolve_config`)
- Test: `tests/llm/test_factory.py`

- [ ] **Step 1: Replace `_resolve_config` and `_build_task_config` with model-profile-aware logic**

```python
def _build_task_config(self, raw: dict) -> TaskConfig:
    raw = raw.copy()
    fallback_raw = raw.pop("fallback", None)
    fallback = None
    if fallback_raw:
        fallback = self._build_task_config(fallback_raw)
    return TaskConfig(fallback=fallback, **raw)

def _resolve_config(self, agent_name: str, task: Optional[str]) -> TaskConfig:
    defaults = self._config.get("defaults", {})
    normalized_name = self._normalize_agent_name(agent_name)
    agent_cfg = self._config.get("agents", {}).get(normalized_name, {})
    task_cfg = agent_cfg.get("tasks", {}).get(task, {}) if task else {}

    # agent base config (without tasks/fallback) — inherited by fallback
    agent_base = {k: v for k, v in agent_cfg.items() if k not in ("tasks", "fallback")}

    # Merge main config: defaults → agent → task
    merged = {**defaults, **agent_cfg, **task_cfg}
    merged.pop("tasks", None)

    # Resolve fallback: inherit agent_base, then fallback self overrides
    fallback = None
    fallback_raw = merged.pop("fallback", None)
    if fallback_raw:
        fallback_merged = {**defaults, **agent_base, **fallback_raw}
        fallback = self._resolve_model_profile(fallback_merged)

    return self._resolve_model_profile(merged, fallback=fallback)

def _resolve_model_profile(
    self, raw: dict, fallback: Optional[TaskConfig] = None
) -> TaskConfig:
    raw = raw.copy()
    model_ref = raw.pop("model", None)
    if model_ref:
        profile = self._config.get("models", {}).get(model_ref, {})
        if not profile:
            raise LLMConfigError(f"Unknown model profile: {model_ref}")
        raw = {**profile, **raw}
    else:
        raise LLMConfigError("Missing model reference")

    if not raw.get("provider") or not raw.get("model"):
        raise LLMConfigError("Missing provider or model after resolving profile")

    return self._build_task_config({**raw, "fallback": fallback})
```

- [ ] **Step 2: Run existing tests — expect failures because test fixture uses old format**

Run: `PYTHONPATH=src python3.11 -m pytest tests/llm/test_factory.py -v`
Expected: Multiple failures (missing model profile in temp_yaml)

- [ ] **Step 3: Commit partial implementation**

```bash
git add src/novel_dev/llm/factory.py
git commit -m "refactor(llm): rewrite _resolve_config with model profile resolution"
```

---

### Task 3: Update test fixture to new config format

**Files:**
- Modify: `tests/llm/test_factory.py:12-37` (`temp_yaml` fixture)
- Test: `tests/llm/test_factory.py`

- [ ] **Step 1: Rewrite `temp_yaml` fixture with `models` section**

```python
@pytest.fixture
def temp_yaml(tmp_path):
    path = tmp_path / "llm_config.yaml"
    path.write_text("""
defaults:
  timeout: 30
  retries: 2
  temperature: 0.7

models:
  gpt-4:
    provider: openai_compatible
    model: gpt-4
    base_url: https://api.openai.com/v1
  claude-opus:
    provider: anthropic
    model: claude-opus-4-6

agents:
  test_agent:
    model: claude-opus
    timeout: 120
    retries: 3
    fallback:
      model: gpt-4
      timeout: 60
      retries: 2
    tasks:
      special_task:
        model: claude-opus
        timeout: 60
""")
    return str(path)
```

- [ ] **Step 2: Update test assertions — `fallback.model` stays `"gpt-4"` (resolved from profile)**

In `test_resolve_config_agent_level`, the assertion `cfg.fallback.model == "gpt-4.1"` → keep as-is? No wait — in new fixture, fallback references `gpt-4` profile which has `model: gpt-4`. So fallback.model should be `"gpt-4"`.

Update:
- `test_resolve_config_agent_level`: `cfg.fallback.model == "gpt-4"`
- `test_resolve_config_task_level`: `cfg.fallback.model == "gpt-4"`

Also update `test_resolve_config_fallback_to_defaults`: the old defaults had `provider: openai_compatible` + `model: gpt-4`. In new format, defaults no longer have provider/model, so unknown agent will hit `Missing model reference` error instead of falling back to defaults.

Actually wait — the test `test_resolve_config_fallback_to_defaults` expects unknown_agent to get defaults. With new format, unknown_agent has no `model` reference → should raise. This test needs to change: either delete it (unknown agent without model = error), or test a different path.

Let me reconsider. The old behavior: unknown agent without agent config falls back to defaults (which included provider+model). New behavior: unknown agent has no model reference → error. This is intentional — every agent must declare its model.

So replace `test_resolve_config_fallback_to_defaults` with a test for unknown profile error.

- [ ] **Step 3: Replace `test_resolve_config_fallback_to_defaults` with unknown profile error test**

```python
def test_resolve_config_unknown_profile_raises(temp_yaml):
    settings = Settings(llm_config_path=temp_yaml, anthropic_api_key="ak")
    factory = LLMFactory(settings)
    # Manually create a config with bad model reference
    factory._config["agents"]["bad_agent"] = {"model": "nonexistent"}
    with pytest.raises(LLMConfigError, match="Unknown model profile"):
        factory._resolve_config("bad_agent", None)
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=src python3.11 -m pytest tests/llm/test_factory.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add tests/llm/test_factory.py
git commit -m "test(llm): update factory tests for model profile config format"
```

---

### Task 4: Update embed test fixture

**Files:**
- Modify: `tests/fixtures/test_embed_config.yaml:1-3`

- [ ] **Step 1: Remove `provider` from defaults (no longer belongs there)**

```yaml
defaults:
  timeout: 30

embedding:
  provider: openai_compatible
  model: text-embedding-3-small
  base_url: https://api.openai.com/v1
  timeout: 30
  retries: 3
  dimensions: 1536
```

- [ ] **Step 2: Run embed tests**

Run: `PYTHONPATH=src python3.11 -m pytest tests/llm/test_factory_embedder.py -v`
Expected: All pass (defaults provider was never used by get_embedder)

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/test_embed_config.yaml
git commit -m "test(fixtures): remove provider from embed config defaults"
```

---

### Task 5: Update config routes validation

**Files:**
- Modify: `src/novel_dev/api/config_routes.py:35-47`
- Test: `tests/test_api/test_config_routes.py`

- [ ] **Step 1: Remove `TaskConfig.model_validate(defaults)` — defaults no longer has required fields**

```python
@router.post("/api/config/llm")
async def save_llm_config(payload: LLMConfigPayload):
    import yaml
    config_dir = os.path.dirname(settings.llm_config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(settings.llm_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload.config, f, allow_unicode=True, sort_keys=False)
    return {"saved": True}
```

- [ ] **Step 2: Update config routes tests to new format**

In `test_get_llm_config`, change:
```python
config_path.write_text("defaults:\n  timeout: 30\nmodels:\n  gpt-4:\n    provider: openai_compatible\n    model: gpt-4\n")
assert resp.json()["defaults"]["timeout"] == 30
```

In `test_save_llm_config`, change:
```python
resp = await client.post("/api/config/llm", json={"config": {"defaults": {"timeout": 30}, "models": {"gpt-4": {"provider": "openai_compatible", "model": "gpt-4"}}}})
```

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=src python3.11 -m pytest tests/test_api/test_config_routes.py -v`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add src/novel_dev/api/config_routes.py tests/test_api/test_config_routes.py
git commit -m "refactor(api): update config routes for new llm config format"
```

---

### Task 6: Rewrite production llm_config.yaml

**Files:**
- Rewrite: `llm_config.yaml`

- [ ] **Step 1: Write new llm_config.yaml**

```yaml
defaults:
  timeout: 30
  retries: 2
  temperature: 0.7

models:
  kimi-for-coding:
    provider: anthropic
    model: kimi-for-coding
    base_url: https://api.kimi.com/coding
  minimax-2-7:
    provider: minimax
    model: Minimax-2.7
    base_url: https://api.minimaxi.com/v1

embedding:
  provider: openai_compatible
  model: bge-m3
  base_url: http://127.0.0.1:9997/v1
  timeout: 30
  retries: 3
  dimensions: 1024

agents:
  brainstorm_agent:
    model: kimi-for-coding
    timeout: 120
    retries: 3
    temperature: 0.9
    fallback:
      model: minimax-2-7
      timeout: 60
      temperature: 0.9
    tasks:
      generate_synopsis:
        temperature: 0.9
      score_synopsis:
        temperature: 0.2

  volume_planner_agent:
    model: kimi-for-coding
    timeout: 60
    fallback:
      model: minimax-2-7
      timeout: 120
    tasks:
      generate_volume_plan:
        timeout: 120
        retries: 3
        temperature: 0.75
      score_volume_plan:
        temperature: 0.2
      revise_volume_plan:
        temperature: 0.65

  setting_extractor_agent:
    model: minimax-2-7
    timeout: 60
    fallback:
      model: kimi-for-coding

  style_profiler_agent:
    model: minimax-2-7
    timeout: 60
    fallback:
      model: kimi-for-coding

  file_classifier:
    model: minimax-2-7
    timeout: 30
    fallback:
      model: kimi-for-coding

  context_agent:
    model: minimax-2-7
    timeout: 30
    fallback:
      model: kimi-for-coding

  writer_agent:
    model: minimax-2-7
    timeout: 60
    temperature: 0.9
    fallback:
      model: kimi-for-coding
    tasks:
      generate_beat:
        temperature: 0.95
      rewrite_beat:
        temperature: 0.8
      generate_relay:
        model: kimi-for-coding
        timeout: 15
        temperature: 0.2

  critic_agent:
    model: kimi-for-coding
    timeout: 60
    temperature: 0.3
    fallback:
      model: minimax-2-7
    tasks:
      score_chapter:
        temperature: 0.2
      score_beats:
        temperature: 0.2

  editor_agent:
    model: kimi-for-coding
    timeout: 60
    temperature: 0.6
    fallback:
      model: minimax-2-7
    tasks:
      polish_beat:
        temperature: 0.6

  fast_review_agent:
    model: kimi-for-coding
    timeout: 30
    temperature: 0.2
    fallback:
      model: minimax-2-7
    tasks:
      fast_review_check:
        temperature: 0.2

  librarian_agent:
    model: kimi-for-coding
    timeout: 60
    temperature: 0.2
    fallback:
      model: minimax-2-7
    tasks:
      extract:
        temperature: 0.15
```

- [ ] **Step 2: Verify YAML is valid**

Run: `python3.11 -c "import yaml; yaml.safe_load(open('llm_config.yaml'))"`
Expected: No error

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=src python3.11 -m pytest tests/ -q`
Expected: All pass (or only pre-existing failures)

- [ ] **Step 4: Commit**

```bash
git add llm_config.yaml
git commit -m "config(llm): rewrite llm_config.yaml with model profiles"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| Global `models` section with 2 profiles | Task 6 |
| Agent `model: <profile>` reference | Task 2, Task 6 |
| Merging priority: task → agent → model → defaults | Task 2 |
| Fallback inherits agent base config | Task 2 |
| Fallback resolves model profile | Task 2 |
| per-task can override `model` (e.g. generate_relay) | Task 2, Task 6 |
| `TaskConfig` fields become Optional | Task 1 |
| Remove old format validation in config routes | Task 5 |
| Update all tests | Task 3, 4, 5 |

### Placeholder Scan

No TBD/TODO/"implement later"/"similar to" patterns found.

### Type Consistency

- `TaskConfig.provider`/`model`/`base_url` consistently `Optional[str]` across all tasks
- `_resolve_config` return type `TaskConfig` preserved
- `_build_task_config` signature preserved

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-20-llm-config-model-profiles.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
