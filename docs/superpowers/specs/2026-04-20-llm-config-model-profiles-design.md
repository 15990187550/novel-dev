# LLM 配置模型引用重构设计

## 背景

当前 `llm_config.yaml` 中每个 agent 都重复配置 `provider`/`model`/`base_url`，且 minimax 的模型名和 base_url 与实际不符。需要重构为全局 models 定义 + agent 引用的模式。

## 目标

1. 全局 models 段只定义两个模型 profile：`kimi-for-coding` 和 `minimax-2.7`
2. 所有 agent 通过 `model: <profile_name>` 引用，不再重复写连接信息
3. per-agent 只保留 `temperature`/`timeout`/`retries` 等调参
4. per-task 可覆盖 `model`（切换 profile）和 `temperature` 等参数
5. fallback 同样引用 model profile

## 最终配置结构

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

## 配置合并规则

### 主配置合并优先级（从高到低）

1. `task` 层覆盖（task 中可写 `model: xxx` 切换 profile）
2. `agent` 层覆盖
3. `models[profile]` 基础连接信息
4. `defaults` 全局默认值

### fallback 合并规则

fallback 继承 agent 层基础配置（不含 `tasks` 和 `fallback` 自身），然后 fallback 自身的字段覆盖。这样 fallback 只需要写：
- `model`（必须，引用 model profile）
- 和主模型不同的参数（如 timeout、temperature）

举例：`brainstorm_agent` 的 fallback 继承 agent 层的 `temperature: 0.9`、`retries: 3`，只需显式写 `timeout: 60` 和 `model: minimax-2-7`。

## 代码改动

### 1. `llm_config.yaml`

完全重写，按新结构。`defaults` 段去掉 `provider`/`model`/`base_url`，仅保留 `timeout`/`retries`/`temperature`。

### 2. `src/novel_dev/llm/factory.py`

重写 `_resolve_config()`，新增 `_build_task_config_with_models()`：

```python
def _resolve_config(self, agent_name: str, task: Optional[str]) -> TaskConfig:
    defaults = self._config.get("defaults", {})
    normalized = self._normalize_agent_name(agent_name)
    agent_cfg = self._config.get("agents", {}).get(normalized, {})
    task_cfg = agent_cfg.get("tasks", {}).get(task, {}) if task else {}

    # agent 层基础配置（不含 tasks/fallback，供 fallback 继承）
    agent_base = {k: v for k, v in agent_cfg.items() if k not in ("tasks", "fallback")}

    # 合并主配置：defaults → agent → task
    merged = {**defaults, **agent_cfg, **task_cfg}
    merged.pop("tasks", None)

    # 解析 fallback：继承 agent_base，fallback 自身覆盖
    fallback = None
    fallback_raw = merged.pop("fallback", None)
    if fallback_raw:
        fallback_merged = {**defaults, **agent_base, **fallback_raw}
        fallback = self._build_task_config_with_models(fallback_merged)

    return self._build_task_config_with_models(merged, fallback=fallback)


def _build_task_config_with_models(
    self, raw: dict, fallback: Optional[TaskConfig] = None
) -> TaskConfig:
    raw = raw.copy()

    # 解析 model profile 引用
    model_ref = raw.pop("model", None)
    if model_ref:
        profile = self._config.get("models", {}).get(model_ref, {})
        if not profile:
            raise LLMConfigError(f"Unknown model profile: {model_ref}")
        # profile 打底，raw 覆盖（agent/task 层的 temperature/timeout 等优先级更高）
        raw = {**profile, **raw}
    else:
        raise LLMConfigError("Missing model reference")

    if not raw.get("provider") or not raw.get("model"):
        raise LLMConfigError("Missing provider or model after resolving profile")

    return TaskConfig(fallback=fallback, **raw)
```

### 3. `src/novel_dev/llm/models.py`

`TaskConfig` 的 `provider`/`model`/`base_url` 从 `Required` 改为 `Optional[str]`，因为解析前可能不完整。

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

但 `_resolve_config` 返回前已确保 `provider` 和 `model` 非空，不影响下游使用。

### 4. 测试

更新 `tests/` 中所有硬编码的 mock config，改为新格式（`models` 段 + agent `model` 引用）。

## 错误处理

- `model` 引用不存在的 profile → `LLMConfigError`
- agent 或 task 未配置 `model` → `LLMConfigError`
- 解析 profile 后仍缺少 `provider` 或 `model` → `LLMConfigError`

## 兼容性

本次重构一次性完成，不保留旧格式兼容层。所有 agent 配置统一迁移。
