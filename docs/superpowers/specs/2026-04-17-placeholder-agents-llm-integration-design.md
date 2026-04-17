# Placeholder Agents LLM Integration Design

> 将项目中剩余的启发式/正则/硬编码 agent 替换为 LLM 驱动。

## Scope

| Agent | 当前实现 | 替换方式 |
|-------|---------|---------|
| `SettingExtractorAgent` | 正则匹配关键词 | LLM 全文理解后结构化提取 |
| `StyleProfilerAgent` | 统计句长/词频/关键词 | LLM 分析风格、视角、节奏 |
| `FileClassifier` | 文件名关键词匹配 | LLM 根据文件名+内容预览分类 |
| `ContextAgent._load_location_context()` | 返回空字符串 | LLM 推断地点 + 数据库回填 parent/narrative |
| `VolumePlannerAgent._generate_volume_plan()` | 硬编码 `第{i+1}章` | LLM 根据 synopsis 生成有意义的章节规划 |

## Architecture

### Shared Helper

新增 `src/novel_dev/agents/_llm_helpers.py`：

```python
import asyncio
from typing import Callable, TypeVar
from novel_dev.llm import llm_factory
from novel_dev.llm.models import ChatMessage
from pydantic import ValidationError
import json

T = TypeVar("T")

async def call_and_parse(
    agent_name: str,
    task: str,
    prompt: str,
    parser: Callable[[str], T],
    max_retries: int = 3,
) -> T:
    client = llm_factory.get(agent_name, task=task)
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.acomplete([ChatMessage(role="user", content=prompt)])
            return parser(response.text)
        except (ValidationError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
    raise RuntimeError(
        f"LLM parse failed after {max_retries} retries for {agent_name}/{task}: {last_error}"
    ) from last_error
```

所有 5 个改动点统一通过此函数调用 LLM。

### Error Handling

- **网络错误**（超时、限流）：由底层 `RetryableDriver` 处理（指数退避，2-5 次重试）
- **解析错误**（JSON 无效、Pydantic ValidationError）：由 `call_and_parse` 处理（最多 3 次重试，间隔递增）
- **用尽重试后**：抛 `RuntimeError`，中断流程，不 fallback 到旧实现

## Per-Agent Design

### 1. SettingExtractorAgent

```python
async def extract(self, text: str) -> ExtractedSetting:
    MAX_CHARS = 24000
    truncated = text[:MAX_CHARS]
    prompt = (
        "你是一位小说设定提取专家。请从以下设定文档中提取结构化信息，"
        "返回严格符合 ExtractedSetting Schema 的 JSON：\n"
        "1. worldview: 世界观概述\n"
        "2. power_system: 修炼/力量体系\n"
        "3. factions: 势力/宗门分布\n"
        "4. character_profiles: 人物列表（每人含 name, identity, personality, goal）\n"
        "5. important_items: 重要物品列表（每件含 name, description, significance）\n"
        "6. plot_synopsis: 剧情梗概\n\n"
        f"文档内容：\n\n{truncated}"
    )
    return await call_and_parse(
        "SettingExtractorAgent", "extract_setting", prompt,
        ExtractedSetting.model_validate_json, max_retries=3
    )
```

**删除：** `_extract_section`、`_extract_characters`、`_extract_items`

### 2. StyleProfilerAgent

```python
async def profile(self, text: str) -> StyleProfile:
    MAX_CHARS = 24000
    sampled = text[:MAX_CHARS]
    prompt = (
        "你是一位文学风格分析师。请分析以下小说文本的写作风格，"
        "返回严格符合 StyleProfile Schema 的 JSON：\n"
        "1. style_guide: 一段自然语言风格描述（100字以内）\n"
        "2. style_config:\n"
        "   - sentence_patterns: 句式特点（如 avg_length、complexity）\n"
        "   - dialogue_style: 对话风格（如 direct_speech_ratio、dialogue_tag_style）\n"
        "   - rhetoric_devices: 常用修辞手法\n"
        "   - pacing: 叙事节奏（fast/moderate/slow）\n"
        "   - vocabulary_preferences: 高频或特色词汇列表（5-10个）\n"
        "   - perspective: 叙事视角（first_person/limited/omniscient）\n"
        "   - tone: 整体基调（intense/dark/hopeful/romantic 等）\n"
        "   - evolution_notes: 风格演变迹象\n\n"
        f"文本样本：\n\n{sampled}"
    )
    return await call_and_parse(
        "StyleProfilerAgent", "profile_style", prompt,
        StyleProfile.model_validate_json, max_retries=3
    )
```

**删除：** `_chunk_text`、`_sample_chunks`、`_avg_sentence_length`、`_dialogue_ratio`、`_extract_vocabulary`

### 3. FileClassifier

`classify()` 从同步改为异步：

```python
async def classify(self, filename: str, content_preview: str) -> FileClassificationResult:
    MAX_CHARS = 3000
    prompt = (
        "你是一位文件分类专家。请根据文件名和内容片段，判断这是小说设定文档还是风格样本。"
        "返回严格符合 FileClassificationResult Schema 的 JSON：\n"
        "file_type: 'setting' 或 'style_sample'\n"
        "confidence: 0.0-1.0 的置信度\n"
        "reason: 分类理由（简短）\n\n"
        f"文件名：{filename}\n"
        f"内容片段：\n{content_preview[:MAX_CHARS]}"
    )
    return await call_and_parse(
        "FileClassifier", "classify_file", prompt,
        FileClassificationResult.model_validate_json, max_retries=3
    )
```

**删除：** `SETTING_KEYWORDS`、`STYLE_KEYWORDS`

**调用方影响：** `ExtractionService.process_upload` 中 `classification = self.classifier.classify(...)` 改为 `classification = await self.classifier.classify(...)`。

### 4. ContextAgent._load_location_context（两步 RAG）

`LocationContext.narrative` 升级为**导演镜头描述**（200-300 字），包含空间环境、时间状态、在场人物动态、物品线索、情绪基调、与上一场景的衔接。

#### 步骤 1：LLM 分析需求

```python
async def _analyze_context_needs(self, chapter_plan: ChapterPlan, novel_id: str) -> dict:
    prompt = (
        "你是一位小说场景分析师。请根据以下章节计划，分析写这一章需要哪些上下文信息。\n"
        "返回严格 JSON：\n"
        "{\n"
        '  "locations": ["地点名1"],\n'
        '  "entities": ["实体名1"],\n'
        '  "time_range": {"start_tick": -3, "end_tick": 2},\n'
        '  "foreshadowing_keywords": ["关键词1"]\n'
        "}\n\n"
        "说明：\n"
        "- locations: 场景涉及的主要地点\n"
        "- entities: 需要知道最新状态的关键人物/物品（超出章节计划已有实体）\n"
        "- time_range: 相对于 current_tick 的时间范围（如 -3 表示往前3个tick）\n"
        "- foreshadowing_keywords: 用于筛选相关伏笔的关键词\n\n"
        f"章节计划：\n{chapter_plan.model_dump_json()}"
    )
    return await call_and_parse(
        "ContextAgent", "analyze_context_needs", prompt,
        json.loads, max_retries=3
    )
```

#### 步骤 2：按需查库 + LLM 生成场景

```python
async def _load_location_context(
    self, chapter_plan: ChapterPlan, novel_id: str
) -> LocationContext:
    needs = await self._analyze_context_needs(chapter_plan, novel_id)

    # 按需查地点
    location_names = needs.get("locations", [])
    locations = []
    if location_names:
        all_locs = await self.spaceline_repo.list_by_novel(novel_id)
        locations = [loc for loc in all_locs if loc.name in location_names]

    # 按需查实体（合并 chapter_plan 已有 + LLM 补充）
    entity_names = list(set(
        needs.get("entities", []) + self._extract_key_entities_from_plan(chapter_plan)
    ))
    entity_states = []
    if entity_names:
        entities = await self.entity_repo.find_by_names(entity_names, novel_id=novel_id)
        for entity in entities:
            latest = await self.version_repo.get_latest(entity.id)
            entity_states.append({
                "name": entity.name,
                "type": entity.type,
                "state": str(latest.state) if latest else "",
            })

    # 按需查时间线
    state = await self.state_repo.get_state(novel_id)
    current_tick = state.checkpoint_data.get("current_time_tick") if state else None
    timeline_events = []
    if current_tick is not None:
        time_range = needs.get("time_range", {})
        start = current_tick + time_range.get("start_tick", -2)
        end = current_tick + time_range.get("end_tick", 2)
        events = await self.timeline_repo.list_between(start, end, novel_id)
        timeline_events = [{"tick": e.tick, "narrative": e.narrative} for e in events]

    # 按需查伏笔
    keywords = needs.get("foreshadowing_keywords", [])
    all_foreshadowings = await self.foreshadowing_repo.list_active(novel_id=novel_id)
    pending_fs = [
        {"id": fs.id, "content": fs.content}
        for fs in all_foreshadowings
        if any(kw in fs.content for kw in keywords) or not keywords
    ]

    # LLM 生成综合场景
    prompt = (
        "你是一位导演，正在为下一幕戏撰写场景说明。请根据以下所有信息，"
        "写一段 200-300 字的场景镜头描述。这段文字将被直接交给小说家作为写作参考，"
        "所以请用具体、可感知的细节，不要抽象概括。必须包含：\n"
        "- 空间环境（地点、光线、声音、气味、天气等感官细节）\n"
        "- 时间状态（时辰、季节、时间推移感）\n"
        "- 在场人物（谁在场、他们在做什么、彼此的空间关系）\n"
        "- 物品线索（场景中有什么道具、伏笔物品、环境线索）\n"
        "- 情绪基调（压抑、紧张、欢快等，用氛围描写传达，不要直接说'很紧张'）\n"
        "- 与上一场景的衔接（如果上一场景有动作延续，请暗示）\n"
        "返回严格 JSON 格式：\n"
        "{\n"
        '  "current": "当前主要地点名称",\n'
        '  "parent": "上级地点/区域（如有）",\n'
        '  "narrative": "完整的场景镜头描述（200-300字）"\n'
        "}\n\n"
        f"地点：{[loc.model_dump() for loc in locations]}\n"
        f"实体状态：{entity_states}\n"
        f"近期时间线：{timeline_events}\n"
        f"待回收伏笔：{pending_fs}\n"
    )
    return await call_and_parse(
        "ContextAgent", "build_scene_context", prompt,
        LocationContext.model_validate_json, max_retries=3
    )
```

**删除：** 原 `_load_location_context(self, names, novel_id)` 的单行实现。

**调用方改动：** `assemble()` 中 `location_context = await self._load_location_context(key_entity_names, novel_id)` 改为 `location_context = await self._load_location_context(chapter_plan, novel_id)`。

**新增 repo 方法：** `TimelineRepository.list_between(start, end, novel_id)`。

### 5. VolumePlannerAgent._generate_volume_plan

改为 async：

```python
async def _generate_volume_plan(
    self, synopsis: SynopsisData, volume_number: int
) -> VolumePlan:
    MAX_CHARS = 12000
    truncated_synopsis = synopsis.model_dump_json()[:MAX_CHARS]

    prompt = (
        "你是一位小说分卷规划专家。请根据以下大纲数据，"
        "生成一个完整的分卷规划 VolumePlan，返回严格符合 VolumePlan Schema 的 JSON。\n"
        "要求：\n"
        "1. 每章必须有有意义的标题和摘要，不能是'第X章'这种占位符\n"
        "2. 每章拆分为 2-4 个节拍（beats），每个节拍有明确的情节推进\n"
        "3. 章节之间要有连贯性，伏笔要合理分布\n"
        "4. 估算字数要合理\n\n"
        f"大纲数据：\n{truncated_synopsis}\n\n"
        f"当前卷号：{volume_number}"
    )
    return await call_and_parse(
        "VolumePlannerAgent", "generate_volume_plan", prompt,
        VolumePlan.model_validate_json, max_retries=3
    )
```

**调用方改动：** `plan()` 方法中 `volume_plan = self._generate_volume_plan(...)` 改为 `volume_plan = await self._generate_volume_plan(...)`。

## Configuration Updates

`llm_config.yaml` 新增以下配置（均支持 `fallback`）：

```yaml
agents:
  setting_extractor_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 60
    fallback:
      provider: anthropic
      model: claude-sonnet-4-6
      timeout: 60

  style_profiler_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 60
    fallback:
      provider: anthropic
      model: claude-sonnet-4-6
      timeout: 60

  file_classifier:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 30
    fallback:
      provider: anthropic
      model: claude-haiku-4-5-20251001
      timeout: 30

  context_agent:
    provider: openai_compatible
    model: kimi-k2.5
    base_url: https://api.moonshot.cn/v1
    timeout: 30
    fallback:
      provider: anthropic
      model: claude-haiku-4-5-20251001
      timeout: 30

  volume_planner_agent:
    tasks:
      generate_volume_plan:
        timeout: 120
        retries: 3
```

`volume_planner_agent` 本身已有配置，只需在 `tasks` 下新增 `generate_volume_plan` 覆盖项。

## Test Strategy

| 测试文件 | 当前状态 | 改后 |
|---------|---------|------|
| `test_setting_extractor.py` | 测试正则匹配 | mock `llm_factory`，测试 LLM 返回正确 JSON 时的解析和错误重试 |
| `test_style_profiler.py` | 测试 `_chunk_text`、`_sample_chunks`、`_dialogue_ratio` | 删除内部方法测试，mock `llm_factory` 测试 `profile()` |
| `test_file_classifier.py` | 测试关键词匹配 | mock `llm_factory`，测试 `classify()` 为 async |
| `test_volume_planner.py` | 已有 mock 测试 | 可能需要新增/调整初始生成路径的测试用例 |
| `test_context_agent.py` | 确认是否存在 | 如存在，补充 `_load_location_context` 的 mock 测试 |

所有测试使用 `AsyncMock` + `LLMResponse` 模式，与现有 agent 测试一致。

## File Map

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/novel_dev/agents/_llm_helpers.py` | 新增 | `call_and_parse()` 共享函数 |
| `src/novel_dev/agents/setting_extractor.py` | 修改 | `extract()` → LLM，删旧正则方法 |
| `src/novel_dev/agents/style_profiler.py` | 修改 | `profile()` → LLM，删旧统计方法 |
| `src/novel_dev/agents/file_classifier.py` | 修改 | `classify()` → async + LLM，删关键词常量 |
| `src/novel_dev/agents/context_agent.py` | 修改 | `_load_location_context()` → LLM + 数据库回填 |
| `src/novel_dev/agents/volume_planner.py` | 修改 | `_generate_volume_plan()` → async + LLM，`plan()` 中加 `await` |
| `src/novel_dev/repositories/timeline_repo.py` | 新增方法 | `list_between(start, end, novel_id)` |
| `src/novel_dev/services/extraction_service.py` | 修改 | `process_upload` 中加 `await` 于 `classifier.classify()` |
| `llm_config.yaml` | 修改 | 新增 4 个 agent 配置 |
| `tests/test_agents/test_setting_extractor.py` | 重写 | mock LLM 测试 |
| `tests/test_agents/test_style_profiler.py` | 重写 | mock LLM 测试 |
| `tests/test_agents/test_file_classifier.py` | 重写 | mock LLM + async 测试 |

## Self-Review

1. **Placeholder scan：** 所有改动点均有具体 prompt 和 parser，无 TBD。
2. **Internal consistency：** `call_and_parse` 只 catch 解析错误，网络错误由 `RetryableDriver` 处理，职责清晰。
3. **Scope check：** 5 个改动点 + 配置 + 测试，适合单轮 implementation plan。
4. **Ambiguity check：** `MAX_CHARS` 已明确标注用途（截断防超长），各 agent 值已确认。
5. **Type consistency：** `FileClassifier.classify()` 和 `VolumePlannerAgent._generate_volume_plan()` 均从 `def` 改 `async def`，调用方已确认加 `await`。
